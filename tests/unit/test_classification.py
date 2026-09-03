import ifcopenshell
import ifcopenshell.api.root
import pytest

from asset_forge.elements.classification import (
    ensure_classified,
    is_generic,
    resolve_generic_fallback_class,
)


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
def test_resolve_generic_fallback_class_is_ifc_building_element_proxy_everywhere(schema):
    model = ifcopenshell.file(schema=schema)
    assert resolve_generic_fallback_class(model) == "IfcBuildingElementProxy"


def test_already_specific_class_is_left_untouched():
    model = ifcopenshell.file(schema="IFC4")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")

    assert not is_generic(wall)
    result = ensure_classified(model, wall)

    assert result is wall
    assert result.is_a() == "IfcWall"


def test_generic_proxy_already_matching_fallback_is_left_untouched():
    model = ifcopenshell.file(schema="IFC4")
    proxy = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingElementProxy")

    assert is_generic(proxy)
    result = ensure_classified(model, proxy)

    assert result is proxy
    assert result.id() == proxy.id()


def test_ensure_classified_preserves_existing_psets_when_no_reassignment_happens():
    import ifcopenshell.api.pset

    model = ifcopenshell.file(schema="IFC4")
    proxy = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingElementProxy")
    pset = ifcopenshell.api.pset.add_pset(model, product=proxy, name="Pset_Demo")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Foo": "bar"})

    result = ensure_classified(model, proxy)

    assert len(result.IsDefinedBy) == 1
