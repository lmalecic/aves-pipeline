configfile: "config/config.yaml"

rule all:
    input:
        "artifacts/state/taxonomy.done"

rule ingest_taxonomy:
    output:
        touch("artifacts/state/taxonomy.done")
    params:
        source_url=config["taxonomy"]["source_url"],
        database=config["mongodb"]["database"],
    script:
        "scripts/ingest_taxonomy.py"

rule ingest_audio:
    input:
        taxonomy="artifacts/state/taxonomy.done"
    output:
        touch("artifacts/state/audio-ingestion.done")
    params:
        database=config["mongodb"]["database"],
        sounds_per_taxon=config["audio"]["sounds_per_taxon"],
    script:
        "scripts/ingest_audio.py"
