from typing import TypedDict
import datetime

class MongoConfig(TypedDict):
    host: str
    username: str
    password: str
    authSource: str

class Location(TypedDict):
    type: str
    coordinates: list[float]

class AudioFileSource(TypedDict):
    provider: str
    occurrence_key: str
    species: str
    media_url: str
    media_format: str
    creator: str
    publisher: str
    license: str

class AudioFileMinIO(TypedDict):
    bucket: str
    object_key: str
    etag: str

class AudioFile(TypedDict):
    sha256: str
    original_filename: str
    content_type: str
    size_bytes: int
    source_taxon_key: int
    location: Location
    source: AudioFileSource
    minio: AudioFileMinIO
    uploaded_at: datetime.datetime
    classification_status: str
