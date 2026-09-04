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

