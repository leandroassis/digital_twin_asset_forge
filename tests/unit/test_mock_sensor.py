import json
import random

from asset_forge.export.aas.solar import PANEL_VARIABLES
from mock_data.mock_sensor import (
    SensorTarget,
    _derive_asset_tag,
    load_targets,
    pick_faulty_panels,
    synthetic_value,
)
from model.detector import AnomalyDetector, PanelReading


def _panel_targets(count: int):
    return [
        SensorTarget(f"sm{i}", var.id_short, f"PANEL-{i}")
        for i in range(count)
        for var in PANEL_VARIABLES
    ]


def test_pick_faulty_panels_assigns_distinct_panels_and_all_fault_types():
    targets = _panel_targets(50) + [SensorTarget("inv", "PowerAC", "INVERTER")]
    faulty = pick_faulty_panels(targets, 6, random.Random(1))

    assert len(faulty) == 6
    assert all(tag.startswith("PANEL-") for tag in faulty)
    assert set(faulty.values()) == {"Sujeira", "Sobreaquecimento", "Sobrecorrente"}
    assert pick_faulty_panels(targets, 0, random.Random(1)) == {}


def test_synthetic_field_is_healthy_and_injected_faults_are_detected():
    """Mock sensor output fed straight into the anomaly model: a normal field
    raises nothing, and each injected fault is caught with its own type."""
    rng = random.Random(42)
    targets = _panel_targets(607)
    faulty = pick_faulty_panels(targets, 3, rng)

    def readings(fault_map):
        fields = {}
        for t in targets:
            fields.setdefault(t.asset_tag, {})[t.id_short] = synthetic_value(
                t.id_short, fault_map.get(t.asset_tag), rng
            )
        return [
            PanelReading(
                asset_tag=tag,
                global_id=tag,
                light_intensity=f["LightIntensity"],
                temperature=f["Temperature"],
                current_dc=f["CurrentDC"],
                voltage_dc=f["VoltageDC"],
            )
            for tag, f in fields.items()
        ]

    detector = AnomalyDetector()
    assert detector.evaluate_batch(readings({})) == []

    alerts = {a.element_id: a.error_type for a in detector.evaluate_batch(readings(faulty))}
    assert alerts == faulty


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
