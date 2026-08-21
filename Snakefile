configfile: "config/config.yaml"

TAXONOMY_INGESTED = "data/taxonomy-ingestion.done"

rule all:
    input:
        config["audio"]["uploaded_manifest_file"]

rule download_aves:
    output:
        config["taxonomy"]["output_file"]
    params:
        source_url=config["taxonomy"]["source_url"]
    script:
        "scripts/download_aves.py"

rule ingest_taxonomy:
    output:
        touch(TAXONOMY_INGESTED)
    params:
        source_file=config["taxonomy"]["output_file"],
        database=config["mongodb"]["database"],
    script:
        "scripts/ingest_taxonomy.py"

rule fetch_sound_candidates:
    input:
        taxonomy = TAXONOMY_INGESTED
    output:
        config["audio"]["candidates_file"]
    params:
        database=config["mongodb"]["database"],
        taxa_sample_size=config["audio"]["taxa_sample_size"],
        sounds_per_taxon=config["audio"]["sounds_per_taxon"]
    script:
        "scripts/fetch_sound_candidates.py"

rule download_sounds:
    input:
        candidates=rules.fetch_sound_candidates.output
    output:
        manifest=config["audio"]["manifest_file"]
    params:
        audio_directory=config["audio"]["directory"]
    script:
        "scripts/download_sounds.py"

rule ingest_audio:
    input:
        manifest=rules.download_sounds.output.manifest
    output:
        uploaded_manifest=config["audio"]["uploaded_manifest_file"]
    params:
        bucket=config["minio"]["audio_bucket"]
    script:
        "scripts/ingest_audio.py"
