"""Builds the AAS submodels this pipeline populates from a plant IFC
element: a minimal Nameplate, a TechnicalData sheet carrying every existing
pset generically (or a lean summary for non-panel elements, see
`build_lean_technicaldata_submodel`), an OPC UA datasheet with a
*configurable* connection endpoint and optional writable sensor Properties,
and a TimeSeries descriptor -- no OPC UA client/server code, see config.py.
"""

from typing import Any, Sequence

import ifcopenshell.util.element
from basyx.aas import model

from asset_forge.config import HISTORY_API_HOST, HISTORY_API_PORT, OPCUA_HOST, OPCUA_PORT
from asset_forge.elements.properties import read_all_psets
from asset_forge.export.aas.idshort import unique_id_shorts
from asset_forge.export.aas.solar import OpcuaVariable
from asset_forge.export.aas.templates import load_template

DEFAULT_LEAN_FIELDS = ("IfcClass", "Name", "GlobalId", "Tag", "ContainingStorey")


def build_nameplate_submodel(entity: Any, namespace: str) -> model.Submodel:
    """Only fields that exist directly on the IFC element -- no fabricated
    manufacturer/serial-number data the source doesn't have."""
    submodel = load_template("nameplate")
    submodel.id_short = "nameplate"

    submodel.get_referable("URIOfTheProduct").value = f"https://{namespace}/asset/{entity.GlobalId}"
    submodel.get_referable("UniqueFacilityIdentifier").value = entity.GlobalId

    if entity.Name:
        submodel.get_referable("ManufacturerProductDesignation").value = {"en": str(entity.Name)}

    # The template ships example list/collection entries with no real
    # idShort of their own, which trips "missing idShort" validation in
    # some viewers -- clear rather than leave broken example data behind.
    submodel.get_referable("Markings").value.clear()
    submodel.get_referable("AssetSpecificProperties").value.clear()

    return submodel


def build_technicaldata_submodel(entity: Any) -> model.Submodel:
    """Carries over every pset already on `entity`, generically -- this is
    what stands in for a per-IFC-class official pset mapping, which this
    pipeline deliberately doesn't build (see elements/classification.py's
    module docstring: no attempt is made to interpret element data beyond
    what the source IFC already states)."""
    submodel = load_template("technicaldata")
    submodel.id_short = "technicaldata"

    # The template ships these as worked examples with placeholder
    # id_shorts, not real data -- leaving them in trips "missing idShort"
    # validation in some viewers, same issue as Nameplate's example lists.
    submodel.get_referable("ProductClassifications").value.clear()
    submodel.get_referable("SpecificDescriptions").value.clear()
    submodel.get_referable("GeneralInformation").get_referable("ProductImages").value.clear()

    areas = submodel.get_referable("TechnicalPropertyAreas")
    areas.value.clear()

    psets = read_all_psets(entity)
    pset_slugs = unique_id_shorts(psets.keys(), fallback="Pset")

    for pset_name, props in psets.items():
        prop_items = {name: value for name, value in props.items() if value is not None}
        prop_slugs = unique_id_shorts(prop_items.keys(), fallback="Prop")

        area = model.SubmodelElementCollection(id_short=pset_slugs[pset_name])
        for prop_name, value in prop_items.items():
            area.value.add(model.Property(id_short=prop_slugs[prop_name], value_type=str, value=str(value)))
        if len(area.value):
            areas.value.add(area)

    return submodel


def build_lean_technicaldata_submodel(entity: Any, fields: Sequence[str] = DEFAULT_LEAN_FIELDS) -> model.Submodel:
    """A deliberately thin TechnicalData for elements that don't need their
    full raw-pset dump (see export/aas/package.py's full/lean split).

    Deliberately NOT built from the official `"technicaldata"` IDTA
    template, unlike `build_technicaldata_submodel` -- every one of that
    template's ~20 leaf fields (semanticId + qualifiers, even when left
    empty) costs 600-800 bytes on its own once serialized, measured at
    ~12KB/element even after clearing every placeholder list this module
    already knew about. Multiplied by several thousand non-panel elements,
    that alone blew the AASX's single data.json past BaSyx's ~100MB
    real-server cap (a live upload 500'd on a 291MB uncompressed data.json --
    the compressed on-disk .aasx size is a poor proxy for this: JSON's
    boilerplate-heavy repetition compresses away almost entirely, so a small
    file on disk can still fail server-side). A bare, from-scratch Submodel
    with only plain Properties has none of that per-field overhead."""
    submodel = model.Submodel(id_="placeholder", id_short="technicaldata")

    storey = ifcopenshell.util.element.get_container(entity)
    values = {
        "IfcClass": entity.is_a(),
        "Name": str(entity.Name) if entity.Name else None,
        "GlobalId": entity.GlobalId,
        "Tag": str(entity.Tag) if entity.Tag else None,
        "ContainingStorey": str(storey.Name) if storey is not None and storey.Name else None,
    }
    prop_items = {name: values[name] for name in fields if values.get(name) is not None}
    prop_slugs = unique_id_shorts(prop_items.keys(), fallback="Prop")

    identification = model.SubmodelElementCollection(id_short="Identification")
    for name, value in prop_items.items():
        identification.value.add(model.Property(id_short=prop_slugs[name], value_type=str, value=str(value)))
    submodel.submodel_element.add(identification)

    return submodel


def build_opcua_submodel(
    host: str = OPCUA_HOST,
    port: int = OPCUA_PORT,
    endpoint_path: str = "freeopcua/server",
    variables: Sequence[OpcuaVariable] = (),
) -> model.Submodel:
    """OPC UA connection info, configurable via `host`/`port`/`endpoint_path`
    -- no OPC UA client/server code exists in this package, see config.py.
    Values chosen to match a live BaSyx aas-environment without tripping
    known JSON/XML round-trip issues in the raw template (int, not bool, for
    the SupportSecurityMode* fields).

    `variables`, when given, adds one writable `Property` per variable
    directly on this submodel (id_short = `variable.id_short`, `value=0.0`)
    -- this is how one asset (e.g. a solar panel) exposes several
    independently-addressable sensor readings through a single `opcua`
    submodel, one per variable, rather than one submodel per reading. An
    external OPC UA server/DataBridge (see export/aas/databridge.py) is
    expected to write live values into these Properties; nothing in this
    package does so itself."""
    submodel = load_template("opcua")
    submodel.id_short = "opcua"

    endpoint = submodel.get_referable("EndpointDescriptions").value[0]
    endpoint.get_referable("EndpointUri").value = f"opc.tcp://{host}:{port}/{endpoint_path}"
    endpoint.get_referable("SecurityMode").value = "None"
    endpoint.get_referable("SecurityPolicyUri").value = "http://opcfoundation.org/UA/SecurityPolicy#None"

    config = submodel.get_referable("Configuration")
    config.get_referable("AllowAnonymousUser").value = True
    config.get_referable("SupportSecurityModeNone").value = 1
    config.get_referable("SupportSecurityModeSign").value = 0
    config.get_referable("SupportSecurityModeSignEncrypt").value = 0
    config.get_referable("SupportRedundancy").value = False
    config.get_referable("NodeSets").value.clear()

    for variable in variables:
        submodel.submodel_element.add(
            model.Property(id_short=variable.id_short, value_type=variable.value_type, value=0.0)
        )

    return submodel


def build_timeseries_submodel(
    label: str,
    variables: Sequence[OpcuaVariable],
    asset_tag: str,
    history_api_host: str = HISTORY_API_HOST,
    history_api_port: int = HISTORY_API_PORT,
) -> model.Submodel:
    """A TimeSeries (IDTA 02008) descriptor for `label`'s `variables`,
    pointing at the intermediary history-query service via
    `Segments.LinkedSegment` -- not `InternalSegment`/`ExternalSegment`,
    since BaSyx itself only ever holds each `opcua` submodel Property's
    *current* value, never a history.

    Deliberately does NOT point `LinkedSegment` at InfluxDB directly: `Query`
    is just the plain `asset_tag` (e.g. "PANEL-1529520"), and `Endpoint` is
    history_api.py's own base URL -- a consumer calls
    `{Endpoint}/series/{Query}` and gets JSON back, never touching Flux or
    knowing InfluxDB is the backend at all. `asset_tag` must match what
    mock_sensor.py tags its InfluxDB points with for the same asset (one
    query/tag returns every one of that asset's variables together, not
    just one -- see mock_sensor.py's module docstring)."""
    submodel = load_template("timeseries")
    submodel.id_short = "timeseries"

    metadata = submodel.get_referable("Metadata")
    metadata.get_referable("Name").value = {"en": f"{label} time series"}
    metadata.get_referable("Description").value = {"en": f"Time series variables for {label}"}

    record_schema = metadata.get_referable("Record")
    record_schema.value.clear()
    record_schema.value.add(model.Property(id_short="Time", value_type=str))
    for variable in variables:
        record_schema.value.add(model.Property(id_short=variable.id_short, value_type=variable.value_type))

    segments = submodel.get_referable("Segments")
    segments.value.remove(segments.get_referable("ExternalSegment"))
    segments.value.remove(segments.get_referable("InternalSegment"))

    linked = segments.get_referable("LinkedSegment")
    linked.get_referable("Name").value = {"en": f"{label} history-api linked segment"}
    linked.get_referable("Description").value = {
        "en": f"Historized telemetry for {label} -- GET {{Endpoint}}/series/{{Query}} for JSON, optionally ?count=N"
    }
    linked.get_referable("Endpoint").value = f"http://{history_api_host}:{history_api_port}"
    linked.get_referable("Query").value = asset_tag

    return submodel


def build_virtual_nameplate_submodel(name: str, virtual_id: str, namespace: str) -> model.Submodel:
    """Nameplate for a synthetic/virtual asset with no backing IFC element
    (e.g. the plant's inverter -- see export/aas/shell.py::build_virtual_shell).
    Same shape as `build_nameplate_submodel`, fed literal strings instead of
    an IFC entity's attributes."""
    submodel = load_template("nameplate")
    submodel.id_short = "nameplate"

    submodel.get_referable("URIOfTheProduct").value = f"https://{namespace}/asset/virtual/{virtual_id}"
    submodel.get_referable("UniqueFacilityIdentifier").value = virtual_id
    submodel.get_referable("ManufacturerProductDesignation").value = {"en": name}

    submodel.get_referable("Markings").value.clear()
    submodel.get_referable("AssetSpecificProperties").value.clear()

    return submodel
