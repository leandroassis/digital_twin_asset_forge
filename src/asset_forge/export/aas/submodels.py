"""Builds the AAS submodels this pipeline populates from a plant IFC
element: a minimal Nameplate, a TechnicalData sheet carrying every existing
pset generically, and an OPC UA datasheet with a *configurable* connection
endpoint only -- no OPC UA client/server code, see config.py.
"""

from typing import Any

from basyx.aas import model

from asset_forge.config import OPCUA_HOST, OPCUA_PORT
from asset_forge.elements.properties import read_all_psets
from asset_forge.export.aas.idshort import unique_id_shorts
from asset_forge.export.aas.templates import load_template


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


def build_opcua_submodel(
    host: str = OPCUA_HOST,
    port: int = OPCUA_PORT,
    endpoint_path: str = "freeopcua/server",
) -> model.Submodel:
    """OPC UA connection info only, configurable via `host`/`port`/
    `endpoint_path` -- no OPC UA client/server code exists in this package,
    see config.py. Values chosen to match a live BaSyx aas-environment
    without tripping known JSON/XML round-trip issues in the raw template
    (int, not bool, for the SupportSecurityMode* fields)."""
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

    return submodel
