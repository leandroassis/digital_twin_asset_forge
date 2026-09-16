"""Parses `infra/databridge/aasserver.json` (see export/aas/databridge.py)
into typed `(submodel, idShort)` write targets, and reads/writes the
matching BaSyx `$value` endpoints.

Shared by every sensor data driver -- real or simulated -- so each one
exercises exactly the same (submodel, idShortPath) pairs the real BaSyx
DataBridge would write to, without re-deriving the panel/inverter list.
`src/data_gen/send_to_basyx.py` (physically-simulated readings) is the
in-repo driver that uses this; a real OPC UA server would reach the same
targets through the DataBridge bridge instead of this module.

Confirmed live against a real BaSyx aas-environment (2.0.0-SNAPSHOT): the
`$value` PATCH body must be the value JSON-encoded *as a string* (e.g.
`"42.5"`, not a bare `42.5`) -- a bare JSON number 500s. This matches AAS's
ValueOnly serialization, which represents xs:double/xs:float this way to
avoid cross-language precision loss; GET on the same endpoint returns the
same quoted-string form.
"""

import json
from pathlib import Path
from typing import List, NamedTuple

import requests

from asset_forge.export.aas.solar import INVERTER_VARIABLES, PANEL_VARIABLES
from asset_forge.ingestion.loader import PathLike

# Longest-suffix-first so e.g. a hypothetical "DC" wouldn't shadow "VDC".
_ALL_TAG_SUFFIXES = tuple(
    sorted({v.tag_suffix for v in (*PANEL_VARIABLES, *INVERTER_VARIABLES)}, key=len, reverse=True)
)


class SensorTarget(NamedTuple):
    submodel_id_b64: str
    id_short: str
    asset_tag: str


def _derive_asset_tag(node_id: str) -> str:
    for suffix in _ALL_TAG_SUFFIXES:
        marker = f"-{suffix}"
        if node_id.endswith(marker):
            return node_id[: -len(marker)]
    return node_id


def load_targets(aasserver_path: PathLike) -> List[SensorTarget]:
    """Parse `aasserver.json`'s sink entries into (submodel id, idShort,
    asset tag) targets. Only the base64url submodel id and idShortPath are
    kept from `submodelEndpoint` -- that also bakes in a host/port, but
    that's the in-Docker-network hostname (e.g. "aas-environment"), not
    necessarily reachable from wherever this runs."""
    entries = json.loads(Path(aasserver_path).read_text())
    targets = []
    for entry in entries:
        submodel_id_b64 = entry["submodelEndpoint"].rsplit("/submodels/", 1)[1]
        node_id = entry["uniqueId"][len("aas-") :] if entry["uniqueId"].startswith("aas-") else entry["uniqueId"]
        targets.append(SensorTarget(submodel_id_b64, entry["idShortPath"], _derive_asset_tag(node_id)))
    return targets


def _value_url(host: str, port: int, target: SensorTarget) -> str:
    return f"http://{host}:{port}/submodels/{target.submodel_id_b64}/submodel-elements/{target.id_short}/$value"


def write_value(host: str, port: int, target: SensorTarget, value: float) -> None:
    resp = requests.patch(_value_url(host, port, target), json=str(value), timeout=10)
    resp.raise_for_status()


def read_value(host: str, port: int, target: SensorTarget) -> float:
    resp = requests.get(_value_url(host, port, target), timeout=10)
    resp.raise_for_status()
    return float(resp.json())
