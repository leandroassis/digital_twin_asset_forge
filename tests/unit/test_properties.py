import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.guid
import pytest

from asset_forge.elements.properties import _read_property_set, read_all_psets, read_pset


@pytest.fixture
def model():
    return ifcopenshell.file(schema="IFC4")


@pytest.fixture
def wall(model):
    return ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")


def test_reads_a_normal_pset(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_Demo")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Foo": "bar", "Count": 3})

    result = read_all_psets(wall)

    assert result["Pset_Demo"] == {"Foo": "bar", "Count": 3}
    assert read_pset(wall, "Pset_Demo") == {"Foo": "bar", "Count": 3}


def test_missing_pset_returns_empty_dict(wall):
    assert read_pset(wall, "Pset_DoesNotExist") == {}


def test_blank_single_space_string_normalizes_to_none(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_Demo")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Blank": " "})

    result = read_pset(wall, "Pset_Demo")

    assert result["Blank"] is None


class _ExplodingProperty:
    """Stand-in for a property so malformed/unreadable that even calling
    .is_a() on it blows up -- proves one bad entry doesn't abort the whole
    pset read, without needing to hand-craft real STEP corruption."""

    Name = "Bad"

    def is_a(self, *_args, **_kwargs):
        raise RuntimeError("simulated malformed property")


def test_malformed_property_is_skipped_not_fatal(model, wall):
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_Demo")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Good": "value"})

    class _FakePsetWithBadEntry:
        Name = "Pset_Demo"
        HasProperties = list(pset.HasProperties) + [_ExplodingProperty()]

    result = _read_property_set(_FakePsetWithBadEntry())

    assert result == {"Good": "value"}


def test_quantity_set_is_read(model, wall):
    length = model.create_entity("IfcQuantityLength", Name="Length", LengthValue=1.5)
    qto = model.create_entity(
        "IfcElementQuantity",
        GlobalId=ifcopenshell.guid.new(),
        Name="Qto_Demo",
        Quantities=[length],
    )
    model.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[wall],
        RelatingPropertyDefinition=qto,
    )

    result = read_pset(wall, "Qto_Demo")

    assert result == {"Length": 1.5}
