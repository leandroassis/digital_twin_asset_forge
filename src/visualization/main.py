"""Módulo Principal da Aplicação FastAPI do Visualizador Web do Gêmeo Digital.

Disponibiliza os endpoints da API REST utilizados pela interface Single Page Application (SPA):
1. `/api/models`: Lista modelos GLB e projetos disponíveis.
2. `/api/tree`: Retorna a árvore de ativos do BaSyx.
3. `/api/basyx/metadata/{global_id:path}`: Retorna Nameplate e Psets do BaSyx.
4. `/api/telemetry/{global_id:path}`: Retorna séries temporais simuladas/OPC UA.
5. `/api/alerts`: Gerencia alertas e anomalias de IA.
"""

from pathlib import Path
import re
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


@app.middleware("http")
async def _no_cache_for_web_assets(request, call_next):
    """Forces every response under `/web/` (the SPA's own JS/CSS/HTML) to
    skip caching entirely. Confirmed live: a stale cached ES module (e.g.
    viewer3d.js) can keep reproducing an already-fixed bug in the browser
    even after the server is verified to be serving the new file
    byte-for-byte -- this is dev-time infra, not app logic, so unconditional
    no-store is simpler and safer here than trying to version-bust
    individual asset URLs."""
    response = await call_next(request)
    if request.url.path.startswith("/web/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

import random
from datetime import datetime, timezone

# Armazenamento em memória para alertas recebidos da IA / simulação
ACTIVE_ALERTS: Dict[str, Dict[str, Any]] = {}
OPERATION_MODE: str = "day"
HISTORICAL_TELEMETRY_LOG: List[Dict[str, Any]] = []

def _get_alert_telemetry_overrides(global_id: str) -> Dict[str, float]:
    """Extrai métricas anômalas de alertas ativos para sincronizar perfeitamente
    as séries temporais do elemento selecionado com as leituras informadas no alerta.
    """
    overrides = {}
    if not global_id or OPERATION_MODE == "night":
        return overrides

    alert = ACTIVE_ALERTS.get(global_id)
    if not alert:
        for elem_id, alt in ACTIVE_ALERTS.items():
            if elem_id and (elem_id in global_id or global_id in elem_id):
                alert = alt
                break

    if not alert:
        return overrides

    error_type = alert.get("error_type", "")
    message = alert.get("message", "")

    if error_type == "Sobreaquecimento":
        match = re.search(r"(\d+\.\d+)\s*°C", message)
        overrides["temperature"] = float(match.group(1)) if match else 48.3
    elif error_type == "Sujeira":
        match_a = re.search(r"(\d+\.\d+)\s*A", message)
        match_lux = re.search(r"(\d+\.\d+)\s*lux", message)
        if match_a:
            overrides["currentDC"] = float(match_a.group(1))
        if match_lux:
            overrides["luminosity"] = float(match_lux.group(1))
    elif error_type == "Sobrecorrente":
        match = re.search(r"(\d+\.\d+)\s*A", message)
        if match:
            overrides["currentDC"] = float(match.group(1))

    return overrides

def _generate_telemetry_sample(mode: str, global_id: Optional[str] = None) -> Dict[str, float]:
    """Gera uma amostra de telemetria com micro-flutuações físicas realistas,
    incorporando leituras anômalas de alertas de IA ativos para evitar descasamentos.
    """
    if mode == "night":
        return {
            "luminosity": 0.0,
            "temperature": round(18.0 + random.uniform(-0.3, 0.3), 1),
            "currentDC": 0.0,
            "voltageDC": 0.0,
            "powerAC": 0.0,
            "currentAC": 0.0,
        }
    
    irradiance = round(980.0 + random.uniform(-10.0, 10.0), 1)
    temp = round(45.2 + random.uniform(-0.6, 0.6), 1)
    current = round(16.2 + random.uniform(-0.25, 0.25), 2)
    voltage = round(36.5 + random.uniform(-0.3, 0.3), 2)

    # Incorporar leituras anômalas do alerta ativo se o elemento possuir anomalia
    if global_id:
        overrides = _get_alert_telemetry_overrides(global_id)
        if "temperature" in overrides:
            temp = round(overrides["temperature"] + random.uniform(-0.3, 0.3), 1)
        if "currentDC" in overrides:
            current = round(overrides["currentDC"] + random.uniform(-0.15, 0.15), 2)
        if "luminosity" in overrides:
            irradiance = round(overrides["luminosity"] + random.uniform(-5.0, 5.0), 1)

    power = round(current * voltage, 1)
    current_ac = round(current * 0.97, 2)
    return {
        "luminosity": irradiance,
        "temperature": temp,
        "currentDC": current,
        "voltageDC": voltage,
        "powerAC": power,
        "currentAC": current_ac,
    }

class AlertModel(BaseModel):
    """Modelo Pydantic para registro e recepção de alertas de anomalias no 3D."""

    element_id: str = Field(..., description="GlobalId, Express ID ou Tag do elemento afetado")
    error_type: str = Field(..., description="Tipo de erro: Sujeira, Sobreaquecimento, Sobrecorrente, Noite")
    severity: str = Field("warning", description="Gravidade do alerta: info, warning, critical")
    message: str = Field(..., description="Mensagem descritiva contextual do alerta")

class SimulationModeModel(BaseModel):
    """Modelo Pydantic para definição do modo de operação da simulação (day / night)."""

    mode: str = Field(..., description="Modo de operação: 'day' para diurno, 'night' para noturno")

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

def _try_write_influxdb(mode: str):
    """Tenta gravar um ponto de telemetria historizado no InfluxDB se o serviço estiver online."""
    try:
        from influxdb_client import InfluxDBClient, Point
        from influxdb_client.client.write_api import SYNCHRONOUS
        from asset_forge.config import INFLUXDB_BUCKET, INFLUXDB_HOST, INFLUXDB_ORG, INFLUXDB_PORT, INFLUXDB_TOKEN
        
        client = InfluxDBClient(url=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}", token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        
        sample = _generate_telemetry_sample(mode)
        p = Point("sensor_reading") \
            .tag("asset", "SOLAR_PLANT_FIELD") \
            .field("LightIntensity", sample["luminosity"]) \
            .field("Temperature", sample["temperature"]) \
            .field("CurrentDC", sample["currentDC"]) \
            .field("VoltageDC", sample["voltageDC"]) \
            .field("PowerAC", sample["powerAC"])
        
        write_api.write(bucket=INFLUXDB_BUCKET, record=p)
        client.close()
    except Exception:
        pass

@app.get("/api/simulation/mode")
def get_simulation_mode():
    """Retorna o modo de operação atual da simulação ('day' ou 'night')."""
    return {"mode": OPERATION_MODE}

@app.post("/api/simulation/mode")
def set_simulation_mode(payload: SimulationModeModel):
    """Define o modo de operação da simulação ('day' para diurno ou 'night' para noturno)
    e grava um novo registro histórico com o timestamp atual.
    """
    global OPERATION_MODE
    if payload.mode not in ("day", "night"):
        raise HTTPException(status_code=400, detail="Modo inválido. Use 'day' ou 'night'.")
    
    OPERATION_MODE = payload.mode
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

    point_record = {
        "timestamp": now_str,
        "mode": OPERATION_MODE,
        "metrics": _generate_telemetry_sample(OPERATION_MODE)
    }
    HISTORICAL_TELEMETRY_LOG.append(point_record)
    
    # Tentar persistência no InfluxDB
    _try_write_influxdb(OPERATION_MODE)

    if OPERATION_MODE == "night":
        ACTIVE_ALERTS["SOLAR_PLANT_FIELD"] = {
            "element_id": "SOLAR_PLANT_FIELD",
            "error_type": "Noite",
            "severity": "info",
            "message": "🌙 Operação noturna / baixa luminosidade: 0.0 lux"
        }
    else:
        ACTIVE_ALERTS.pop("SOLAR_PLANT_FIELD", None)

    return {"status": "success", "mode": OPERATION_MODE}

@app.get("/api/models")
def list_models():
    """Lista todos os projetos contidos no diretório `assets/` e verifica se possuem arquivo `.glb`.

    :return: Dicionário contendo a lista de projetos, flags de presença do GLB e suas URLs.
    """
    projects = []
    if ASSETS_DIR.exists():
        for proj_dir in ASSETS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            glb_dir = proj_dir / "output" / "glb"
            glb_file = glb_dir / "plant.glb"
            glb_name = "plant.glb"
            if not glb_file.exists():
                glb_file = glb_dir / f"{proj_dir.name}.glb"
                glb_name = f"{proj_dir.name}.glb"
            projects.append({
                "name": proj_dir.name,
                "hasGlb": glb_file.exists(),
                "glbUrl": f"/assets/{proj_dir.name}/output/glb/{glb_name}" if glb_file.exists() else None
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
    """Obtém todos os submodelos AAS do elemento, cada um como uma árvore
    genérica de seus elementos (Nameplate, TechnicalData, OPC UA,
    TimeSeries, e qualquer outro presente -- nada é descartado).

    Aceita parâmetros de caminho completos (URLs/URIs com barras ou Express IDs).

    :param global_id: Identificador global ou Express ID do ativo.
    :return: Dicionário {globalId, aasId, idShort, foundInBasyx, submodels}.
    """
    return basyx_service.get_submodel_tree_for_element(global_id)

@app.get("/api/telemetry/{global_id:path}")
def get_element_telemetry(global_id: str, count: Optional[int] = Query(None, ge=1)):
    """Retorna séries temporais de telemetria para o elemento selecionado.

    Mescla as leituras historizadas do BaSyx/history-api com os pontos gravados
    durante a alternância dos modos de operação (Abordagem 2), garantindo que
    a evolução histórica (transição dia/noite) seja acumulada na linha do tempo.

    :param global_id: Identificador do elemento selecionado.
    :param count: Limite opcional de registros mais recentes por métrica.
    :return: Dicionário contendo o tipo de ativo, métricas e timestamps.
    """
    telemetry = basyx_service.get_telemetry_for_element(global_id, count=count)
    
    metrics = telemetry.get("metrics", {})
    timestamps = telemetry.get("timestamps", [])
    
    if not metrics:
        # Se o elemento não tiver série no BaSyx, prover estrutura base com variações realistas
        num_initial = 12
        timestamps = [f"T-{i}m" for i in range(num_initial, 0, -1)]
        metrics = {"luminosity": [], "temperature": [], "currentDC": [], "voltageDC": [], "powerAC": []}
        for _ in range(num_initial):
            sample = _generate_telemetry_sample(OPERATION_MODE, global_id=global_id)
            for m_key in metrics.keys():
                metrics[m_key].append(sample.get(m_key, 0.0))
        telemetry["metrics"] = metrics
        telemetry["timestamps"] = timestamps

    # Anexar a sequência de pontos históricos gravados durante as alternâncias nesta sessão
    if HISTORICAL_TELEMETRY_LOG:
        for record in HISTORICAL_TELEMETRY_LOG:
            t_str = record["timestamp"]
            timestamps.append(t_str)
            rec_metrics = record["metrics"]
            for m_key in metrics.keys():
                val = rec_metrics.get(m_key, 0.0 if record["mode"] == "night" else 980.0)
                metrics[m_key].append(val)

    # Anexar ponto corrente ao vivo com micro-flutuação para animar o gráfico em tempo real
    now_live = datetime.now(timezone.utc).strftime("%H:%M:%S")
    live_sample = _generate_telemetry_sample(OPERATION_MODE, global_id=global_id)
    timestamps.append(now_live)
    for m_key in metrics.keys():
        metrics[m_key].append(live_sample.get(m_key, 0.0))

    # Se o modo atual for noturno, garantir que a telemetria do ativo reflita o repouso noturno (0.0 lux / 0.0 A / 18°C)
    if OPERATION_MODE == "night":
        for m_key in metrics.keys():
            if m_key in ("luminosity", "currentDC", "voltageDC", "powerAC", "currentAC"):
                metrics[m_key] = [0.0] * len(metrics[m_key])
            elif m_key == "temperature":
                metrics[m_key] = [round(18.0 + random.uniform(-0.2, 0.2), 1) for _ in metrics[m_key]]

    telemetry["mode"] = OPERATION_MODE
    return telemetry

@app.get("/api/alerts")
def get_active_alerts():
    """Retorna a lista de todos os alertas de anomalia ativos no sistema.
    Em Modo Noturno, oculta anomalias diurnas de painéis desenergizados (sobfeaquecimento/sujeira)
    e exibe exclusivamente a operação noturna.

    :return: Dicionário contendo a lista de alertas registrados.
    """
    if OPERATION_MODE == "night":
        if "SOLAR_PLANT_FIELD" not in ACTIVE_ALERTS:
            ACTIVE_ALERTS["SOLAR_PLANT_FIELD"] = {
                "element_id": "SOLAR_PLANT_FIELD",
                "error_type": "Noite",
                "severity": "info",
                "message": "🌙 Operação noturna / baixa luminosidade: 0.0 lux"
            }
        return {"alerts": [alert for alert in ACTIVE_ALERTS.values() if alert.get("error_type") == "Noite"]}
    else:
        ACTIVE_ALERTS.pop("SOLAR_PLANT_FIELD", None)
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

