# Aves pipeline
Fetch bird taxonomy, download sounds, classify birds with sounds, generate report with fuzzy matching.

## How to run?
Run the docker containers for MinIO and MongoDB:
```
docker compose up -d
```

Then, to run all scripts:
```
snakemake --cores 1
```

You can run specific scripts with:
```
snakemake scriptname --cores 1
```

## Configuration
You can make your own config in ``config/``, see ``config/config.yaml`` for reference.

Or if you'd like to run snakemake with specific config parameters:
```
snakemake scriptname --cores 1 --config foo="bar" bar="foo" ...
```
