# Installs the full asset-forge package (ifcopenshell, pyDEXPI,
# basyx-python-sdk etc. included) rather than a minimal image like
# history-api's own -- model/collector.py imports asset_forge.integration.*
# directly, so this keeps that code identical to what `asset-forge
# convert`/`basyx upload` already run with, at the cost of a heavier image.
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/asset_forge src/asset_forge
COPY src/model src/model
RUN pip install --no-cache-dir -e .

# `network_mode: host` (see ../docker-compose.apps.yml) makes "localhost"
# inside this container resolve to the same host ports aas-environment/
# history-api are already published on, so the CLI's own "localhost"
# defaults (asset_forge/config.py) -- and the WORKDIR-relative default
# config path below -- are correct as-is; no --host-aas-env/--viz-url
# overrides needed here.
ENTRYPOINT ["asset-forge", "model", "run"]
