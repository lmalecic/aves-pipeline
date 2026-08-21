from dataclasses import asdict
import datetime
import json
from pathlib import Path

import requests

from src.audio_download import (
    AudioManifestRecord,
    downloadSound,
    getOriginalFilename,
    storeDownloadedAudio,
)
from src.gbif_sounds import SoundCandidate


def loadCandidates(inputFile: Path) -> list[SoundCandidate]:
    with inputFile.open("r", encoding = "utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise TypeError("Expected sound candidates to contain a JSON list")

    return [SoundCandidate.fromDictionary(candidate) for candidate in data]


def loadDownloadedUrls(manifestFile: Path) -> set[str]:
    downloadedUrls: set[str] = set()

    if not manifestFile.exists():
        return downloadedUrls

    with manifestFile.open("r", encoding = "utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            record = AudioManifestRecord.fromDictionary(json.loads(line))
            downloadedUrls.add(record.source.media_url)

    return downloadedUrls


def downloadSounds(
    candidatesFile: Path,
    audioDirectory: Path,
    manifestFile: Path,
) -> None:
    audioDirectory.mkdir(parents = True, exist_ok = True)
    manifestFile.parent.mkdir(parents = True, exist_ok = True)

    candidates = loadCandidates(candidatesFile)
    downloadedUrls = loadDownloadedUrls(manifestFile)
    downloadedCount = 0

    with (
        requests.Session() as session,
        manifestFile.open("a", encoding = "utf-8") as manifest,
    ):
        session.headers.update({"User-Agent": "aves-pipeline"})

        for candidate in candidates:
            mediaUrl = candidate.source.media_url

            if mediaUrl in downloadedUrls:
                continue

            downloadedAudio = None

            try:
                downloadedAudio = downloadSound(session, mediaUrl, candidate.source.media_format, audioDirectory)
                originalFilename = getOriginalFilename(mediaUrl)
                localPath = storeDownloadedAudio(audioDirectory, originalFilename, downloadedAudio)

                record = AudioManifestRecord.fromCandidate(
                    candidate = candidate,
                    originalFilename = originalFilename,
                    localPath = localPath,
                    downloadedAudio = downloadedAudio,
                    downloadedAt = datetime.datetime.now(
                        datetime.UTC
                    ).isoformat(),
                )

                _ = manifest.write(
                    json.dumps(asdict(record), ensure_ascii = False) + "\n"
                )
                manifest.flush()

                downloadedUrls.add(mediaUrl)
                downloadedCount += 1
                print(f"Downloaded {localPath}")
            except (requests.RequestException, ValueError, FileExistsError) as error:
                if downloadedAudio is not None:
                    downloadedAudio.temporaryPath.unlink(missing_ok = True)

                print(f"Failed to download {mediaUrl}: {error}")

    print(f"Downloaded {downloadedCount} audio files")


def main() -> None:
    downloadSounds(
        candidatesFile = Path(str(snakemake.input.candidates)),
        audioDirectory = Path(str(snakemake.params.audio_directory)),
        manifestFile = Path(str(snakemake.output.manifest)),
    )


if __name__ == "__main__":
    main()
