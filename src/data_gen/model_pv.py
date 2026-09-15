"""Single-diode photovoltaic panel model.

All electrical values refer to one complete panel. Irradiance is in W/m²,
temperatures in °C, voltage in V, current in A, and power in W. Plotting is
optional and does not add a dependency to the simulation runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, expm1, isfinite, sqrt
from typing import NamedTuple

import numpy as np

from configs import (
    ABSOLUTE_ZERO_C,
    BOLTZMANN_CONSTANT_J_K,
    ELEMENTARY_CHARGE_C,
)


@dataclass(frozen=True)
class PVParameters:
    """Reference data and physical parameters for one PV panel.

    ``rs`` and ``rsh`` are panel-level resistances (not per-cell). Reference
    values (``*_ref``) are the panel's datasheet ratings under Standard Test
    Conditions (STC): 1000 W/m² irradiance, 25°C cell temperature. Frozen so
    a single validated instance can be safely reused as the default
    ``parameters`` argument across every function in this module.

    Attributes:
        isc_ref: Short-circuit current at STC, in A (datasheet ``Isc``).
        voc_ref: Open-circuit voltage at STC, in V (datasheet ``Voc``).
        rs: Panel-level series resistance, in Ω. Models resistive losses in
            cell interconnects/contacts; small relative to ``rsh``.
        rsh: Panel-level shunt (parallel) resistance, in Ω. Models leakage
            current across the cell junction; large relative to ``rs``.
        ns: Number of PV cells wired in series inside the panel.
        ideality: Diode ideality factor (dimensionless, typically 1-2),
            capturing deviation from an ideal p-n junction diode.
        bandgap: Semiconductor bandgap energy, in eV (silicon ≈ 1.12).
            Drives how strongly the saturation current grows with
            temperature.
        temperature_ref: Reference cell temperature for the ``*_ref``
            ratings, in °C. Fixed at STC (25°C) unless recalibrating against
            a different datasheet condition.
        irradiance_ref: Reference irradiance for the ``*_ref`` ratings, in
            W/m². Fixed at STC (1000 W/m²) unless recalibrating.
        current_temperature_coefficient: Rate of change of the short-circuit
            current with cell temperature, in A/°C (datasheet ``α_Isc``).
            Positive: current rises with temperature.
        temperature_irradiance_coefficient: Approximate rise of cell
            temperature above ambient per unit of irradiance, in °C per
            W/m². Used by :func:`cell_temperature`; calibrate for the actual
            panel installation (mounting, ventilation) when better data is
            known.
        is0_ref: Optional override for the diode reverse saturation current
            at ``temperature_ref``, in A. When ``None`` (default), it is
            instead calibrated from the ``isc_ref``/``voc_ref`` pair (see
            :func:`_reference_saturation_current`).
    """

    isc_ref: float = 17.7
    voc_ref: float = 48.7
    rs: float = 0.15
    rsh: float = 200.0
    ns: int = 72
    ideality: float = 1.3
    bandgap: float = 1.12
    temperature_ref: float = 25.0
    irradiance_ref: float = 1000.0
    current_temperature_coefficient: float = 0.0045
    temperature_irradiance_coefficient: float = 0.0274
    is0_ref: float | None = None

    def __post_init__(self) -> None:
        """Validate that every field is finite and physically valid."""
        positive = {
            "isc_ref": self.isc_ref,
            "voc_ref": self.voc_ref,
            "rsh": self.rsh,
            "ns": self.ns,
            "ideality": self.ideality,
            "bandgap": self.bandgap,
            "irradiance_ref": self.irradiance_ref,
        }
        for name, value in positive.items():
            if not isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in {
            "rs": self.rs,
            "current_temperature_coefficient": self.current_temperature_coefficient,
            "temperature_irradiance_coefficient": self.temperature_irradiance_coefficient,
            "temperature_ref": self.temperature_ref,
        }.items():
            if not isfinite(value) or (name == "rs" and value < 0):
                raise ValueError(
                    f"{name} must be finite"
                    + (" and non-negative" if name == "rs" else "")
                )
        if self.is0_ref is not None and (
            not isfinite(self.is0_ref) or self.is0_ref <= 0
        ):
            raise ValueError("is0_ref must be finite and positive when provided")


class PVOperatingPoint(NamedTuple):
    """Panel operating point returned by :func:`maximum_power_point`."""

    voltage_v: float
    current_a: float
    power_w: float
    cell_temperature_c: float
    irradiance_w_m2: float


def _finite(value: float, name: str) -> float:
    """Coerce ``value`` to ``float``, raising ``ValueError`` if it isn't finite."""
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _kelvin(temperature_c: float) -> float:
    """Convert a Celsius temperature to Kelvin, validating it's above absolute zero."""
    temperature_c = _finite(temperature_c, "temperature")
    temperature_k = temperature_c - ABSOLUTE_ZERO_C
    if temperature_k <= 0:
        raise ValueError("temperature must be above absolute zero")
    return temperature_k


def _exp_clamped(value: float) -> float:
    """Avoid overflow for extreme, user-supplied environmental conditions."""
    return exp(min(700.0, max(-700.0, value)))


def cell_temperature(
    ambient_temperature_c: float,
    irradiance_w_m2: float,
    parameters: PVParameters = PVParameters(),
) -> float:
    """Estimate cell temperature from ambient temperature and irradiance."""
    ambient_temperature_c = _finite(ambient_temperature_c, "ambient_temperature_c")
    irradiance_w_m2 = _finite(irradiance_w_m2, "irradiance_w_m2")
    if irradiance_w_m2 < 0:
        raise ValueError("irradiance_w_m2 cannot be negative")
    result = (
        ambient_temperature_c
        + parameters.temperature_irradiance_coefficient * irradiance_w_m2
    )
    _kelvin(result)
    return result


def photocurrent(
    irradiance_w_m2: float,
    cell_temperature_c: float,
    parameters: PVParameters = PVParameters(),
) -> float:
    """Calculate the light-generated current for the given conditions."""
    irradiance_w_m2 = _finite(irradiance_w_m2, "irradiance_w_m2")
    cell_temperature_c = _finite(cell_temperature_c, "cell_temperature_c")
    _kelvin(cell_temperature_c)
    if irradiance_w_m2 < 0:
        raise ValueError("irradiance_w_m2 cannot be negative")
    irradiance_ratio = irradiance_w_m2 / parameters.irradiance_ref
    temperature_adjusted_isc = (
        parameters.isc_ref
        + parameters.current_temperature_coefficient
        * (cell_temperature_c - parameters.temperature_ref)
    )
    return max(0.0, temperature_adjusted_isc * irradiance_ratio)


def _thermal_voltage(temperature_k: float, parameters: PVParameters) -> float:
    """
    Return the panel's thermal voltage (``ideality * ns * k * T / q``) 
    at ``temperature_k``.
    """
    return (
        parameters.ideality
        * parameters.ns
        * BOLTZMANN_CONSTANT_J_K
        * temperature_k
        / ELEMENTARY_CHARGE_C
    )


def _reference_saturation_current(parameters: PVParameters) -> float:
    """
    Return I0 at ``temperature_ref``: ``is0_ref`` if set, 
    else calibrated from Isc/Voc.
    """
    if parameters.is0_ref is not None:
        return parameters.is0_ref

    reference_temperature_k = _kelvin(parameters.temperature_ref)
    thermal_voltage = _thermal_voltage(reference_temperature_k, parameters)
    # Calibrate I0 against the panel's Isc/Voc pair at the reference point.
    numerator = (
        parameters.isc_ref * (1.0 + parameters.rs / parameters.rsh)
        - parameters.voc_ref / parameters.rsh
    )
    denominator = _exp_clamped(parameters.voc_ref / thermal_voltage) - _exp_clamped(
        parameters.isc_ref * parameters.rs / thermal_voltage
    )
    if numerator <= 0 or denominator <= 0:
        raise ValueError(
            "panel parameters do not produce a valid reference saturation current"
        )
    return numerator / denominator


def saturation_current(
    cell_temperature_c: float,
    parameters: PVParameters = PVParameters(),
) -> float:
    """Calculate diode reverse saturation current at cell temperature."""
    temperature_k = _kelvin(cell_temperature_c)
    reference_temperature_k = _kelvin(parameters.temperature_ref)
    exponent = (
        parameters.bandgap
        * ELEMENTARY_CHARGE_C
        / (parameters.ideality * BOLTZMANN_CONSTANT_J_K)
        * (1.0 / reference_temperature_k - 1.0 / temperature_k)
    )
    return (
        _reference_saturation_current(parameters)
        * (temperature_k / reference_temperature_k) ** 3
        * _exp_clamped(exponent)
    )


def _current_residual(
    current_a: float,
    voltage_v: float,
    light_current_a: float,
    saturation_current_a: float,
    thermal_voltage_v: float,
    parameters: PVParameters,
) -> float:
    """Return the single-diode current-balance residual, zero at the true operating current."""
    diode_voltage = voltage_v + current_a * parameters.rs
    diode_current = saturation_current_a * expm1(
        min(700.0, max(-700.0, diode_voltage / thermal_voltage_v))
    )
    shunt_current = diode_voltage / parameters.rsh
    return light_current_a - diode_current - shunt_current - current_a


def _current_at_voltage(
    voltage_v: float,
    light_current_a: float,
    saturation_current_a: float,
    thermal_voltage_v: float,
    parameters: PVParameters,
    iterations: int = 80,
) -> float:
    """Solve the single-diode equation for current using bisection."""
    if light_current_a <= 0:
        return 0.0
    lower, upper = 0.0, light_current_a
    if (
        _current_residual(
            lower,
            voltage_v,
            light_current_a,
            saturation_current_a,
            thermal_voltage_v,
            parameters,
        )
        < 0
    ):
        return 0.0
    if (
        _current_residual(
            upper,
            voltage_v,
            light_current_a,
            saturation_current_a,
            thermal_voltage_v,
            parameters,
        )
        > 0
    ):
        return upper

    for _ in range(iterations):
        middle = (lower + upper) / 2.0
        residual = _current_residual(
            middle,
            voltage_v,
            light_current_a,
            saturation_current_a,
            thermal_voltage_v,
            parameters,
        )
        if residual > 0:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def _open_circuit_voltage(
    light_current_a: float,
    saturation_current_a: float,
    thermal_voltage_v: float,
    parameters: PVParameters,
) -> float:
    """Solve for the panel's open-circuit voltage (current = 0) by bisection."""
    if light_current_a <= 0:
        return 0.0

    lower, upper = 0.0, parameters.voc_ref
    while (
        _current_residual(
            0.0,
            upper,
            light_current_a,
            saturation_current_a,
            thermal_voltage_v,
            parameters,
        )
        > 0
    ):
        upper *= 2.0
        if upper > parameters.voc_ref * 64.0:
            raise ArithmeticError("failed to bound the panel open-circuit voltage")

    for _ in range(80):
        middle = (lower + upper) / 2.0
        residual = _current_residual(
            0.0,
            middle,
            light_current_a,
            saturation_current_a,
            thermal_voltage_v,
            parameters,
        )
        if residual > 0:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def _operating_conditions(
    irradiance_w_m2: float,
    ambient_temperature_c: float,
    parameters: PVParameters,
) -> tuple[float, float, float, float, float]:
    """Compute the intermediate quantities shared by the MPP search and the I-V curve.

    Returns ``(cell_temperature_c, light_current_a, diode_saturation_current_a,
    thermal_voltage_v, irradiance_w_m2)``.
    """
    irradiance_w_m2 = _finite(irradiance_w_m2, "irradiance_w_m2")
    ambient_temperature_c = _finite(ambient_temperature_c, "ambient_temperature_c")
    if irradiance_w_m2 < 0:
        raise ValueError("irradiance_w_m2 cannot be negative")
    cell_temperature_c_value = cell_temperature(
        ambient_temperature_c, irradiance_w_m2, parameters
    )
    temperature_k = _kelvin(cell_temperature_c_value)
    light_current_a = photocurrent(
        irradiance_w_m2, cell_temperature_c_value, parameters
    )
    diode_saturation_current_a = saturation_current(
        cell_temperature_c_value, parameters
    )
    thermal_voltage_v = _thermal_voltage(temperature_k, parameters)
    return (
        cell_temperature_c_value,
        light_current_a,
        diode_saturation_current_a,
        thermal_voltage_v,
        irradiance_w_m2,
    )


def maximum_power_point(
    irradiance: float,
    ambient_temperature: float,
    parameters: PVParameters = PVParameters(),
    voltage_tolerance: float = 1e-5,
    max_iterations: int = 80,
) -> PVOperatingPoint:
    """Return the maximum-power operating point for one panel.

    Solves for the point on the I-V curve where power (voltage × current)
    is maximum, using golden-section search over voltage. Returns a
    :class:`PVOperatingPoint` with fields ordered ``(voltage_v, current_a,
    power_w, cell_temperature_c, irradiance_w_m2)``.
    """
    voltage_tolerance = _finite(voltage_tolerance, "voltage_tolerance")
    if voltage_tolerance <= 0:
        raise ValueError("voltage_tolerance must be positive")
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")

    cell_temp, light_current, diode_i0, thermal_voltage, irradiance_value = (
        _operating_conditions(irradiance, ambient_temperature, parameters)
    )
    if light_current <= 0:
        return PVOperatingPoint(0.0, 0.0, 0.0, cell_temp, irradiance_value)

    upper = _open_circuit_voltage(light_current, diode_i0, thermal_voltage, parameters)

    def power_at(voltage_v: float) -> tuple[float, float]:
        current_a = _current_at_voltage(
            voltage_v, light_current, diode_i0, thermal_voltage, parameters
        )
        return voltage_v * current_a, current_a

    lower = 0.0
    ratio = (sqrt(5.0) - 1.0) / 2.0
    left = upper - ratio * upper
    right = ratio * upper
    left_power, _ = power_at(left)
    right_power, _ = power_at(right)
    for _ in range(max_iterations):
        if upper - lower <= voltage_tolerance:
            break
        if left_power < right_power:
            lower, left, left_power = left, right, right_power
            right = lower + ratio * (upper - lower)
            right_power, _ = power_at(right)
        else:
            upper, right, right_power = right, left, left_power
            left = upper - ratio * (upper - lower)
            left_power, _ = power_at(left)

    voltage_v = (lower + upper) / 2.0
    power_w, current_a = power_at(voltage_v)
    return PVOperatingPoint(voltage_v, current_a, power_w, cell_temp, irradiance_value)


def pv_curve(
    irradiance: float,
    ambient_temperature: float,
    parameters: PVParameters = PVParameters(),
    points: int = 300,
) -> tuple[np.ndarray, np.ndarray]:
    """Return voltage and current arrays for the panel's I-V curve."""
    if points < 2:
        raise ValueError("points must be at least 2")
    _, light_current, diode_i0, thermal_voltage, _ = _operating_conditions(
        irradiance, ambient_temperature, parameters
    )
    if light_current <= 0:
        return np.zeros(points), np.zeros(points)
    open_circuit_voltage = _open_circuit_voltage(
        light_current, diode_i0, thermal_voltage, parameters
    )
    voltage = np.linspace(0.0, open_circuit_voltage, points)
    current = np.array(
        [
            _current_at_voltage(
                float(value), light_current, diode_i0, thermal_voltage, parameters
            )
            for value in voltage
        ]
    )
    return voltage, current


def _plot_curve(
    irradiance: float,
    ambient_temperature: float,
    power: bool,
    parameters: PVParameters,
    points: int,
):
    """Build the shared matplotlib figure/axes for :func:`plot_pv_curve` and :func:`plot_pv_power_curve`."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "install the 'plots' extra to use PV plotting functions"
        ) from exc

    voltage, current = pv_curve(irradiance, ambient_temperature, parameters, points)
    figure, axes = plt.subplots(figsize=(8, 5))
    values = voltage * current if power else current
    axes.plot(voltage, values, linewidth=2)
    axes.set_xlabel("Panel voltage (V)")
    axes.set_ylabel("Panel power (W)" if power else "Panel current (A)")
    axes.set_title("PV voltage-power curve" if power else "PV voltage-current curve")
    axes.grid(True, alpha=0.3)
    figure.tight_layout()
    return figure, axes


def plot_pv_curve(
    irradiance: float,
    ambient_temperature: float,
    parameters: PVParameters = PVParameters(),
    points: int = 300,
):
    """Plot the panel's voltage-current curve (requires the optional plots extra)."""
    return _plot_curve(irradiance, ambient_temperature, False, parameters, points)


def plot_pv_power_curve(
    irradiance: float,
    ambient_temperature: float,
    parameters: PVParameters = PVParameters(),
    points: int = 300,
):
    """Plot the panel's voltage-power curve (requires the optional plots extra)."""
    return _plot_curve(irradiance, ambient_temperature, True, parameters, points)


if __name__ == "__main__":
    point = maximum_power_point(irradiance=1000.0, ambient_temperature=25.0)
    print(f"Voltage: {point.voltage_v:.2f} V")
    print(f"Current: {point.current_a:.2f} A")
    print(f"Power: {point.power_w:.2f} W")
    print(f"Cell temperature: {point.cell_temperature_c:.2f} °C")
    print(f"Irradiance: {point.irradiance_w_m2:.0f} W/m²")
