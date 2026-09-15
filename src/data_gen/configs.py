"""Physical and simulation constants for the data_gen module."""

from datetime import datetime, timedelta
from pathlib import Path

# Physical constants used by the PV panel model (model_pv.py).
ELEMENTARY_CHARGE_C = 1.602176634e-19
BOLTZMANN_CONSTANT_J_K = 1.380649e-23
ABSOLUTE_ZERO_C = -273.15

# Simulation constants used by send_data_to_OPCUA.py.
INITIAL_DATETIME = datetime(2026, 1, 1, 0, 0)
SIMULATION_START_DATETIME = datetime(2026, 7, 19, 14, 0, 0)
SIMULATION_STEP = timedelta(seconds=1)

# Dataset location, resolved relative to this file so it works regardless of
# the current working directory.
DATA_DIR = Path(__file__).resolve().parent / "dataset"
DATASET_PATH = DATA_DIR / "a621_2026_irradiancia_temperatura.npy"
