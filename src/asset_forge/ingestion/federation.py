"""Federates multiple .ifc files belonging to the same project into one
ifcopenshell.file.

Validated empirically against the reference multi-discipline sample (a
building exported as separate Architecture/Heating/Ventilation/Sanitary
.ifc files that share the same IfcProject/IfcSite/IfcBuilding GlobalId, but
each discipline has its own set of IfcBuildingStorey and its own unit
assignment):

- `ifcopenshell.file.add()` only follows an entity's *forward* attribute
  references (geometry, placement, type) -- never its *inverse*
  relationships. An added IfcPipeSegment came back with zero psets attached
  until its IfcRelDefinesByProperties relationships were added explicitly.
  Ports are the same story: they are only reachable via a parent element's
  IsNestedBy, never carried along automatically.
- `add()` *does* deduplicate: calling it twice on the same source entity, or
  on a relationship whose RelatedObjects/RelatingPropertyDefinition were
  already added separately (in either order), correctly reuses the same
  target entity instead of duplicating it. This is what makes it safe to
  add an IfcRelConnectsPorts relationship that reaches across two different
  source elements without worrying about which one gets processed first.
- Each source file keeps its own IfcGeometricRepresentationContext /
  IfcUnitAssignment through `add()`'s forward-copy -- geometry copied from a
  millimetre-unit discipline file stays self-consistent once merged into a
  metre-unit base file; no unit conversion is attempted or needed.

Every element also gets grouped by its originating discipline/file via a
plain `IfcGroup` (+ `IfcRelAssignsToGroup`), one group per source file --
most IFC viewers expose groups as a browsable tree independent of the
spatial structure, which is what makes it possible to isolate/hide one
discipline (e.g. just heating, or just ventilation) inside the single
federated plant.ifc. This is in addition to, not instead of, the per-element
`Pset_SourceProvenance` pset already carrying the same origin as inspectable
property data.
"""

from pathlib import Path
from typing import Dict, List, Sequence

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
from loguru import logger

from asset_forge.exceptions import FederationError
from asset_forge.ingestion.loader import PathLike, load_ifc

PROVENANCE_PSET = "Pset_SourceProvenance"


def federate(paths: Sequence[PathLike]) -> ifcopenshell.file:
    """Combine the .ifc files in `paths` (all belonging to one project) into
    a single ifcopenshell.file. With a single path, just loads and returns
    it unchanged -- most projects under `assets/` need no federation at all
    (grouping by discipline, below, is meaningless with only one).
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise FederationError("no IFC files given to federate")

    models = [(p, load_ifc(p)) for p in paths]
    if len(models) == 1:
        return models[0][1]

    base_path, base = _pick_primary(models)
    logger.info(f"federation: using '{base_path.name}' as the primary/base model")

    storey_index = _index_storeys(base)
    overflow_storeys: Dict[str, ifcopenshell.entity_instance] = {}

    # The base file's own elements never go through _copy_element (they're
    # already in `base`), so they need their provenance/grouping done here
    # explicitly, same label convention (source file stem) as merged files.
    elements_by_discipline: Dict[str, List[ifcopenshell.entity_instance]] = {
        base_path.stem: list(base.by_type("IfcElement"))
    }
    for entity in elements_by_discipline[base_path.stem]:
        _tag_provenance(base, entity, base_path.stem)

    for path, model in models:
        if model is base:
            continue
        elements_by_discipline[path.stem] = _merge_into(base, model, path.stem, storey_index, overflow_storeys)

    _group_by_discipline(base, elements_by_discipline)

    return base


def _pick_primary(models):
    """The file with the most IfcBuildingStorey entities is assumed to carry
    the authoritative spatial structure (confirmed for the reference
    sample: the architecture discipline defines the real storeys; MEP
    disciplines re-export storeys sharing the same Name but a different
    GlobalId)."""
    return max(models, key=lambda pm: len(pm[1].by_type("IfcBuildingStorey")))


def _index_storeys(model: ifcopenshell.file) -> Dict[str, ifcopenshell.entity_instance]:
    index: Dict[str, ifcopenshell.entity_instance] = {}
    for storey in model.by_type("IfcBuildingStorey"):
        index[f"guid:{storey.GlobalId}"] = storey
        if storey.Name:
            index.setdefault(f"name:{storey.Name}", storey)
    return index


def _merge_into(base, source, source_label, storey_index, overflow_storeys) -> List[ifcopenshell.entity_instance]:
    contained_ids = set()
    copied: List[ifcopenshell.entity_instance] = []

    for storey in source.by_type("IfcBuildingStorey"):
        target_storey = (
            storey_index.get(f"guid:{storey.GlobalId}")
            or storey_index.get(f"name:{storey.Name}")
            or _overflow_storey(base, source_label, overflow_storeys)
        )
        for rel in storey.ContainsElements:
            for element in rel.RelatedElements:
                contained_ids.add(element.id())
                copied.append(_copy_element(base, element, target_storey, source_label))

    # Safety net: any IfcProduct never bucketed under a storey at all.
    # IfcPort/IfcSpatialStructureElement are skipped on purpose -- ports
    # travel with their parent element via IsNestedBy (see _copy_element).
    stray_storey = None
    for element in source.by_type("IfcProduct"):
        if element.id() in contained_ids:
            continue
        if element.is_a("IfcPort") or element.is_a("IfcSpatialStructureElement"):
            continue
        if element.is_a() in ("IfcProject", "IfcSite", "IfcBuilding"):
            continue
        stray_storey = stray_storey or _overflow_storey(base, source_label, overflow_storeys)
        copied.append(_copy_element(base, element, stray_storey, source_label))

    logger.info(f"federation: merged {len(copied)} element(s) from '{source_label}'")
    return copied


def _overflow_storey(base, source_label, overflow_storeys):
    if source_label in overflow_storeys:
        return overflow_storeys[source_label]

    building = base.by_type("IfcBuilding")[0]
    storey = ifcopenshell.api.root.create_entity(
        base, ifc_class="IfcBuildingStorey", name=f"unmatched ({source_label})"
    )
    ifcopenshell.api.aggregate.assign_object(base, products=[storey], relating_object=building)
    overflow_storeys[source_label] = storey
    logger.warning(
        f"federation: no matching storey for some elements from '{source_label}'; "
        f"created overflow storey '{storey.Name}'"
    )
    return storey


def _copy_element(base, element, target_storey, source_label):
    new_entity = base.add(element)

    for rel in getattr(element, "IsDefinedBy", None) or ():
        base.add(rel)
    for rel in getattr(element, "IsTypedBy", None) or ():
        base.add(rel)
    for nest_rel in getattr(element, "IsNestedBy", None) or ():
        base.add(nest_rel)
        for port in nest_rel.RelatedObjects:
            connections = list(getattr(port, "ConnectedTo", None) or ()) + list(
                getattr(port, "ConnectedFrom", None) or ()
            )
            for conn_rel in connections:
                base.add(conn_rel)

    ifcopenshell.api.spatial.assign_container(base, products=[new_entity], relating_structure=target_storey)
    _tag_provenance(base, new_entity, source_label)
    return new_entity


def _tag_provenance(base, entity, source_label):
    pset = ifcopenshell.api.pset.add_pset(base, product=entity, name=PROVENANCE_PSET)
    ifcopenshell.api.pset.edit_pset(base, pset=pset, properties={"SourceFile": source_label})


def _group_by_discipline(base, elements_by_discipline: Dict[str, List[ifcopenshell.entity_instance]]) -> None:
    """One IfcGroup per source file, holding every element copied/kept from
    it -- lets a viewer isolate/hide one discipline independently of the
    spatial structure, which is shared/merged across all of them."""
    for label, entities in elements_by_discipline.items():
        if not entities:
            continue
        group = ifcopenshell.api.group.add_group(base, name=label)
        ifcopenshell.api.group.assign_group(base, products=entities, group=group)
    logger.info(f"federation: grouped elements by discipline: {sorted(elements_by_discipline)}")
