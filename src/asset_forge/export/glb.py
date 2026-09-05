"""Converts a plant IFC model into one combined glTF binary (.glb) -- the
whole-plant 3D deliverable the visualizer loads, complementing (not
replacing) the per-panel Model3DIFC geometry files carried in the AAS
package (see export/aas/package.py). One file for the entire plant, with one
node per element so the visualizer can look up/highlight an element by its
IFC GlobalId.
"""

import math
import multiprocessing
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ifcopenshell
import ifcopenshell.geom
import numpy as np
from loguru import logger
from pygltflib import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_INT,
    Accessor,
    Asset,
    Buffer,
    BufferView,
    GLTF2,
    Material,
    Mesh,
    Node,
    PbrMetallicRoughness,
    Primitive,
    Scene,
)

from asset_forge.ingestion.loader import PathLike

# IFC is Z-up, glTF/three.js is Y-up. Rather than transform every vertex,
# wrap all element nodes under one root node carrying this fixed rotation
# (-90 degrees about X, as a quaternion) -- the standard Z-up -> Y-up fix.
_Z_UP_TO_Y_UP_ROTATION = [-0.7071067811865476, 0.0, 0.0, 0.7071067811865476]

_DEFAULT_MATERIAL_RGBA = (0.6, 0.6, 0.6, 1.0)


def build_and_write_glb(
    plant_model: ifcopenshell.file,
    output_path: PathLike,
    elements: Optional[List[Any]] = None,
) -> Path:
    """Triangulate every element in `elements` (default: every `IfcElement`
    in `plant_model`) and write them all into a single `.glb` at
    `output_path`, one glTF Node per element (`node.name` = GlobalId),
    carrying each element's real IFC surface style colors."""
    elements = list(elements if elements is not None else plant_model.by_type("IfcElement"))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("weld-vertices", True)

    gltf = GLTF2(asset=Asset(generator="asset-forge"))
    gltf.scenes.append(Scene(nodes=[]))
    gltf.scene = 0

    binary_blob = bytearray()
    material_cache: Dict[Tuple[float, float, float, float], int] = {}
    element_node_indices: List[int] = []

    if elements:
        iterator = ifcopenshell.geom.iterator(settings, plant_model, multiprocessing.cpu_count(), include=elements)
        if iterator.initialize():
            while True:
                shape = iterator.get()
                element_node_indices.append(_add_shape_node(gltf, binary_blob, shape, material_cache))
                if not iterator.next():
                    break

    if element_node_indices:
        root_index = len(gltf.nodes)
        gltf.nodes.append(Node(name="plant", rotation=_Z_UP_TO_Y_UP_ROTATION, children=element_node_indices))
        gltf.scenes[0].nodes.append(root_index)

    gltf.buffers.append(Buffer(byteLength=len(binary_blob)))
    gltf.set_binary_blob(bytes(binary_blob))
    gltf.save_binary(str(output_path))

    logger.info(f"wrote {output_path} ({len(element_node_indices)} element node(s))")
    return output_path


def _get_or_create_material(gltf: GLTF2, cache: Dict[Tuple[float, float, float, float], int], rgba) -> int:
    key = tuple(round(c, 4) for c in rgba)
    if key in cache:
        return cache[key]
    index = len(gltf.materials)
    gltf.materials.append(
        Material(
            pbrMetallicRoughness=PbrMetallicRoughness(
                baseColorFactor=list(key), metallicFactor=0.05, roughnessFactor=0.7
            ),
            alphaMode="BLEND" if key[3] < 1.0 else "OPAQUE",
            doubleSided=True,
        )
    )
    cache[key] = index
    return index


def _add_shape_node(
    gltf: GLTF2,
    binary_blob: bytearray,
    shape: Any,
    material_cache: Dict[Tuple[float, float, float, float], int],
) -> int:
    geometry = shape.geometry
    verts = np.array(geometry.verts, dtype=np.float32).reshape(-1, 3)
    faces = np.array(geometry.faces, dtype=np.uint32).reshape(-1, 3)
    material_ids = np.array(geometry.material_ids, dtype=np.int64) if len(geometry.material_ids) else None

    verts_offset = len(binary_blob)
    verts_bytes = verts.tobytes()
    binary_blob.extend(verts_bytes)
    # glTF requires 4-byte alignment for each bufferView.
    while len(binary_blob) % 4:
        binary_blob.append(0)

    buffer_index = 0
    verts_view_index = len(gltf.bufferViews)
    gltf.bufferViews.append(
        BufferView(buffer=buffer_index, byteOffset=verts_offset, byteLength=len(verts_bytes), target=ARRAY_BUFFER)
    )
    verts_accessor_index = len(gltf.accessors)
    gltf.accessors.append(
        Accessor(
            bufferView=verts_view_index,
            componentType=FLOAT,
            count=len(verts),
            type="VEC3",
            min=verts.min(axis=0).tolist(),
            max=verts.max(axis=0).tolist(),
        )
    )

    primitives = []
    for local_material_id, face_group in _group_faces_by_material(faces, material_ids, geometry):
        material_index = _get_or_create_material(gltf, material_cache, _resolve_rgba(geometry, local_material_id))
        faces_offset = len(binary_blob)
        faces_bytes = face_group.tobytes()
        binary_blob.extend(faces_bytes)
        while len(binary_blob) % 4:
            binary_blob.append(0)

        faces_view_index = len(gltf.bufferViews)
        gltf.bufferViews.append(
            BufferView(
                buffer=buffer_index, byteOffset=faces_offset, byteLength=len(faces_bytes), target=ELEMENT_ARRAY_BUFFER
            )
        )
        faces_accessor_index = len(gltf.accessors)
        gltf.accessors.append(
            Accessor(bufferView=faces_view_index, componentType=UNSIGNED_INT, count=face_group.size, type="SCALAR")
        )
        primitives.append(
            Primitive(
                attributes={"POSITION": verts_accessor_index}, indices=faces_accessor_index, material=material_index
            )
        )

    mesh_index = len(gltf.meshes)
    gltf.meshes.append(Mesh(primitives=primitives))

    node_index = len(gltf.nodes)
    gltf.nodes.append(
        Node(
            name=shape.guid,
            mesh=mesh_index,
            extras={"globalId": shape.guid, "ifcClass": shape.type, "name": shape.name or ""},
        )
    )
    return node_index


def _group_faces_by_material(faces: np.ndarray, material_ids: Optional[np.ndarray], geometry: Any):
    """Yields (local_material_id, faces_subset) pairs, grouping this shape's
    triangles by their IFC surface style (an index into `geometry.materials`,
    or None if the shape has no style info) so each style ends up in its own
    glTF primitive/material."""
    styles = list(getattr(geometry, "materials", []) or [])

    if material_ids is None or not styles:
        yield None, faces
        return

    for local_id in sorted(set(material_ids.tolist())):
        subset = faces[material_ids == local_id]
        if subset.size == 0:
            continue
        yield local_id, subset


def _resolve_rgba(geometry: Any, local_material_id: Optional[int]) -> Tuple[float, float, float, float]:
    """Reads a shape's IFC surface style (diffuse color + transparency) for
    `local_material_id`, or falls back to a flat gray when the shape carries
    no style at all -- every primitive gets *some* color either way, so
    nothing renders as an untinted default-white glTF mesh."""
    if local_material_id is None:
        return _DEFAULT_MATERIAL_RGBA
    style = geometry.materials[local_material_id]
    transparency = style.transparency
    # Real solar-plant data measured ~26% of elements (HVAC ductwork/fittings
    # with a "DefaultMaterial" style) reporting transparency=NaN; a bare
    # unstyled shape (no IfcStyledItem at all) gets ifcopenshell's own
    # synthetic placeholder at transparency=1.0. Neither reflects an
    # author's real intent to hide the surface -- both would otherwise
    # render fully invisible, so both fall back to opaque.
    if not math.isfinite(transparency) or transparency >= 1.0:
        transparency = 0.0
    return (style.diffuse.r(), style.diffuse.g(), style.diffuse.b(), max(0.0, 1.0 - transparency))
