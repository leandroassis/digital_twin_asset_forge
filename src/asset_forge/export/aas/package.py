"""Builds one AAS Shell per plant IFC element (plus a virtual shell for the
plant's inverter, which has no backing IfcElement) and writes them into
.aasx package(s), batched to stay under a real, confirmed Apache POI limit."""

import io
from pathlib import Path
from typing import Any, List, Optional, Tuple

from basyx.aas import model
from basyx.aas.adapter import aasx
from loguru import logger

from asset_forge.export.aas.databridge import DatabridgeContract, write_databridge_config
from asset_forge.export.aas.geometry import extract_element_ifc
from asset_forge.export.aas.shell import build_shell, build_virtual_shell
from asset_forge.export.aas.solar import INVERTER_VARIABLES, PANEL_VARIABLES, OpcuaVariable, is_solar_panel
from asset_forge.export.aas.submodels import (
    build_lean_technicaldata_submodel,
    build_nameplate_submodel,
    build_opcua_submodel,
    build_technicaldata_submodel,
    build_timeseries_submodel,
    build_virtual_nameplate_submodel,
)
from asset_forge.ingestion.loader import PathLike

_MODEL_3D_ID_SHORT = "Model3DIFC"

# Element classes that get an OPC UA datasheet submodel regardless of the
# panel/lean split below -- a live OPC UA endpoint would only ever expose a
# value for a sensor/meter; everything else (other than solar panels) gets
# just Nameplate + TechnicalData.
_OPCUA_ELIGIBLE_CLASSES = ("IfcSensor", "IfcFlowMeter")

# A single AASX package (a zip/OPC package) has one real, confirmed,
# non-configurable Apache POI limit to stay under: `org.apache.poi.util.IOUtils`
# refuses to allocate more than 100,000,000 bytes for a single record/part
# when reading it back. A naive single `/aasx/data.json` holding a full
# raw-pset TechnicalData dump for every element of a several-thousand-element
# plant can measure well over that (confirmed: 158MB for a 5096-element
# plant). The full/lean TechnicalData split (see export/aas/solar.py,
# submodels.py) is what actually keeps a single package's data.json under
# this cap now; `batch_size` remains as a safety net for a plant whose
# full/lean split still doesn't fit.
#
# The *other* Apache POI limit this pipeline used to also guard against --
# `ZipSecureFile`'s 1000-total-zip-entries cap -- no longer needs batching to
# stay under: `_attach_geometry` (one embedded IFC file per element) is now
# only called for the "full" tier (solar panels + the virtual inverter),
# so a plant's total entry count is bounded by that tier's size, not by its
# total element count.
DEFAULT_BATCH_SIZE = 20_000

# Above this, a written package is getting close to the ~100MB hard cap --
# logged as an early warning at build time rather than discovered as a 500
# at upload time.
_SIZE_WARNING_BYTES = 80_000_000


def build_and_write_aasx(
    plant_model: Any,
    output_dir: PathLike,
    namespace: str,
    opcua_host: str,
    opcua_port: int,
    elements: Optional[List[Any]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    databridge_dir: Optional[PathLike] = None,
    aas_env_host: str = "localhost",
    aas_env_port: int = 8081,
) -> List[Path]:
    """Write one or more .aasx packages (batched per `batch_size` elements)
    into `output_dir`. A single batch is named `model.aasx`; multiple
    batches are named `model-0001.aasx`, `model-0002.aasx`, etc. Returns the
    list of paths written, in order.

    Every solar-panel element (see export/aas/solar.py::is_solar_panel) gets
    the full treatment (raw-pset TechnicalData, embedded geometry, an
    `opcua` submodel with its 4 sensor Properties, a `timeseries`
    descriptor); every other element gets a lean TechnicalData only. A
    single virtual "Inverter" shell (no backing IfcElement) is added
    carrying the plant's 3 AC output variables, the same way. If
    `databridge_dir` is given and at least one panel/inverter variable was
    produced, the DataBridge config bridging an external OPC UA server's
    writes into these submodels is written there too."""
    elements = list(elements if elements is not None else plant_model.by_type("IfcElement"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batches = [elements[i : i + batch_size] for i in range(0, len(elements), batch_size)] or [[]]

    written: List[Path] = []
    all_contracts: List[DatabridgeContract] = []
    for index, batch in enumerate(batches, start=1):
        suffix = "" if len(batches) == 1 else f"-{index:04d}"
        path = output_dir / f"model{suffix}.aasx"
        virtual_assets = [_build_inverter_shell(namespace, opcua_host, opcua_port)] if index == 1 else []
        contracts = _write_batch(batch, path, namespace, opcua_host, opcua_port, virtual_assets)
        all_contracts.extend(contracts)
        written.append(path)

    if databridge_dir is not None and all_contracts:
        write_databridge_config(databridge_dir, all_contracts, opcua_host, opcua_port, aas_env_host, aas_env_port)

    return written


def _build_inverter_shell(
    namespace: str, opcua_host: str, opcua_port: int
) -> Tuple[model.AssetAdministrationShell, List[model.Submodel], Optional[DatabridgeContract]]:
    asset_tag = "INVERTER"
    opcua_sm = build_opcua_submodel(host=opcua_host, port=opcua_port, variables=INVERTER_VARIABLES)
    submodels = [
        build_virtual_nameplate_submodel("Inverter", "inverter", namespace),
        opcua_sm,
        build_timeseries_submodel("Inverter", INVERTER_VARIABLES, asset_tag=asset_tag),
    ]
    shell, submodels = build_virtual_shell("inverter", "Inverter", namespace, submodels)
    contract = DatabridgeContract(asset_tag, opcua_sm.id, INVERTER_VARIABLES)
    return shell, submodels, contract


def _write_batch(
    elements: List[Any],
    output_path: Path,
    namespace: str,
    opcua_host: str,
    opcua_port: int,
    virtual_assets: List[Tuple[model.AssetAdministrationShell, List[model.Submodel], Optional[DatabridgeContract]]],
) -> List[DatabridgeContract]:
    object_store: model.DictIdentifiableStore = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    used_file_names_lower: set = set()
    aas_ids: List[str] = []
    contracts: List[DatabridgeContract] = []

    for entity in elements:
        panel = is_solar_panel(entity)
        variables: Tuple[OpcuaVariable, ...] = PANEL_VARIABLES if panel else ()

        technicaldata = build_technicaldata_submodel(entity) if panel else build_lean_technicaldata_submodel(entity)
        if panel:
            _attach_geometry(technicaldata, entity, file_store, used_file_names_lower)

        # Nameplate is skipped for the lean tier: it's built from the same
        # kind of heavy IDTA template as the full TechnicalData (see
        # build_lean_technicaldata_submodel's docstring) and would be pure
        # per-field overhead here -- lean TechnicalData's own Identification
        # properties (Name/GlobalId/...) already cover what a non-panel
        # element's Nameplate would have said anyway.
        submodels = [build_nameplate_submodel(entity, namespace), technicaldata] if panel else [technicaldata]
        opcua_sm = None
        asset_tag = f"PANEL-{entity.Tag}"
        if entity.is_a() in _OPCUA_ELIGIBLE_CLASSES or variables:
            opcua_sm = build_opcua_submodel(host=opcua_host, port=opcua_port, variables=variables)
            submodels.append(opcua_sm)
            if variables:
                submodels.append(
                    build_timeseries_submodel(str(entity.Tag or entity.GlobalId), variables, asset_tag=asset_tag)
                )

        shell, submodels = build_shell(entity, namespace, submodels)
        object_store.add(shell)
        for submodel in submodels:
            object_store.add(submodel)
        aas_ids.append(shell.id)

        if variables and opcua_sm is not None:
            contracts.append(DatabridgeContract(asset_tag, opcua_sm.id, variables))

    for shell, submodels, contract in virtual_assets:
        object_store.add(shell)
        for submodel in submodels:
            object_store.add(submodel)
        aas_ids.append(shell.id)
        if contract is not None:
            contracts.append(contract)

    with aasx.AASXWriter(str(output_path)) as writer:
        # Submodels serialized as JSON inside the AASX, not XML: confirmed
        # against a live BaSyx aas-environment (2.0.0-SNAPSHOT) that the XML
        # variant fails upload with a DeserializationException-400, while
        # the JSON variant succeeds.
        writer.write_aas(aas_ids, object_store, file_store, write_json=True)

    size = output_path.stat().st_size
    if size > _SIZE_WARNING_BYTES:
        logger.warning(f"{output_path} is {size:,} bytes -- approaching BaSyx's ~100,000,000 byte package cap")

    logger.info(f"wrote {output_path} ({len(aas_ids)} shell(s))")
    return contracts


def _attach_geometry(
    technicaldata: model.Submodel,
    entity: Any,
    file_store: aasx.DictSupplementaryFileContainer,
    used_file_names_lower: set,
) -> None:
    """Extract `entity`'s own 3D geometry and attach it to `technicaldata`
    as a File element (`Model3DIFC`), so the plant's 3D model is actually
    available in BaSyx per-component, not just property values.

    IFC GlobalIds are case-sensitive, but OPC part names (what a zip entry
    inside an AASX becomes once BaSyx reads it back) are compared
    case-insensitively per the OPC spec (ECMA-376). Confirmed live: two
    digihub_building elements whose GlobalIds differed only in the case of
    their last character (`...UIv` vs `...UIV`) produced two byte-distinct,
    validly-named zip entries that our own zipfile/basyx-python-sdk saw as
    fine, but Apache POI's OPC-aware reader on the BaSyx server rejected the
    whole upload with "Input file contains more than 1 entry with the name
    ...UIV.ifc". `used_file_names_lower` tracks case-folded names already
    used in this batch so a colliding entity gets a disambiguated name
    instead of silently colliding server-side.
    """
    name = f"/aasx/{entity.GlobalId}.ifc"
    folded = name.lower()
    if folded in used_file_names_lower:
        suffix = 2
        while f"{folded}.{suffix}" in used_file_names_lower:
            suffix += 1
        name = f"{name}.{suffix}"
        folded = name.lower()
    used_file_names_lower.add(folded)

    ifc_bytes = extract_element_ifc(entity)
    stored_name = file_store.add_file(name, io.BytesIO(ifc_bytes), "application/x-step")
    technicaldata.submodel_element.add(
        model.File(id_short=_MODEL_3D_ID_SHORT, content_type="application/x-step", value=stored_name)
    )
