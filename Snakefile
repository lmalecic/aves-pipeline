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
