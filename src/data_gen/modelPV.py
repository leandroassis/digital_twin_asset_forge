from dataclasses import dataclass
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np


# Constantes fisicas no SI.
Q = 1.6e-19  # C
K = 1.3806505e-23  # J/K


@dataclass(frozen=True)
class PVParameters:
    """Parametros de referencia/nominais do painel.

    As temperaturas de entrada sao informadas em graus Celsius e a
    irradiancia em W/m2. As grandezas eletricas sao do painel inteiro.
    ``rs`` e a resistencia serie do painel; internamente ela e dividida
    por ``ns`` para formar a tensao por celula em v_d.
    """

    isc_ref: float = 17.7
    voc_ref: float = 48.7
    rs: float = 0.15
    rsh: float = 200.0
    ns: int = 72
    ideality: float = 1.3
    bandgap: float = 1.12  # eV, numericamente equivalente a volts
    temperature_ref: float = 25.0  # graus Celsius
    irradiance_ref: float = 1000.0  # W/m2
    current_temperature_coefficient: float = 0.0045  # A/K
    temperature_irradiance_coefficient: float = 0.0007  # graus C por W/m2
    Ks: float = 0.0274  # graus C por W/m2
    is0_ref: Optional[float] = None

    def __post_init__(self):
        if self.isc_ref <= 0 or self.voc_ref <= 0:
            raise ValueError("isc_ref e voc_ref devem ser positivos")
        if self.rs < 0 or self.rsh <= 0:
            raise ValueError("rs deve ser nao negativa e rsh deve ser positiva")
        if self.ns <= 0 or self.ideality <= 0:
            raise ValueError("ns e ideality devem ser positivos")
        if self.irradiance_ref <= 0:
            raise ValueError("irradiance_ref deve ser positiva")


def _kelvin(temperature_c: float) -> float:
    """Converte graus Celsius para Kelvin e valida a temperatura."""
    temperature_k = temperature_c + 273.15
    if temperature_k <= 0:
        raise ValueError("a temperatura deve ser maior que -273,15 graus C")
    return temperature_k


def cell_temperature(ambient_temperature: float, irradiance: float,
                     parameters: PVParameters = PVParameters()) -> float:
    """Calcula a temperatura da celula em graus Celsius."""
    if irradiance < 0:
        raise ValueError("a irradiancia nao pode ser negativa")
    return (ambient_temperature
            + parameters.temperature_irradiance_coefficient * irradiance)


def photocurrent(irradiance: float, cell_temperature_c: float,
                 parameters: PVParameters = PVParameters()) -> float:
    """Calcula i_ph para uma irradiancia e temperatura de celula."""
    if irradiance < 0:
        raise ValueError("a irradiancia nao pode ser negativa")
    return (parameters.isc_ref * irradiance / parameters.irradiance_ref
            + parameters.current_temperature_coefficient
            * (cell_temperature_c - parameters.temperature_ref))


def saturation_current(cell_temperature_c: float,
                       parameters: PVParameters = PVParameters()) -> float:
    """Calcula I_0; por padrao, calibra I_s0 pela tensao de circuito aberto."""
    temperature_k = _kelvin(cell_temperature_c)
    reference_k = _kelvin(parameters.temperature_ref)

    if parameters.is0_ref is None:
        reference_voltage = parameters.voc_ref / parameters.ns
        reference_exponential = np.exp(
            np.clip(Q * reference_voltage
                    / (parameters.ideality * K * reference_k), -700, 700)
        ) - 1.0
        is0 = parameters.isc_ref / reference_exponential
    else:
        is0 = parameters.is0_ref

    temperature_ratio = (temperature_k / reference_k) ** 3
    bandgap_joule = parameters.bandgap * Q
    temperature_factor = np.exp(
        np.clip(
            bandgap_joule / (parameters.ideality * K)
            * (1.0 / reference_k - 1.0 / temperature_k),
            -700,
            700,
        )
    )
    return is0 * temperature_ratio * temperature_factor


def _current_residual(current: float, voltage: float, iph: float,
                      is0: float, temperature_k: float,
                      parameters: PVParameters) -> float:
    cell_series_resistance = parameters.rs / parameters.ns
    diode_voltage = voltage / parameters.ns + current * cell_series_resistance
    exponential = np.exp(np.clip(
        Q * diode_voltage / (parameters.ideality * K * temperature_k),
        -700,
        700,
    ))
    diode_current = is0 * (exponential - 1.0)
    shunt_current = diode_voltage / parameters.rsh
    return iph - diode_current - shunt_current - current


def _calibrated_photocurrent(short_circuit_current: float, is0: float,
                             temperature_k: float,
                             parameters: PVParameters) -> float:
    """Ajusta i_ph para que I(V=0) seja a corrente de curto especificada.

    Em um painel real, a corrente de curto-circuito terminal tambem precisa
    fornecer as correntes do diodo e de Rsh causadas por i * Rs.
    """
    cell_series_resistance = parameters.rs / parameters.ns
    diode_voltage = short_circuit_current * cell_series_resistance
    diode_argument = Q * diode_voltage / (
        parameters.ideality * K * temperature_k
    )
    diode_current = is0 * (np.exp(np.clip(diode_argument, -700, 700)) - 1.0)
    shunt_current = diode_voltage / parameters.rsh
    return short_circuit_current + diode_current + shunt_current


def _bisect_current(voltage: float, iph: float, is0: float,
                    temperature_k: float, parameters: PVParameters,
                    iterations: int = 80) -> float:
    """Resolve a ponto da curva I(V) por bissecao."""
    lower = 0.0
    upper = max(iph, 0.0)
    lower_value = _current_residual(
        lower, voltage, iph, is0, temperature_k, parameters
    )
    upper_value = _current_residual(
        upper, voltage, iph, is0, temperature_k, parameters
    )

    if lower_value < 0:
        return 0.0
    if upper_value > 0:
        return upper

    for _ in range(iterations):
        middle = (lower + upper) / 2.0
        middle_value = _current_residual(
            middle, voltage, iph, is0, temperature_k, parameters
        )
        if middle_value > 0:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def pv_curve(irradiance: float, ambient_temperature: float,
             parameters: PVParameters = PVParameters(),
             points: int = 300) -> Tuple[np.ndarray, np.ndarray]:
    """Retorna tensao [V] e corrente [A] da curva estatica do painel."""
    if irradiance < 0:
        raise ValueError("a irradiancia nao pode ser negativa")
    if points < 2:
        raise ValueError("points deve ser pelo menos 2")

    cell_temperature_c = cell_temperature(
        ambient_temperature, irradiance, parameters
    )
    temperature_k = _kelvin(cell_temperature_c)
    short_circuit_current = photocurrent(
        irradiance, cell_temperature_c, parameters
    )
    is0 = saturation_current(cell_temperature_c, parameters)
    iph = _calibrated_photocurrent(
        short_circuit_current, is0, temperature_k, parameters
    )

    # Uma margem acima de Voc_ref acomoda variacoes de irradiancia e temperatura.
    voltage = np.linspace(0.0, parameters.voc_ref , points)
    current = np.array([
        _bisect_current(v, iph, is0, temperature_k, parameters)
        for v in voltage
    ])
    return voltage, current


def maximum_power_point(
    irradiance: float,
    ambient_temperature: float,
    parameters: PVParameters = PVParameters(),
    voltage_tolerance: float = 1e-5,
    max_iterations: int = 80,
) -> Tuple[float, float, float]:
    """Calcula o ponto de maxima potencia do painel fotovoltaico nas
    condições de operação.

    Retorna ``(tensao_mpp, corrente_mpp, potencia_mpp)``.
    """
    if irradiance < 0:
        raise ValueError("a irradiancia nao pode ser negativa")
    if voltage_tolerance <= 0:
        raise ValueError("voltage_tolerance deve ser positiva")
    if max_iterations < 1:
        raise ValueError("max_iterations deve ser pelo menos 1")

    cell_temperature_c = cell_temperature(
        ambient_temperature, irradiance, parameters
    )
    temperature_k = _kelvin(cell_temperature_c)
    short_circuit_current = photocurrent(
        irradiance, cell_temperature_c, parameters
    )
    is0 = saturation_current(cell_temperature_c, parameters)
    iph = _calibrated_photocurrent(
        short_circuit_current, is0, temperature_k, parameters
    )

    def power_at_voltage(voltage: float) -> Tuple[float, float]:
        current = _bisect_current(
            voltage, iph, is0, temperature_k, parameters
        )
        return voltage * current, current

    lower = 0.0
    upper = parameters.voc_ref
    golden_ratio = (np.sqrt(5.0) - 1.0) / 2.0
    first_voltage = upper - golden_ratio * (upper - lower)
    second_voltage = lower + golden_ratio * (upper - lower)
    first_power, _ = power_at_voltage(first_voltage)
    second_power, _ = power_at_voltage(second_voltage)

    for _ in range(max_iterations):
        if upper - lower <= voltage_tolerance:
            break
        if first_power < second_power:
            lower = first_voltage
            first_voltage = second_voltage
            first_power = second_power
            second_voltage = lower + golden_ratio * (upper - lower)
            second_power, _ = power_at_voltage(second_voltage)
        else:
            upper = second_voltage
            second_voltage = first_voltage
            second_power = first_power
            first_voltage = upper - golden_ratio * (upper - lower)
            first_power, _ = power_at_voltage(first_voltage)

    voltage_mpp = (lower + upper) / 2.0
    power_mpp, current_mpp = power_at_voltage(voltage_mpp)
    temp_mpp = ambient_temperature + parameters.Ks*irradiance
    return voltage_mpp, current_mpp, power_mpp, temp_mpp, irradiance


def plot_pv_curve(irradiance: float, ambient_temperature: float,
                  parameters: PVParameters = PVParameters(),
                  points: int = 300):
    """Plota e retorna ``(figure, axes)`` para a curva V-I do painel."""
    voltage, current = pv_curve(
        irradiance, ambient_temperature, parameters, points
    )
    figure, axes = plt.subplots(figsize=(8, 5))
    axes.plot(voltage, current, color="#d46b32", linewidth=2,
              label=f"S = {irradiance:.0f} W/m2, Ta = {ambient_temperature:.1f} C")
    axes.set_xlabel("Tensao do painel (V)")
    axes.set_ylabel("Corrente do painel (A)")
    axes.set_title("Curva estatica V-I do painel fotovoltaico")
    axes.grid(True, alpha=0.3)
    axes.legend()
    figure.tight_layout()
    return figure, axes


def plot_pv_power_curve(irradiance: float, ambient_temperature: float,
                       parameters: PVParameters = PVParameters(),
                       points: int = 300):
    """Plota e retorna ``(figure, axes)`` para a curva VxP do painel."""
    voltage, current = pv_curve(
        irradiance, ambient_temperature, parameters, points
    )
    power = voltage * current
    figure, axes = plt.subplots(figsize=(8, 5))
    axes.plot(voltage, power, color="#2f6fb3", linewidth=2,
              label=f"S = {irradiance:.0f} W/m2, Ta = {ambient_temperature:.1f} C")
    axes.set_xlabel("Tensao do painel (V)")
    axes.set_ylabel("Potencia do painel (W)")
    axes.set_title("Curva estatica VxP do painel fotovoltaico")
    axes.grid(True, alpha=0.3)
    axes.legend()
    figure.tight_layout()
    return figure, axes

if __name__ == "__main__":
    # Operação normal do painel fotovoltaico (modo MPPT)
    voltage, current, power, temperature, irradiance = maximum_power_point(irradiance=1000.0, ambient_temperature=25.0)

    print(f"Voltage: {voltage:.2f} V")
    print(f"Current: {current:.2f} A")
    print(f"Power: {power:.2f} W")
    print(f"Temperature: {temperature:.2f} C")
    print(f"Irradiance: {irradiance:.0f} W/m2")


