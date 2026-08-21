import datetime
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


REPORT_FIELDS = (
    "species_name",
    "common_name",
    "taxon_keys",
    "classified_observation_count",
    "positive_prediction_count",
    "average_confidence",
    "maximum_confidence",
    "first_classified_at",
    "last_classified_at",
    "fuzzy_match_score",
    "observations",
)


def cleanText(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def normalizeName(value: str) -> str:
    return cleanText(value).casefold()


def fuzzyMatchScore(query: str, *names: str) -> int:
    normalizedQuery = normalizeName(query)

    if not normalizedQuery:
        return 100

    scores: list[int] = []

    for name in names:
        normalizedName = normalizeName(name)

        if not normalizedName:
            continue

        if normalizedQuery in normalizedName or normalizedName in normalizedQuery:
            scores.append(100)
        else:
            scores.append(
                round(SequenceMatcher(None, normalizedQuery, normalizedName).ratio() * 100)
            )

    return max(scores, default = 0)


def parseConfidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return None

    return confidence


def parseCoordinates(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None

    coordinates = value.get("coordinates")

    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None

    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None

    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        return None

    return longitude, latitude


def formatDateTime(value: Any) -> str:
    if isinstance(value, datetime.datetime):
        return value.isoformat()

    return cleanText(value)


def chooseMostCommon(values: Counter[str]) -> str:
    if not values:
        return ""

    return sorted(
        values,
        key = lambda value: (-values[value], normalizeName(value)),
    )[0]


@dataclass
class ObservationSummary:
    audioFileId: str
    filename: str
    longitude: float | None
    latitude: float | None
    occurrenceKey: int | None
    sourceTaxonKey: int | None
    predictionCount: int = 0
    maximumConfidence: float = 0.0

    def addPrediction(self, confidence: float) -> None:
        self.predictionCount += 1
        self.maximumConfidence = max(self.maximumConfidence, confidence)

    def toDictionary(self) -> dict[str, Any]:
        return {
            "audioFileId": self.audioFileId,
            "filename": self.filename,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "occurrenceKey": self.occurrenceKey,
            "sourceTaxonKey": self.sourceTaxonKey,
            "predictionCount": self.predictionCount,
            "maximumConfidence": round(self.maximumConfidence, 6),
        }


@dataclass
class SpeciesAccumulator:
    scientificNames: Counter[str] = field(default_factory = Counter)
    commonNames: Counter[str] = field(default_factory = Counter)
    taxonKeys: set[int] = field(default_factory = set)
    confidences: list[float] = field(default_factory = list)
    classifiedAtValues: list[str] = field(default_factory = list)
    observations: dict[str, ObservationSummary] = field(default_factory = dict)


@dataclass(frozen = True)
class ReportBuildResult:
    rows: list[dict[str, Any]]
    acceptedPredictions: int
    skippedPredictions: int
    filteredSpecies: int


def buildSpeciesReport(
    records: list[dict[str, Any]],
    minimumConfidence: float,
    fuzzySpecies: str | None,
    fuzzyThreshold: int,
) -> ReportBuildResult:
    if not 0.0 <= minimumConfidence <= 1.0:
        raise ValueError("minimumConfidence must be between 0 and 1")

    if not 0 <= fuzzyThreshold <= 100:
        raise ValueError("fuzzyThreshold must be between 0 and 100")

    groups: dict[str, SpeciesAccumulator] = {}
    acceptedPredictions = 0
    skippedPredictions = 0

    for record in records:
        prediction = record.get("prediction")
        audio = record.get("audio")

        if not isinstance(prediction, dict) or not isinstance(audio, dict):
            skippedPredictions += 1
            continue

        scientificName = cleanText(prediction.get("scientificName"))
        confidence = parseConfidence(prediction.get("confidence"))

        if (
            not scientificName
            or confidence is None
            or confidence < minimumConfidence
        ):
            skippedPredictions += 1
            continue

        rawAudioFileId = record.get("audioFileId")

        if rawAudioFileId is None:
            skippedPredictions += 1
            continue

        audioFileId = str(rawAudioFileId).strip()

        if not audioFileId:
            skippedPredictions += 1
            continue

        acceptedPredictions += 1
        group = groups.setdefault(normalizeName(scientificName), SpeciesAccumulator())
        group.scientificNames[scientificName] += 1

        commonName = cleanText(prediction.get("commonName"))

        if commonName:
            group.commonNames[commonName] += 1

        taxonKey = prediction.get("taxonKey")

        if isinstance(taxonKey, int):
            group.taxonKeys.add(taxonKey)

        group.confidences.append(confidence)
        classifiedAt = formatDateTime(record.get("classifiedAt"))

        if classifiedAt:
            group.classifiedAtValues.append(classifiedAt)

        coordinates = parseCoordinates(audio.get("location"))
        longitude, latitude = coordinates or (None, None)
        observation = group.observations.setdefault(
            audioFileId,
            ObservationSummary(
                audioFileId = audioFileId,
                filename = cleanText(audio.get("originalFilename")),
                longitude = longitude,
                latitude = latitude,
                occurrenceKey = audio.get("occurrenceKey")
                if isinstance(audio.get("occurrenceKey"), int)
                else None,
                sourceTaxonKey = record.get("sourceTaxonKey")
                if isinstance(record.get("sourceTaxonKey"), int)
                else None,
            ),
        )
        observation.addPrediction(confidence)

    rows: list[dict[str, Any]] = []
    filteredSpecies = 0
    normalizedFilter = cleanText(fuzzySpecies)

    for group in groups.values():
        speciesName = chooseMostCommon(group.scientificNames)
        commonName = chooseMostCommon(group.commonNames)
        matchScore = (
            fuzzyMatchScore(normalizedFilter, speciesName, commonName)
            if normalizedFilter
            else None
        )

        if matchScore is not None and matchScore < fuzzyThreshold:
            filteredSpecies += 1
            continue

        observations = sorted(
            group.observations.values(),
            key = lambda observation: (
                observation.filename.casefold(),
                observation.audioFileId,
            ),
        )
        classifiedAtValues = sorted(group.classifiedAtValues)

        rows.append({
            "species_name": speciesName,
            "common_name": commonName,
            "taxon_keys": json.dumps(sorted(group.taxonKeys)),
            "classified_observation_count": len(observations),
            "positive_prediction_count": len(group.confidences),
            "average_confidence": round(
                sum(group.confidences) / len(group.confidences),
                6,
            ),
            "maximum_confidence": round(max(group.confidences), 6),
            "first_classified_at": classifiedAtValues[0]
            if classifiedAtValues
            else "",
            "last_classified_at": classifiedAtValues[-1]
            if classifiedAtValues
            else "",
            "fuzzy_match_score": matchScore if matchScore is not None else "",
            "observations": json.dumps(
                [observation.toDictionary() for observation in observations],
                ensure_ascii = False,
                separators = (",", ":"),
                sort_keys = True,
            ),
        })

    rows.sort(
        key = lambda row: (
            -int(row["classified_observation_count"]),
            normalizeName(str(row["species_name"])),
        )
    )

    return ReportBuildResult(
        rows = rows,
        acceptedPredictions = acceptedPredictions,
        skippedPredictions = skippedPredictions,
        filteredSpecies = filteredSpecies,
    )
