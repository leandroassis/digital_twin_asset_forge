# Deliberately not the full asset-forge package: visualization only ever
# needs ifcopenshell (GUID compression + the legacy express-map generator
# in pipeline/converter.py) and its own small web stack -- none of
# asset_forge's pyDEXPI/pygltflib/basyx-python-sdk dependencies are used
# here (mirrors ../history-api/Dockerfile's own reasoning for staying
# minimal).
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir ifcopenshell==0.8.5 fastapi "uvicorn[standard]" pydantic requests

COPY src/visualization src/visualization

# `network_mode: host` (see ../docker-compose.apps.yml) -- BASYX_AAS_ENV_HOST/
# BASYX_REGISTRY_HOST (visualization/config.py) default to
# "http://localhost:8081"/"...:8082", which already resolve correctly
# since aas-environment/aas-registry publish those exact ports to the
# host; same for every AAS `timeseries` submodel's Endpoint, baked at
# `asset-forge convert` time with the same "localhost" assumption.
CMD ["python", "-m", "uvicorn", "src.visualization.main:app", "--host", "0.0.0.0", "--port", "8000"]
