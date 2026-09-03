"""Passthrough classification with a schema-aware generic fallback.

No attempt is made here to *interpret* an element's data to guess a more
specific IFC class -- that would need a source-specific rule table (vendor
psets, an external mapping table, ...) this pipeline deliberately doesn't
build, since it isn't a hard requirement and doesn't generalize across
heterogeneous sources. If the source IFC already classifies an element
concretely, that classification is trusted and left untouched. Only
elements stuck on the schema's generic placeholder class are candidates for
"promotion" -- and even then, promotion only ever means resolving to the
current schema's own concrete generic element class, never guessing a
specific one.

Every element in a valid IFC file is already some concrete (non-abstract)
class -- the EXPRESS schema doesn't allow instantiating an abstract type
like `IfcElement` directly. So the only class this module ever needs to
treat as "not really classified" is the industry-standard generic
placeholder, `IfcBuildingElementProxy`. Confirmed valid/non-abstract in
IFC2X3, IFC4 and IFC4X3 -- but resolved against the loaded model's actual
schema rather than hardcoded, since a pipeline meant to take IFC files from
arbitrary sources shouldn't assume one schema version.
"""

from typing import Any

import ifcopenshell
import ifcopenshell.api.root
from loguru import logger

from asset_forge.pipeline.stage import Record, Stage

# Ordered by preference: the first name that is a valid, non-abstract class
# in the loaded model's schema is used as the generic fallback. Extend this
# list (not the resolution logic below) if a future schema ever drops
# IfcBuildingElementProxy.
_GENERIC_FALLBACK_CANDIDATES = ("IfcBuildingElementProxy",)

# Classes treated as "not really classified" and therefore eligible for
# fallback promotion. Extend here if a future source's own generic
# placeholder convention differs from IfcBuildingElementProxy.
_GENERIC_CLASSES = {"IfcBuildingElementProxy"}


def resolve_generic_fallback_class(model: ifcopenshell.file) -> str:
    """Return the concrete, schema-valid generic element class for
    `model`'s schema. Raises if none of the known candidate names exist as
    a concrete class in this schema, surfacing the gap instead of silently
    instantiating something invalid."""
    schema = ifcopenshell.ifcopenshell_wrapper.schema_by_name(model.schema)
    for candidate in _GENERIC_FALLBACK_CANDIDATES:
        try:
            declaration = schema.declaration_by_name(candidate)
        except RuntimeError:
            continue
        if not declaration.is_abstract():
            return candidate
    raise ValueError(
        f"no known generic fallback class is valid/concrete in schema "
        f"{model.schema!r}; add one to _GENERIC_FALLBACK_CANDIDATES"
    )


def is_generic(entity: Any) -> bool:
    return entity.is_a() in _GENERIC_CLASSES


def ensure_classified(model: ifcopenshell.file, entity: Any) -> Any:
    """If `entity` is already a specific, non-generic class, return it
    unchanged -- this is the common case for well-formed source IFCs.
    Otherwise reassign it to the schema's generic fallback class (a no-op
    if it already is that class) and return the resulting entity. Only the
    IFC class itself changes; existing psets are never touched here."""
    if not is_generic(entity):
        return entity

    fallback = resolve_generic_fallback_class(model)
    if entity.is_a() == fallback:
        return entity

    logger.debug(f"classification: promoting #{entity.id()} {entity.is_a()} -> {fallback}")
    return ifcopenshell.api.root.reassign_class(model, product=entity, ifc_class=fallback)


class ClassificationStage(Stage):
    """Pipeline Stage wrapper around `ensure_classified`, for use with
    `PlantPipeline.run(..., entities=model.by_type("IfcElement"))`."""

    def __call__(self, record: Record) -> bool:
        record.entity = ensure_classified(record.model, record.entity)
        return True
