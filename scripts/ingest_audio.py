import json
import os
from dataclasses import asdict
from pathlib import Path

import boto3
from dotenv import load_dotenv

from src.audio_download import AudioManifestRecord
from src.audio_upload import ensureBucket, uploadAudio


def loadAudioManifest(manifestFile: Path) -> list[AudioManifestRecord]:
    records: list[AudioManifestRecord] = []

    with manifestFile.open("r", encoding = "utf-8") as file:
        for lineNumber, line in enumerate(file, start = 1):
            if not line.strip():
                continue

            try:
                records.append(
                    AudioManifestRecord.fromDictionary(json.loads(line))
                )
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid audio manifest entry on line {lineNumber}"
                ) from error

    return records


def ingestAudio(
    s3,
    bucket: str,
    inputManifest: Path,
    outputManifest: Path,
) -> None:
    ensureBucket(s3, bucket)
    records = loadAudioManifest(inputManifest)
    outputManifest.parent.mkdir(parents = True, exist_ok = True)

    with outputManifest.open("w", encoding = "utf-8") as outputFile:
        for record in records:
            uploadedRecord = uploadAudio(s3, bucket, record)

            _ = outputFile.write(
                json.dumps(asdict(uploadedRecord), ensure_ascii = False) + "\n"
            )
            outputFile.flush()

            print(
                f"Uploaded {record.localPath} to "
                f"s3://{bucket}/{uploadedRecord.minio.objectKey}"
            )

    print(f"Uploaded {len(records)} audio files")


def main() -> None:
    load_dotenv()

    s3 = boto3.client(
        "s3",
        endpoint_url = os.environ["MINIO_ENDPOINT_URL"],
        aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    ingestAudio(
        s3 = s3,
        bucket = str(snakemake.params.bucket),
        inputManifest = Path(str(snakemake.input.manifest)),
        outputManifest = Path(str(snakemake.output.uploaded_manifest)),
    )


if __name__ == "__main__":
    main()
