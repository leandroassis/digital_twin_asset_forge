# Deliberately not `pip install -e .` against the full asset-forge package
# -- that would drag in ifcopenshell/pyDEXPI/pygltflib/etc, none of which
# this tiny read-only HTTP service touches. It only ever imports
# asset_forge.config (stdlib-only: os + pathlib) and asset_forge.history_api
# itself, so those two files are copied in directly instead.
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" influxdb-client

COPY src/asset_forge/config.py src/asset_forge/history_api.py /app/asset_forge/
RUN touch /app/asset_forge/__init__.py

ENV PYTHONPATH=/app
EXPOSE 8090
CMD ["uvicorn", "asset_forge.history_api:app", "--host", "0.0.0.0", "--port", "8090"]
