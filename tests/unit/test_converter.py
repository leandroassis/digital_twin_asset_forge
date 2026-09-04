from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "visualization"))

from pipeline.converter import convert_ifc_to_glb
from config import IFCCONVERT_BIN

def test_convert_ifc_to_glb_file_not_found(tmp_path):
    non_existent = tmp_path / "missing.ifc"
    output_glb = tmp_path / "out.glb"
    assert convert_ifc_to_glb(non_existent, output_glb) is False

def test_convert_ifc_to_glb_idempotent(tmp_path):
    input_ifc = tmp_path / "test.ifc"
    input_ifc.write_text("ISO-10303-21;")
    output_glb = tmp_path / "test.glb"
    output_glb.write_text("dummy glb content")

    with patch("subprocess.run") as mock_run:
        res = convert_ifc_to_glb(input_ifc, output_glb, force=False)
        assert res is True
        mock_run.assert_not_called()

def test_convert_ifc_to_glb_executes_ifcconvert(tmp_path):
    input_ifc = tmp_path / "test.ifc"
    input_ifc.write_text("ISO-10303-21;")
    output_glb = tmp_path / "test.glb"

    with patch("pipeline.converter.IFCCONVERT_BIN", tmp_path / "IfcConvert"), \
         patch("subprocess.run") as mock_run:
        (tmp_path / "IfcConvert").touch()
        mock_run.return_value = MagicMock(returncode=0)

        res = convert_ifc_to_glb(input_ifc, output_glb)
        assert res is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert str(input_ifc) in args
        assert str(output_glb) in args
        assert "--use-world-coords" in args
