import datetime
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv
from pymongo import GEOSPHERE, MongoClient

from src.audio_download import AudioManifestRecord
from src.audio_upload import UploadedAudioRecord, ensureBucket, uploadAudio
from src.types import MongoConfig


def loadAudioManifest(manifestFile: Path) -> list[AudioManifestRecord]:
    records: list[AudioManifestRecord] = []

    with manifestFile.open("r", encoding = "utf-8") as file:
        for lineNumber, line in enumerate(file, start = 1):
            if not line.strip():
                continue

            try:
                records.append(
                    AudioManifestRecord.fromDictionary(json.loads(line))
                )
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid audio manifest entry on line {lineNumber}"
                ) from error

    return records


def ingestAudio(
    s3,
    bucket: str,
    databaseName: str,
    audioCollectionName: str,
    mongodb: MongoConfig,
    inputManifest: Path,
    outputManifest: Path,
) -> None:
    ensureBucket(s3, bucket)
    records = loadAudioManifest(inputManifest)
    outputManifest.parent.mkdir(parents = True, exist_ok = True)

    with MongoClient(
        host = mongodb["host"],
        username = mongodb["username"],
        password = mongodb["password"],
        authSource = mongodb["authSource"],
    ) as client:
        client.admin.command("ping")

        audioFiles = client[databaseName][audioCollectionName]
        audioFiles.create_index(
            "source.media_url",
            unique = True,
            name = "uq_audio_source_url",
            partialFilterExpression = {
                "source.media_url": {"$type": "string"}
            },
        )
        audioFiles.create_index(
            "minio.objectKey",
            unique = True,
            name = "uq_audio_minio_object_key",
            partialFilterExpression = {
                "minio.objectKey": {"$type": "string"}
            },
        )
        audioFiles.create_index("sha256", name = "idx_audio_sha256")
        audioFiles.create_index(
            [("location", GEOSPHERE)],
            name = "idx_audio_location",
        )

        with outputManifest.open("w", encoding = "utf-8") as outputFile:
            for record in records:
                uploadedRecord = uploadAudio(s3, bucket, record)
                storeAudioMetadata(audioFiles, uploadedRecord)

                _ = outputFile.write(
                    json.dumps(asdict(uploadedRecord), ensure_ascii = False) + "\n"
                )
                outputFile.flush()

                print(
                    f"Uploaded {record.localPath} to "
                    f"s3://{bucket}/{uploadedRecord.minio.objectKey}"
                )

    print(f"Uploaded {len(records)} audio files")


def storeAudioMetadata(
    audioFiles: Any,
    record: UploadedAudioRecord,
) -> None:
    document = asdict(record)
    document["downloadedAt"] = datetime.datetime.fromisoformat(
        record.downloadedAt
    )
    document["uploadedAt"] = datetime.datetime.fromisoformat(
        record.uploadedAt
    )

    audioFiles.update_one(
        {"source.media_url": record.source.media_url},
        {
            "$set": document,
            "$setOnInsert": {
                "classificationStatus": "pending",
                "createdAt": datetime.datetime.now(datetime.UTC),
            },
        },
        upsert = True,
    )

    audioFiles.update_one(
        {
            "source.media_url": record.source.media_url,
            "classificationStatus": {"$exists": False},
        },
        {"$set": {"classificationStatus": "pending"}},
    )


def main() -> None:
    load_dotenv()

    s3 = boto3.client(
        "s3",
        endpoint_url = os.environ["MINIO_ENDPOINT_URL"],
        aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    ingestAudio(
        s3 = s3,
        bucket = str(snakemake.params.bucket),
        databaseName = str(snakemake.params.database),
        audioCollectionName = str(snakemake.params.audio_collection),
        mongodb = MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.environ["MONGO_INITDB_ROOT_USERNAME"],
            password = os.environ["MONGO_INITDB_ROOT_PASSWORD"],
            authSource = os.getenv("MONGO_AUTH_DATABASE", "admin"),
        ),
        inputManifest = Path(str(snakemake.input.manifest)),
        outputManifest = Path(str(snakemake.output.uploaded_manifest)),
    )


if __name__ == "__main__":
    main()
