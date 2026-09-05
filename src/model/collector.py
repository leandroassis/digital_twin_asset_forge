"""Telemetry data collection and identity resolution (Asset Tag -> IFC GlobalId)."""

import base64
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from influxdb_client import InfluxDBClient
from loguru import logger

from asset_forge import config
from model.detector import PanelReading

_B64_PAD_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _decode_b64url(s: str) -> str:
    """Decodes a base64url string with or without padding."""
    remainder = len(s) % 4
    if remainder > 0:
        s += "=" * (4 - remainder)
    return base64.urlsafe_b64decode(s.encode("utf-8")).decode("utf-8", errors="ignore")


def load_tag_to_global_id_map(aasserver_path: Optional[Path] = None) -> Dict[str, str]:
    """Extracts mapping from `asset_tag` (e.g. 'PANEL-1529520') to IFC `GlobalId`.

    `aasserver.json` holds the base64-encoded submodel URI in `submodelEndpoint`,
    which follows the pipeline's schema: `.../aas/ifc/{GlobalId}/sm/opcua`.
    """
    path = aasserver_path or (config.DATABRIDGE_DIR / "aasserver.json")
    tag_map: Dict[str, str] = {}

    if not path.exists():
        logger.warning(f"Route file {path} not found. GlobalIds will not be resolved from databridge config.")
        return tag_map

    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        for entry in entries:
            # uniqueId e.g. "opcua-PANEL-1529520-LUX" -> asset_tag: "PANEL-1529520"
            raw_id = entry.get("uniqueId", "")
            if raw_id.startswith("opcua-"):
                raw_id = raw_id[len("opcua-") :]
            asset_tag = raw_id.rsplit("-", 1)[0] if "-" in raw_id else raw_id

            # submodelEndpoint e.g. ".../submodels/aHR0cHM6Ly9leGFtcGxlLm9yZy9hc3NldC1mb3JnZS9hYXMvaWZjLzJR.../..."
            endpoint = entry.get("submodelEndpoint", "")
            if "/submodels/" in endpoint:
                b64_part = endpoint.split("/submodels/")[1].split("/")[0]
                decoded_uri = _decode_b64url(b64_part)
                # URI e.g.: "https://example.org/asset-forge/aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/opcua"
                if "/aas/ifc/" in decoded_uri:
                    global_id = decoded_uri.split("/aas/ifc/")[1].split("/sm/")[0]
                    tag_map[asset_tag] = global_id
    except Exception as exc:
        logger.warning(f"Error parsing databridge tag mappings from {path}: {exc}")

    return tag_map


def fetch_latest_readings_from_influx(
    influx_host: str = config.INFLUXDB_HOST,
    influx_port: int = config.INFLUXDB_PORT,
    influx_token: str = config.INFLUXDB_TOKEN,
    influx_org: str = config.INFLUXDB_ORG,
    influx_bucket: str = config.INFLUXDB_BUCKET,
    tag_to_global_id: Optional[Dict[str, str]] = None,
    time_window: str = "-15m",
) -> List[PanelReading]:
    """Fetches the latest reading of every variable across all panels from InfluxDB.

    Executes a single high-performance Flux query, aggregating all metrics per panel.
    """
    tag_map = tag_to_global_id or {}
    client = InfluxDBClient(url=f"http://{influx_host}:{influx_port}", token=influx_token, org=influx_org)
    query_api = client.query_api()

    # Flux query: retrieve only the latest readings across all sensor fields
    flux = f"""
    from(bucket: "{influx_bucket}")
      |> range(start: {time_window})
      |> filter(fn: (r) => r["_measurement"] == "sensor_reading")
      |> last()
    """

    try:
        tables = query_api.query(flux)
    except Exception as exc:
        logger.error(f"Error querying InfluxDB ({influx_host}:{influx_port}): {exc}")
        return []

    data_by_asset: Dict[str, Dict[str, float]] = {}

    for table in tables:
        for record in table.records:
            asset_tag = record.values.get("asset")
            if not asset_tag or asset_tag == "INVERTER":
                continue  # Panel-level anomaly detection focuses on PV modules

            field = record.get_field()
            value = float(record.get_value() or 0.0)

            if asset_tag not in data_by_asset:
                data_by_asset[asset_tag] = {}
            data_by_asset[asset_tag][field] = value

    readings: List[PanelReading] = []
    for asset_tag, fields in data_by_asset.items():
        global_id = tag_map.get(asset_tag, asset_tag)
        readings.append(
            PanelReading(
                asset_tag=asset_tag,
                global_id=global_id,
                light_intensity=fields.get("LightIntensity", 0.0),
                temperature=fields.get("Temperature", 0.0),
                current_dc=fields.get("CurrentDC", 0.0),
                voltage_dc=fields.get("VoltageDC", 0.0),
            )
        )

    return readings
