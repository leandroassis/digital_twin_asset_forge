"""Send simulation data to OPCUA server."""

import time
from datetime import datetime

import pandas as pd
import numpy as np

from configs import (
    DATASET_PATH,
    INITIAL_DATETIME,
    SIMULATION_START_DATETIME,
    SIMULATION_STEP,
)
from model_pv import maximum_power_point


dataset = np.load(DATASET_PATH)


def datetime_to_index(datetime_string: str, dataset_length: int | None = None) -> int:
    """Converte uma data/hora em seu indice horario desde 01/01/2026 00:00.

    Aceita ``DD/MM/AAAA HH:MM`` e o formato ISO ``AAAA-MM-DD HH:MM``.
    Como o dataset tem uma amostra por hora, os minutos devem ser zero.
    Quando ``dataset_length`` e informado, tambem valida se o indice existe.
    """
    accepted_formats = ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M")
    parsed_datetime = None

    for datetime_format in accepted_formats:
        try:
            parsed_datetime = datetime.strptime(datetime_string, datetime_format)
            break
        except ValueError:
            continue

    if parsed_datetime is None:
        raise ValueError("use o formato 'DD/MM/AAAA HH:MM' ou 'AAAA-MM-DD HH:MM'")
    if parsed_datetime.minute != 0:
        raise ValueError("o horario deve estar alinhado a uma hora cheia")

    elapsed_time = parsed_datetime - INITIAL_DATETIME
    if elapsed_time.total_seconds() < 0:
        raise ValueError("a data deve ser posterior a 01/01/2026 00:00")

    index = int(elapsed_time.total_seconds() // 3600)
    if dataset_length is not None and not 0 <= index < dataset_length:
        raise IndexError(
            f"o indice {index} esta fora do dataset, que tem {dataset_length} linhas"
        )
    return index


def interpolate_dataset(current_datetime: datetime) -> np.ndarray:
    """Retorna a amostra do dataset interpolada para o instante informado."""
    elapsed_hours = (current_datetime - INITIAL_DATETIME).total_seconds() / 3600
    last_index = len(dataset) - 1

    if not 0 <= elapsed_hours <= last_index:
        raise IndexError(
            f"o instante esta fora do dataset, que vai de 0 a {last_index} horas"
        )

    lower_index = int(elapsed_hours)
    upper_index = min(lower_index + 1, last_index)
    interpolation_factor = elapsed_hours - lower_index

    return dataset[lower_index] + interpolation_factor * (
        dataset[upper_index] - dataset[lower_index]
    )


def run_simulation() -> None:
    """Atualiza e imprime os dados uma vez por segundo em tempo real."""
    current_datetime = SIMULATION_START_DATETIME

    try:
        while True:
            loop_start = time.monotonic()
            try:
                irradiance, ambient_temperature = interpolate_dataset(current_datetime)
                voltage, current, power, cell_temperature, irradiance = (
                    maximum_power_point(
                        irradiance=irradiance, ambient_temperature=ambient_temperature
                    )
                )
            except IndexError:
                print("fim do dataset; simulacao encerrada")
                break

            print(
                f"simulado = {current_datetime:%d/%m/%Y %H:%M:%S} | "
                f"irradiancia = {irradiance:.2f} W/m2 | "
                f"ambiente = {ambient_temperature:.2f} °C | "
                f"celula = {cell_temperature:.2f} °C | "
                f"tensao = {voltage:.2f} V | "
                f"corrente = {current:.2f} A | "
                f"potencia = {power:.2f} W\n\n",
                flush=True,
            )

            current_datetime += SIMULATION_STEP
            time.sleep(max(0, 1 - (time.monotonic() - loop_start)))
    except KeyboardInterrupt:
        print("simulacao interrompida")


if __name__ == "__main__":
    run_simulation()
