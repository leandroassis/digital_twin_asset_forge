"""Defensive reading of IFC property sets.

`ifcopenshell.util.element.get_psets()` raises `RuntimeError` and aborts the
*entire* read if a single `IfcPropertySingleValue` is malformed (e.g. a
missing `NominalValue`) -- a real failure mode with some vendor exports.
This module walks `IsDefinedBy` itself and reads each property
individually, inside its own try/except, so one bad property only costs
that one property, never the whole element's metadata.

Blank string properties from some exporters come back as a single space
(`" "`) rather than an empty string or null, which silently breaks
truthiness/equality checks downstream -- `_normalize` strips and folds
those into `None` too.
"""

from typing import Any, Dict

from loguru import logger

_QUANTITY_ATTR = {
    "IfcQuantityLength": "LengthValue",
    "IfcQuantityArea": "AreaValue",
    "IfcQuantityVolume": "VolumeValue",
    "IfcQuantityCount": "CountValue",
    "IfcQuantityWeight": "WeightValue",
    "IfcQuantityTime": "TimeValue",
}


def read_all_psets(entity: Any) -> Dict[str, Dict[str, Any]]:
    """Return `{pset_name: {prop_name: value}}` for every property set or
    quantity set directly attached to `entity` via `IsDefinedBy`. Tolerant
    of malformed individual properties; never raises on account of the
    source data."""
    result: Dict[str, Dict[str, Any]] = {}
    for rel in getattr(entity, "IsDefinedBy", None) or ():
        definition = getattr(rel, "RelatingPropertyDefinition", None)
        if definition is None or not definition.Name:
            continue
        if definition.is_a("IfcPropertySet"):
            result[definition.Name] = _read_property_set(definition)
        elif definition.is_a("IfcElementQuantity"):
            result[definition.Name] = _read_quantity_set(definition)
    return result


def read_pset(entity: Any, pset_name: str) -> Dict[str, Any]:
    """Convenience wrapper: read just one named pset/qto (empty dict if the
    element doesn't carry it)."""
    return read_all_psets(entity).get(pset_name, {})


def _read_property_set(pset: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for prop in pset.HasProperties or ():
        try:
            normalized = _normalize(_property_value(prop))
        except Exception as exc:  # defend against any malformed property
            logger.debug(
                f"skipping malformed property {getattr(prop, 'Name', '?')!r} "
                f"in pset {pset.Name!r}: {exc}"
            )
            continue
        if prop.Name:
            values[prop.Name] = normalized
    return values


def _read_quantity_set(qto: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for quantity in qto.Quantities or ():
        try:
            normalized = _normalize(_quantity_value(quantity))
        except Exception as exc:
            logger.debug(
                f"skipping malformed quantity {getattr(quantity, 'Name', '?')!r} "
                f"in qto {qto.Name!r}: {exc}"
            )
            continue
        if quantity.Name:
            values[quantity.Name] = normalized
    return values


def _property_value(prop: Any) -> Any:
    if prop.is_a("IfcPropertySingleValue"):
        nominal = prop.NominalValue
        return nominal.wrappedValue if nominal is not None else None
    if prop.is_a("IfcPropertyEnumeratedValue"):
        return [v.wrappedValue for v in prop.EnumerationValues or ()]
    if prop.is_a("IfcPropertyListValue"):
        return [v.wrappedValue for v in prop.ListValues or ()]
    if prop.is_a("IfcPropertyBoundedValue"):
        return {
            "LowerBound": getattr(prop.LowerBoundValue, "wrappedValue", None),
            "UpperBound": getattr(prop.UpperBoundValue, "wrappedValue", None),
        }
    if prop.is_a("IfcComplexProperty"):
        return {
            p.Name: _normalize(_property_value(p))
            for p in prop.HasProperties or ()
            if p.Name
        }
    return None


def _quantity_value(quantity: Any) -> Any:
    attr = _QUANTITY_ATTR.get(quantity.is_a())
    return getattr(quantity, attr, None) if attr else None


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value
