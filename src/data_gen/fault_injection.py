"""Injeção controlada de falhas nas medições simuladas dos painéis."""

from collections.abc import Mapping


SUPPORTED_FAULT_TYPES = {
    "Sujeira",
    "Sobreaquecimento",
    "Sobrecorrente",
    "Noite",
}

REQUIRED_MEASUREMENTS = {
    "LightIntensity",
    "Temperature",
    "CurrentDC",
    "VoltageDC",
    "PowerDC",
}

OVERHEAT_TEMPERATURE_C = 90.0
DIRT_CURRENT_FACTOR = 0.30
DIRT_VOLTAGE_FACTOR = 0.95
OVERCURRENT_FACTOR = 1.50


def apply_fault(
    measurements: Mapping[str, float],
    fault_type: str | None,
) -> dict[str, float]:
    """Retorna uma cópia das medições com a falha solicitada aplicada.

    A função nunca modifica o dicionário recebido. Quando ``fault_type`` é
    ``None``, as medições são apenas copiadas, representando a operação normal.

    Args:
        measurements: Medições normais calculadas pelo modelo fotovoltaico.
        fault_type: Tipo de falha ativa ou None para operação normal.

    Returns:
        Novo dicionário contendo as medições normais ou modificadas.

    Raises:
        ValueError: Se faltarem medições ou o tipo de falha for desconhecido.
    """

    missing_measurements = REQUIRED_MEASUREMENTS - measurements.keys()

    if missing_measurements:
        missing = ", ".join(sorted(missing_measurements))
        raise ValueError(f"Medições obrigatórias ausentes: {missing}")

    if fault_type is not None and fault_type not in SUPPORTED_FAULT_TYPES:
        raise ValueError(f"Tipo de falha desconhecido: {fault_type}")

    modified = dict(measurements)

    if fault_type is None:
        return modified

    if fault_type == "Sobreaquecimento":
        modified["Temperature"] = max(
            modified["Temperature"],
            OVERHEAT_TEMPERATURE_C,
        )

    elif fault_type == "Sobrecorrente":
        modified["CurrentDC"] *= OVERCURRENT_FACTOR
        modified["PowerDC"] = (
            modified["VoltageDC"] * modified["CurrentDC"]
        )

    elif fault_type == "Sujeira":
        # A irradiância medida permanece normal. A redução da produção,
        # mesmo com irradiância disponível, representa o efeito da sujeira.
        modified["CurrentDC"] *= DIRT_CURRENT_FACTOR
        modified["VoltageDC"] *= DIRT_VOLTAGE_FACTOR
        modified["PowerDC"] = (
            modified["VoltageDC"] * modified["CurrentDC"]
        )

    elif fault_type == "Noite":
        modified["LightIntensity"] = 0.0
        modified["CurrentDC"] = 0.0
        modified["VoltageDC"] = 0.0
        modified["PowerDC"] = 0.0

    return modified