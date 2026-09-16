"""Resolves every panel/inverter's `timeseries` submodel from a running
BaSyx deployment into its `Segments.LinkedSegment` (Endpoint/Query) --
mirrors what src/visualization/basyx_vis/basyx_service.py::get_telemetry_for_element
does for a single element, swept across every eligible shell in one pass.

`Query` doubles as the asset_tag (e.g. "PANEL-1529520"/"INVERTER", see
export/aas/submodels.py::build_timeseries_submodel) -- the same id InfluxDB
is tagged with -- and `Endpoint` is the history-api base URL to call it
against. A consumer resolving these live from BaSyx, instead of assuming
config.HISTORY_API_HOST/PORT, never needs to touch InfluxDB directly and
stays correct even if a given upload's timeseries submodels were built
pointing at a different history-api deployment.
"""

from typing import Any, Dict, Iterator, List, NamedTuple, Optional

import requests
from loguru import logger

from asset_forge.integration.basyx_client import _b64url


def _global_id_from_shell_id(shell_id: str) -> str:
    """asset-forge's own shells id panels as ".../aas/ifc/{GlobalId}" (see
    export/aas/shell.py::build_shell) -- the virtual inverter shell
    (".../aas/virtual/inverter") has no GlobalId, so it's returned as-is."""
    if "/aas/ifc/" in shell_id:
        return shell_id.split("/aas/ifc/", 1)[1]
    return shell_id


def _find_submodel_id(shell: Dict[str, Any], id_short: str) -> Optional[str]:
    """asset-forge's own shells always id submodels as ".../sm/{idShort}"
    (see export/aas/shell.py::build_shell) -- recover the real idShort from
    that rather than guessing from a substring."""
    for ref in shell.get("submodels", []) or []:
        keys = ref.get("keys", [])
        sm_id = keys[0].get("value") if keys else ref.get("id")
        if sm_id and sm_id.rsplit("/sm/", 1)[-1] == id_short:
            return sm_id
    return None


def _paginated_shells(aas_env_url: str, session: requests.Session, limit: int = 1000) -> Iterator[Dict[str, Any]]:
    cursor: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            response = session.get(f"{aas_env_url}/shells", params=params, timeout=10)
        except requests.RequestException as exc:
            logger.warning(f"failed to list shells from {aas_env_url}: {exc}")
            return
        if response.status_code != 200:
            logger.warning(f"failed to list shells from {aas_env_url}: {response.status_code}")
            return
        body = response.json()
        yield from body.get("result", [])
        cursor = body.get("paging_metadata", {}).get("cursor")
        if not cursor:
            return


def _read_linked_segment(aas_env_url: str, session: requests.Session, submodel_id: str) -> Optional[Dict[str, str]]:
    url = f"{aas_env_url}/submodels/{_b64url(submodel_id)}/submodel-elements"
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        elements = response.json().get("result", [])
    except requests.RequestException as exc:
        logger.warning(f"failed to read timeseries submodel {submodel_id!r}: {exc}")
        return None

    segments = next((el for el in elements if el.get("idShort") == "Segments"), None)
    if not segments:
        return None
    linked = next((el for el in segments.get("value", []) or [] if el.get("idShort") == "LinkedSegment"), None)
    if not linked:
        return None

    result: Dict[str, str] = {}
    for prop in linked.get("value", []) or []:
        if prop.get("idShort") in ("Endpoint", "Query") and prop.get("value"):
            result[prop["idShort"]] = prop["value"]
    return result if "Endpoint" in result and "Query" in result else None


class TimeseriesTarget(NamedTuple):
    asset_tag: str
    global_id: str
    endpoint: str
    query: str


def resolve_timeseries_targets(
    aas_env_host: str,
    aas_env_port: int,
    session: Optional[requests.Session] = None,
) -> List[TimeseriesTarget]:
    """Every shell carrying a `timeseries` submodel (panels + the virtual
    inverter, see export/aas/package.py) resolved to its LinkedSegment."""
    aas_env_url = f"http://{aas_env_host}:{aas_env_port}"
    session = session or requests.Session()
    targets: List[TimeseriesTarget] = []

    for shell in _paginated_shells(aas_env_url, session):
        ts_id = _find_submodel_id(shell, "timeseries")
        if not ts_id:
            continue

        linked = _read_linked_segment(aas_env_url, session, ts_id)
        if not linked:
            continue

        targets.append(
            TimeseriesTarget(
                asset_tag=linked["Query"],
                global_id=_global_id_from_shell_id(shell.get("id", "")),
                endpoint=linked["Endpoint"],
                query=linked["Query"],
            )
        )

    return targets
