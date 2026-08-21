from typing import TypedDict

class MongoConfig(TypedDict):
    host: str
    username: str
    password: str
    authSource: str

class Location(TypedDict):
    type: str
    coordinates: list[float]

class AudioFileMinIO(TypedDict):
    bucket: str
    object_key: str
    etag: str
