"""Builds a pydexpi DexpiModel from a plant IFC + its native connections.

Deliberately conservative, matching the project's "reproduce, don't
reinterpret" stance: nothing here infers a specific DEXPI piping subtype
(valve, fitting, reducer...) from IFC data that doesn't reliably carry one.
Every element becomes a generic `pydexpi.dexpi_classes.piping.CustomPipingComponent`
(carrying its real IFC class as `typeName`), except an `IfcTank`, which maps
to the one confident equipment mapping, `pydexpi.dexpi_classes.equipment.Tank`.

Scope is limited to elements that participate in at least one connection
found by `linking.native.find_connections` -- DEXPI is a P&ID/topology
standard, so an element with no connection (an architectural wall, a
free-standing opening) has nothing to contribute to it. This is also a
load-bearing performance decision, not just a scoping one: an earlier spike
that included every IfcElement plus a full pset-by-pset CustomAttribute dump
against the reference multi-discipline sample (5096 elements, ~200k
attributes) made pydexpi's GraphLoader take several minutes and was still
running past a 3-minute timeout; scoping to the ~4100 connected elements and
a handful of identifying attributes per item (Tag, Description,
PredefinedType -- not a full pset dump, which belongs on the AAS
TechnicalData submodel instead, see export/aas/submodels.py) brought the
same export down to about two minutes end to end, graph export included.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

from pydexpi.dexpi_classes import equipment, piping
from pydexpi.dexpi_classes.customization import CustomAttribute
from pydexpi.dexpi_classes.dexpiModel import ConceptualModel, DexpiModel
from pydexpi.dexpi_classes.metaData import MetaData

from asset_forge.exceptions import DexpiUnavailableError
from asset_forge.linking.native import Connection, find_connections

_ORIGINATING_SYSTEM_NAME = "asset-forge"
_ORIGINATING_SYSTEM_VERSION = "0.1"

# Copied verbatim onto every DEXPI item as CustomAttributes -- basic
# identification only, not a full pset dump (see module docstring).
_IDENTIFYING_ATTRS = ("Tag", "Description", "PredefinedType")


def build_dexpi_model(model: Any, project_name: str) -> DexpiModel:
    """Build a DexpiModel for `model` (a federated, classified plant IFC).

    Raises DexpiUnavailableError if the source IFC carries no native
    connectivity relations -- callers (the CLI) are expected to catch this
    and skip DEXPI export with a clear message, never fall back to
    reconstructing connections via geometry.
    """
    connections = find_connections(model)
    if not connections:
        raise DexpiUnavailableError(
            f"'{project_name}' has no native IFC connectivity relations "
            "(IfcRelConnectsPorts / IfcRelConnectsElements) -- DEXPI export "
            "needs a real topology to build from and none was found."
        )

    connected_guids = {c.element_a_guid for c in connections} | {c.element_b_guid for c in connections}
    elements = [e for e in model.by_type("IfcElement") if e.GlobalId in connected_guids]

    items_by_guid: Dict[str, Any] = {}
    tagged_items: List[Any] = []
    for entity in elements:
        item = _build_tank(entity) if entity.is_a("IfcTank") else _build_generic_component(entity)
        items_by_guid[entity.GlobalId] = item
        if isinstance(item, equipment.Equipment):
            tagged_items.append(item)

    segment = piping.PipingNetworkSegment()
    segment.items = [i for i in items_by_guid.values() if not isinstance(i, equipment.Equipment)]

    for connection in connections:
        _wire_connection(segment, items_by_guid, connection)

    system = piping.PipingNetworkSystem(segments=[segment], lineNumber=project_name)
    conceptual = ConceptualModel(
        taggedPlantItems=tagged_items,
        pipingNetworkSystems=[system],
        metaData=MetaData(),
    )

    return DexpiModel(
        conceptualModel=conceptual,
        exportDateTime=datetime.now(timezone.utc),
        originatingSystemName=_ORIGINATING_SYSTEM_NAME,
        originatingSystemVendorName=project_name,
        originatingSystemVersion=_ORIGINATING_SYSTEM_VERSION,
    )


def _build_tank(entity: Any) -> Any:
    tank = equipment.Tank(tagName=entity.Name or entity.GlobalId)
    _attach_identifying_attributes(tank, entity)
    return tank


def _build_generic_component(entity: Any) -> Any:
    component = piping.CustomPipingComponent(typeName=entity.is_a(), pipingComponentName=entity.Name)
    _attach_identifying_attributes(component, entity)
    return component


def _attach_identifying_attributes(item: Any, entity: Any) -> None:
    for attr_name in _IDENTIFYING_ATTRS:
        value = getattr(entity, attr_name, None)
        if not value:
            continue
        item.customAttributes.append(
            CustomAttribute(
                attributeName=attr_name,
                attributeURI=f"urn:asset-forge:ifc-attribute:{attr_name}",
                value=str(value),
            )
        )


def _connection_point(item: Any):
    """Return (source_or_target_item, node) for a fresh connection endpoint
    on `item`. Equipment can only be a piping source/target through a
    Nozzle; ordinary piping components connect directly via their own
    PipingNode list. A fresh node/nozzle is created per connection, never
    reused -- there is no reliable per-component port count in the source
    IFC to size a pool up front."""
    if isinstance(item, equipment.Equipment):
        nozzle = equipment.Nozzle()
        node = piping.PipingNode()
        nozzle.nodes.append(node)
        item.nozzles.append(nozzle)
        return nozzle, node
    node = piping.PipingNode()
    item.nodes.append(node)
    return item, node


def _wire_connection(segment: Any, items_by_guid: Dict[str, Any], connection: Connection) -> None:
    a = items_by_guid.get(connection.element_a_guid)
    b = items_by_guid.get(connection.element_b_guid)
    if a is None or b is None:
        return
    source, source_node = _connection_point(a)
    target, target_node = _connection_point(b)
    segment.connections.append(
        piping.PipingConnection(sourceItem=source, sourceNode=source_node, targetItem=target, targetNode=target_node)
    )
