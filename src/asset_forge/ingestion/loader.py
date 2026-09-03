"""Defensive opening of a single source .ifc file.

Some vendor IFC exporters embed raw Windows paths or `DOMAIN\\user` strings
inside STEP string literals. Per ISO-10303-21 a bare backslash starts a
control sequence, so an unescaped single backslash desyncs the STEP
tokenizer and truncates every attribute after it on that entity's line —
silently turning otherwise-good properties into blank/malformed values.

An earlier version of this function doubled *every* backslash to work
around that. That is wrong: ISO-10303-21 Annex E encoded-character escapes
(`\\S\\<char>` to shift a character +128, `\\X\\HH`, `\\X2\\...\\X0\\`,
`\\X4\\...\\X0\\`, `\\P<A-Z>\\` to switch character sets) are themselves
built out of backslashes, and real exports use them for non-ASCII text —
confirmed on the HVAC/VDI3805 sample in this project's own `assets/`, where
`\\S\\Vl-Brennwertkessel` is the correctly-escaped German
"Öl-Brennwertkessel" (oil condensing boiler). Blindly doubling every
backslash corrupts exactly these sequences instead of fixing anything.
`_escape_bare_backslashes` only doubles a backslash that is *not* part of
one of these recognized escapes.
"""

import re
import tempfile
from pathlib import Path
from typing import Union

import ifcopenshell

from asset_forge.exceptions import ModelLoadError

PathLike = Union[str, Path]

_STEP_ENCODED_CHARACTER_ESCAPE = re.compile(
    r"\\X2\\(?:[0-9A-Fa-f]{4})*\\X0\\"  # \X2\....\X0\ (UCS-2 run)
    r"|\\X4\\(?:[0-9A-Fa-f]{8})*\\X0\\"  # \X4\....\X0\ (UCS-4 run)
    r"|\\X\\[0-9A-Fa-f]{2}"  # \X\HH (single 8-bit char)
    r"|\\S\\."  # \S\C (shift next char +128)
    r"|\\P[A-Z]\\"  # \PA\.. (select character set)
    r"|\\P\\"  # \P\ (reset character set)
)


def _escape_bare_backslashes(text: str) -> str:
    out = []
    pos = 0
    for match in _STEP_ENCODED_CHARACTER_ESCAPE.finditer(text):
        out.append(text[pos : match.start()].replace("\\", "\\\\"))
        out.append(match.group(0))
        pos = match.end()
    out.append(text[pos:].replace("\\", "\\\\"))
    return "".join(out)


def _sanitized_copy(ifc_path: Path) -> Path:
    text = ifc_path.read_text(encoding="utf-8", errors="replace")
    text = _escape_bare_backslashes(text)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ifc", encoding="utf-8", delete=False)
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


def load_ifc(ifc_path: PathLike) -> ifcopenshell.file:
    """Open `ifc_path` as an ifcopenshell model, via a sanitized temp copy."""
    path = Path(ifc_path)
    if not path.is_file():
        raise ModelLoadError(f"IFC file not found: {path}")

    sanitized = _sanitized_copy(path)
    try:
        return ifcopenshell.open(str(sanitized))
    except Exception as exc:
        raise ModelLoadError(f"failed to parse {path}: {exc}") from exc
    finally:
        sanitized.unlink(missing_ok=True)
