from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")
pytest.importorskip("basyx")

from basyx.aas import model  # noqa: E402
from basyx.aas.adapter import aasx  # noqa: E402

from asset_forge.export.aas.package import build_and_write_aasx  # noqa: E402
from asset_forge.export.ifc_writer import build_plant  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLAR_PLANT_FILE = REPO_ROOT / "assets" / "solar-plant" / "20220221KT-ZCB (combined).ifc"


@pytest.mark.skipif(not SOLAR_PLANT_FILE.is_file(), reason="sample asset not present")
def test_solar_plant_produces_exactly_one_aasx_with_panels_and_a_virtual_inverter(tmp_path):
    plant = build_plant([SOLAR_PLANT_FILE])

    out_paths = build_and_write_aasx(
        plant,
        tmp_path,
        namespace="example.org/asset-forge",
        opcua_host="localhost",
        opcua_port=4840,
    )

    assert [p.name for p in out_paths] == ["model.aasx"]
    assert out_paths[0].stat().st_size < 100_000_000

    store = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    with aasx.AASXReader(str(out_paths[0])) as reader:
        reader.read_into(object_store=store, file_store=file_store)

    shells = [o for o in store if isinstance(o, model.AssetAdministrationShell)]
    submodels = [o for o in store if isinstance(o, model.Submodel)]

    element_count = len(plant.by_type("IfcElement"))
    assert len(shells) == element_count + 1  # + the virtual inverter

    inverter_shells = [s for s in shells if "/aas/virtual/inverter" in s.id]
    assert len(inverter_shells) == 1

    opcua_submodels_with_sensor_properties = [
        sm
        for sm in submodels
        if sm.id_short == "opcua" and any(isinstance(e, model.Property) for e in sm.submodel_element)
    ]
    # 607 real panels + 1 virtual inverter, each carrying their own sensor Properties
    assert len(opcua_submodels_with_sensor_properties) == 608

    model3difc_submodels = [
        sm
        for sm in submodels
        if sm.id_short == "technicaldata" and any(e.id_short == "Model3DIFC" for e in sm.submodel_element)
    ]
    # 607 real panels only -- the virtual inverter has no technicaldata submodel at all (not IFC-backed)
    assert len(model3difc_submodels) == 607
