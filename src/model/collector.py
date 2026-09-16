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

from typing import Dict, List, Optional

import requests
from loguru import logger

from asset_forge.integration.timeseries import TimeseriesTarget
from model.detector import PanelReading

_REQUIRED_FIELDS = ("LightIntensity", "Temperature", "CurrentDC")


def fetch_latest_readings(
    targets: List[TimeseriesTarget],
    session: Optional[requests.Session] = None,
) -> List[PanelReading]:
    """Fetches each target's single latest reading per variable from the
    history-api endpoint it points at (skipping the virtual inverter --
    panel-level anomaly detection focuses on PV modules). `targets` is
    typically resolved once at startup via `resolve_timeseries_targets`."""
    session = session or requests.Session()

    data_by_asset: Dict[str, Dict[str, float]] = {}
    global_id_by_asset: Dict[str, str] = {}

    for target in targets:
        if target.asset_tag == "INVERTER":
            continue

        try:
            resp = session.get(
                f"{target.endpoint.rstrip('/')}/series/{target.query}", params={"count": 1}, timeout=5
            )
            resp.raise_for_status()
            series = resp.json()
        except requests.RequestException as exc:
            logger.warning(f"history-api unreachable for {target.asset_tag} ({target.endpoint}): {exc}")
            continue

        fields = {name: points[-1]["value"] for name, points in series.items() if points}
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
