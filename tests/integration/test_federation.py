from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from asset_forge.ingestion.federation import federate  # noqa: E402
from asset_forge.ingestion.loader import load_ifc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DIGIHUB_DIR = REPO_ROOT / "assets" / "digihub_building"
HVAC_FILE = REPO_ROOT / "assets" / "HVAC" / "301110PART03_Buderus_200406_20070209_ifc.ifc"

pytestmark = pytest.mark.skipif(not DIGIHUB_DIR.is_dir(), reason="sample assets not present")


def _discipline_paths():
    return sorted(DIGIHUB_DIR.glob("DigitalHub_FM-*_v2.ifc"))


def test_single_file_project_is_a_passthrough():
    model = federate([HVAC_FILE])
    assert model.schema == "IFC2X3"
    assert len(model.by_type("IfcProduct")) > 0


def test_federating_digihub_disciplines_preserves_all_native_connections_and_dedupes_identity_entities():
    paths = _discipline_paths()
    assert len(paths) == 4, "expected 4 discipline files in assets/digihub_building"

    expected_connections = sum(
        len(load_ifc(p).by_type("IfcRelConnectsPorts")) for p in paths
    )

    merged = federate(paths)

    assert len(merged.by_type("IfcRelConnectsPorts")) == expected_connections

    roots = merged.by_type("IfcRoot")
    guids = [r.GlobalId for r in roots]
    assert len(guids) == len(set(guids)), "federation must not duplicate GlobalIds"

    assert len(merged.by_type("IfcProject")) == 1
    assert len(merged.by_type("IfcSite")) == 1
    assert len(merged.by_type("IfcBuilding")) == 1


def test_federating_digihub_disciplines_groups_every_element_by_discipline():
    paths = _discipline_paths()
    merged = federate(paths)

    groups = {g.Name: g for g in merged.by_type("IfcGroup")}
    expected_labels = {p.stem for p in paths}
    assert set(groups) == expected_labels

    grouped_ids = set()
    for group in groups.values():
        rels = group.IsGroupedBy
        assert len(rels) == 1, "expected all of a group's members in a single IfcRelAssignsToGroup"
        for obj in rels[0].RelatedObjects:
            assert obj.id() not in grouped_ids, "element assigned to more than one discipline group"
            grouped_ids.add(obj.id())

    all_element_ids = {e.id() for e in merged.by_type("IfcElement")}
    assert grouped_ids == all_element_ids, "every element must belong to exactly one discipline group"


def test_federated_model_round_trips_through_disk(tmp_path):
    merged = federate(_discipline_paths())
    out_path = tmp_path / "plant.ifc"
    merged.write(str(out_path))

    reopened = ifcopenshell.open(str(out_path))
    assert len(reopened.by_type("IfcRelConnectsPorts")) == len(merged.by_type("IfcRelConnectsPorts"))
