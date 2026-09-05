from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "visualization"))

from basyx_vis.basyx_service import VisualizationBasyxService, b64url, b64url_decode

def test_b64url_encoding():
    original = "https://example.org/aas/12345"
    encoded = b64url(original)
    assert "=" not in encoded
    decoded = b64url_decode(encoded)
    assert decoded == original

def test_get_all_shells_mock():
    service = VisualizationBasyxService()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": [
            {"id": "shell_1", "idShort": "SolarPanel_1", "assetInformation": {"globalAssetId": "12345"}}
        ]
    }

    with patch.object(service._session, "get", return_value=mock_response):
        shells = service.get_all_shells()
        assert len(shells) == 1
        assert shells[0]["idShort"] == "SolarPanel_1"

def test_build_tree_from_basyx_mock():
    service = VisualizationBasyxService()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": [
            {"id": "shell_inv", "idShort": "Inverter_Main", "assetInformation": {"globalAssetId": "INV001"}},
            {"id": "shell_pv", "idShort": "PV_Modul_01", "assetInformation": {"globalAssetId": "PV001"}}
        ]
    }

    with patch.object(service._session, "get", return_value=mock_response):
        tree = service.build_tree_from_basyx()
        assert tree["type"] == "AASRepository"
        assert len(tree["children"]) == 2

def test_get_shell_by_global_id_uuid_conversion():
    service = VisualizationBasyxService()
    # UUID '872196f4-e2d8-4c51-86d3-d7ccaf742cae' maps to IFC GUID '278PRqujXCKORJryolT2ok'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": [
            {
                "id": "https://example.org/asset-forge/aas/ifc/278PRqujXCKORJryolT2ok",
                "idShort": "HVAC-AS-AHU-B05_906281",
                "assetInformation": {"globalAssetId": "https://example.org/asset-forge/asset/ifc/278PRqujXCKORJryolT2ok"}
            }
        ]
    }

    with patch.object(service._session, "get", return_value=mock_response):
        # Pass GLB mesh name format: product-<uuid>-body
        shell = service.get_shell_by_global_id("product-872196f4-e2d8-4c51-86d3-d7ccaf742cae-body")
        assert shell is not None
        assert shell["idShort"] == "HVAC-AS-AHU-B05_906281"


def test_get_telemetry_for_element_follows_linked_segment_to_history_api():
    service = VisualizationBasyxService()

    shells_response = MagicMock(status_code=200)
    shells_response.json.return_value = {
        "result": [
            {
                "id": "https://example.org/asset-forge/aas/ifc/PANEL123",
                "idShort": "SolarPanel_1",
                "assetInformation": {"globalAssetId": "https://example.org/asset-forge/asset/ifc/PANEL123"},
                "submodels": [{"keys": [{"type": "Submodel", "value": "sm-timeseries-panel123"}]}],
            }
        ]
    }

    elements_response = MagicMock(status_code=200)
    elements_response.json.return_value = {
        "result": [
            {
                "idShort": "Segments",
                "modelType": "SubmodelElementCollection",
                "value": [
                    {
                        "idShort": "LinkedSegment",
                        "modelType": "SubmodelElementCollection",
                        "value": [
                            {"idShort": "Endpoint", "modelType": "Property", "value": "http://localhost:8090"},
                            {"idShort": "Query", "modelType": "Property", "value": "PANEL-123"},
                        ],
                    }
                ],
            }
        ]
    }

    series_response = MagicMock(status_code=200)
    series_response.json.return_value = {
        "CurrentDC": [{"time": "2026-01-01T00:00:00+00:00", "value": 9.1}],
        "VoltageDC": [{"time": "2026-01-01T00:00:00+00:00", "value": 38.2}],
    }

    def fake_get(url, *args, **kwargs):
        if url.endswith("/shells?limit=15000"):
            return shells_response
        if "/submodel-elements" in url:
            return elements_response
        if url == "http://localhost:8090/series/PANEL-123":
            return series_response
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(service._session, "get", side_effect=fake_get):
        telemetry = service.get_telemetry_for_element("PANEL123")

    assert telemetry["foundInBasyx"] is True
    assert telemetry["type"] == "SolarPanel"
    assert telemetry["metrics"] == {"currentDC": [9.1], "voltageDC": [38.2]}
    assert telemetry["timestamps"] == ["2026-01-01T00:00:00+00:00"]


def test_get_submodel_tree_for_element_reconstructs_every_submodel_as_a_nested_tree():
    service = VisualizationBasyxService()

    shells_response = MagicMock(status_code=200)
    shells_response.json.return_value = {
        "result": [
            {
                "id": "https://example.org/asset-forge/aas/ifc/PANEL123",
                "idShort": "SolarPanel_1",
                "assetInformation": {"globalAssetId": "https://example.org/asset-forge/asset/ifc/PANEL123"},
                "submodels": [
                    {"keys": [{"type": "Submodel", "value": "https://example.org/aas/ifc/PANEL123/sm/nameplate"}]},
                    {"keys": [{"type": "Submodel", "value": "https://example.org/aas/ifc/PANEL123/sm/timeseries"}]},
                ],
            }
        ]
    }

    nameplate_elements = MagicMock(status_code=200)
    nameplate_elements.json.return_value = {
        "result": [{"idShort": "UniqueFacilityIdentifier", "modelType": "Property", "value": "PANEL123"}]
    }
    timeseries_elements = MagicMock(status_code=200)
    timeseries_elements.json.return_value = {
        "result": [
            {
                "idShort": "Segments",
                "modelType": "SubmodelElementCollection",
                "value": [
                    {
                        "idShort": "LinkedSegment",
                        "modelType": "SubmodelElementCollection",
                        "value": [
                            {"idShort": "Endpoint", "modelType": "Property", "value": "http://localhost:8090"},
                            {"idShort": "Query", "modelType": "Property", "value": "PANEL-123"},
                        ],
                    }
                ],
            }
        ]
    }

    nameplate_url_part = b64url("https://example.org/aas/ifc/PANEL123/sm/nameplate")
    timeseries_url_part = b64url("https://example.org/aas/ifc/PANEL123/sm/timeseries")

    def fake_get(url, *args, **kwargs):
        if url.endswith("/shells?limit=15000"):
            return shells_response
        if nameplate_url_part in url:
            return nameplate_elements
        if timeseries_url_part in url:
            return timeseries_elements
        raise AssertionError(f"unexpected URL {url}")

    with patch.object(service._session, "get", side_effect=fake_get):
        tree = service.get_submodel_tree_for_element("PANEL123")

    assert tree["foundInBasyx"] is True
    assert [sm["idShort"] for sm in tree["submodels"]] == ["nameplate", "timeseries"]

    nameplate_sm = tree["submodels"][0]
    assert nameplate_sm["children"] == [
        {"idShort": "UniqueFacilityIdentifier", "modelType": "Property", "value": "PANEL123"}
    ]

    timeseries_sm = tree["submodels"][1]
    segments = timeseries_sm["children"][0]
    assert segments["idShort"] == "Segments"
    linked_segment = segments["children"][0]
    assert linked_segment["idShort"] == "LinkedSegment"
    assert {c["idShort"]: c["value"] for c in linked_segment["children"]} == {
        "Endpoint": "http://localhost:8090",
        "Query": "PANEL-123",
    }


def test_get_telemetry_for_element_returns_empty_shape_when_shell_not_found():
    service = VisualizationBasyxService()
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"result": []}

    with patch.object(service._session, "get", return_value=mock_response):
        telemetry = service.get_telemetry_for_element("does-not-exist")

    assert telemetry == {
        "globalId": "does-not-exist",
        "type": "Unknown",
        "metrics": {},
        "timestamps": [],
        "foundInBasyx": False,
    }

