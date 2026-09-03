import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import pytest

pytest.importorskip("basyx")

from asset_forge.export.aas.submodels import (  # noqa: E402
    build_nameplate_submodel,
    build_opcua_submodel,
    build_technicaldata_submodel,
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
