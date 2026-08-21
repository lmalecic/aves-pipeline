import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from src.audio_download import AudioManifestRecord


@dataclass
class MinIOAudioObject:
    bucket: str
    objectKey: str
    etag: str

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> "MinIOAudioObject":
        return cls(
            bucket = data["bucket"],
            objectKey = data["objectKey"],
            etag = data["etag"],
        )


@dataclass
class UploadedAudioRecord(AudioManifestRecord):
    sha256: str
    minio: MinIOAudioObject
    uploadedAt: str

    @classmethod
    def fromAudioManifest(
        cls,
        record: AudioManifestRecord,
        sha256: str,
        minio: MinIOAudioObject,
    ) -> "UploadedAudioRecord":
        return cls(
            sourceTaxonKey = record.sourceTaxonKey,
            location = record.location,
            source = record.source,
            originalFilename = record.originalFilename,
            localPath = record.localPath,
            contentType = record.contentType,
            sizeBytes = record.sizeBytes,
            downloadedAt = record.downloadedAt,
            sha256 = sha256,
            minio = minio,
            uploadedAt = datetime.datetime.now(datetime.UTC).isoformat(),
        )

    @classmethod
    def fromDictionary(cls, data: dict[str, Any]) -> "UploadedAudioRecord":
        record = AudioManifestRecord.fromDictionary(data)

        return cls(
            sourceTaxonKey = record.sourceTaxonKey,
            location = record.location,
            source = record.source,
            originalFilename = record.originalFilename,
            localPath = record.localPath,
            contentType = record.contentType,
            sizeBytes = record.sizeBytes,
            downloadedAt = record.downloadedAt,
            sha256 = data["sha256"],
            minio = MinIOAudioObject.fromDictionary(data["minio"]),
            uploadedAt = data["uploadedAt"],
        )


def ensureBucket(s3: Any, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket = bucket)
    except ClientError as error:
        errorCode = str(error.response["Error"].get("Code"))

        if errorCode not in {"404", "NoSuchBucket", "NotFound"}:
            raise

        s3.create_bucket(Bucket = bucket)


def calculateSha256(filePath: Path) -> str:
    sha256 = hashlib.sha256()

    with filePath.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            sha256.update(chunk)

    return sha256.hexdigest()


def createObjectKey(record: AudioManifestRecord, sha256: str) -> str:
    extension = Path(record.originalFilename).suffix.lower()
    return (
        f"recordings/gbif/"
        f"{record.sourceTaxonKey}/"
        f"{record.source.occurrenceKey}/"
        f"{sha256}{extension}"
    )


def createLocationMetadata(record: AudioManifestRecord) -> dict[str, str]:
    longitude, latitude = record.location["coordinates"]

    return {
        "location": json.dumps(record.location, separators = (",", ":")),
        "longitude": str(longitude),
        "latitude": str(latitude),
        "source-taxon-key": str(record.sourceTaxonKey),
        "occurrence-key": str(record.source.occurrenceKey),
    }


def uploadAudio(
    s3: Any,
    bucket: str,
    record: AudioManifestRecord,
) -> UploadedAudioRecord:
    localPath = Path(record.localPath)

    if not localPath.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {localPath}")

    if localPath.stat().st_size != record.sizeBytes:
        raise ValueError(f"Audio file size does not match its manifest: {localPath}")

    sha256 = calculateSha256(localPath)
    objectKey = createObjectKey(record, sha256)

    s3.upload_file(
        str(localPath),
        bucket,
        objectKey,
        ExtraArgs = {
            "ContentType": record.contentType,
            "Metadata": createLocationMetadata(record),
        },
    )

    uploadedObject = s3.head_object(
        Bucket = bucket,
        Key = objectKey,
    )

    return UploadedAudioRecord.fromAudioManifest(
        record = record,
        sha256 = sha256,
        minio = MinIOAudioObject(
            bucket = bucket,
            objectKey = objectKey,
            etag = uploadedObject["ETag"].strip('"'),
        ),
    )
