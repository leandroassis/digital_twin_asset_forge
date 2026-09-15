import sys
from math import inf, nan
from pathlib import Path

import numpy as np
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "data_gen"))

from model_pv import PVOperatingPoint, PVParameters, cell_temperature, maximum_power_point, photocurrent, pv_curve, saturation_current


def test_default_parameters_are_valid():
    PVParameters()


@pytest.mark.parametrize(
    "field,value",
    [
        ("isc_ref", 0.0),
        ("isc_ref", -1.0),
        ("voc_ref", 0.0),
        ("rsh", 0.0),
        ("ns", 0),
        ("ideality", 0.0),
        ("bandgap", 0.0),
        ("irradiance_ref", 0.0),
        ("rs", -0.1),
        ("is0_ref", -1.0),
        ("is0_ref", 0.0),
        ("isc_ref", nan),
        ("isc_ref", inf),
    ],
)
def test_invalid_parameters_are_rejected(field, value):
    with pytest.raises(ValueError):
        PVParameters(**{field: value})


def test_cell_temperature_equals_ambient_at_zero_irradiance():
    assert cell_temperature(25.0, 0.0) == 25.0


def test_cell_temperature_rejects_negative_irradiance():
    with pytest.raises(ValueError):
        cell_temperature(25.0, -1.0)


def test_cell_temperature_rejects_non_finite_input():
    with pytest.raises(ValueError):
        cell_temperature(nan, 0.0)


def test_photocurrent_at_reference_conditions_equals_isc_ref():
    parameters = PVParameters()
    assert photocurrent(parameters.irradiance_ref, parameters.temperature_ref, parameters) == pytest.approx(
        parameters.isc_ref
    )


def test_photocurrent_is_zero_at_zero_irradiance():
    assert photocurrent(0.0, 25.0) == 0.0


def test_photocurrent_rejects_negative_irradiance():
    with pytest.raises(ValueError):
        photocurrent(-1.0, 25.0)


def test_saturation_current_increases_with_temperature():
    assert saturation_current(50.0) > saturation_current(25.0)


def test_saturation_current_is_positive():
    assert saturation_current(25.0) > 0.0


def test_maximum_power_point_at_standard_test_conditions():
    point = maximum_power_point(irradiance=1000.0, ambient_temperature=25.0)

    assert isinstance(point, PVOperatingPoint)
    assert 0.0 < point.voltage_v < 48.7  # below voc_ref
    assert 0.0 < point.current_a < 17.7  # below isc_ref
    assert point.power_w == pytest.approx(point.voltage_v * point.current_a)
    assert point.cell_temperature_c == pytest.approx(cell_temperature(25.0, 1000.0))
    assert point.irradiance_w_m2 == 1000.0


def test_maximum_power_point_unpacks_as_a_plain_tuple():
    # send_data_to_OPCUA.py relies on this 5-tuple unpacking.
    voltage, current, power, cell_temperature_c, irradiance = maximum_power_point(
        irradiance=1000.0, ambient_temperature=25.0
    )
    assert (voltage, current, power) > (0.0, 0.0, 0.0)
    assert cell_temperature_c > 25.0
    assert irradiance == 1000.0


def test_maximum_power_point_is_zero_at_zero_irradiance():
    point = maximum_power_point(irradiance=0.0, ambient_temperature=25.0)
    assert point == PVOperatingPoint(0.0, 0.0, 0.0, 25.0, 0.0)


def test_maximum_power_point_rejects_negative_irradiance():
    with pytest.raises(ValueError):
        maximum_power_point(irradiance=-1.0, ambient_temperature=25.0)


def test_maximum_power_point_rejects_non_positive_voltage_tolerance():
    with pytest.raises(ValueError):
        maximum_power_point(irradiance=1000.0, ambient_temperature=25.0, voltage_tolerance=0.0)


def test_maximum_power_point_rejects_too_few_iterations():
    with pytest.raises(ValueError):
        maximum_power_point(irradiance=1000.0, ambient_temperature=25.0, max_iterations=0)


def test_maximum_power_point_matches_the_iv_curve_maximum():
    point = maximum_power_point(irradiance=1000.0, ambient_temperature=25.0)
    voltage, current = pv_curve(1000.0, 25.0, points=200)
    curve_max_power = float(np.max(voltage * current))

    # The golden-section search is more precise than a coarse curve sample,
    # so the true MPP should be at least as good, but not far off it.
    assert point.power_w >= curve_max_power - 1e-6
    assert point.power_w == pytest.approx(curve_max_power, rel=1e-3)


def test_pv_curve_rejects_too_few_points():
    with pytest.raises(ValueError):
        pv_curve(1000.0, 25.0, points=1)


def test_pv_curve_shape_and_endpoints():
    voltage, current = pv_curve(1000.0, 25.0, points=50)

    assert len(voltage) == len(current) == 50
    assert voltage[0] == 0.0
    assert current[-1] == pytest.approx(0.0, abs=1e-6)  # open-circuit point


def test_pv_curve_current_is_monotonically_non_increasing():
    _, current = pv_curve(1000.0, 25.0, points=50)
    assert np.all(np.diff(current) <= 1e-9)


def test_pv_curve_is_zero_at_zero_irradiance():
    voltage, current = pv_curve(0.0, 25.0, points=10)
    assert np.all(voltage == 0.0)
    assert np.all(current == 0.0)
