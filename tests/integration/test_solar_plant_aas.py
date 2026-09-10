import zipfile
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
def test_solar_plant_every_shell_is_fully_decorated_across_all_produced_aasx(tmp_path):
    # Every shell now carries Nameplate + full TechnicalData + Model3DIFC
    # (not just solar panels), which no longer fits in a single package --
    # multiple .aasx files is the expected, supported outcome (see
    # package.py's module docstring). `just basyx-upload`/`asset-forge basyx
    # upload` already iterate over every file a project produces, so this
    # test does the same: aggregate across every file produced, like a real
    # upload would end up with in one running BaSyx instance.
    plant = build_plant([SOLAR_PLANT_FILE])

    out_paths = build_and_write_aasx(
        plant,
        tmp_path,
        namespace="example.org/asset-forge",
        opcua_host="localhost",
        opcua_port=4840,
    )

    assert len(out_paths) > 1
    for path in out_paths:
        assert path.stat().st_size < 100_000_000
        with zipfile.ZipFile(path) as zf:
            assert len(zf.namelist()) < 1000

    store = model.DictIdentifiableStore()
    file_store = aasx.DictSupplementaryFileContainer()
    for path in out_paths:
        with aasx.AASXReader(str(path)) as reader:
            reader.read_into(object_store=store, file_store=file_store)

    shells = [o for o in store if isinstance(o, model.AssetAdministrationShell)]
    submodels = [o for o in store if isinstance(o, model.Submodel)]

    element_count = len(plant.by_type("IfcElement"))
    assert len(shells) == element_count + 1  # + the virtual inverter

    inverter_shells = [s for s in shells if "/aas/virtual/inverter" in s.id]
    assert len(inverter_shells) == 1

    nameplate_submodels = [sm for sm in submodels if sm.id_short == "nameplate"]
    # every real element + the virtual inverter
    assert len(nameplate_submodels) == element_count + 1

    model3difc_submodels = [
        sm
        for sm in submodels
        if sm.id_short == "technicaldata" and any(e.id_short == "Model3DIFC" for e in sm.submodel_element)
    ]
    # every real element -- the virtual inverter has no technicaldata submodel at all (not IFC-backed)
    assert len(model3difc_submodels) == element_count

    opcua_submodels_with_sensor_properties = [
        sm
        for sm in submodels
        if sm.id_short == "opcua" and any(isinstance(e, model.Property) for e in sm.submodel_element)
    ]
    # 607 real panels + 1 virtual inverter, each carrying their own sensor Properties
    assert len(opcua_submodels_with_sensor_properties) == 608

    timeseries_submodels = [sm for sm in submodels if sm.id_short == "timeseries"]
    assert len(timeseries_submodels) == 608
