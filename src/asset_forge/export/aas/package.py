"""Builds one AAS Shell per plant IFC element and writes them into .aasx
package(s), batched to stay under two real, confirmed Apache POI limits."""

import io
from pathlib import Path
from typing import Any, List, Optional

from basyx.aas import model
from basyx.aas.adapter import aasx
from loguru import logger

from asset_forge.export.aas.geometry import extract_element_ifc
from asset_forge.export.aas.shell import build_shell
from asset_forge.export.aas.submodels import (
    build_nameplate_submodel,
    build_opcua_submodel,
    build_technicaldata_submodel,
)
from asset_forge.ingestion.loader import PathLike

_MODEL_3D_ID_SHORT = "Model3DIFC"

# Element classes that get an OPC UA datasheet submodel -- a live OPC UA
# endpoint would only ever expose a value for a sensor/meter; everything
# else gets just Nameplate + TechnicalData.
_OPCUA_ELIGIBLE_CLASSES = ("IfcSensor", "IfcFlowMeter")

# One AASX package (a zip/OPC package) per project would be simpler, but two
# *separate*, confirmed-live Apache POI safety limits rule that out for any
# project with a few thousand elements -- both are enforced by the BaSyx
# server reading the package back, not by anything on our side:
#
# 1. `org.apache.poi.util.IOUtils` refuses to allocate more than 100,000,000
#    bytes for a single record/part when reading it. A naive single
#    `/aasx/data.json` holding all 5096 digihub_building elements measured
#    158,364,119 bytes and 500'd on upload
#    (`RecordFormatException: ... maximum length for this record type is
#    100,000,000`).
# 2. Splitting *within one package* into multiple smaller JSON parts (each
#    under limit 1) does NOT work either -- it trades that limit for a
#    second, separate one: `ZipSecureFile`'s zip-bomb guard caps the total
#    *number* of entries in a single zip/OPC package at 1000
#    (`MAX_FILE_COUNT`), and this pipeline attaches one geometry file per
#    element (see `_attach_geometry`), so a project's total entry count is
#    roughly (element count) + (number of JSON parts) -- 5096 elements blows
#    past 1000 long before the byte-size limit is even relevant. Confirmed
#    live: a single `model.aasx` with 5096 geometry entries + 11 JSON parts
#    (5122 entries total) failed with `IOException: The file appears to be
#    potentially malicious. This file embeds more internal file entries than
#    expected ... Limits: MAX_FILE_COUNT: 1000`. Neither limit is
#    configurable from the server side we control (no env var; it's a Java
#    API default baked into the image).
#
# Both limits are per*-package*, so multiple smaller *files* -- not multiple
# parts inside one file -- is the only fix that works for both at once. 500
# elements/file keeps every file's entry count (~501: 500 geometry files + 1
# data.json) comfortably under 1000, and every data.json (~31KB/element
# measured on that project, so ~15.5MB) comfortably under the byte cap, while
# staying a no-op (single `model.aasx`) for small projects like HVAC.
DEFAULT_BATCH_SIZE = 500


def build_and_write_aasx(
    plant_model: Any,
    output_dir: PathLike,
    namespace: str,
    opcua_host: str,
    opcua_port: int,
    elements: Optional[List[Any]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List[Path]:
    """Write one or more .aasx packages (batched per `batch_size` elements)
    into `output_dir`. A single batch is named `model.aasx`; multiple
    batches are named `model-0001.aasx`, `model-0002.aasx`, etc. Returns the
    list of paths written, in order."""
    elements = list(elements if elements is not None else plant_model.by_type("IfcElement"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batches = [elements[i : i + batch_size] for i in range(0, len(elements), batch_size)] or [[]]

    written: List[Path] = []
    for index, batch in enumerate(batches, start=1):
        suffix = "" if len(batches) == 1 else f"-{index:04d}"
        path = output_dir / f"model{suffix}.aasx"
        _write_batch(batch, path, namespace, opcua_host, opcua_port)
        written.append(path)

    return written


def _write_batch(
    elements: List[Any],
    output_path: Path,
    namespace: str,
    opcua_host: str,
    opcua_port: int,
) -> None:
    object_store: model.DictIdentifiableStore = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    used_file_names_lower: set = set()
    aas_ids: List[str] = []

    for entity in elements:
        technicaldata = build_technicaldata_submodel(entity)
        _attach_geometry(technicaldata, entity, file_store, used_file_names_lower)

        submodels = [build_nameplate_submodel(entity, namespace), technicaldata]
        if entity.is_a() in _OPCUA_ELIGIBLE_CLASSES:
            submodels.append(build_opcua_submodel(host=opcua_host, port=opcua_port))

        shell, submodels = build_shell(entity, namespace, submodels)
        object_store.add(shell)
        for submodel in submodels:
            object_store.add(submodel)
        aas_ids.append(shell.id)

    with aasx.AASXWriter(str(output_path)) as writer:
        # Submodels serialized as JSON inside the AASX, not XML: confirmed
        # against a live BaSyx aas-environment (2.0.0-SNAPSHOT) that the XML
        # variant fails upload with a DeserializationException-400, while
        # the JSON variant succeeds.
        writer.write_aas(aas_ids, object_store, file_store, write_json=True)

    logger.info(f"wrote {output_path} ({len(aas_ids)} shell(s))")


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
