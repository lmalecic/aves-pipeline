import os

import requests

filePath = "data/audio/XC1022089-Red-breasted.mp3"
API_URL = "https://aves.regoch.net/api/classify"

with open(filePath, "rb") as f:
    files = { "file": (filePath, f, "audio/wav") }
    response = requests.post(API_URL, files=files)

print(response.json())
