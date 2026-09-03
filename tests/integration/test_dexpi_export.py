from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")
pytest.importorskip("pydexpi")

from asset_forge.export.dexpi_builder import build_dexpi_model  # noqa: E402
from asset_forge.export.dexpi_export import export_dexpi  # noqa: E402
from asset_forge.export.ifc_writer import build_plant  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HZG_FILE = REPO_ROOT / "assets" / "digihub_building" / "DigitalHub_FM-HZG_v2.ifc"
HVAC_FILE = REPO_ROOT / "assets" / "HVAC" / "301110PART03_Buderus_200406_20070209_ifc.ifc"


@pytest.mark.skipif(not HZG_FILE.is_file(), reason="sample asset not present")
def test_dexpi_export_against_a_real_mep_discipline_file(tmp_path):
    model = build_plant([HZG_FILE])

    dexpi_model = build_dexpi_model(model, project_name="digihub_building_hzg")
    summary = export_dexpi(dexpi_model, tmp_path)

    assert summary.json_path.is_file() and summary.json_path.stat().st_size > 0
    assert summary.graphml_path.is_file() and summary.graphml_path.stat().st_size > 0
    assert summary.proteus_xml_path.is_file() and summary.proteus_xml_path.stat().st_size > 0
    assert summary.piping_item_count > 0
    assert summary.connection_count > 0


@pytest.mark.skipif(not HVAC_FILE.is_file(), reason="sample asset not present")
def test_dexpi_export_is_gated_off_for_a_project_with_no_native_connections():
    from asset_forge.exceptions import DexpiUnavailableError

    model = build_plant([HVAC_FILE])

    with pytest.raises(DexpiUnavailableError):
        build_dexpi_model(model, project_name="HVAC")
