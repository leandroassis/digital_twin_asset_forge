from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")

from asset_forge.ingestion.federation import federate  # noqa: E402
from asset_forge.linking.native import find_connections, has_native_connections  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DIGIHUB_DIR = REPO_ROOT / "assets" / "digihub_building"
HVAC_FILE = REPO_ROOT / "assets" / "HVAC" / "301110PART03_Buderus_200406_20070209_ifc.ifc"


@pytest.mark.skipif(not HVAC_FILE.is_file(), reason="sample asset not present")
def test_isolated_catalog_object_has_no_real_connections():
    # HVAC has IfcRelConnectsPortToElement (ports belonging to the single
    # cataloged device) but no IfcRelConnectsPorts/IfcRelConnectsElements --
    # port-to-element "ownership" must not be mistaken for a connection.
    model = federate([HVAC_FILE])

    assert find_connections(model) == []
    assert has_native_connections(model) is False


@pytest.mark.skipif(not DIGIHUB_DIR.is_dir(), reason="sample assets not present")
def test_federated_building_keeps_all_native_port_connections():
    paths = sorted(DIGIHUB_DIR.glob("DigitalHub_FM-*_v2.ifc"))
    model = federate(paths)

    connections = find_connections(model)

    assert has_native_connections(model) is True
    assert len(connections) == len(model.by_type("IfcRelConnectsPorts"))
    assert all(c.kind == "port" for c in connections)
    assert all(c.element_a_guid != c.element_b_guid for c in connections)
