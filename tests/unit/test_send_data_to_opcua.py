import sys
from datetime import datetime
from pathlib import Path

import pytest

DATA_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "data_gen"


@pytest.fixture(scope="module")
def opcua_module():
    sys.path.append(str(DATA_GEN_DIR))
    import send_data_to_OPCUA as module

    yield module


def test_datetime_to_index_accepts_br_and_iso_formats(opcua_module):
    assert opcua_module.datetime_to_index("01/01/2026 00:00") == 0
    assert opcua_module.datetime_to_index("2026-01-01 00:00") == 0
    assert opcua_module.datetime_to_index("01/01/2026 01:00") == 1


def test_datetime_to_index_rejects_unrecognized_format(opcua_module):
    with pytest.raises(ValueError):
        opcua_module.datetime_to_index("not a date")


def test_datetime_to_index_rejects_minutes_not_aligned_to_the_hour(opcua_module):
    with pytest.raises(ValueError):
        opcua_module.datetime_to_index("01/01/2026 00:30")


def test_datetime_to_index_rejects_dates_before_initial_datetime(opcua_module):
    with pytest.raises(ValueError):
        opcua_module.datetime_to_index("31/12/2025 23:00")


def test_datetime_to_index_validates_against_dataset_length(opcua_module):
    with pytest.raises(IndexError):
        opcua_module.datetime_to_index("01/01/2027 00:00", dataset_length=10)


def test_interpolate_dataset_matches_raw_sample_at_exact_hour(opcua_module):
    sample = opcua_module.interpolate_dataset(datetime(2026, 1, 1, 0, 0))
    assert list(sample) == list(opcua_module.dataset[0])


def test_interpolate_dataset_interpolates_between_hours(opcua_module):
    midpoint = opcua_module.interpolate_dataset(datetime(2026, 1, 1, 0, 30))
    expected = (opcua_module.dataset[0] + opcua_module.dataset[1]) / 2
    assert midpoint == pytest.approx(expected)


def test_interpolate_dataset_raises_past_the_end_of_the_dataset(opcua_module):
    far_future = datetime(2030, 1, 1)
    with pytest.raises(IndexError):
        opcua_module.interpolate_dataset(far_future)
