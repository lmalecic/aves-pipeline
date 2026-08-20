import io
import mimetypes
import os
import hashlib
import datetime
from pathlib import Path
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError
import requests
import tempfile

from typing import Any, BinaryIO, Iterator
from dotenv import load_dotenv
from pymongo import MongoClient, GEOSPHERE
from dataclasses import dataclass
from src.types import *
from contextlib import contextmanager
from typing_extensions import Generator

@dataclass
class DownloadedSound:
    file: tempfile.SpooledTemporaryFile[bytes]
    sha256: str
    sizeBytes: int
    contentType: str

@dataclass
class SoundCandidate:
    taxonKey: int
    occurrenceKey: str
    species: str
    latitude: float
    longitude: float
    mediaUrl: str
    mediaFormat: str
    creator: str
    license: str
    publisher: str

GBIF_OCCURENCE_URL = "https://api.gbif.org/v1/occurrence/search"

TAXA_COLLECTION = "taxa"
AUDIO_COLLECTION = "audio_files"
AUDIO_BUCKET = "bird-audio"

MIME_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/vnd.wave": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
}

def ensureBucket(s3) -> None:
    try:
        s3.head_bucket(Bucket = AUDIO_BUCKET)
    except ClientError as error:
        errorCode = str(error.response["Error"].get("Code"))

        if errorCode not in {"404", "NoSuchBucket", "NotFound"}:
            raise

        s3.create_bucket(Bucket = AUDIO_BUCKET)

@contextmanager
def downloadSound(
    session: requests.Session,
    mediaUrl: str,
    declaredContentType: str | None,
) -> Generator[DownloadedSound, None, None]:
    temporaryFile = tempfile.SpooledTemporaryFile(
        max_size = 10 * 1024 * 1024,
        mode = "w+b"
    )

    try:
        sha256 = hashlib.sha256()
        sizeBytes = 0

        with session.get(
            mediaUrl,
            stream=True,
            timeout=(10, 120)
        ) as response:
            response.raise_for_status()

            responseContentType = response.headers.get(
                "Content-Type",
                "",
            ).split(";", maxsplit=1)[0].strip().lower()

            gbifContentType = declaredContentType.split(";", maxsplit=1)[0].strip().lower() if declaredContentType else None

            guessedContentType, _ = mimetypes.guess_type(urlparse(mediaUrl).path)

            contentType = next(
                (
                    candidateType
                    for candidateType in (
                        responseContentType,
                        gbifContentType,
                        guessedContentType,
                    )
                    if candidateType and candidateType.startswith("audio/")
                ),
                None,
            )

            if contentType is None:
                raise ValueError(f"Could not determine an audio content type for {mediaUrl}. HTTP type: {responseContentType or 'missing'}, GBIF type: {gbifContentType or 'missing'}")

            # if not contentType.startswith("audio/"):
            #     temporaryFile.close()
            #     raise ValueError(f"Expected audio content from {mediaUrl}, got {contentType}")

            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue

                temporaryFile.write(chunk)
                sha256.update(chunk)
                sizeBytes += len(chunk)

        temporaryFile.seek(0)

        yield DownloadedSound(
            file = temporaryFile,
            sha256 = sha256.hexdigest(),
            sizeBytes = sizeBytes,
            contentType = contentType
        )

    finally:
        temporaryFile.close()

def uploadSoundToMinIO(
    downloadedSound: DownloadedSound,
    s3,
    mediaUrl: str,
    objectKey: str,
):
    s3.upload_fileobj(
        downloadedSound.file,
        AUDIO_BUCKET,
        objectKey,
        ExtraArgs = { "ContentType": downloadedSound.contentType },
    )

def fetchSoundCandidates(
    session: requests.Session,
    taxonKey: int,
    limit: int,
) -> list[SoundCandidate]:
    response = session.get(
        GBIF_OCCURENCE_URL,
        params = {
            "taxon_key": taxonKey,
            "media_type": "Sound",
            "has_coordinate": "true",
            "limit": limit # this might not be correct, use 50 if not correct
        },
        timeout = (10, 60),
    )

    response.raise_for_status()

    data = response.json()
    candidates: list[SoundCandidate] = []

    for occurrence in data.get("results", []):
        latitude = occurrence.get("decimalLatitude")
        longitude = occurrence.get("decimalLongitude")

        if latitude is None or longitude is None:
            continue

        for media in occurrence.get("media", []):
            if media.get("type") != "Sound":
                continue

            mediaUrl = media.get("identifier")

            if not mediaUrl:
                continue

            candidates.append(
                SoundCandidate(
                    taxonKey=taxonKey,
                    occurrenceKey=occurrence.get("key"),
                    species=occurrence.get("species"),
                    latitude=float(latitude),
                    longitude=float(longitude),
                    mediaUrl=mediaUrl,
                    mediaFormat=media.get("format"),
                    creator=media.get("creator"),
                    license=media.get("license"),
                    publisher=media.get("publisher"),
                )
            )

            if len(candidates) >= limit:
                return candidates

    return candidates

def ingestAudio(*, s3, databaseName: str, mongodb: MongoConfig):
    with MongoClient(
        host=mongodb["host"],
        username=mongodb["username"],
        password=mongodb["password"],
        authSource=mongodb["authSource"],
    ) as client:
        _ = client.admin.command("ping")

        database = client[databaseName]
        taxa = database[TAXA_COLLECTION]
        audioFiles = database[AUDIO_COLLECTION]
        soundsPerTaxon = int(snakemake.params.sounds_per_taxon)

        audioFiles.create_index("sha256", unique=True, name = "uq_audio_sha256")
        audioFiles.create_index("source.media_url", unique=True, name = "uqaudio_source_url")
        audioFiles.create_index([("location", GEOSPHERE)], name="idx_audio_location")

        with requests.Session() as session:
            for taxon in taxa.find():
                candidates = fetchSoundCandidates(
                    session = session,
                    taxonKey = taxon["key"],
                    limit = soundsPerTaxon
                )
                for candidate in candidates:
                    existingAudio = audioFiles.find_one(
                        {"source.media_url": candidate.mediaUrl},
                        {"_id": 1},
                    )

                    if existingAudio is not None:
                        print(f"Audio already exists: {existingAudio['_id']}")
                        continue

                    mediaUrl = candidate.mediaUrl

                    if not mediaUrl:
                        continue

                    with downloadSound(session, mediaUrl, candidate.mediaFormat) as sound:
                        extension = MIME_EXTENSIONS.get(sound.contentType.lower())

                        if extension is None:
                            raise ValueError(f"Unsupported MIME type: {sound.contentType}")

                        existingAudio = audioFiles.find_one(
                            {"sha256": sound.sha256},
                            {"_id": 1},
                        )

                        if existingAudio is not None:
                            print(f"Audio already exists: {existingAudio['_id']}; skipping duplicate")
                            continue

                        objectKey = f"recordings/gbif/{candidate.taxonKey}/{candidate.occurrenceKey}/{sound.sha256}{extension}"

                        uploadSoundToMinIO(
                            downloadedSound = sound,
                            s3 = s3,
                            mediaUrl = mediaUrl,
                            objectKey = objectKey
                        )

                        uploadedObject = s3.head_object(
                            Bucket=AUDIO_BUCKET,
                            Key=objectKey,
                        )

                        sourceFilename = Path(
                            urlparse(candidate.mediaUrl).path
                        ).name

                        if not sourceFilename:
                            sourceFilename = f"{sound.sha256}{extension}"

                        document = AudioFile(
                            sha256 = sound.sha256,
                            original_filename = sourceFilename,
                            content_type = uploadedObject["ContentType"],
                            size_bytes = uploadedObject["ContentLength"],
                            source_taxon_key = candidate.taxonKey,
                            location = Location(
                                type = "Point",
                                coordinates = [candidate.longitude, candidate.latitude]
                            ),
                            source = AudioFileSource(
                                provider = "GBIF",
                                occurrence_key = candidate.occurrenceKey,
                                species = candidate.species,
                                media_url = candidate.mediaUrl,
                                media_format = candidate.mediaFormat,
                                creator = candidate.creator,
                                publisher = candidate.publisher,
                                license = candidate.license,
                            ),
                            minio = AudioFileMinIO(
                                bucket = AUDIO_BUCKET,
                                object_key = objectKey,
                                etag = uploadedObject["ETag"].strip('"'),
                            ),
                            uploaded_at = datetime.datetime.now(datetime.UTC),
                            classification_status = "pending",
                        )

                        result = audioFiles.insert_one(document)

                        print(f"Stored audio metadata with MongoDB ID {result.inserted_id}")

def main():
    load_dotenv()

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    ensureBucket(s3)

    ingestAudio(
        databaseName = os.environ["MONGO_DATABASE"],
        mongodb = MongoConfig(
            host = os.getenv("MONGO_HOST", "localhost"),
            username = os.environ["MONGO_INITDB_ROOT_USERNAME"],
            password = os.environ["MONGO_INITDB_ROOT_PASSWORD"],
            authSource = os.environ["MONGO_AUTH_DATABASE"]
        ),
        s3 = s3
    )

if __name__ == "__main__":
    main()
