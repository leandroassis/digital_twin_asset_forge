"""Unit tests for the AI Anomaly Detection Model (src/model) including a dedicated Mock Sensor Simulator."""

import json
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from model.collector import load_tag_to_global_id_map
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


def test_load_tag_to_global_id_map(tmp_path):
    aasserver_file = tmp_path / "aasserver.json"
    import base64

    fake_uri = "https://example.org/asset-forge/aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/opcua"
    b64_uri = base64.urlsafe_b64encode(fake_uri.encode()).decode().rstrip("=")

    content = [
        {
            "uniqueId": "opcua-PANEL-1529520-LUX",
            "submodelEndpoint": f"http://aas-environment:8081/submodels/{b64_uri}/submodel-elements/LightIntensity",
            "idShortPath": "LightIntensity",
        }
    ]
    aasserver_file.write_text(json.dumps(content))

    tag_map = load_tag_to_global_id_map(aasserver_file)
    assert tag_map.get("PANEL-1529520") == "2QF3$F$XHF1A$PuubJ8dJ8"


@patch("requests.post")
@patch("requests.delete")
def test_alert_notifier_sync(mock_delete, mock_post):
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
