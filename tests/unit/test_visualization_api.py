from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "visualization"))

from main import app

client = TestClient(app)

def test_root_redirect():
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/web/index.html" in response.headers["location"]

def test_list_models_endpoint():
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "projects" in data

def test_basyx_tree_endpoint():
    response = client.get("/api/tree")
    assert response.status_code == 200
    data = response.json()
    assert "tree" in data
    assert "basyxOnline" in data

def test_alerts_lifecycle():
    alert_payload = {
        "element_id": "TEST_PANEL_001",
        "error_type": "Sobreaquecimento",
        "severity": "critical",
        "message": "Temperatura crítica detectada no painel"
    }
    post_res = client.post("/api/alerts", json=alert_payload)
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "success"

    get_res = client.get("/api/alerts")
    assert get_res.status_code == 200
    alerts = get_res.json()["alerts"]
    assert any(a["element_id"] == "TEST_PANEL_001" for a in alerts)

    del_res = client.delete("/api/alerts/TEST_PANEL_001")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "cleared"

def test_telemetry_endpoint():
    res = client.get("/api/telemetry/TEST_PANEL_001")
    assert res.status_code == 200
    data = res.json()
    assert "metrics" in data
    assert "timestamps" in data

def test_simulation_mode_endpoint():
    # Garantir retorno inicial
    get_res = client.get("/api/simulation/mode")
    assert get_res.status_code == 200
    assert "mode" in get_res.json()

    # Definir para modo noturno
    post_res = client.post("/api/simulation/mode", json={"mode": "night"})
    assert post_res.status_code == 200
    assert post_res.json()["mode"] == "night"

    # Verificar presença de alerta noturno
    alerts_res = client.get("/api/alerts")
    assert alerts_res.status_code == 200
    alerts = alerts_res.json()["alerts"]
    assert any(a["error_type"] == "Noite" for a in alerts)

    # Verificar transformação da telemetria no modo noturno
    telem_res = client.get("/api/telemetry/TEST_PANEL_001")
    assert telem_res.status_code == 200
    telem_data = telem_res.json()
    assert telem_data.get("mode") == "night"
    metrics = telem_data.get("metrics", {})
    if "luminosity" in metrics:
        assert all(v == 0.0 for v in metrics["luminosity"])

    # Restaurar para modo diurno
    reset_res = client.post("/api/simulation/mode", json={"mode": "day"})
    assert reset_res.status_code == 200
    assert reset_res.json()["mode"] == "day"

