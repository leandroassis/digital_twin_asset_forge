"""Assembles an AAS Shell (AssetAdministrationShell + its Submodels) for one
plant IFC element."""

from typing import Any, List, Tuple

from basyx.aas import model

from asset_forge.export.aas.idshort import valid_id_short


def build_shell(
    entity: Any,
    namespace: str,
    submodels: List[model.Submodel],
) -> Tuple[model.AssetAdministrationShell, List[model.Submodel]]:
    """Build one AAS Shell for `entity`, referencing every submodel in
    `submodels`. Assigns each submodel's id as a side effect. Returns
    (shell, submodels), ready to hand to export/aas/package.py.

    A bare AssetAdministrationShell with no idShort is legal in basyx's
    Python model but a real AAS spec violation some viewers/servers reject
    -- id_short is always built as a valid one, from the element's Name,
    falling back to its GlobalId (which starts with a digit as often as
    not, e.g. IFC's base64-like GlobalIds)."""
    global_id = entity.GlobalId
    id_short = valid_id_short(str(entity.Name) if entity.Name else global_id)

    for submodel in submodels:
        submodel.id = f"https://{namespace}/aas/ifc/{global_id}/sm/{submodel.id_short}"

    asset_information = model.AssetInformation(
        asset_kind=model.AssetKind.INSTANCE,
        global_asset_id=f"https://{namespace}/asset/ifc/{global_id}",
    )
    shell = model.AssetAdministrationShell(
        asset_information=asset_information,
        id_=f"https://{namespace}/aas/ifc/{global_id}",
        id_short=id_short,
    )
    for submodel in submodels:
        shell.submodel.add(model.ModelReference.from_referable(submodel))

    return shell, submodels
