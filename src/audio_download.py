import mimetypes
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from src.gbif_sounds import SoundCandidate


@dataclass
class AudioManifestRecord(SoundCandidate):
    originalFilename: str
    localPath: str
    contentType: str
    sizeBytes: int
    downloadedAt: str

    @classmethod
    def fromCandidate(
        cls,
        candidate: SoundCandidate,
        originalFilename: str,
        localPath: Path,
        downloadedAudio: "DownloadedAudio",
        downloadedAt: str,
    ) -> "AudioManifestRecord":
        return cls(
            sourceTaxonKey = candidate.sourceTaxonKey,
            location = candidate.location,
            source = candidate.source,
            originalFilename = originalFilename,
            localPath = localPath.as_posix(),
            contentType = downloadedAudio.contentType,
            sizeBytes = downloadedAudio.sizeBytes,
            downloadedAt = downloadedAt,
        )

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> "AudioManifestRecord":
        candidate = SoundCandidate.fromDictionary(data)

        return cls(
            sourceTaxonKey = candidate.sourceTaxonKey,
            location = candidate.location,
            source = candidate.source,
            originalFilename = data["originalFilename"],
            localPath = data["localPath"],
            contentType = data["contentType"],
            sizeBytes = data["sizeBytes"],
            downloadedAt = data["downloadedAt"],
        )

MIME_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/vnd.wave": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
}


@dataclass
class DownloadedAudio:
    temporaryPath: Path
    contentType: str
    extension: str
    sizeBytes: int


def determineContentType(
    mediaUrl: str,
    httpContentType: str | None,
    declaredContentType: str | None,
) -> str:
    guessedContentType, _ = mimetypes.guess_type(urlparse(mediaUrl).path)

    for candidateType in (
        httpContentType,
        declaredContentType,
        guessedContentType,
    ):
        if not candidateType:
            continue

        contentType = candidateType.split(";", 1)[0].strip().lower()

        if contentType.startswith("audio/"):
            return contentType

    raise ValueError(f"Could not determine an audio content type for {mediaUrl}")


def getOriginalFilename(mediaUrl: str) -> str:
    filename = Path(unquote(urlparse(mediaUrl).path)).name

    if not filename:
        raise ValueError(f"Media URL does not contain a filename: {mediaUrl}")

    return filename


def downloadSound(
    session: requests.Session,
    mediaUrl: str,
    declaredContentType: str | None,
    temporaryDirectory: Path,
) -> DownloadedAudio:
    temporaryPath: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode = "w+b",
            prefix = ".download-",
            dir = temporaryDirectory,
            delete = False,
        ) as temporaryFile:
            temporaryPath = Path(temporaryFile.name)

            with session.get(
                mediaUrl,
                stream = True,
                timeout = (10, 120),
            ) as response:
                response.raise_for_status()

                contentType = determineContentType(
                    mediaUrl,
                    response.headers.get("Content-Type"),
                    declaredContentType,
                )
                extension = MIME_EXTENSIONS.get(contentType)

                if extension is None:
                    raise ValueError(f"Unsupported audio content type: {contentType}")

                sizeBytes = 0

                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue

                    temporaryFile.write(chunk)
                    sizeBytes += len(chunk)

        if temporaryPath is None:
            raise RuntimeError("Temporary audio file was not created")

        return DownloadedAudio(
            temporaryPath = temporaryPath,
            contentType = contentType,
            extension = extension,
            sizeBytes = sizeBytes,
        )
    except Exception:
        if temporaryPath is not None:
            temporaryPath.unlink(missing_ok = True)

        raise


def storeDownloadedAudio(
    audioDirectory: Path,
    originalFilename: str,
    downloadedAudio: DownloadedAudio,
) -> Path:
    destination = audioDirectory / originalFilename

    if destination.exists():
        downloadedAudio.temporaryPath.unlink()
        raise FileExistsError(
            f"Cannot store {originalFilename}: a file with that name already exists"
        )

    downloadedAudio.temporaryPath.replace(destination)
    return destination
