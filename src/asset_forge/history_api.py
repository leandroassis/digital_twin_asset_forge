"""Intermediary history-query service: sits in front of InfluxDB so the AAS
`timeseries` submodel's `LinkedSegment` never needs to carry a raw Flux
query. Instead, `Endpoint` holds this service's own base URL and `Query`
holds a plain opaque asset id (e.g. "PANEL-1529520") -- see
export/aas/submodels.py::build_timeseries_submodel. Whoever reads that
submodel (the visualizer, in the target architecture) calls this service
with that same id and gets JSON back; nothing outside this module needs to
know Flux, or even that InfluxDB specifically is the storage backend behind
it, so that choice can change later without touching anything already
uploaded to BaSyx.

    GET /series/{asset_id}          -- every point in the last hour
    GET /series/{asset_id}?count=N  -- only the last N points per variable,
                                       regardless of how long ago (an
                                       all-time lookup, not windowed to the
                                       last hour -- "count" means "give me
                                       the last N that exist", not "the
                                       last N of the last hour's worth")

Run standalone with `uvicorn asset_forge.history_api:app`; containerized by
infra/history-api/Dockerfile, wired into infra/docker-compose.yml.
"""

import re
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from influxdb_client import InfluxDBClient
from pydantic import BaseModel

from asset_forge.config import INFLUXDB_BUCKET, INFLUXDB_HOST, INFLUXDB_ORG, INFLUXDB_PORT, INFLUXDB_TOKEN

app = FastAPI(title="asset-forge history-api")

# Asset ids are only ever produced by this pipeline itself (see
# export/aas/solar.py -- "PANEL-<tag>"/"INVERTER"), so this is a defensive
# allow-list against Flux injection via a crafted path parameter, not a
# real-world naming constraint.
_ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

_client = InfluxDBClient(url=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}", token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
_query_api = _client.query_api()


class SeriesPoint(BaseModel):
    time: str
    value: float


def build_flux_query(bucket: str, asset_id: str, count: Optional[int]) -> str:
    """`count` bypasses the usual time window entirely (`range(start: 0)`)
    -- Flux's `range` filters *before* `tail` ever runs, so a short default
    window would silently return fewer than N points (or none) whenever
    the last write happened to be older than that window, even though N
    real points exist further back."""
    if count:
        range_clause = "range(start: 0)"
        tail_clause = f" |> tail(n: {int(count)})"
    else:
        range_clause = "range(start: -1h)"
        tail_clause = ""

    return (
        f'from(bucket: "{bucket}") |> {range_clause} '
        f'|> filter(fn: (r) => r["_measurement"] == "sensor_reading" and r["asset"] == "{asset_id}")'
        f"{tail_clause}"
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/series/{asset_id}")
def get_series(
    asset_id: str,
    count: Optional[int] = Query(None, ge=1, description="last N points per variable, regardless of age"),
) -> Dict[str, List[SeriesPoint]]:
    if not _ASSET_ID_PATTERN.match(asset_id):
        raise HTTPException(status_code=400, detail="invalid asset id")

    flux = build_flux_query(INFLUXDB_BUCKET, asset_id, count)
    tables = _query_api.query(flux)

    series: Dict[str, List[SeriesPoint]] = {}
    for table in tables:
        for record in table.records:
            series.setdefault(record.get_field(), []).append(
                SeriesPoint(time=record.get_time().isoformat(), value=record.get_value())
            )

    return series
