import json

from mock_data.mock_sensor import SensorTarget, _derive_asset_tag, load_targets


def test_load_targets_parses_aasserver_json_sinks(tmp_path):
    aasserver_path = tmp_path / "aasserver.json"
    aasserver_path.write_text(
        json.dumps(
            [
                {
                    "uniqueId": "aas-PANEL-1529520-IDC",
                    "submodelEndpoint": "http://aas-environment:8081/submodels/abc123/",
                    "idShortPath": "CurrentDC",
                    "api": "DOT_AAS_V3",
                },
                {
                    "uniqueId": "aas-INVERTER-PAC",
                    "submodelEndpoint": "http://aas-environment:8081/submodels/def456",
                    "idShortPath": "PowerAC",
                    "api": "DOT_AAS_V3",
                },
            ]
        )
    )

    targets = load_targets(aasserver_path)

    assert SensorTarget("abc123/", "CurrentDC", "PANEL-1529520") in targets
    assert SensorTarget("def456", "PowerAC", "INVERTER") in targets
    assert len(targets) == 2


def test_derive_asset_tag_strips_known_variable_suffix():
    assert _derive_asset_tag("PANEL-1529520-IDC") == "PANEL-1529520"
    assert _derive_asset_tag("PANEL-1529520-LUX") == "PANEL-1529520"
    assert _derive_asset_tag("INVERTER-PAC") == "INVERTER"
    assert _derive_asset_tag("UNKNOWN-FORMAT") == "UNKNOWN-FORMAT"


def test_load_targets_with_empty_list_returns_empty(tmp_path):
    aasserver_path = tmp_path / "aasserver.json"
    aasserver_path.write_text("[]")

    assert load_targets(aasserver_path) == []
