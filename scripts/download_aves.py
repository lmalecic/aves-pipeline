import os
from pathlib import Path

import requests


def ensureOutputDir(outputFile: str):
    Path(outputFile).parent.mkdir(parents=True, exist_ok=True)


def downloadAves(sourceUrl: str, outputFile: str):
    response = requests.get(
        sourceUrl,
        headers = { "User-Agent": "aves-pipeline" },
        timeout = (10, 60),
    )

    response.raise_for_status()

    with open(outputFile, "wb") as f:
        f.write(response.content)

    print(f"Downloaded Aves taxonomy to {outputFile}")


def main():
    ensureOutputDir(snakemake.output[0])
    downloadAves(snakemake.params["source_url"], snakemake.output[0])


if __name__ == "__main__":
    main()
