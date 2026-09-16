import sys
from pathlib import Path

import base64
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "data_gen"))

from send_to_basyx import PANEL_ID_SHORTS, SensorTarget, _global_ids_by_panel, _group_by_panel, panel_reading


def test_panel_reading_keys_match_the_real_panel_property_id_shorts():
    reading = panel_reading(1000.0, 25.0, irradiance_factor=1.0, temperature_offset=0.0)
    assert set(reading.keys()) == PANEL_ID_SHORTS


def test_panel_reading_neutral_profile_matches_the_unperturbed_model():
    from model_pv import maximum_power_point

    reading = panel_reading(1000.0, 25.0, irradiance_factor=1.0, temperature_offset=0.0)
    point = maximum_power_point(irradiance=1000.0, ambient_temperature=25.0)

    assert reading["LightIntensity"] == 1000.0
    assert reading["Temperature"] == point.cell_temperature_c
    assert reading["CurrentDC"] == point.current_a
    assert reading["VoltageDC"] == point.voltage_v


def test_panel_reading_applies_the_irradiance_factor():
    full = panel_reading(1000.0, 25.0, irradiance_factor=1.0, temperature_offset=0.0)
    shaded = panel_reading(1000.0, 25.0, irradiance_factor=0.2, temperature_offset=0.0)

    assert shaded["LightIntensity"] == pytest.approx(200.0)
    # Less light generates less current; voltage isn't monotonic in
    # irradiance here because less irradiance also means a cooler cell
    # (see test_panel_reading_applies_the_temperature_offset), which raises
    # voltage -- so only current is asserted directly.
    assert shaded["CurrentDC"] < full["CurrentDC"]
    assert shaded["Temperature"] < full["Temperature"]


def test_panel_reading_applies_the_temperature_offset():
    baseline = panel_reading(1000.0, 25.0, irradiance_factor=1.0, temperature_offset=0.0)
    hotter = panel_reading(1000.0, 25.0, irradiance_factor=1.0, temperature_offset=15.0)

    assert hotter["Temperature"] > baseline["Temperature"]
    # Higher cell temperature reduces a silicon panel's output voltage.
    assert hotter["VoltageDC"] < baseline["VoltageDC"]


def test_group_by_panel_keeps_only_panel_targets():
    targets = [
        SensorTarget("sm1", "CurrentDC", "PANEL-1"),
        SensorTarget("sm1", "VoltageDC", "PANEL-1"),
        SensorTarget("sm2", "CurrentDC", "PANEL-2"),
        SensorTarget("sm3", "PowerAC", "INVERTER"),
    ]

    groups = _group_by_panel(targets)

    assert set(groups.keys()) == {"PANEL-1", "PANEL-2"}
    assert len(groups["PANEL-1"]) == 2
    assert len(groups["PANEL-2"]) == 1


def test_group_by_panel_with_no_panels_returns_empty():
    targets = [SensorTarget("sm3", "PowerAC", "INVERTER")]
    assert _group_by_panel(targets) == {}

def test_global_ids_by_panel_decodes_submodel_id():
    global_id = "2QF3$F$XHF1A$PuubJ8dJ8"
    submodel_id = (
        "https://example.org/asset-forge/aas/ifc/"
        f"{global_id}/sm/opcua"
    )

    encoded = base64.urlsafe_b64encode(
        submodel_id.encode("utf-8")
    ).decode("utf-8").rstrip("=")

    panels = {
        "PANEL-1529520": [
            SensorTarget(
                encoded,
                "CurrentDC",
                "PANEL-1529520",
            )
        ]
    }

    result = _global_ids_by_panel(panels)

    assert result == {
        "PANEL-1529520": global_id
    }