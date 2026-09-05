import ifcopenshell
import ifcopenshell.api.root
import pytest

from asset_forge.export.aas.solar import INVERTER_VARIABLES, PANEL_VARIABLES, is_solar_panel


@pytest.fixture
def model():
    return ifcopenshell.file(schema="IFC4")


def test_matches_the_real_source_ifc_family_name(model):
    panel = ifcopenshell.api.root.create_entity(
        model, ifc_class="IfcBuildingElementProxy", name="Solar Panel_ZCB:1000 x 1835mm:1529520"
    )
    panel.ObjectType = "Solar Panel_ZCB:1000 x 1835mm"

    assert is_solar_panel(panel)


def test_matches_case_insensitively_and_by_object_type_alone(model):
    panel = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingElementProxy", name="anything")
    panel.ObjectType = "SOLAR PANEL Foo"

    assert is_solar_panel(panel)


def test_does_not_match_unrelated_elements(model):
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall-01")

    assert not is_solar_panel(wall)


def test_panel_variables_cover_the_diagrams_per_panel_readings():
    ids = {v.id_short for v in PANEL_VARIABLES}
    assert ids == {"LightIntensity", "Temperature", "CurrentDC", "VoltageDC"}


def test_inverter_variables_cover_the_diagrams_ac_output():
    ids = {v.id_short for v in INVERTER_VARIABLES}
    assert ids == {"VoltageAC", "CurrentAC", "PowerAC"}
