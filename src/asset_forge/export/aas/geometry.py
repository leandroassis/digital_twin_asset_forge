"""Extracts one IFC element's own 3D geometry as a standalone .ifc, so it can
be attached to that element's AAS shell as a supplementary file -- the AAS
package alone otherwise carries only metadata, no model to actually look at.
"""

from typing import Any

import ifcopenshell


def extract_element_ifc(entity: Any) -> bytes:
    """Build a minimal standalone .ifc containing just `entity`'s own
    geometry (+ the shared IfcProject/geometric representation context/unit
    assignment it references) and return it serialized as bytes.

    `ifcopenshell.file.add()` only follows *forward* attribute references
    (confirmed in ingestion/federation.py) -- entity.Representation and
    entity.ObjectPlacement are forward attributes, so the geometry, its
    placement chain and the IfcGeometricRepresentationContext they resolve
    against all come along automatically. IfcProject is added explicitly
    afterward for a more complete/renderable file; since add() dedupes on
    source-entity identity, if the project's own RepresentationContexts is
    the same context object entity's placement chain already reached, it is
    reused, not duplicated.
    """
    source: ifcopenshell.file = entity.file
    extract = ifcopenshell.file(schema=source.schema)
    extract.add(entity)

    projects = source.by_type("IfcProject")
    if projects:
        extract.add(projects[0])

    return extract.to_string().encode("utf-8")
