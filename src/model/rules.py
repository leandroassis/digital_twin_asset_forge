"""Fault classification rules based on spatial Z-Scores and solar field physics.

Thresholds are centrally and easily configurable via `AnomalyThresholds`:
- Night: Solar irradiance below night threshold
- Dirt / Soiling: Normal daylight, but current significantly below field average (Z < -2.5)
- Overheating: Temperature significantly above field average (Z > +2.5) or exceeding absolute safe threshold
- Overcurrent: Current surge exceeding statistical limit (Z > +3.0) or nominal maximum rating
"""

from dataclasses import asdict, dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union


class FaultType(str, Enum):
    """Fault types matching the exact strings expected by the 3D visualizer."""

    DIRT = "Sujeira"
    OVERHEAT = "Sobreaquecimento"
    OVERCURRENT = "Sobrecorrente"
    NIGHT = "Noite"


@dataclass
class AnomalyThresholds:
    """Configurable detection thresholds.

    Modify default values here, load from a JSON configuration file,
    or pass an instance with customized values to tune detection sensitivity.
    """

    # 1. Night Detection Thresholds
    night_lux_threshold: float = 50.0  # Luminosity (lux) below which conditions are classified as night
    night_current_threshold: float = 0.1  # Mean field current (A) below which the plant is inactive

    # 2. Z-Score Statistical Thresholds (Z = (x - mean) / std)
    z_score_dirt: float = -2.5  # DC current Z-Score below this value indicates dirt / partial shading
    z_score_overheat: float = 2.5  # Temperature Z-Score above this value indicates abnormal heating (hotspot)
    z_score_overcurrent: float = 3.0  # DC current Z-Score above this value indicates abnormal overcurrent

    # 3. Absolute Hard Safety Limits
    max_safe_temperature_c: float = 65.0  # Temperature (°C) above which overheating alert is unconditionally raised
    max_safe_current_a: float = 16.0  # DC current (A) above which overcurrent alert is unconditionally raised

    def to_dict(self) -> Dict[str, float]:
        """Returns threshold attributes as a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnomalyThresholds":
        """Creates an AnomalyThresholds instance from a flat or nested dictionary.

        Accepts nested groups like `{"statistical_z_scores": {"z_score_dirt": -2.0}}`
        or flat keys like `{"z_score_dirt": -2.0}`.
        """
        flattened: Dict[str, Any] = {}
        for key, val in data.items():
            if isinstance(val, dict):
                flattened.update(val)
            else:
                flattened[key] = val

        valid_fields = set(cls.__dataclass_fields__.keys())
        kwargs: Dict[str, float] = {}
        for k, v in flattened.items():
            if k in valid_fields and v is not None:
                try:
                    kwargs[k] = float(v)
                except (ValueError, TypeError):
                    continue

        return cls(**kwargs)

    @classmethod
    def from_file(cls, path: Union[Path, str]) -> "AnomalyThresholds":
        """Loads anomaly detection thresholds from a JSON file.

        Falls back to default thresholds if the file does not exist or cannot be parsed.
        """
        file_path = Path(path)
        if not file_path.is_file():
            return cls()

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            if isinstance(content, dict):
                return cls.from_dict(content)
        except Exception:
            pass

        return cls()


@dataclass
class AlertPayload:
    """Alert structure required by the visualizer backend (/api/alerts)."""

    element_id: str
    error_type: str
    severity: str  # "info", "warning", "critical"
    message: str

    def to_dict(self) -> dict:
        return {
            "element_id": self.element_id,
            "error_type": self.error_type,
            "severity": self.severity,
            "message": self.message,
        }


def evaluate_panel(
    element_id: str,
    light_val: float,
    temp_val: float,
    current_val: float,
    temp_z: float,
    current_z: float,
    avg_light: float,
    thresholds: Optional[AnomalyThresholds] = None,
) -> Optional[AlertPayload]:
    """Evaluates a single panel's operational status and classifies anomalies if present.

    Returns an `AlertPayload` if a fault is detected, or `None` during normal operation.
    User-facing alert messages are kept in Portuguese for direct display in the frontend UI.
    """
    t = thresholds or AnomalyThresholds()

    # 1. Night condition check
    # If both local and mean plant irradiance are low, classify as night condition (not a defect)
    if light_val < t.night_lux_threshold and avg_light < t.night_lux_threshold:
        return AlertPayload(
            element_id=element_id,
            error_type=FaultType.NIGHT.value,
            severity="info",
            message=f"Operação noturna / baixa luminosidade: {light_val:.1f} lux",
        )

    # 2. Overcurrent condition check
    # Caused by short circuits, string mismatch or current surges
    if current_z >= t.z_score_overcurrent or current_val >= t.max_safe_current_a:
        return AlertPayload(
            element_id=element_id,
            error_type=FaultType.OVERCURRENT.value,
            severity="critical",
            message=(
                f"Sobrecorrente anômala: {current_val:.2f} A "
                f"(Z-Score = +{current_z:.2f}, limite = {t.z_score_overcurrent})"
            ),
        )

    # 3. Overheating condition check (thermal hotspot)
    # Caused by damaged cell, bypass diode defect or severe localized shading
    if temp_z >= t.z_score_overheat or temp_val >= t.max_safe_temperature_c:
        return AlertPayload(
            element_id=element_id,
            error_type=FaultType.OVERHEAT.value,
            severity="critical",
            message=(
                f"Sobreaquecimento detectado: {temp_val:.1f} °C "
                f"(Z-Score = +{temp_z:.2f}, limite = {t.z_score_overheat})"
            ),
        )

    # 4. Dirt / Soiling condition check
    # Normal sunlight present, but this panel's current is significantly below peer average
    if light_val >= t.night_lux_threshold and current_z <= t.z_score_dirt:
        return AlertPayload(
            element_id=element_id,
            error_type=FaultType.DIRT.value,
            severity="warning",
            message=(
                f"Perda de geração por sujeira/sombreamento: {current_val:.2f} A com {light_val:.1f} lux "
                f"(Z-Score = {current_z:.2f}, limite = {t.z_score_dirt})"
            ),
        )

    # Normal healthy operation
    return None
