import ifcopenshell
import ifcopenshell.api.root
import pytest

pytest.importorskip("basyx")

from basyx.aas import model  # noqa: E402

from asset_forge.export.aas.shell import build_shell, build_virtual_shell  # noqa: E402


def test_virtual_shell_uses_the_virtual_path_segment_not_ifc():
    submodel = model.Submodel(id_="placeholder", id_short="nameplate")

    shell, submodels = build_virtual_shell("inverter", "Inverter", "example.org/asset-forge", [submodel])

    assert shell.id == "https://example.org/asset-forge/aas/virtual/inverter"
    assert shell.asset_information.global_asset_id == "https://example.org/asset-forge/asset/virtual/inverter"
    assert submodels[0].id == "https://example.org/asset-forge/aas/virtual/inverter/sm/nameplate"


def test_virtual_and_ifc_backed_shells_are_distinguishable_by_path_segment():
    ifc_model = ifcopenshell.file(schema="IFC4")
    wall = ifcopenshell.api.root.create_entity(ifc_model, ifc_class="IfcWall", name="Wall-01")
    ifc_submodel = model.Submodel(id_="placeholder", id_short="nameplate")
    virtual_submodel = model.Submodel(id_="placeholder", id_short="nameplate")

    ifc_shell, _ = build_shell(wall, "example.org/asset-forge", [ifc_submodel])
    virtual_shell, _ = build_virtual_shell("inverter", "Inverter", "example.org/asset-forge", [virtual_submodel])

    assert "/aas/ifc/" in ifc_shell.id
    assert "/aas/virtual/" in virtual_shell.id
