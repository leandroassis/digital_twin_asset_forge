import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock

import requests


DATA_GEN_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "data_gen"
)

sys.path.append(str(DATA_GEN_DIR))

from fault_client import (
    fetch_active_faults,
    global_id_from_submodel_id_b64,
)


def encode_submodel_id(value):
    return base64.urlsafe_b64encode(
        value.encode("utf-8")
    ).decode("utf-8").rstrip("=")


def test_extracts_global_id_from_submodel_id():
    global_id = "2QF3$F$XHF1A$PuubJ8dJ8"
    submodel_id = (
        "https://example.org/asset-forge/aas/ifc/"
        f"{global_id}/sm/opcua"
    )

    encoded = encode_submodel_id(submodel_id)

    assert global_id_from_submodel_id_b64(encoded) == global_id


def test_invalid_submodel_id_returns_none():
    assert global_id_from_submodel_id_b64("invalid") is None


def test_fetch_active_faults():
    session = MagicMock()
    response = session.get.return_value

    response.json.return_value = {
        "faults": [
            {
                "element_id": "PANEL_GLOBAL_ID",
                "fault_type": "Sobreaquecimento",
            }
        ]
    }

    result = fetch_active_faults(
        "http://localhost:8000",
        session=session,
    )

    assert result == {
        "PANEL_GLOBAL_ID": "Sobreaquecimento"
    }

    response.raise_for_status.assert_called_once()


def test_unavailable_visualizer_returns_empty_dict():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError(
        "visualizador indisponível"
    )

    result = fetch_active_faults(
        "http://localhost:8000",
        session=session,
    )

    assert result == {}