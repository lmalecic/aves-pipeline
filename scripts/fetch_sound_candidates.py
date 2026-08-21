import json
import os
from dataclasses import asdict
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from src.gbif_sounds import SoundCandidate, fetchSoundCandidates
from src.types import MongoConfig


TAXA_COLLECTION = snakemake.config["mongodb"]["taxa_collection"]


def collectSoundCandidates(
    mongodb: MongoConfig,
    taxaSampleSize: int,
    soundsPerTaxon: int,
) -> list[SoundCandidate]:
    candidates: list[SoundCandidate] = []
    seenUrls: set[str] = set()

    with MongoClient(
        host=mongodb["host"],
        username=mongodb["username"],
        password=mongodb["password"],
        authSource=mongodb["authSource"],
    ) as client:
        client.admin.command("ping")

        taxa = client[snakemake.config["mongodb"]["database"]][TAXA_COLLECTION]

        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "aves-pipeline",
            })

            sampledTaxa = taxa.aggregate([
                {"$sample": {"size": taxaSampleSize}},
                {"$project": {"_id": 0, "key": 1}},
            ])

            for taxon in sampledTaxa:
                taxonKey = taxon["key"]

                for candidate in fetchSoundCandidates(
                    session,
                    taxonKey,
                    soundsPerTaxon,
                ):
                    mediaUrl = candidate.source.media_url

                    if mediaUrl in seenUrls:
                        continue

                    seenUrls.add(mediaUrl)
                    candidates.append(candidate)

                print(f"Collected candidates for taxon {taxonKey}")

        return candidates

def main():
    load_dotenv()

    outputFile = Path(str(snakemake.output[0]))
    outputFile.parent.mkdir(parents=True, exist_ok=True)

    candidates = collectSoundCandidates(
        MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.environ["MONGO_INITDB_ROOT_USERNAME"],
            password = os.environ["MONGO_INITDB_ROOT_PASSWORD"],
            authSource = os.getenv("MONGO_AUTH_SOURCE", "admin"),
        ),
        taxaSampleSize = int(snakemake.params.taxa_sample_size),
        soundsPerTaxon = int(snakemake.params.sounds_per_taxon),
    )

    with outputFile.open("w", encoding="utf-8") as file:
        json.dump(
            [asdict(candidate) for candidate in candidates],
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Written {len(candidates)} candidates to {outputFile}")


if __name__ == "__main__":
    main()
