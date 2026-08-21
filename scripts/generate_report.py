import csv
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient

from src.reporting import REPORT_FIELDS, ReportBuildResult, buildSpeciesReport
from src.types import MongoConfig


def fetchClassificationRecords(
    database: Any,
    audioCollectionName: str,
    classificationCollectionName: str,
) -> list[dict[str, Any]]:
    classifications = database[classificationCollectionName]

    return list(classifications.aggregate([
        {
            "$match": {
                "status": "succeeded",
                "predictions": {"$type": "array"},
            }
        },
        {"$unwind": "$predictions"},
        {
            "$lookup": {
                "from": audioCollectionName,
                "localField": "audioFileId",
                "foreignField": "_id",
                "as": "audio",
            }
        },
        {"$unwind": "$audio"},
        {
            "$project": {
                "_id": 0,
                "audioFileId": 1,
                "sourceTaxonKey": 1,
                "classifiedAt": 1,
                "prediction": "$predictions",
                "audio": {
                    "originalFilename": "$audio.originalFilename",
                    "location": "$audio.location",
                    "occurrenceKey": "$audio.source.occurrenceKey",
                },
            }
        },
    ]))


def writeCsv(outputFile: Path, report: ReportBuildResult) -> None:
    outputFile.parent.mkdir(parents = True, exist_ok = True)

    with outputFile.open("w", encoding = "utf-8", newline = "") as file:
        writer = csv.DictWriter(file, fieldnames = REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(report.rows)


def generateReport(
    databaseName: str,
    audioCollectionName: str,
    classificationCollectionName: str,
    outputFile: Path,
    minimumConfidence: float,
    fuzzySpecies: str | None,
    fuzzyThreshold: int,
    mongodb: MongoConfig,
) -> None:
    with MongoClient(
        host = mongodb["host"],
        username = mongodb["username"],
        password = mongodb["password"],
        authSource = mongodb["authSource"],
    ) as client:
        client.admin.command("ping")
        records = fetchClassificationRecords(
            database = client[databaseName],
            audioCollectionName = audioCollectionName,
            classificationCollectionName = classificationCollectionName,
        )

    report = buildSpeciesReport(
        records = records,
        minimumConfidence = minimumConfidence,
        fuzzySpecies = fuzzySpecies,
        fuzzyThreshold = fuzzyThreshold,
    )
    writeCsv(outputFile, report)

    print(
        f"Generated {len(report.rows)} species rows in {outputFile}; "
        f"accepted {report.acceptedPredictions} positive predictions, "
        f"skipped {report.skippedPredictions} invalid or low-confidence "
        f"predictions, filtered {report.filteredSpecies} species"
    )


def main() -> None:
    load_dotenv()
    fuzzySpecies = str(snakemake.params.fuzzy_species).strip() or None

    generateReport(
        databaseName = str(snakemake.params.database),
        audioCollectionName = str(snakemake.params.audio_collection),
        classificationCollectionName = str(
            snakemake.params.classification_collection
        ),
        outputFile = Path(str(snakemake.output.report)),
        minimumConfidence = float(snakemake.params.minimum_confidence),
        fuzzySpecies = fuzzySpecies,
        fuzzyThreshold = int(snakemake.params.fuzzy_threshold),
        mongodb = MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.environ["MONGO_INITDB_ROOT_USERNAME"],
            password = os.environ["MONGO_INITDB_ROOT_PASSWORD"],
            authSource = os.getenv("MONGO_AUTH_DATABASE", "admin"),
        ),
    )


if __name__ == "__main__":
    main()
