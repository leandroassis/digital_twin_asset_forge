import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "data_gen"))

import configs


def test_physical_constants_have_expected_values():
    assert configs.ELEMENTARY_CHARGE_C == pytest.approx(1.602176634e-19)
    assert configs.BOLTZMANN_CONSTANT_J_K == pytest.approx(1.380649e-23)
    assert configs.ABSOLUTE_ZERO_C == -273.15


def test_simulation_constants_have_expected_values():
    assert configs.INITIAL_DATETIME == datetime(2026, 1, 1, 0, 0)
    assert configs.SIMULATION_START_DATETIME == datetime(2026, 7, 19, 14, 0, 0)
    assert configs.SIMULATION_STEP == timedelta(seconds=1)
