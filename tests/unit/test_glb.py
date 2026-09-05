import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import pytest

pygltflib = pytest.importorskip("pygltflib")

from asset_forge.export.glb import build_and_write_glb  # noqa: E402


@pytest.fixture
def wall_with_geometry():
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Project-01")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall-01")

    model_context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body_context = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model_context
    )
    representation = ifcopenshell.api.geometry.add_wall_representation(
        model, context=body_context, length=1.0, height=3.0, thickness=0.2
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=representation)

    return model, wall


def test_glb_round_trips_with_one_node_per_element(wall_with_geometry, tmp_path):
    model, wall = wall_with_geometry

    out_path = build_and_write_glb(model, tmp_path / "plant.glb", elements=[wall])

    assert out_path.is_file()

    gltf = pygltflib.GLTF2().load(str(out_path))
    assert len(gltf.nodes) == 1
    assert gltf.nodes[0].name == wall.GlobalId
    assert gltf.nodes[0].extras["ifcClass"] == "IfcWall"
    assert len(gltf.meshes) == 1
    assert len(gltf.accessors) == 2  # positions + indices


def test_glb_with_no_elements_still_writes_a_valid_empty_file(tmp_path):
    model = ifcopenshell.file(schema="IFC4")

    out_path = build_and_write_glb(model, tmp_path / "plant.glb", elements=[])

    gltf = pygltflib.GLTF2().load(str(out_path))
    assert gltf.nodes == []
