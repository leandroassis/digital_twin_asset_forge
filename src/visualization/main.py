"""Módulo Principal da Aplicação FastAPI do Visualizador Web do Gêmeo Digital.

Disponibiliza os endpoints da API REST utilizados pela interface Single Page Application (SPA):
1. `/api/models`: Lista modelos GLB e projetos disponíveis.
2. `/api/tree`: Retorna a árvore de ativos do BaSyx.
3. `/api/basyx/metadata/{global_id:path}`: Retorna Nameplate e Psets do BaSyx.
4. `/api/telemetry/{global_id:path}`: Retorna séries temporais simuladas/OPC UA.
5. `/api/alerts`: Gerencia alertas e anomalias de IA.
"""

from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Adicionar caminho do módulo de visualização
sys.path.append(str(Path(__file__).resolve().parent))

from config import ASSETS_DIR, WEB_DIR, is_safe_path
from basyx_vis.basyx_service import VisualizationBasyxService

app = FastAPI(
    title="Gêmeo Digital Asset Forge - Visualizador Web",
    description="API REST de alta responsividade integrada ao BaSyx para visualização 3D, árvore de ativos e telemetria.",
    version="1.0.0"
)

basyx_service = VisualizationBasyxService()

# Armazenamento em memória para alertas recebidos da IA / simulação
ACTIVE_ALERTS: Dict[str, Dict[str, Any]] = {}

class AlertModel(BaseModel):
    """Modelo Pydantic para registro e recepção de alertas de anomalias no 3D."""

    element_id: str = Field(..., description="GlobalId, Express ID ou Tag do elemento afetado")
    error_type: str = Field(..., description="Tipo de erro: Sujeira, Sobreaquecimento, Sobrecorrente, Noite")
    severity: str = Field("warning", description="Gravidade do alerta: info, warning, critical")
    message: str = Field(..., description="Mensagem descritiva contextual do alerta")

# Montagem de rotas estáticas para a SPA (web) e arquivos de assets (GLB)
if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

@app.get("/")
def root():
    """Redireciona a rota raiz para a página principal da SPA (`/web/index.html`).

    :return: RedirectResponse redirecionando para a SPA.
    """
    return RedirectResponse(url="/web/index.html")

@app.get("/api/models")
def list_models():
    """Lista todos os projetos contidos no diretório `assets/` e verifica se possuem arquivo `.glb`.

    :return: Dicionário contendo a lista de projetos, flags de presença do GLB e suas URLs.
    """
    projects = []
    if ASSETS_DIR.exists():
        for proj_dir in ASSETS_DIR.iterdir():
            if proj_dir.is_dir():
                glb_file = proj_dir / "output" / "glb" / f"{proj_dir.name}.glb"
                projects.append({
                    "name": proj_dir.name,
                    "hasGlb": glb_file.exists(),
                    "glbUrl": f"/assets/{proj_dir.name}/output/glb/{proj_dir.name}.glb" if glb_file.exists() else None
                })
    return {"projects": projects}

@app.get("/api/tree")
def get_basyx_tree():
    """Retorna a árvore de ativos cadastrada no Eclipse BaSyx.

    Lê todas as Shells ativas diretamente do servidor BaSyx no Docker e constrói a hierarquia.

    :return: Dicionário contendo o nó raiz da árvore e o status online do BaSyx.
    """
    tree = basyx_service.build_tree_from_basyx()
    return {"tree": tree, "basyxOnline": basyx_service.is_alive()}

@app.get("/api/basyx/shells")
def get_basyx_shells():
    """Retorna a lista de todas as Shells AAS cadastradas no servidor BaSyx.

    :return: Dicionário com a quantidade total e a lista completa de Shells.
    """
    shells = basyx_service.get_all_shells()
    return {"count": len(shells), "shells": shells}

@app.get("/api/basyx/metadata/{global_id:path}")
def get_basyx_metadata(global_id: str):
    """Obtém os metadados AAS (Nameplate, TechnicalData, OPC UA) para um elemento.

    Aceita parâmetros de caminho completos (URLs/URIs com barras ou Express IDs).

    :param global_id: Identificador global ou Express ID do ativo.
    :return: Dicionário com metadados Nameplate, TechnicalData e OPC UA.
    """
    metadata = basyx_service.get_metadata_for_element(global_id)
    return metadata

@app.get("/api/telemetry/{global_id:path}")
def get_element_telemetry(global_id: str):
    """Retorna séries temporais de telemetria simuladas (ou OPC UA) para o elemento selecionado.

    Gera métricas específicas como Tensão CC/CA, Corrente CC/CA, Temperatura e Luminosidade.

    :param global_id: Identificador do elemento selecionado.
    :return: Dicionário contendo o tipo de ativo, métricas e timestamps.
    """
    import random
    from datetime import datetime, timedelta

    now = datetime.now()
    timestamps = [(now - timedelta(minutes=i*5)).isoformat() for i in range(12)][::-1]

    is_inverter = "inverter" in global_id.lower() or "inv" in global_id.lower()

    if is_inverter:
        data = {
            "type": "Inverter",
            "globalId": global_id,
            "metrics": {
                "voltageAC": [round(220 + random.uniform(-5, 5), 2) for _ in timestamps],
                "currentAC": [round(45 + random.uniform(-3, 3), 2) for _ in timestamps],
                "powerAC": [round(9.9 + random.uniform(-0.5, 0.5), 2) for _ in timestamps]
            },
            "timestamps": timestamps
        }
    else:
        data = {
            "type": "SolarPanel",
            "globalId": global_id,
            "metrics": {
                "luminosity": [round(850 + random.uniform(-50, 50), 1) for _ in timestamps],
                "temperature": [round(42 + random.uniform(-2, 3), 1) for _ in timestamps],
                "currentDC": [round(9.2 + random.uniform(-0.4, 0.4), 2) for _ in timestamps],
                "voltageDC": [round(38.5 + random.uniform(-1, 1), 2) for _ in timestamps]
            },
            "timestamps": timestamps
        }

    return data

@app.get("/api/alerts")
def get_active_alerts():
    """Retorna a lista de todos os alertas de anomalia ativos no sistema.

    :return: Dicionário contendo a lista de alertas registrados.
    """
    return {"alerts": list(ACTIVE_ALERTS.values())}

@app.post("/api/alerts")
def create_alert(alert: AlertModel):
    """Registra ou atualiza um alerta para um determinado elemento do modelo.

    :param alert: Objeto AlertModel contendo os dados do alerta.
    :return: Dicionário com confirmação de sucesso e os dados do alerta.
    """
    ACTIVE_ALERTS[alert.element_id] = alert.model_dump() if hasattr(alert, "model_dump") else alert.dict()
    return {"status": "success", "alert": ACTIVE_ALERTS[alert.element_id]}

@app.delete("/api/alerts/{element_id:path}")
def clear_alert(element_id: str):
    """Remove o alerta ativo de um elemento pelo seu ID.

    :param element_id: ID do elemento cujo alerta deve ser limpo.
    :return: Dicionário indicando a remoção.
    """
    if element_id in ACTIVE_ALERTS:
        del ACTIVE_ALERTS[element_id]
        return {"status": "cleared", "element_id": element_id}
    raise HTTPException(status_code=404, detail="Alerta não encontrado.")
