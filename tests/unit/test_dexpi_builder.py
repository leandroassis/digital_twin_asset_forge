import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.guid
import pytest
from pydexpi.dexpi_classes import equipment, piping

from asset_forge.exceptions import DexpiUnavailableError
from asset_forge.export.dexpi_builder import build_dexpi_model


def _connect(model, a, b):
    """Nest a fresh port under each of `a`/`b` and connect them, mirroring
    the real IFC shape find_connections() reads (see linking/native.py)."""
    port_a = ifcopenshell.api.root.create_entity(model, ifc_class="IfcDistributionPort")
    port_b = ifcopenshell.api.root.create_entity(model, ifc_class="IfcDistributionPort")
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=a,
        RelatedObjects=[port_a],
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=b,
        RelatedObjects=[port_b],
    )
    model.create_entity(
        "IfcRelConnectsPorts",
        GlobalId=ifcopenshell.guid.new(),
        RelatingPort=port_a,
        RelatedPort=port_b,
    )


@pytest.fixture
def model():
    return ifcopenshell.file(schema="IFC4")


def test_raises_when_no_native_connections(model):
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment")

    with pytest.raises(DexpiUnavailableError):
        build_dexpi_model(model, project_name="demo")


def test_two_connected_pipe_segments_become_one_segment_with_one_connection(model):
    a = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment", name="Segment A")
    b = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment", name="Segment B")
    _connect(model, a, b)

    dexpi_model = build_dexpi_model(model, project_name="demo")

    systems = dexpi_model.conceptualModel.pipingNetworkSystems
    assert len(systems) == 1
    assert systems[0].lineNumber == "demo"

    segments = systems[0].segments
    assert len(segments) == 1
    assert len(segments[0].items) == 2
    assert all(isinstance(i, piping.CustomPipingComponent) for i in segments[0].items)
    assert {i.typeName for i in segments[0].items} == {"IfcPipeSegment"}

    assert len(segments[0].connections) == 1


def test_unconnected_element_is_excluded_from_the_dexpi_model(model):
    a = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment")
    b = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment")
    _connect(model, a, b)
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")  # no connection at all

    dexpi_model = build_dexpi_model(model, project_name="demo")

    segment = dexpi_model.conceptualModel.pipingNetworkSystems[0].segments[0]
    assert len(segment.items) == 2


def test_tank_becomes_equipment_connected_via_a_fresh_nozzle(model):
    tank = ifcopenshell.api.root.create_entity(model, ifc_class="IfcTank", name="T-100")
    pipe = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment")
    _connect(model, tank, pipe)

    dexpi_model = build_dexpi_model(model, project_name="demo")

    tagged = dexpi_model.conceptualModel.taggedPlantItems
    assert len(tagged) == 1
    assert isinstance(tagged[0], equipment.Tank)
    assert tagged[0].tagName == "T-100"
    assert len(tagged[0].nozzles) == 1

    segment = dexpi_model.conceptualModel.pipingNetworkSystems[0].segments[0]
    # Only the pipe segment goes into segment.items -- equipment does not.
    assert len(segment.items) == 1
    assert len(segment.connections) == 1
    connection = segment.connections[0]
    assert tagged[0].nozzles[0] in (connection.sourceItem, connection.targetItem)
