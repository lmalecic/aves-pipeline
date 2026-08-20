import os
import datetime
from pathlib import Path
from typing import Any, TypedDict

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from src.types import MongoConfig

TAXA_COLLECTION = "taxa"

def fetchTaxa(sourceUrl: str) -> list[dict[str, Any]]:
    response = requests.get(
        sourceUrl,
        headers = { "User-Agent": "aves-pipeline" },
        timeout = (10, 60),
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise TypeError("Expected the taxonomy response to contain a JSON list")

    if not data:
        raise ValueError("The taxonomy response is empty")

    seenKeys: set[int] = set()

    for position, taxon in enumerate(data):
        if not isinstance(taxon, dict):
            raise TypeError(f"Expected each taxon to be a dictionary at position {position}")

        taxonKey = taxon.get("key")
        scientificName = taxon.get("scientificName")

        if taxonKey is None:
            raise ValueError(f"Expected each taxon to have a 'key' field at position {position}")

        if not scientificName:
            raise ValueError(f"Expected each taxon to have a 'scientificName' field at position {position}")

        if taxonKey in seenKeys:
            raise ValueError(f"Duplicate taxon key '{taxonKey}' found at position {position}")

        seenKeys.add(taxonKey)

    return data

def ingestTaxa(*, databaseName: str, sourceUrl: str, mongodb: MongoConfig) -> None:
    with MongoClient(
        host = mongodb["host"],
        username = mongodb["username"],
        password = mongodb["password"],
        authSource = mongodb["authSource"],
    ) as client:
        _ = client.admin.command("ping")

        database = client[databaseName]
        collection = database[TAXA_COLLECTION]

        if collection.find_one({}, {"_id": 1}) is not None:
            print("Collection already contains data. Skipping ingestion.")
            return

        taxa = fetchTaxa(sourceUrl)
        ingestedAt = datetime.datetime.now(datetime.UTC)

        documents = []

        for taxon in taxa:
            document = dict(taxon)

            document["_metadata"] = {
                "source_url": sourceUrl,
                "ingested_at": ingestedAt,
            }

            documents.append(document)

        collection.create_index("key", unique = True, name = "uq_taxa_key")
        collection.create_index("canonicalName", name="idx_taxa_canonical_name")

        result = collection.insert_many(documents)
        print(f"Inserted {len(result.inserted_ids)} taxa into {databaseName}.{TAXA_COLLECTION}")

def main() -> None:
    load_dotenv()

    marker_path = Path(str(snakemake.output[0]))
    marker_path.parent.mkdir(parents = True, exist_ok = True)

    ingestTaxa(
        databaseName = str(snakemake.params.database),
        sourceUrl = str(snakemake.params.source_url),
        mongodb = MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.getenv("MONGO_INITDB_ROOT_USERNAME", "root"),
            password = os.getenv("MONGO_INITDB_ROOT_PASSWORD", "password"),
            authSource = os.getenv("MONGO_AUTH_DATABASE", "admin")
        ),
    )


if __name__ == "__main__":
    main()
