from pathlib import Path
import sys

import pytest


SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.append(str(SRC_DIR))

from data_gen.fault_injection import apply_fault


@pytest.fixture
def normal_measurements():
    return {
        "LightIntensity": 800.0,
        "Temperature": 45.0,
        "CurrentDC": 12.0,
        "VoltageDC": 40.0,
        "PowerDC": 480.0,
    }


def test_no_fault_preserves_values(normal_measurements):
    result = apply_fault(normal_measurements, None)

    assert result == normal_measurements
    assert result is not normal_measurements


def test_overheating_changes_temperature_only(normal_measurements):
    result = apply_fault(normal_measurements, "Sobreaquecimento")

    assert result["Temperature"] == 90.0
    assert result["CurrentDC"] == 12.0
    assert result["VoltageDC"] == 40.0


def test_overcurrent_increases_current(normal_measurements):
    result = apply_fault(normal_measurements, "Sobrecorrente")

    assert result["CurrentDC"] == pytest.approx(18.0)
    assert result["PowerDC"] == pytest.approx(720.0)


def test_dirt_reduces_electrical_production(normal_measurements):
    result = apply_fault(normal_measurements, "Sujeira")

    assert result["LightIntensity"] == 800.0
    assert result["CurrentDC"] == pytest.approx(3.6)
    assert result["VoltageDC"] == pytest.approx(38.0)
    assert result["PowerDC"] == pytest.approx(136.8)


def test_night_zeros_generation(normal_measurements):
    result = apply_fault(normal_measurements, "Noite")

    assert result["LightIntensity"] == 0.0
    assert result["CurrentDC"] == 0.0
    assert result["VoltageDC"] == 0.0
    assert result["PowerDC"] == 0.0


def test_unknown_fault_is_rejected(normal_measurements):
    with pytest.raises(ValueError, match="Tipo de falha desconhecido"):
        apply_fault(normal_measurements, "Falha inexistente")


def test_original_measurements_are_not_modified(normal_measurements):
    original = normal_measurements.copy()

    apply_fault(normal_measurements, "Sujeira")

    assert normal_measurements == original