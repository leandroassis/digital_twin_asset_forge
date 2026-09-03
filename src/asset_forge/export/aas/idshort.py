"""Shared AASd-002 idShort sanitization.

Used for AssetAdministrationShell/Submodel id_shorts (built from an IFC
element's Name/GlobalId) *and* for arbitrary IFC property/pset names
becoming Property id_shorts inside the TechnicalData submodel -- both are
free-form text with no guarantee of being AAS-valid on their own (non-ASCII
characters, IFC GlobalIds that start with a digit, pset property names like
"#Object Class").
"""

import re
from typing import Dict, Iterable


def valid_id_short(candidate: str, fallback: str = "Asset") -> str:
    """AASd-002: idShort must contain only [0-9a-zA-Z_-], start with a
    *letter* specifically (basyx's own validator rejects a leading
    underscore or digit too, despite some looser readings of the spec) and
    not end with a hyphen."""
    slug = re.sub(r"[^0-9a-zA-Z_-]", "_", candidate).strip("_-")
    if not slug:
        return fallback
    if not slug[0].isalpha():
        slug = f"{fallback}_{slug}"
    return slug


def unique_id_shorts(names: Iterable[str], fallback: str = "Item") -> Dict[str, str]:
    """Slugify every name in `names`, disambiguating collisions (distinct
    raw names that happen to slugify to the same id_short -- a real risk
    with arbitrary IFC property/pset names, e.g. "Object Class" and
    "Object_Class") with a numeric suffix. A SubmodelElementCollection's
    children must have unique id_shorts among siblings; without this,
    populating one from arbitrary source data can raise a duplicate-id_short
    error partway through a run over thousands of elements."""
    used = set()
    result: Dict[str, str] = {}
    for name in names:
        base = valid_id_short(name, fallback=fallback)
        slug = base
        suffix = 2
        while slug in used:
            slug = f"{base}_{suffix}"
            suffix += 1
        used.add(slug)
        result[name] = slug
    return result
