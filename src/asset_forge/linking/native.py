"""Reads connectivity relations already present in the source IFC.

No attempt is made to infer missing connections from geometry: a
proximity/bounding-box heuristic can fail silently and produce wrong
topology in many real cases, so this pipeline never runs one. If a source
project carries no native connectivity, `find_connections` simply returns
an empty list -- callers (the DEXPI export stage) use that as the signal to
skip, with a clear message, rather than guessing.

Two relation types are read, both standard since IFC2X3:

- `IfcRelConnectsPorts`: an explicit connection between two distinct
  components' ports -- the strongest, most common signal in well-modelled
  piping/ducting systems (this is what a real MEP export like
  `digihub_building`'s heating/ventilation/sanitary disciplines uses,
  thousands of times over).
- `IfcRelConnectsElements`: a direct element-to-element connection with no
  explicit ports involved.

`IfcRelConnectsPortToElement` is deliberately *not* read here: it only
states "this port belongs to this element" (closer to nesting than to
topology), not a connection between two different components.
"""

from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass(frozen=True)
class Connection:
    element_a_guid: str
    element_b_guid: str
    kind: str  # "port" | "element"
    basis: Optional[str] = None


def _owning_element(port: Any) -> Optional[Any]:
    for nest in getattr(port, "Nests", None) or ():
        return nest.RelatingObject
    return None


def find_connections(model: Any) -> List[Connection]:
    connections: List[Connection] = []

    for rel in model.by_type("IfcRelConnectsPorts"):
        a = _owning_element(rel.RelatingPort)
        b = _owning_element(rel.RelatedPort)
        if a is None or b is None or a.GlobalId == b.GlobalId:
            continue
        connections.append(Connection(a.GlobalId, b.GlobalId, "port", rel.Description))

    for rel in model.by_type("IfcRelConnectsElements"):
        a, b = rel.RelatingElement, rel.RelatedElement
        if a is None or b is None or a.GlobalId == b.GlobalId:
            continue
        connections.append(Connection(a.GlobalId, b.GlobalId, "element", rel.Description))

    return connections


def has_native_connections(model: Any) -> bool:
    return len(find_connections(model)) > 0
