"""Central place for environment/CLI-configurable settings."""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent  # src/asset_forge
REPO_ROOT = PACKAGE_ROOT.parent.parent

SUBMODEL_TEMPLATE_CACHE_DIR = Path(
    os.environ.get("ASSET_FORGE_TEMPLATE_CACHE", str(REPO_ROOT / "data" / "submodels"))
)

DEFAULT_NAMESPACE = os.environ.get("ASSET_FORGE_NAMESPACE", "example.org/asset-forge")

AAS_ENV_HOST = os.environ.get("AAS_ENV_HOST", "localhost")
AAS_ENV_PORT = int(os.environ.get("AAS_ENV_PORT", "8081"))
AAS_REGISTRY_HOST = os.environ.get("AAS_REGISTRY_HOST", "localhost")
AAS_REGISTRY_PORT = int(os.environ.get("AAS_REGISTRY_PORT", "8082"))

# OPC UA connection info is only ever baked into the AAS "OPC UA datasheet"
# submodel as configuration -- no OPC UA client/server code exists in this
# package. See export/aas/submodels.py.
OPCUA_HOST = os.environ.get("OPCUA_HOST", "localhost")
OPCUA_PORT = int(os.environ.get("OPCUA_PORT", "4840"))

# Where the BaSyx DataBridge config bridging an external OPC UA server's
# writes into this plant's AAS submodels gets written. See
# export/aas/databridge.py; mounted into the `databridge` service in
# infra/docker-compose.yml.
DATABRIDGE_DIR = Path(os.environ.get("ASSET_FORGE_DATABRIDGE_DIR", str(REPO_ROOT / "infra" / "databridge")))

# Real historized sensor storage (see export/aas/submodels.py's
# build_timeseries_submodel and mock_sensor.py) -- BaSyx itself only ever
# holds each Property's *current* value, never a history, regardless of
# backend. Token/org/bucket defaults match infra/docker-compose.yml's
# `influxdb` service; this is a local dev stack, not a secret worth
# protecting.
INFLUXDB_HOST = os.environ.get("INFLUXDB_HOST", "localhost")
INFLUXDB_PORT = int(os.environ.get("INFLUXDB_PORT", "8086"))
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "asset-forge")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "sensors")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "asset-forge-dev-token")

# The intermediary history-query service (history_api.py) -- the `timeseries`
# submodel's LinkedSegment now points here, not at InfluxDB directly, and
# carries a plain asset id (e.g. "PANEL-1529520") as its Query instead of a
# raw Flux string. See infra/history-api/Dockerfile + docker-compose.yml.
HISTORY_API_HOST = os.environ.get("HISTORY_API_HOST", "localhost")
HISTORY_API_PORT = int(os.environ.get("HISTORY_API_PORT", "8090"))
