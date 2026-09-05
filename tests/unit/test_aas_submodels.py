import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import pytest

pytest.importorskip("basyx")

from basyx.aas import model as aas_model  # noqa: E402

from asset_forge.export.aas.solar import OpcuaVariable  # noqa: E402
from asset_forge.export.aas.submodels import (  # noqa: E402
    build_lean_technicaldata_submodel,
    build_nameplate_submodel,
    build_opcua_submodel,
    build_technicaldata_submodel,
    build_timeseries_submodel,
    build_virtual_nameplate_submodel,
)


@pytest.fixture
def model():
    return ifcopenshell.file(schema="IFC4")


@pytest.fixture
def wall(model):
    return ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall-01")


def test_nameplate_carries_only_data_the_element_actually_has(wall):
    submodel = build_nameplate_submodel(wall, namespace="example.org/asset-forge")

    assert submodel.id_short == "nameplate"
    assert submodel.get_referable("URIOfTheProduct").value == (
        f"https://example.org/asset-forge/asset/{wall.GlobalId}"
    )
    assert submodel.get_referable("UniqueFacilityIdentifier").value == wall.GlobalId
    assert submodel.get_referable("ManufacturerProductDesignation").value["en"] == "Wall-01"
    # example placeholder content must not survive into an instance submodel
    assert len(submodel.get_referable("Markings").value) == 0
    assert len(submodel.get_referable("AssetSpecificProperties").value) == 0


def test_technicaldata_carries_every_pset_generically(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"FireRating": "REI60", "IsExternal": True})

    submodel = build_technicaldata_submodel(wall)

    areas = {area.id_short: area for area in submodel.get_referable("TechnicalPropertyAreas").value}
    assert "Pset_WallCommon" in areas
    values = {p.id_short: p.value for p in areas["Pset_WallCommon"].value}
    assert values == {"FireRating": "REI60", "IsExternal": "True"}

    # example placeholder content must not survive into an instance submodel
    assert len(submodel.get_referable("ProductClassifications").value) == 0
    assert len(submodel.get_referable("SpecificDescriptions").value) == 0
    general_info = submodel.get_referable("GeneralInformation")
    assert len(general_info.get_referable("ProductImages").value) == 0


def test_technicaldata_skips_none_valued_properties(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_Demo")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Blank": None})

    submodel = build_technicaldata_submodel(wall)

    areas = list(submodel.get_referable("TechnicalPropertyAreas").value)
    assert areas == []


def test_opcua_submodel_uses_configured_host_and_port_and_int_not_bool_flags():
    submodel = build_opcua_submodel(host="opcua.example.org", port=4843)

    endpoint = submodel.get_referable("EndpointDescriptions").value[0]
    assert endpoint.get_referable("EndpointUri").value == "opc.tcp://opcua.example.org:4843/freeopcua/server"

    config = submodel.get_referable("Configuration")
    assert config.get_referable("SupportSecurityModeNone").value == 1
    assert isinstance(config.get_referable("SupportSecurityModeNone").value, int)
    assert config.get_referable("SupportSecurityModeSign").value == 0

    # default (no variables) reproduces today's exact shape -- no extra top-level Properties
    top_level_properties = [e for e in submodel.submodel_element if isinstance(e, aas_model.Property)]
    assert top_level_properties == []


def test_opcua_submodel_adds_one_writable_property_per_variable():
    variables = (OpcuaVariable("CurrentDC", "IDC"), OpcuaVariable("VoltageDC", "VDC"))

    submodel = build_opcua_submodel(host="localhost", port=4840, variables=variables)

    properties = {e.id_short: e for e in submodel.submodel_element if isinstance(e, aas_model.Property)}
    assert set(properties) == {"CurrentDC", "VoltageDC"}
    assert properties["CurrentDC"].value == 0.0
    assert properties["CurrentDC"].value_type == float


def test_lean_technicaldata_carries_only_identifying_fields(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"FireRating": "REI60"})

    submodel = build_lean_technicaldata_submodel(wall)

    assert submodel.id_short == "technicaldata"
    # deliberately a bare Submodel, not built from the IDTA template -- no
    # TechnicalPropertyAreas/GeneralInformation wrapper, just one
    # Identification collection directly on the submodel (see the
    # function's docstring for why: per-field IDTA template overhead was
    # what blew a real upload past BaSyx's data.json size cap).
    top_level = list(submodel.submodel_element)
    assert len(top_level) == 1
    identification = top_level[0]
    assert identification.id_short == "Identification"

    values = {p.id_short: p.value for p in identification.value}
    assert values["IfcClass"] == "IfcWall"
    assert values["Name"] == "Wall-01"
    assert values["GlobalId"] == wall.GlobalId
    # the full raw-pset dump must not appear in the lean version
    assert "Pset_WallCommon" not in {p.id_short for p in identification.value}


def test_timeseries_submodel_points_a_linked_segment_at_the_history_api():
    variables = (OpcuaVariable("CurrentDC", "IDC"),)

    submodel = build_timeseries_submodel(
        "panel-123",
        variables,
        asset_tag="PANEL-123",
        history_api_host="history-api.example.org",
        history_api_port=8090,
    )

    assert submodel.id_short == "timeseries"
    segments = {s.id_short for s in submodel.get_referable("Segments").value}
    assert segments == {"LinkedSegment"}

    linked = submodel.get_referable("Segments").get_referable("LinkedSegment")
    # Endpoint is the history-api service, not InfluxDB -- Query is just the
    # plain asset id, no Flux at all, so a consumer never needs to know
    # InfluxDB is the backend behind it.
    assert linked.get_referable("Endpoint").value == "http://history-api.example.org:8090"
    assert linked.get_referable("Query").value == "PANEL-123"

    record_schema = submodel.get_referable("Metadata").get_referable("Record")
    assert {p.id_short for p in record_schema.value} == {"Time", "CurrentDC"}


def test_virtual_nameplate_uses_literal_strings_not_an_ifc_entity():
    submodel = build_virtual_nameplate_submodel("Inverter", "inverter", namespace="example.org/asset-forge")

    assert submodel.get_referable("UniqueFacilityIdentifier").value == "inverter"
    assert submodel.get_referable("ManufacturerProductDesignation").value["en"] == "Inverter"
    assert submodel.get_referable("URIOfTheProduct").value == "https://example.org/asset-forge/asset/virtual/inverter"
