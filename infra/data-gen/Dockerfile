# Full asset-forge package install (see ../model/Dockerfile's comment for
# why) -- data_gen isn't itself an installable package (no __init__.py,
# see its own README), so its scripts are copied in as plain files and run
# directly; they still import asset_forge.integration.sensor_targets/
# export.aas.solar/config, hence installing the real package alongside.
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/asset_forge src/asset_forge
RUN pip install --no-cache-dir -e . pandas

COPY src/data_gen src/data_gen

# `network_mode: host` (see ../docker-compose.apps.yml) makes "localhost"
# resolve to the same host ports aas-environment/influxdb are published
# on, so the script's own "localhost" defaults (asset_forge/config.py)
# need no override here. This is the continuous sensor-simulation loop
# (the "service"); one-off runs of generate_profiles_cli.py use this same
# image with a different command, e.g.:
#   docker compose -f infra/docker-compose.yml -f infra/docker-compose.apps.yml \
#     run --rm data-gen python src/data_gen/generate_profiles_cli.py --mode perturbed --seed 42
CMD ["python", "src/data_gen/send_to_basyx.py"]
