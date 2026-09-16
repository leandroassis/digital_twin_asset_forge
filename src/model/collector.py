"""Telemetry data collection: reads each panel's latest reading from the
history-api endpoint its `timeseries` submodel points at -- never connects
to InfluxDB directly, so this stays correct even if the storage backend
behind history-api changes (see asset_forge.integration.timeseries and
export/aas/submodels.py's build_timeseries_submodel).

Target resolution (which shells have a `timeseries` submodel, and what
Endpoint/Query it points at) is a separate, one-time step -- see
`resolve_timeseries_targets` -- deliberately not repeated on every
evaluation round: that config is static BaSyx state for the lifetime of a
`model run` process, and re-enumerating every shell in the plant (~10k for
solar-plant) on every round would be pure overhead."""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests
from loguru import logger

from asset_forge.integration.timeseries import TimeseriesTarget
from model.detector import PanelReading

_REQUIRED_FIELDS = ("LightIntensity", "Temperature", "CurrentDC")


def _fetch_one(
    session: requests.Session, target: TimeseriesTarget
) -> Tuple[TimeseriesTarget, Optional[Dict[str, float]]]:
    try:
        resp = session.get(f"{target.endpoint.rstrip('/')}/series/{target.query}", params={"count": 1}, timeout=5)
        resp.raise_for_status()
        series = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"history-api unreachable for {target.asset_tag} ({target.endpoint}): {exc}")
        return target, None

    fields = {name: points[-1]["value"] for name, points in series.items() if points}
    return target, (fields or None)


def fetch_latest_readings(
    targets: List[TimeseriesTarget],
    session: Optional[requests.Session] = None,
    max_workers: int = 16,
) -> List[PanelReading]:
    """Fetches each target's single latest reading per variable from the
    history-api endpoint it points at (skipping the virtual inverter --
    panel-level anomaly detection focuses on PV modules). `targets` is
    typically resolved once at startup via `resolve_timeseries_targets`.

    Fetches run concurrently (thread pool, default 16 workers): a real
    sensor driver (e.g. src/data_gen/send_to_basyx.py) keeps writing fresh
    rounds continuously while this sweeps every panel, so a slow, fully
    sequential sweep of ~600+ panels risks reading a torn mix of two
    different rounds across the sweep -- confirmed live: with 607 panels
    read one at a time, a handful queried late in the sweep already
    reflected the next round's values, showing up as spurious Z-score
    outliers against the rest. A short, concurrent sweep shrinks that
    window; it doesn't eliminate it (there's no cross-panel snapshot
    isolation in this design), but the tighter the sweep, the smaller the
    chance any one round change lands mid-sweep.
    """
    session = session or requests.Session()

    data_by_asset: Dict[str, Dict[str, float]] = {}
    global_id_by_asset: Dict[str, str] = {}

    targets_to_fetch = [target for target in targets if target.asset_tag != "INVERTER"]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for target, fields in executor.map(lambda t: _fetch_one(session, t), targets_to_fetch):
            if fields:
                data_by_asset[target.asset_tag] = fields
                global_id_by_asset[target.asset_tag] = target.global_id

    return build_panel_readings(data_by_asset, global_id_by_asset)


def build_panel_readings(
    data_by_asset: Dict[str, Dict[str, float]],
    tag_to_global_id: Optional[Dict[str, str]] = None,
) -> List[PanelReading]:
    """Turns `{asset_tag: {field: value}}` into `PanelReading`s, resolving each
    tag to its IFC GlobalId and skipping panels with incomplete readings."""
    tag_map = tag_to_global_id or {}
    readings: List[PanelReading] = []
    skipped: List[str] = []

    for asset_tag, fields in data_by_asset.items():
        if any(name not in fields for name in _REQUIRED_FIELDS):
            skipped.append(asset_tag)
            continue

        global_id = tag_map.get(asset_tag)
        if global_id is None:
            logger.debug(f"No GlobalId mapping for {asset_tag}; alert will use the raw tag")
            global_id = asset_tag
        readings.append(
            PanelReading(
                asset_tag=asset_tag,
                global_id=global_id,
                light_intensity=fields["LightIntensity"],
                temperature=fields["Temperature"],
                current_dc=fields["CurrentDC"],
                voltage_dc=fields.get("VoltageDC", 0.0),
            )
        )

    if skipped:
        logger.warning(
            f"Skipped {len(skipped)} panel(s) with incomplete readings "
            f"(missing one of {', '.join(_REQUIRED_FIELDS)}): {', '.join(skipped[:5])}"
        )

    return readings
