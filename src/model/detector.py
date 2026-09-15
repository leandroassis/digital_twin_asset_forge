"""Statistical spatial Z-Score calculation and anomaly detection coordinator."""

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from model.rules import AlertPayload, AnomalyThresholds, evaluate_panel


def compute_z_scores(values: np.ndarray) -> np.ndarray:
    """Calculates spatial Z-Score: (x - mean) / std.

    Returns an array of zeros if standard deviation is zero (homogeneous peer data).
    Avoids division by zero safely.
    """
    if len(values) == 0:
        return np.array([], dtype=float)

    mean = float(np.mean(values))
    std = float(np.std(values))

    # Protect against zero division when all peer values are identical
    if std < 1e-6:
        return np.zeros_like(values, dtype=float)

    return (values - mean) / std


@dataclass
class PanelReading:
    """Telemetry reading of a solar panel at a given evaluation timestamp."""

    asset_tag: str  # e.g. "PANEL-1529520"
    global_id: str  # IFC GlobalId (e.g. "2QF3$F$XHF1A$PuubJ8dJ8")
    light_intensity: float = 0.0  # lux
    temperature: float = 0.0  # °C
    current_dc: float = 0.0  # A
    voltage_dc: float = 0.0  # V


class AnomalyDetector:
    """Coordinates spatial statistical anomaly detection across the solar field."""

    def __init__(self, thresholds: Optional[AnomalyThresholds] = None):
        self.thresholds = thresholds or AnomalyThresholds()

    def evaluate_batch(self, readings: List[PanelReading]) -> List[AlertPayload]:
        """Evaluates a batch of panel readings across the plant.

        Computes spatial Z-Scores comparing each panel against its peers in the field.
        """
        if not readings:
            return []

        # Extract numeric vectors
        lights = np.array([r.light_intensity for r in readings], dtype=float)
        temps = np.array([r.temperature for r in readings], dtype=float)
        currents = np.array([r.current_dc for r in readings], dtype=float)

        # Plant-wide mean irradiance
        avg_light = float(np.mean(lights))

        # Spatial Z-Scores for temperature and current
        z_temps = compute_z_scores(temps)
        z_currents = compute_z_scores(currents)

        alerts: List[AlertPayload] = []

        for i, reading in enumerate(readings):
            # Prefer IFC GlobalId for 3D mesh highlighting in Three.js, fallback to asset_tag
            element_id = reading.global_id or reading.asset_tag

            alert = evaluate_panel(
                element_id=element_id,
                light_val=reading.light_intensity,
                temp_val=reading.temperature,
                current_val=reading.current_dc,
                temp_z=float(z_temps[i]),
                current_z=float(z_currents[i]),
                avg_light=avg_light,
                thresholds=self.thresholds,
            )

            if alert:
                alerts.append(alert)

        return alerts
