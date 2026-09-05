import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import pytest

pygltflib = pytest.importorskip("pygltflib")

from asset_forge.export.glb import _resolve_rgba, build_and_write_glb  # noqa: E402


class _FakeColour:
    def __init__(self, r, g, b):
        self._r, self._g, self._b = r, g, b

    def r(self):
        return self._r

    def g(self):
        return self._g

    def b(self):
        return self._b


class _FakeStyle:
    def __init__(self, rgb, transparency):
        self.diffuse = _FakeColour(*rgb)
        self.transparency = transparency


class _FakeGeometry:
    def __init__(self, materials):
        self.materials = materials


def test_resolve_rgba_treats_nan_transparency_as_opaque():
    # Measured against the real solar-plant IFC: ~26% of elements (HVAC
    # ductwork/fittings carrying a "DefaultMaterial" style) report
    # transparency=NaN. `max(0.0, 1.0 - nan)` silently evaluates to 0.0 in
    # Python (NaN comparisons are always False), which would have rendered
    # over a quarter of the plant invisible.
    geometry = _FakeGeometry(materials=[_FakeStyle((0.7, 0.7, 0.7), float("nan"))])

    rgba = _resolve_rgba(geometry, 0)

    assert rgba == (0.7, 0.7, 0.7, 1.0)


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


def test_glb_round_trips_with_one_node_per_element_under_a_rotated_root(wall_with_geometry, tmp_path):
    model, wall = wall_with_geometry

    out_path = build_and_write_glb(model, tmp_path / "plant.glb", elements=[wall])

    assert out_path.is_file()

    gltf = pygltflib.GLTF2().load(str(out_path))
    # one node for the element, one wrapping "plant" root that carries the
    # IFC (Z-up) -> glTF (Y-up) rotation fix
    assert len(gltf.nodes) == 2
    element_node = gltf.nodes[0]
    root_node = gltf.nodes[1]

    assert element_node.name == wall.GlobalId
    assert element_node.extras["ifcClass"] == "IfcWall"
    assert root_node.children == [0]
    assert root_node.rotation == pytest.approx([-0.7071067811865476, 0.0, 0.0, 0.7071067811865476])
    assert gltf.scenes[gltf.scene].nodes == [1]

    assert len(gltf.meshes) == 1
    assert len(gltf.accessors) == 2  # positions + indices


def test_glb_forces_ifcopenshells_invisible_placeholder_style_opaque(wall_with_geometry, tmp_path):
    # A bare element with no IfcStyledItem gets ifcopenshell's own synthetic
    # placeholder material at transparency=1.0 (confirmed against this exact
    # fixture) -- rendering it verbatim would make the element invisible, so
    # it must come out fully opaque instead.
    model, wall = wall_with_geometry

    out_path = build_and_write_glb(model, tmp_path / "plant.glb", elements=[wall])

    gltf = pygltflib.GLTF2().load(str(out_path))
    assert len(gltf.materials) == 1
    assert gltf.meshes[0].primitives[0].material == 0
    assert gltf.materials[0].pbrMetallicRoughness.baseColorFactor[3] == pytest.approx(1.0)
    assert gltf.materials[0].alphaMode == "OPAQUE"


def test_glb_with_no_elements_still_writes_a_valid_empty_file(tmp_path):
    model = ifcopenshell.file(schema="IFC4")

    out_path = build_and_write_glb(model, tmp_path / "plant.glb", elements=[])

    gltf = pygltflib.GLTF2().load(str(out_path))
    assert gltf.nodes == []
