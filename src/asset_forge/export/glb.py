"""Converts a plant IFC model into one combined glTF binary (.glb) -- the
whole-plant 3D deliverable the visualizer loads, complementing (not
replacing) the per-panel Model3DIFC geometry files carried in the AAS
package (see export/aas/package.py). One file for the entire plant, with one
node per element so the visualizer can look up/highlight an element by its
IFC GlobalId.
"""

import multiprocessing
from pathlib import Path
from typing import Any, List, Optional

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
    Mesh,
    Node,
    Primitive,
    Scene,
)

from asset_forge.ingestion.loader import PathLike


def build_and_write_glb(
    plant_model: ifcopenshell.file,
    output_path: PathLike,
    elements: Optional[List[Any]] = None,
) -> Path:
    """Triangulate every element in `elements` (default: every `IfcElement`
    in `plant_model`) and write them all into a single `.glb` at
    `output_path`, one glTF Node per element (`node.name` = GlobalId)."""
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

    if elements:
        iterator = ifcopenshell.geom.iterator(settings, plant_model, multiprocessing.cpu_count(), include=elements)
        if iterator.initialize():
            while True:
                shape = iterator.get()
                _add_shape_node(gltf, binary_blob, shape)
                if not iterator.next():
                    break

    gltf.buffers.append(Buffer(byteLength=len(binary_blob)))
    gltf.set_binary_blob(bytes(binary_blob))
    gltf.save_binary(str(output_path))

    logger.info(f"wrote {output_path} ({len(gltf.nodes)} node(s))")
    return output_path


def _add_shape_node(gltf: GLTF2, binary_blob: bytearray, shape: Any) -> None:
    geometry = shape.geometry
    verts = np.array(geometry.verts, dtype=np.float32).reshape(-1, 3)
    faces = np.array(geometry.faces, dtype=np.uint32)

    verts_offset = len(binary_blob)
    verts_bytes = verts.tobytes()
    binary_blob.extend(verts_bytes)
    # glTF requires 4-byte alignment for each bufferView.
    while len(binary_blob) % 4:
        binary_blob.append(0)

    faces_offset = len(binary_blob)
    faces_bytes = faces.tobytes()
    binary_blob.extend(faces_bytes)
    while len(binary_blob) % 4:
        binary_blob.append(0)

    buffer_index = 0
    verts_view_index = len(gltf.bufferViews)
    gltf.bufferViews.append(
        BufferView(buffer=buffer_index, byteOffset=verts_offset, byteLength=len(verts_bytes), target=ARRAY_BUFFER)
    )
    faces_view_index = len(gltf.bufferViews)
    gltf.bufferViews.append(
        BufferView(
            buffer=buffer_index, byteOffset=faces_offset, byteLength=len(faces_bytes), target=ELEMENT_ARRAY_BUFFER
        )
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
    faces_accessor_index = len(gltf.accessors)
    gltf.accessors.append(
        Accessor(bufferView=faces_view_index, componentType=UNSIGNED_INT, count=len(faces), type="SCALAR")
    )

    mesh_index = len(gltf.meshes)
    gltf.meshes.append(
        Mesh(primitives=[Primitive(attributes={"POSITION": verts_accessor_index}, indices=faces_accessor_index)])
    )

    node_index = len(gltf.nodes)
    gltf.nodes.append(
        Node(
            name=shape.guid,
            mesh=mesh_index,
            extras={"globalId": shape.guid, "ifcClass": shape.type, "name": shape.name or ""},
        )
    )
    gltf.scenes[0].nodes.append(node_index)
