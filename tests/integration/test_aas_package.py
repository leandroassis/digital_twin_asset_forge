from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")
pytest.importorskip("basyx")

from basyx.aas import model  # noqa: E402
from basyx.aas.adapter import aasx  # noqa: E402

from asset_forge.export.aas.package import build_and_write_aasx  # noqa: E402
from asset_forge.export.ifc_writer import build_plant  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HVAC_FILE = REPO_ROOT / "assets" / "HVAC" / "301110PART03_Buderus_200406_20070209_ifc.ifc"


@pytest.mark.skipif(not HVAC_FILE.is_file(), reason="sample asset not present")
def test_aasx_round_trips_through_disk_for_a_real_element(tmp_path):
    plant = build_plant([HVAC_FILE])

    out_paths = build_and_write_aasx(
        plant,
        tmp_path,
        namespace="example.org/asset-forge",
        opcua_host="localhost",
        opcua_port=4840,
    )

    assert [p.name for p in out_paths] == ["model.aasx"]

    store = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    with aasx.AASXReader(str(out_paths[0])) as reader:
        reader.read_into(object_store=store, file_store=file_store)

    shells = [o for o in store if isinstance(o, model.AssetAdministrationShell)]
    submodels = [o for o in store if isinstance(o, model.Submodel)]

    assert len(shells) == 1
    model.AssetAdministrationShell.validate_id_short(shells[0].id_short)
    assert {sm.id_short for sm in submodels} == {"nameplate", "technicaldata"}

    technicaldata = next(sm for sm in submodels if sm.id_short == "technicaldata")
    model_file = technicaldata.get_referable("Model3DIFC")
    assert model_file.content_type == "application/x-step"

    import io

    buffer = io.BytesIO()
    file_store.write_file(model_file.value, buffer)
    extracted_ifc = buffer.getvalue().decode("utf-8")
    assert "ISO-10303-21" in extracted_ifc
    assert "IFCENERGYCONVERSIONDEVICE" in extracted_ifc.upper()


def test_large_element_counts_are_split_into_multiple_files(tmp_path):
    # Real bug, found live: batching into multiple JSON *parts* within a
    # single .aasx (instead of multiple files) still failed against a real
    # BaSyx server, just on a different Apache POI safety cap than the byte
    # size one this batching was originally built for -- ZipSecureFile's
    # zip-bomb guard rejects a single zip/OPC package with more than 1000
    # total entries, and one geometry file per element blows past that long
    # before the byte-size cap matters. Splitting into multiple *files*
    # keeps every single package's entry count low too, which is why that's
    # the only design confirmed to work for large element counts.
    import ifcopenshell
    import ifcopenshell.api.root

    ifc_model = ifcopenshell.file(schema="IFC4")
    elements = [
        ifcopenshell.api.root.create_entity(ifc_model, ifc_class="IfcWall", name=f"Wall-{i}")
        for i in range(5)
    ]

    out_paths = build_and_write_aasx(
        ifc_model,
        tmp_path,
        namespace="example.org/asset-forge",
        opcua_host="localhost",
        opcua_port=4840,
        elements=elements,
        batch_size=2,
    )

    assert [p.name for p in out_paths] == ["model-0001.aasx", "model-0002.aasx", "model-0003.aasx"]
    for path in out_paths:
        assert path.is_file()


def test_globalids_differing_only_by_case_do_not_collide_as_opc_part_names(tmp_path):
    # Real bug, found live: OPC part names (what a zip entry becomes once
    # BaSyx reads an .aasx back) are compared case-insensitively per the OPC
    # spec, even though IFC GlobalIds are case-sensitive. Two elements whose
    # GlobalIds differed only by the case of one character produced an AASX
    # that Apache POI's OPC-aware reader on a real BaSyx server rejected
    # with "Input file contains more than 1 entry with the name ...".
    import ifcopenshell
    import ifcopenshell.api.root

    # Named as solar panels: only panel elements get the full TechnicalData
    # treatment (incl. the embedded Model3DIFC geometry file this test is
    # about) since export/aas/package.py's full/lean split, see
    # export/aas/solar.py::is_solar_panel.
    ifc_model = ifcopenshell.file(schema="IFC4")
    a = ifcopenshell.api.root.create_entity(ifc_model, ifc_class="IfcBuildingElementProxy", name="Solar Panel_Test:A")
    b = ifcopenshell.api.root.create_entity(ifc_model, ifc_class="IfcBuildingElementProxy", name="Solar Panel_Test:B")
    a.GlobalId = "3A8hY1UoD7JhnLeZeDyUIv"
    b.GlobalId = "3A8hY1UoD7JhnLeZeDyUIV"

    out_paths = build_and_write_aasx(
        ifc_model,
        tmp_path,
        namespace="example.org/asset-forge",
        opcua_host="localhost",
        opcua_port=4840,
        elements=[a, b],
    )

    store = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    with aasx.AASXReader(str(out_paths[0])) as reader:
        reader.read_into(object_store=store, file_store=file_store)

    technicaldata_sms = [
        o for o in store if isinstance(o, model.Submodel) and o.id_short == "technicaldata"
    ]
    file_names = [sm.get_referable("Model3DIFC").value for sm in technicaldata_sms]

    assert len(file_names) == 2
    assert len({name.lower() for name in file_names}) == 2, "case-folded names must not collide"
