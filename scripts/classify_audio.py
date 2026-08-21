import datetime
import json
import os
import time
import uuid
from dataclasses import asdict
from typing import Any

import boto3
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from src.audio_classification import (
    ClassificationPrediction,
    ClassifierResult,
)
from src.types import MongoConfig


def resolvePredictionTaxa(
    taxa: Any,
    predictions: list[ClassificationPrediction],
) -> None:
    for prediction in predictions:
        taxon = taxa.find_one(
            {"canonicalName": prediction.scientificName},
            {"_id": 0, "key": 1},
        )

        if taxon is not None:
            prediction.taxonKey = taxon["key"]


def classifyAudio(
    s3: Any,
    session: requests.Session,
    classifierUrl: str,
    audioFile: dict[str, Any],
) -> tuple[int | None, Any, list[ClassificationPrediction], str | None, int]:
    started = time.perf_counter()
    statusCode: int | None = None
    rawResponse: Any = None
    predictions: list[ClassificationPrediction] = []
    errorMessage: str | None = None

    try:
        minioResponse = s3.get_object(
            Bucket = audioFile["minio"]["bucket"],
            Key = audioFile["minio"]["objectKey"],
        )

        with minioResponse["Body"] as audioStream:
            audioBytes = audioStream.read()

        response = session.post(
            classifierUrl,
            files = {
                "file": (
                    audioFile["originalFilename"],
                    audioBytes,
                    audioFile["contentType"],
                )
            },
            timeout = (10, 180),
        )
        statusCode = response.status_code

        try:
            rawResponse = response.json()
        except ValueError:
            rawResponse = {"text": response.text}

        if response.status_code == 413:
            errorMessage = "file too large"
        elif not response.ok:
            errorMessage = (
                f"Classifier returned HTTP {response.status_code} "
                f"for {audioFile['originalFilename']}"
            )
        else:
            classifierResult = ClassifierResult.fromDictionary(rawResponse)
            predictions.extend(classifierResult.results)
    except Exception as error:
        errorMessage = f"{type(error).__name__}: {error}"

    durationMilliseconds = round((time.perf_counter() - started) * 1000)

    return (
        statusCode,
        rawResponse,
        predictions,
        errorMessage,
        durationMilliseconds,
    )


def storeRequestLog(
    s3: Any,
    logPrefix: str,
    requestId: str,
    audioFile: dict[str, Any],
    classifierUrl: str,
    statusCode: int | None,
    rawResponse: Any,
    errorMessage: str | None,
    durationMilliseconds: int,
) -> dict[str, str]:
    log = {
        "requestId": requestId,
        "requestedAt": datetime.datetime.now(datetime.UTC).isoformat(),
        "durationMilliseconds": durationMilliseconds,
        "request": {
            "method": "POST",
            "url": classifierUrl,
            "multipartField": "file",
            "audioFileId": str(audioFile["_id"]),
            "filename": audioFile["originalFilename"],
            "contentType": audioFile["contentType"],
            "sourceObject": audioFile["minio"],
        },
        "response": {
            "statusCode": statusCode,
            "body": rawResponse,
        },
        "error": errorMessage,
    }

    bucket = audioFile["minio"]["bucket"]
    objectKey = f"{logPrefix}/{audioFile['sha256']}/{requestId}.json"

    result = s3.put_object(
        Bucket = bucket,
        Key = objectKey,
        Body = json.dumps(log, ensure_ascii = False).encode("utf-8"),
        ContentType = "application/json",
        Metadata = {
            "request-id": requestId,
            "audio-sha256": audioFile["sha256"],
        },
    )

    return {
        "bucket": bucket,
        "objectKey": objectKey,
        "etag": result["ETag"].strip('"'),
    }


def classifyPendingAudio(
    s3: Any,
    classifierUrl: str,
    logPrefix: str,
    databaseName: str,
    taxaCollectionName: str,
    audioCollectionName: str,
    classificationCollectionName: str,
    mongodb: MongoConfig,
) -> None:
    successCount = 0
    failureCount = 0

    with MongoClient(
        host = mongodb["host"],
        username = mongodb["username"],
        password = mongodb["password"],
        authSource = mongodb["authSource"],
    ) as client:
        client.admin.command("ping")

        database = client[databaseName]
        taxa = database[taxaCollectionName]
        audioFiles = database[audioCollectionName]
        classifications = database[classificationCollectionName]

        classifications.create_index(
            "audioFileId",
            unique = True,
            name = "uq_classification_audio_file",
        )
        classifications.create_index(
            "predictions.taxonKey",
            name = "idx_classification_taxon_key",
        )

        with requests.Session() as session:
            session.headers.update({"User-Agent": "aves-pipeline"})

            for audioFile in audioFiles.find(
                {"classificationStatus": {"$ne": "succeeded"}}
            ):
                requestId = uuid.uuid4().hex

                (
                    statusCode,
                    rawResponse,
                    predictions,
                    errorMessage,
                    durationMilliseconds,
                ) = classifyAudio(
                    s3,
                    session,
                    classifierUrl,
                    audioFile,
                )

                resolvePredictionTaxa(taxa, predictions)
                status = "succeeded" if errorMessage is None else "failed"

                requestLog = storeRequestLog(
                    s3 = s3,
                    logPrefix = logPrefix,
                    requestId = requestId,
                    audioFile = audioFile,
                    classifierUrl = classifierUrl,
                    statusCode = statusCode,
                    rawResponse = rawResponse,
                    errorMessage = errorMessage,
                    durationMilliseconds = durationMilliseconds,
                )

                classifications.update_one(
                    {"audioFileId": audioFile["_id"]},
                    {
                        "$set": {
                            "audioFileId": audioFile["_id"],
                            "sourceTaxonKey": audioFile["sourceTaxonKey"],
                            "status": status,
                            "classifierUrl": classifierUrl,
                            "httpStatus": statusCode,
                            "durationMilliseconds": durationMilliseconds,
                            "predictions": [
                                asdict(prediction) for prediction in predictions
                            ],
                            "rawResult": rawResponse,
                            "error": errorMessage,
                            "requestLog": requestLog,
                            "classifiedAt": datetime.datetime.now(datetime.UTC),
                        }
                    },
                    upsert = True,
                )

                audioFiles.update_one(
                    {"_id": audioFile["_id"]},
                    {"$set": {"classificationStatus": status}},
                )

                if status == "succeeded":
                    successCount += 1
                    print(f"Classified {audioFile['originalFilename']}: succeeded")
                else:
                    failureCount += 1
                    print(
                        f"Classified {audioFile['originalFilename']}: "
                        f"failed: {errorMessage}"
                    )

    print(
        f"Classification complete: {successCount} succeeded, "
        f"{failureCount} failed"
    )


def main() -> None:
    load_dotenv()

    s3 = boto3.client(
        "s3",
        endpoint_url = os.environ["MINIO_ENDPOINT_URL"],
        aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    classifyPendingAudio(
        s3 = s3,
        classifierUrl = str(snakemake.params.classifier_url),
        logPrefix = str(snakemake.params.log_prefix),
        databaseName = str(snakemake.params.database),
        taxaCollectionName = str(snakemake.params.taxa_collection),
        audioCollectionName = str(snakemake.params.audio_collection),
        classificationCollectionName = str(
            snakemake.params.classification_collection
        ),
        mongodb = MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.environ["MONGO_INITDB_ROOT_USERNAME"],
            password = os.environ["MONGO_INITDB_ROOT_PASSWORD"],
            authSource = os.getenv("MONGO_AUTH_DATABASE", "admin"),
        ),
    )


if __name__ == "__main__":
    main()
