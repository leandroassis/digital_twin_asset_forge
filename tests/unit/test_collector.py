from unittest.mock import MagicMock

from asset_forge.integration.timeseries import TimeseriesTarget
from model.collector import fetch_latest_readings


def _response(json_body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=json_body)
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_latest_readings_resolves_via_history_api_not_influx():
    targets = [
        TimeseriesTarget("PANEL-1", "GUID-1", "http://localhost:8090", "PANEL-1"),
        TimeseriesTarget("INVERTER", "aas/virtual/inverter", "http://localhost:8090", "INVERTER"),
    ]

    session = MagicMock()
    session.get.return_value = _response(
        {
            "LightIntensity": [{"time": "t0", "value": 900.0}, {"time": "t1", "value": 910.0}],
            "Temperature": [{"time": "t1", "value": 40.0}],
            "CurrentDC": [{"time": "t1", "value": 8.5}],
            "VoltageDC": [{"time": "t1", "value": 38.0}],
        }
    )

    readings = fetch_latest_readings(targets, session=session)

    assert len(readings) == 1  # INVERTER skipped -- panel-level detection only
    assert readings[0].asset_tag == "PANEL-1"
    assert readings[0].global_id == "GUID-1"
    assert readings[0].light_intensity == 910.0  # last point, not the first
    # only one history-api call was made -- INVERTER never queried
    assert session.get.call_count == 1
    called_url = session.get.call_args_list[0].args[0]
    assert called_url == "http://localhost:8090/series/PANEL-1"


def test_fetch_latest_readings_skips_targets_whose_history_api_is_unreachable():
    import requests

    targets = [TimeseriesTarget("PANEL-1", "GUID-1", "http://localhost:8090", "PANEL-1")]

    session = MagicMock()
    session.get.side_effect = requests.RequestException("connection refused")

    readings = fetch_latest_readings(targets, session=session)

    assert readings == []


def test_fetch_latest_readings_with_no_targets_returns_empty():
    assert fetch_latest_readings([], session=MagicMock()) == []


def test_fetch_latest_readings_fetches_every_panel_concurrently():
    targets = [
        TimeseriesTarget(f"PANEL-{i}", f"GUID-{i}", "http://localhost:8090", f"PANEL-{i}") for i in range(50)
    ]

    session = MagicMock()
    session.get.return_value = _response(
        {
            "LightIntensity": [{"time": "t0", "value": 900.0}],
            "Temperature": [{"time": "t0", "value": 40.0}],
            "CurrentDC": [{"time": "t0", "value": 8.5}],
            "VoltageDC": [{"time": "t0", "value": 38.0}],
        }
    )

    readings = fetch_latest_readings(targets, session=session, max_workers=8)

    assert len(readings) == 50
    assert session.get.call_count == 50
    assert {r.asset_tag for r in readings} == {t.asset_tag for t in targets}
