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
