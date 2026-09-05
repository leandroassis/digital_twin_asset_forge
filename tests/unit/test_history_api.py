from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from asset_forge import history_api
from asset_forge.history_api import app, build_flux_query


@pytest.fixture
def client():
    return TestClient(app)


def test_build_flux_query_without_count_uses_a_one_hour_window():
    flux = build_flux_query("sensors", "PANEL-123", None)

    assert 'range(start: -1h)' in flux
    assert 'r["asset"] == "PANEL-123"' in flux
    assert "tail(" not in flux


def test_build_flux_query_with_count_ignores_the_time_window():
    # count means "last N that exist, ever" -- range must be wide open
    # (start: 0), not the usual -1h default, or a count could silently
    # come back empty/short just because the last write was >1h ago.
    flux = build_flux_query("sensors", "PANEL-123", 5)

    assert "range(start: 0)" in flux
    assert "tail(n: 5)" in flux


def test_get_series_rejects_an_invalid_asset_id(client):
    response = client.get("/series/not valid; drop everything")

    assert response.status_code == 400


class _FakeRecord:
    def __init__(self, field, value, time):
        self._field = field
        self._value = value
        self._time = time

    def get_field(self):
        return self._field

    def get_value(self):
        return self._value

    def get_time(self):
        return self._time


class _FakeTable:
    def __init__(self, records):
        self.records = records


def test_get_series_groups_records_by_field(client, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_tables = [
        _FakeTable([_FakeRecord("CurrentDC", 12.3, now)]),
        _FakeTable([_FakeRecord("VoltageDC", 45.6, now)]),
    ]
    monkeypatch.setattr(history_api._query_api, "query", lambda flux: fake_tables)

    response = client.get("/series/PANEL-123")

    assert response.status_code == 200
    body = response.json()
    assert body["CurrentDC"] == [{"time": now.isoformat(), "value": 12.3}]
    assert body["VoltageDC"] == [{"time": now.isoformat(), "value": 45.6}]


def test_get_series_passes_count_through_to_the_query(client, monkeypatch):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return []

    monkeypatch.setattr(history_api._query_api, "query", fake_query)

    response = client.get("/series/PANEL-123", params={"count": 10})

    assert response.status_code == 200
    assert "tail(n: 10)" in captured["flux"]
