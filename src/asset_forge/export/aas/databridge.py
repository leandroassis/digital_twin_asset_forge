"""Generates the config an Eclipse BaSyx DataBridge instance needs to bridge
an external OPC UA server's writes into this plant's `opcua` submodels.

This is the concrete "API e infra necessária" contract for the mock sensor
service: it just needs to expose a Variable node named
`ns=2;s=<unique_id_prefix>-<tag_suffix>` per variable -- it never needs to
read this pipeline's source to know where a value should land in BaSyx.
Config shape (3 files, wired by matching `uniqueId`) confirmed against a
real BaSyx DataBridge deployment (`gdi-platform/infra/databridge/*.json`).
"""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from asset_forge.export.aas.solar import OpcuaVariable
from asset_forge.ingestion.loader import PathLike


@dataclass(frozen=True)
class DatabridgeContract:
    unique_id_prefix: str  # e.g. "PANEL-1529520" or "INVERTER"
    submodel_id: str  # the opcua submodel's own AAS id (assigned by build_shell/build_virtual_shell)
    variables: Sequence[OpcuaVariable]


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def write_databridge_config(
    output_dir: PathLike,
    contracts: Sequence[DatabridgeContract],
    opcua_host: str,
    opcua_port: int,
    aas_env_host: str,
    aas_env_port: int,
) -> List[Path]:
    """Write `opcuaconsumer.json`/`aasserver.json`/`routes.json` into
    `output_dir`, one entry per (contract, variable) pair. Returns the 3
    paths written, in that order."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    consumers, sinks, routes = [], [], []
    for contract in contracts:
        encoded_submodel_id = _b64url(contract.submodel_id)
        for variable in contract.variables:
            node_id = f"{contract.unique_id_prefix}-{variable.tag_suffix}"
            consumers.append(
                {
                    "uniqueId": f"opcua-{node_id}",
                    "serverUrl": opcua_host,
                    "serverPort": opcua_port,
                    "pathToService": "",
                    "nodeInformation": f"ns=2;s={node_id}",
                    "requestedPublishingInterval": 1000,
                }
            )
            sinks.append(
                {
                    "uniqueId": f"aas-{node_id}",
                    "submodelEndpoint": f"http://{aas_env_host}:{aas_env_port}/submodels/{encoded_submodel_id}",
                    "idShortPath": variable.id_short,
                    "api": "DOT_AAS_V3",
                }
            )
            routes.append(
                {
                    "routeId": f"route-{node_id}",
                    "datasource": f"opcua-{node_id}",
                    "datasinks": [f"aas-{node_id}"],
                    "trigger": "event",
                }
            )

    paths = []
    for filename, payload in (
        ("opcuaconsumer.json", consumers),
        ("aasserver.json", sinks),
        ("routes.json", routes),
    ):
        path = output_dir / filename
        path.write_text(json.dumps(payload, indent=2))
        paths.append(path)

    return paths
