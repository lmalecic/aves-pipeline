from dataclasses import dataclass
from typing import Any


@dataclass
class ClassificationPrediction:
    commonName: str
    scientificName: str
    startTime: float
    endTime: float
    confidence: float
    label: str
    taxonKey: int | None = None

    @classmethod
    def fromDictionary(
        cls,
        data: dict[str, Any],
    ) -> "ClassificationPrediction":
        return cls(
            commonName = data["common_name"],
            scientificName = data["scientific_name"],
            startTime = float(data["start_time"]),
            endTime = float(data["end_time"]),
            confidence = float(data["confidence"]),
            label = data["label"],
        )


@dataclass
class ClassifierResult:
    results: list[ClassificationPrediction]

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> "ClassifierResult":
        results = data.get("results")

        if not isinstance(results, list):
            raise ValueError("Classifier response does not contain a results list")

        return cls(
            results = [
                ClassificationPrediction.fromDictionary(result)
                for result in results
            ]
        )
