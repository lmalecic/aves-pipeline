configfile: "config/config.yaml"

TAXONOMY_INGESTED = "data/taxonomy-ingestion.done"

rule all:
    input:
        config["report"]["output_file"]

rule download_aves:
    output:
        taxonomy=config["taxonomy"]["output_file"]
    params:
        source_url=config["taxonomy"]["source_url"]
    script:
        "scripts/download_aves.py"

rule ingest_taxonomy:
    input:
        source_file=rules.download_aves.output.taxonomy
    output:
        touch(TAXONOMY_INGESTED)
    params:
        database=config["mongodb"]["database"]
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
        bucket=config["minio"]["audio_bucket"],
        database=config["mongodb"]["database"],
        audio_collection=config["mongodb"]["audio_collection"]
    script:
        "scripts/ingest_audio.py"

rule classify_audio:
    input:
        uploaded_manifest=rules.ingest_audio.output.uploaded_manifest
    output:
        touch(config["audio"]["classification_done_file"])
    params:
        classifier_url=config["audio"]["classifier_url"],
        log_prefix=config["minio"]["classification_log_prefix"],
        database=config["mongodb"]["database"],
        taxa_collection=config["mongodb"]["taxa_collection"],
        audio_collection=config["mongodb"]["audio_collection"],
        classification_collection=config["mongodb"]["classification_collection"]
    script:
        "scripts/classify_audio.py"

rule generate_report:
    input:
        classification_done=rules.classify_audio.output
    output:
        report=config["report"]["output_file"]
    params:
        database=config["mongodb"]["database"],
        audio_collection=config["mongodb"]["audio_collection"],
        classification_collection=config["mongodb"]["classification_collection"],
        minimum_confidence=config["report"]["minimum_confidence"],
        fuzzy_species=config.get("fuzzy_species", ""),
        fuzzy_threshold=config["report"]["fuzzy_threshold"]
    script:
        "scripts/generate_report.py"
