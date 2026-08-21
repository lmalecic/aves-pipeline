from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Self

import requests

from src.types import Location

GBIF_OCCURRENCE_URL = "https://api.gbif.org/v1/occurrence/search"
MAX_PAGE_SIZE = 300

@dataclass
class SoundSource:
    provider: str
    occurrenceKey: int
    species: str | None
    media_url: str
    media_format: str | None
    creator: str | None
    publisher: str | None
    license: str | None

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> Self:
        return cls(
            provider = data["provider"],
            occurrenceKey = data["occurrenceKey"],
            species = data.get("species"),
            media_url = data["media_url"],
            media_format = data.get("media_format"),
            creator = data.get("creator"),
            publisher = data.get("publisher"),
            license = data.get("license"),
        )

@dataclass
class SoundCandidate:
    sourceTaxonKey: int
    location: Location
    source: SoundSource

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> Self:
        location = data["location"]

        return cls(
            sourceTaxonKey = data["sourceTaxonKey"],
            location = Location(
                type = location["type"],
                coordinates = location["coordinates"],
            ),
            source = SoundSource.fromDictionary(data["source"]),
        )


def fetchSoundCandidates(
    session: requests.Session,
    taxonKey: int,
    limit: int,
) -> Iterator[SoundCandidate]:
    if limit < 1:
        return

    offset = 0
    yieldedCount = 0

    while True:
        response = session.get(
            GBIF_OCCURRENCE_URL,
            params = {
                "taxon_key": taxonKey,
                "media_type": "Sound",
                "has_coordinate": True,
                "limit": min(limit, MAX_PAGE_SIZE),
                "offset": offset
            },
            timeout = (10, 60),
        )

        response.raise_for_status()
        data = response.json()
        occurrences = data.get("results", [])

        for occurrence in occurrences:
            latitude = occurrence.get("decimalLatitude")
            longitude = occurrence.get("decimalLongitude")
            occurrenceKey = occurrence.get("key")

            if (
                latitude is None
                or longitude is None
                or occurrenceKey is None
            ):
                continue

            for media in occurrence.get("media", []):
                if media.get("type") != "Sound":
                    continue

                mediaUrl = media.get("identifier")

                if not mediaUrl:
                    continue

                yield SoundCandidate(
                    sourceTaxonKey = taxonKey,
                    location = Location(
                        type = "Point",
                        coordinates = [
                            float(longitude),
                            float(latitude)
                        ]
                    ),
                    source = SoundSource(
                        provider = "GBIF",
                        occurrenceKey = occurrenceKey,
                        species = occurrence.get("species"),
                        media_url = mediaUrl,
                        media_format = media.get("format"),
                        creator = media.get("creator"),
                        publisher = media.get("publisher"),
                        license = media.get("license"),
                    ),
                )

                yieldedCount += 1

                if yieldedCount >= limit:
                    return

        if data.get("endOfRecords", False) or not occurrences:
            return

        offset += len(occurrences)

        if offset >= 100_000:
            raise RuntimeError(f"GBIF pagination limit reached for taxon {taxonKey}")
