import ifcopenshell
import ifcopenshell.api.root

from asset_forge.export.aas.geometry import extract_element_ifc


def test_extract_produces_a_reopenable_ifc_with_just_that_entity():
    model = ifcopenshell.file(schema="IFC4")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall-01")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcDoor", name="Door-01")  # a sibling, must not leak in

    extracted_bytes = extract_element_ifc(wall)

    reopened = ifcopenshell.file.from_string(extracted_bytes.decode("utf-8"))
    assert reopened.schema == "IFC4"

    walls = reopened.by_type("IfcWall")
    assert len(walls) == 1
    assert walls[0].GlobalId == wall.GlobalId
    assert reopened.by_type("IfcDoor") == []


def test_extract_includes_the_shared_project_when_present():
    model = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Project-01")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall-01")

    extracted_bytes = extract_element_ifc(wall)
    reopened = ifcopenshell.file.from_string(extracted_bytes.decode("utf-8"))

    projects = reopened.by_type("IfcProject")
    assert len(projects) == 1
    assert projects[0].GlobalId == project.GlobalId
