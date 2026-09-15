"""Unit tests for the AI Anomaly Detection Model (src/model) including a dedicated Mock Sensor Simulator."""

import json
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from model.collector import build_panel_readings, load_tag_to_global_id_map
from model.detector import AnomalyDetector, PanelReading, compute_z_scores
from model.notifier import AlertNotifier
from model.rules import AlertPayload, AnomalyThresholds, FaultType, evaluate_panel


class MockSolarSensorSimulator:
    """Dedicated in-test solar plant sensor simulator with controlled fault injection.

    Allows testing the anomaly detection model without relying on external services or modifying mock_sensor.py.
    """

    def __init__(self, num_panels: int = 50, seed: int = 42):
        self.num_panels = num_panels
        self.rng = np.random.default_rng(seed)

    def generate_readings(
        self,
        fault_type: Optional[str] = None,
        faulty_indices: Optional[Dict[int, str]] = None,
    ) -> List[PanelReading]:
        """Generates a batch of physical panel readings across the solar field."""
        # 1. Simulate plant-wide night condition
        if fault_type == "noite":
            return [
                PanelReading(
                    asset_tag=f"PANEL-{1000 + i}",
                    global_id=f"GUID_{1000 + i}",
                    light_intensity=float(self.rng.normal(15.0, 2.0)),
                    temperature=float(self.rng.normal(20.0, 1.0)),
                    current_dc=0.0,
                    voltage_dc=0.0,
                )
                for i in range(self.num_panels)
            ]

        # 2. Normal daylight baseline with realistic physical correlation
        readings = []
        for i in range(self.num_panels):
            light = float(self.rng.normal(850.0, 10.0))
            temp = float(self.rng.normal(38.0, 1.0))
            current = float(self.rng.normal(8.5, 0.2))
            voltage = float(self.rng.normal(38.0, 0.3))

            # Apply specific injected fault if requested for this panel index
            assigned_fault = (faulty_indices or {}).get(i)
            if assigned_fault == "Sujeira":
                current = float(self.rng.normal(2.5, 0.1))  # Heavy generation loss from dirt
            elif assigned_fault == "Sobreaquecimento":
                temp = float(self.rng.normal(76.0, 1.0))  # Thermal hotspot
            elif assigned_fault == "Sobrecorrente":
                current = float(self.rng.normal(22.0, 0.3))  # Current surge

            readings.append(
                PanelReading(
                    asset_tag=f"PANEL-{1000 + i}",
                    global_id=f"GUID_{1000 + i}",
                    light_intensity=light,
                    temperature=temp,
                    current_dc=current,
                    voltage_dc=voltage,
                )
            )

        return readings


def test_compute_z_scores_basic():
    values = np.array([10.0, 10.0, 10.0, 10.0, 100.0])
    z = compute_z_scores(values)
    assert len(z) == 5
    assert z[-1] > 1.5  # 100.0 is an unmistakable positive outlier
    assert z[0] < 0.0


def test_compute_z_scores_zero_variance():
    # If all readings are identical, std is zero and no division by zero should occur
    values = np.array([5.0, 5.0, 5.0])
    z = compute_z_scores(values)
    assert np.all(z == 0.0)


def test_compute_z_scores_empty():
    z = compute_z_scores(np.array([]))
    assert len(z) == 0


def test_evaluate_panel_normal_operation():
    alert = evaluate_panel(
        element_id="PANEL_001",
        light_val=800.0,
        temp_val=38.0,
        current_val=8.5,
        temp_z=0.1,
        current_z=-0.2,
        avg_light=800.0,
    )
    assert alert is None


def test_evaluate_panel_night_detection():
    alert = evaluate_panel(
        element_id="PANEL_001",
        light_val=10.0,
        temp_val=20.0,
        current_val=0.0,
        temp_z=0.0,
        current_z=0.0,
        avg_light=15.0,
    )
    assert alert is not None
    assert alert.error_type == FaultType.NIGHT.value
    assert alert.severity == "info"


def test_evaluate_panel_overcurrent():
    alert = evaluate_panel(
        element_id="PANEL_002",
        light_val=850.0,
        temp_val=40.0,
        current_val=22.0,
        temp_z=0.2,
        current_z=3.5,
        avg_light=850.0,
    )
    assert alert is not None
    assert alert.error_type == FaultType.OVERCURRENT.value
    assert alert.severity == "critical"


def test_evaluate_panel_overheat():
    alert = evaluate_panel(
        element_id="PANEL_003",
        light_val=850.0,
        temp_val=75.0,
        current_val=8.2,
        temp_z=3.2,
        current_z=-0.5,
        avg_light=850.0,
    )
    assert alert is not None
    assert alert.error_type == FaultType.OVERHEAT.value
    assert alert.severity == "critical"


def test_evaluate_panel_dirt():
    alert = evaluate_panel(
        element_id="PANEL_004",
        light_val=850.0,
        temp_val=37.0,
        current_val=2.5,
        temp_z=-0.4,
        current_z=-2.9,
        avg_light=850.0,
    )
    assert alert is not None
    assert alert.error_type == FaultType.DIRT.value
    assert alert.severity == "warning"


def test_custom_thresholds_configuration():
    # Demonstrates easily adjustable detection sensitivity
    custom_thresholds = AnomalyThresholds(
        z_score_dirt=-1.5,
        z_score_overheat=1.8,
        night_lux_threshold=100.0,
    )

    alert = evaluate_panel(
        element_id="PANEL_005",
        light_val=600.0,
        temp_val=40.0,
        current_val=6.0,
        temp_z=0.0,
        current_z=-1.8,
        avg_light=600.0,
        thresholds=custom_thresholds,
    )
    assert alert is not None
    assert alert.error_type == FaultType.DIRT.value


def test_mock_sensor_simulation_normal_field():
    simulator = MockSolarSensorSimulator(num_panels=60)
    readings = simulator.generate_readings()

    detector = AnomalyDetector()
    alerts = detector.evaluate_batch(readings)

    # In a normal simulated field, no anomaly should be flagged
    assert len(alerts) == 0


def test_mock_sensor_simulation_with_all_injected_faults():
    simulator = MockSolarSensorSimulator(num_panels=60)
    # Inject 3 specific faults in panels 5, 15, and 25
    faulty_indices = {
        5: "Sujeira",
        15: "Sobreaquecimento",
        25: "Sobrecorrente",
    }
    readings = simulator.generate_readings(faulty_indices=faulty_indices)

    detector = AnomalyDetector()
    alerts = detector.evaluate_batch(readings)

    alert_map = {a.element_id: a.error_type for a in alerts}

    # Verify each injected fault is successfully caught by the spatial Z-Score detector
    assert "GUID_1005" in alert_map
    assert alert_map["GUID_1005"] == FaultType.DIRT.value

    assert "GUID_1015" in alert_map
    assert alert_map["GUID_1015"] == FaultType.OVERHEAT.value

    assert "GUID_1025" in alert_map
    assert alert_map["GUID_1025"] == FaultType.OVERCURRENT.value


def test_mock_sensor_simulation_night_condition():
    simulator = MockSolarSensorSimulator(num_panels=30)
    readings = simulator.generate_readings(fault_type="noite")

    detector = AnomalyDetector()
    alerts = detector.evaluate_batch(readings)

    assert len(alerts) == 30
    assert all(a.error_type == FaultType.NIGHT.value for a in alerts)


@pytest.mark.parametrize("unique_id", ["aas-PANEL-1529520-LUX", "opcua-PANEL-1529520-LUX"])
def test_load_tag_to_global_id_map(tmp_path, unique_id):
    aasserver_file = tmp_path / "aasserver.json"
    import base64

    fake_uri = "https://example.org/asset-forge/aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/opcua"
    b64_uri = base64.urlsafe_b64encode(fake_uri.encode()).decode().rstrip("=")

    # Same shape databridge.py writes: "aas-" prefix, no trailing path after the id
    content = [
        {
            "uniqueId": unique_id,
            "submodelEndpoint": f"http://localhost:8081/submodels/{b64_uri}",
            "idShortPath": "LightIntensity",
            "api": "DOT_AAS_V3",
        }
    ]
    aasserver_file.write_text(json.dumps(content))

    tag_map = load_tag_to_global_id_map(aasserver_file)
    assert tag_map == {"PANEL-1529520": "2QF3$F$XHF1A$PuubJ8dJ8"}


def test_load_tag_to_global_id_map_against_generated_databridge_config():
    from asset_forge import config

    aasserver_path = config.DATABRIDGE_DIR / "aasserver.json"
    if not aasserver_path.is_file():
        pytest.skip("infra/databridge/aasserver.json not generated")

    tag_map = load_tag_to_global_id_map(aasserver_path)
    assert tag_map, "no panel mappings resolved from the generated databridge config"
    assert all(tag.startswith("PANEL-") for tag in tag_map)


def test_build_panel_readings_resolves_global_id_and_skips_incomplete():
    data = {
        "PANEL-1": {"LightIntensity": 900.0, "Temperature": 40.0, "CurrentDC": 8.5, "VoltageDC": 38.0},
        "PANEL-2": {"LightIntensity": 900.0, "Temperature": 40.0},  # CurrentDC missing
        "PANEL-3": {"LightIntensity": 900.0, "Temperature": 40.0, "CurrentDC": 8.4},  # unmapped
    }
    readings = build_panel_readings(data, {"PANEL-1": "GUID-1"})

    by_tag = {r.asset_tag: r for r in readings}
    assert set(by_tag) == {"PANEL-1", "PANEL-3"}
    assert by_tag["PANEL-1"].global_id == "GUID-1"
    assert by_tag["PANEL-3"].global_id == "PANEL-3"


@patch("requests.get")
@patch("requests.post")
@patch("requests.delete")
def test_alert_notifier_sync(mock_delete, mock_post, mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"alerts": []}
    mock_post.return_value.status_code = 200
    mock_delete.return_value.status_code = 200

    notifier = AlertNotifier("http://localhost:8000")

    # Round 1: dispatches 1 alert
    alert1 = AlertPayload("PANEL_001", "Sujeira", "warning", "Sujeira detectada")
    res1 = notifier.sync_alerts([alert1])
    assert res1["created"] == 1
    assert res1["active"] == 1
    assert mock_post.called

    # Round 2: panel normalized -> triggers DELETE to clear
    res2 = notifier.sync_alerts([])
    assert res2["cleared"] == 1
    assert res2["active"] == 0
    assert mock_delete.called


@patch("requests.get")
@patch("requests.delete")
def test_alert_notifier_reconciles_preexisting_alerts(mock_delete, mock_get):
    # Simulates visualizer already having an active alert from an earlier run
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "alerts": [{"element_id": "PANEL_OLD", "error_type": "Sobreaquecimento"}]
    }
    mock_delete.return_value.status_code = 200

    notifier = AlertNotifier("http://localhost:8000")
    assert "PANEL_OLD" in notifier._last_alerted_elements

    # Evaluating with empty list (or healthy panels) must trigger DELETE for PANEL_OLD
    res = notifier.sync_alerts([])
    assert res["cleared"] == 1
    assert mock_delete.called
    assert "PANEL_OLD" in mock_delete.call_args[0][0]


def test_anomaly_thresholds_from_dict():
    # Flat dictionary
    t1 = AnomalyThresholds.from_dict({"z_score_dirt": -1.8, "max_safe_temperature_c": 72.0})
    assert t1.z_score_dirt == -1.8
    assert t1.max_safe_temperature_c == 72.0
    assert t1.night_lux_threshold == 50.0  # default preserved

    # Nested dictionary matching config/rules.json structure
    nested = {
        "night_detection": {"night_lux_threshold": 60.0},
        "statistical_z_scores": {"z_score_dirt": -3.2, "z_score_overheat": 2.8},
        "safety_limits": {"max_safe_temperature_c": 75.0, "max_safe_current_a": 18.0},
        "ignored_key": "some_extra_info",
    }
    t2 = AnomalyThresholds.from_dict(nested)
    assert t2.night_lux_threshold == 60.0
    assert t2.z_score_dirt == -3.2
    assert t2.z_score_overheat == 2.8
    assert t2.max_safe_temperature_c == 75.0
    assert t2.max_safe_current_a == 18.0


def test_anomaly_thresholds_from_file(tmp_path):
    config_file = tmp_path / "custom_rules.json"
    config_file.write_text(
        json.dumps(
            {
                "statistical_z_scores": {"z_score_dirt": -2.2, "z_score_overheat": 2.1},
                "safety_limits": {"max_safe_temperature_c": 68.0},
            }
        )
    )

    thresholds = AnomalyThresholds.from_file(config_file)
    assert thresholds.z_score_dirt == -2.2
    assert thresholds.z_score_overheat == 2.1
    assert thresholds.max_safe_temperature_c == 68.0

    # Non-existent file returns default instance safely
    missing_thresholds = AnomalyThresholds.from_file(tmp_path / "does_not_exist.json")
    assert missing_thresholds.z_score_dirt == -2.5
    assert missing_thresholds.max_safe_temperature_c == 75.0


def test_project_default_rules_json_exists():
    from pathlib import Path

    repo_rules = Path("config/rules.json")
    assert repo_rules.is_file(), "config/rules.json must exist in the repository root"

    thresholds = AnomalyThresholds.from_file(repo_rules)
    assert thresholds.night_lux_threshold == 50.0
    assert thresholds.z_score_dirt == -2.5
    assert thresholds.z_score_overheat == 2.5
    assert thresholds.max_safe_temperature_c == 75.0
    assert thresholds.max_safe_current_a == 16.0

    assert AnomalyThresholds() == thresholds
