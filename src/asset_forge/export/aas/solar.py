"""Solar-plant-specific role data: which OPC UA variables a panel/inverter
carries, and how to recognize a panel element in the source IFC.

Not a generic per-project config mechanism -- this pipeline now targets one
specific plant, so the pattern/variables live here as plain, easy-to-edit
constants rather than an external config file.
"""

from dataclasses import dataclass
from typing import Any

_PANEL_NAME_PATTERNS = ("solar panel",)


@dataclass(frozen=True)
class OpcuaVariable:
    id_short: str
    tag_suffix: str
    value_type: type = float


# Per-panel sensor readings (see the project's architecture diagram: "Por
# painel").
PANEL_VARIABLES = (
    OpcuaVariable("LightIntensity", "LUX"),
    OpcuaVariable("Temperature", "TEMP"),
    OpcuaVariable("CurrentDC", "IDC"),
    OpcuaVariable("VoltageDC", "VDC"),
)

# Plant-level inverter output ("Saída do inversor") -- no IfcElement exists
# for this in the source model, so it's carried by a virtual/synthetic shell
# (see export/aas/shell.py::build_virtual_shell).
INVERTER_VARIABLES = (
    OpcuaVariable("VoltageAC", "VAC"),
    OpcuaVariable("CurrentAC", "IAC"),
    OpcuaVariable("PowerAC", "PAC"),
)


def is_solar_panel(entity: Any) -> bool:
    """Case-insensitive substring match on Name/ObjectType. Matches this
    project's 'Solar Panel_ZCB:...' family without hardcoding to that exact
    string, so a differently-named panel family would still match."""
    haystacks = (str(entity.Name or ""), str(getattr(entity, "ObjectType", "") or ""))
    return any(pattern in haystack.lower() for haystack in haystacks for pattern in _PANEL_NAME_PATTERNS)
