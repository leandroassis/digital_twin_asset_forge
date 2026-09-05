"""Módulo de Serviço e Integração com a API REST do Eclipse BaSyx.

Fornece a classe `VisualizationBasyxService` para interagir com os servidores
AAS Environment e Registry do Eclipse BaSyx rodando via Docker. Responsável por:
1. Construir a árvore de ativos categorizados (`GET /api/tree`).
2. Resolver IDs de malhas 3D (Express IDs, UUIDs e IFC GlobalIds) para Shells AAS.
3. Buscar submodelos de dados (*Nameplate*, *TechnicalData*, *OPC UA*).
"""

import base64
import logging
import re
from typing import Any, Dict, List, Optional
import requests
from pathlib import Path
import sys

import ifcopenshell.guid

# Importar config.py a partir de src/visualization
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import BASYX_AAS_ENV_HOST, BASYX_REGISTRY_HOST, ASSETS_DIR

logger = logging.getLogger(__name__)

# opcua/timeseries Property id_shorts (see asset_forge/export/aas/solar.py)
# -> the metric keys dashboard.js's titleMap already renders.
_METRIC_KEY_MAP = {
    "LightIntensity": "luminosity",
    "Temperature": "temperature",
    "CurrentDC": "currentDC",
    "VoltageDC": "voltageDC",
    "VoltageAC": "voltageAC",
    "CurrentAC": "currentAC",
    "PowerAC": "powerAC",
}
_INVERTER_ONLY_ID_SHORTS = {"VoltageAC", "CurrentAC", "PowerAC"}

def b64url(value: str) -> str:
    """Codifica uma string URI em formato base64url sem padding '='.

    Requisitado pela API REST v3 do Eclipse BaSyx para passagem de IDs em URLs.

    :param value: String URI original (ex: URL de um submodelo).
    :return: String codificada em base64url.
    """
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

def b64url_decode(value: str) -> str:
    """Decodifica uma string codificada em base64url vinda de URLs do BaSyx.

    :param value: String codificada em base64url.
    :return: String decodificada original.
    """
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")

def compress_uuid_to_ifc_guid(uuid_str: str) -> Optional[str]:
    """Converte um UUID (36 chars formatado ou 32 chars hex) para IFC GlobalId (22 chars base64).

    Utilizado quando exportações de malha GLB do IfcConvert usam UUIDs padrão.

    :param uuid_str: String contendo o UUID de 36 caracteres ou 32 hexadecimais.
    :return: String de 22 caracteres base64 do IFC GlobalId, ou None se inválido.
    """
    clean_hex = uuid_str.replace("-", "").strip()
    if len(clean_hex) == 32 and all(c in "0123456789abcdefABCDEF" for c in clean_hex):
        try:
            formatted = f"{clean_hex[0:8]}-{clean_hex[8:12]}-{clean_hex[12:16]}-{clean_hex[16:20]}-{clean_hex[20:32]}"
            return ifcopenshell.guid.compress(formatted)
        except Exception:
            pass
    return None

class VisualizationBasyxService:
    """Serviço cliente para comunicação REST com a stack do Eclipse BaSyx.

    Encapsula chamadas aos contêineres Docker do BaSyx Environment (`:8081`) e
    Registry (`:8082`), gerenciando o cache de mapeamento de IDs e montagem da árvore.

    :param aas_env_host: URL do servidor AAS Environment (padrão `http://localhost:8081`).
    :param registry_host: URL do servidor Registry (padrão `http://localhost:8082`).
    """

    def __init__(self, aas_env_host: str = BASYX_AAS_ENV_HOST, registry_host: str = BASYX_REGISTRY_HOST):
        self.aas_env_url = aas_env_host.rstrip("/")
        self.registry_url = registry_host.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._express_map: Optional[Dict[str, str]] = None

    def is_alive(self) -> bool:
        """Testa se o servidor BaSyx está online e respondendo a requisições.

        :return: True se a resposta HTTP for 200 OK, False em erro de conexão ou offline.
        """
        try:
            res = self._session.get(f"{self.aas_env_url}/shells?limit=1", timeout=2)
            return res.status_code == 200
        except Exception:
            return False

    def get_all_shells(self, limit: int = 15000) -> List[Dict[str, Any]]:
        """Consulta o servidor BaSyx e retorna a lista de todas as Shells AAS cadastradas.

        Tenta primariamente a rota `/shells` no AAS Environment. Em caso de falha,
        utiliza o fallback na rota `/shell-descriptors` do Registry.

        :param limit: Limite máximo de Shells a retornar por requisição (padrão 15.000).
        :return: Lista de dicionários representando as Shells AAS ativas.
        """
        try:
            res = self._session.get(f"{self.aas_env_url}/shells?limit={limit}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                return data.get("result", [])
        except Exception as exc:
            logger.warning(f"Erro ao consultar /shells no BaSyx ({self.aas_env_url}): {exc}")

        try:
            res = self._session.get(f"{self.registry_url}/shell-descriptors?limit={limit}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                return data.get("result", [])
        except Exception as exc:
            logger.warning(f"Erro ao consultar /shell-descriptors no Registry ({self.registry_url}): {exc}")

        return []

    def build_tree_from_basyx(self) -> Dict[str, Any]:
        """Obtém todas as Shells cadastradas e constrói a estrutura hierárquica por disciplinas.

        Categoriza os ativos em grupos como "Inversores", "Painéis Fotovoltaicos",
        "Sensores e Medidores" e "Equipamentos Gerais" para renderização na SPA.

        :return: Dicionário em formato de árvore com nós raiz, categorias e folhas.
        """
        shells = self.get_all_shells()
        if not shells:
            return {
                "id": "basyx_root",
                "name": "BaSyx AAS Repository (Nenhuma Shell carregada - execute `just basyx-upload`)",
                "type": "AASRepository",
                "children": []
            }

        categories: Dict[str, List[Dict[str, Any]]] = {}

        for shell in shells:
            aas_id = shell.get("id", "")
            id_short = shell.get("idShort", "Asset")
            asset_info = shell.get("assetInformation", {})
            global_asset_id = asset_info.get("globalAssetId") or shell.get("globalAssetId") or aas_id

            id_lower = id_short.lower()
            if "inverter" in id_lower or "inversor" in id_lower or "wechselrichter" in id_lower:
                category_name = "Inversores (Inverters)"
            elif "panel" in id_lower or "solar" in id_lower or "kt" in id_lower or "modul" in id_lower or "pv" in id_lower:
                category_name = "Painéis Fotovoltaicos (PV Modules)"
            elif "sensor" in id_lower or "temperatur" in id_lower or "meter" in id_lower:
                category_name = "Sensores e Medidores (Sensors/Meters)"
            else:
                category_name = "Equipamentos e Estruturas Geral"

            if category_name not in categories:
                categories[category_name] = []

            categories[category_name].append({
                "id": global_asset_id,
                "name": id_short,
                "type": "AssetAdministrationShell",
                "aasId": aas_id,
                "submodelsCount": len(shell.get("submodels", []) or shell.get("submodelDescriptors", []))
            })

        children_categories = []
        for cat_name, items in categories.items():
            children_categories.append({
                "id": f"cat_{cat_name.lower().replace(' ', '_')}",
                "name": f"{cat_name} ({len(items)})",
                "type": "CategoryGroup",
                "children": items
            })

        return {
            "id": "basyx_root",
            "name": f"Gêmeo Digital BaSyx ({len(shells)} Ativos)",
            "type": "AASRepository",
            "children": children_categories
        }

    def _get_express_map(self) -> Dict[str, str]:
        """Carrega e armazena em cache o dicionário de mapeamento Express ID -> GlobalId.

        Lê arquivos `express_map.json` gerados na pasta de saída dos projetos.

        :return: Dicionário contendo {express_id_str: global_id_str}.
        """
        if self._express_map is None:
            import json
            self._express_map = {}
            for map_file in ASSETS_DIR.glob("*/output/express_map.json"):
                try:
                    with open(map_file, "r", encoding="utf-8") as f:
                        self._express_map.update(json.load(f))
                except Exception as exc:
                    logger.warning(f"Erro ao carregar express_map de {map_file}: {exc}")
        return self._express_map

    def get_shell_by_global_id(self, global_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma Shell específica no BaSyx combinando múltiplas estratégias de ID.

        Estratégias de busca aplicadas em sequência:
        1. Limpeza de prefixos/sufixos de malha 3D (`-world-coords`, `product-`).
        2. Mapeamento de Express IDs geométricos via `express_map.json` para `GlobalId`.
        3. Conversão de UUIDs de 36 caracteres para IFC GlobalId de 22 caracteres base64.
        4. Comparação por igualdade direta em `globalAssetId`, `id` ou `idShort`.
        5. Busca por sufixos numéricos (Express ID no idShort) ou substrings.

        :param global_id: Identificador enviado pela SPA 3D ou árvore do BaSyx.
        :return: Dicionário da Shell AAS encontrada ou None se não localizada.
        """
        if not global_id:
            return None

        shells = self.get_all_shells()
        raw_id = global_id.strip()

        # Remover sufixos e prefixos conhecidos de meshes 3D
        clean_id = re.sub(r'(-world-coords|-body|-geometry|-mesh)$', '', raw_id)
        clean_id = re.sub(r'^(product-|mesh-|element-|body-)', '', clean_id)

        # 1. Checar se clean_id é um Express ID de representação geométrica mapeado para GlobalId
        express_map = self._get_express_map()
        if clean_id in express_map:
            clean_id = express_map[clean_id]

        # 2. Tentar conversão UUID -> IFC 22-char GlobalId (se formatado como GUID/UUID)
        ifc_guid_converted = compress_uuid_to_ifc_guid(clean_id)

        for shell in shells:
            asset_info = shell.get("assetInformation", {})
            g_id = asset_info.get("globalAssetId", "") or ""
            aas_id = shell.get("id", "") or ""
            id_short = shell.get("idShort", "") or ""

            # Se convertemos de UUID para IFC GlobalId (ex: 278PRqujXCKORJryolT2ok)
            if ifc_guid_converted:
                if ifc_guid_converted in g_id or ifc_guid_converted in aas_id or ifc_guid_converted == id_short:
                    return shell

            # Correspondência exata em qualquer dos atributos
            if clean_id in (g_id, aas_id, id_short, raw_id):
                return shell
            if g_id.endswith(clean_id) or aas_id.endswith(clean_id):
                return shell

            # Correspondência por Express ID numérico (ex: ..._1510189_7 ou ..._2460883)
            if clean_id.isdigit():
                if f"_{clean_id}_" in id_short or id_short.endswith(f"_{clean_id}") or clean_id in aas_id:
                    return shell

            # Substring fallback
            if len(clean_id) >= 4 and (clean_id in g_id or clean_id in aas_id or clean_id in id_short):
                return shell

        return None

    def get_submodel_elements(self, submodel_id: str) -> List[Dict[str, Any]]:
        """Busca os elementos (propriedades, Psets) de um submodelo do BaSyx por seu ID.

        :param submodel_id: ID único do submodelo (URI).
        :return: Lista de elementos de submodelo parseados da API REST.
        """
        encoded_id = b64url(submodel_id)
        url = f"{self.aas_env_url}/submodels/{encoded_id}/submodel-elements"
        try:
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return data.get("result", []) if isinstance(data, dict) else data
        except Exception as exc:
            logger.warning(f"Erro ao buscar submodel-elements de {submodel_id}: {exc}")
        return []

    def get_metadata_for_element(self, global_id: str) -> Dict[str, Any]:
        """Obtém metadados agregados (Nameplate, TechnicalData, OPC UA) para um elemento.

        :param global_id: Identificador global do ativo.
        :return: Dicionário contendo Nameplate, TechnicalData e OPC UA extraídos do BaSyx.
        """
        shell = self.get_shell_by_global_id(global_id)
        if not shell:
            return {
                "globalId": global_id,
                "foundInBasyx": False,
                "nameplate": {},
                "technicalData": {},
                "opcua": {}
            }

        submodels_refs = shell.get("submodels", []) or shell.get("submodelDescriptors", [])
        result_metadata = {
            "globalId": global_id,
            "aasId": shell.get("id"),
            "idShort": shell.get("idShort"),
            "foundInBasyx": True,
            "nameplate": {},
            "technicalData": {},
            "opcua": {}
        }

        for sm_ref in submodels_refs:
            keys = sm_ref.get("keys", [])
            sm_id = keys[0].get("value") if keys else sm_ref.get("id")
            if not sm_id:
                continue

            elements = self.get_submodel_elements(sm_id)
            if "nameplate" in sm_id.lower():
                result_metadata["nameplate"] = self._parse_submodel_elements(elements)
            elif "technicaldata" in sm_id.lower():
                result_metadata["technicalData"] = self._parse_submodel_elements(elements)
            elif "opcua" in sm_id.lower():
                result_metadata["opcua"] = self._parse_submodel_elements(elements)

        return result_metadata

    def _find_submodel_id(self, shell: Dict[str, Any], id_short_substring: str) -> Optional[str]:
        """Finds the id of the first submodel reference on `shell` whose id
        contains `id_short_substring` (e.g. "timeseries", "opcua")."""
        for sm_ref in shell.get("submodels", []) or shell.get("submodelDescriptors", []):
            keys = sm_ref.get("keys", [])
            sm_id = keys[0].get("value") if keys else sm_ref.get("id")
            if sm_id and id_short_substring in sm_id.lower():
                return sm_id
        return None

    def get_telemetry_for_element(self, global_id: str, count: Optional[int] = None) -> Dict[str, Any]:
        """Fetches real historized telemetry for an asset by following its
        `timeseries` submodel's `Segments.LinkedSegment` to the history-api
        service (see export/aas/submodels.py::build_timeseries_submodel and
        history_api.py) -- never simulated/random data.

        :param global_id: Identificador do elemento selecionado.
        :param count: Limite opcional de últimos N registros por métrica.
        :return: Dicionário {globalId, type, metrics, timestamps, foundInBasyx}.
        """
        empty: Dict[str, Any] = {
            "globalId": global_id,
            "type": "Unknown",
            "metrics": {},
            "timestamps": [],
            "foundInBasyx": False,
        }

        shell = self.get_shell_by_global_id(global_id)
        if not shell:
            return empty

        sm_id = self._find_submodel_id(shell, "timeseries")
        if not sm_id:
            return {**empty, "foundInBasyx": True}

        parsed = self._parse_submodel_elements(self.get_submodel_elements(sm_id))
        linked = (parsed.get("Segments") or {}).get("LinkedSegment") or {}
        endpoint = linked.get("Endpoint")
        query = linked.get("Query")
        if not endpoint or not query:
            return {**empty, "foundInBasyx": True}

        try:
            params = {"count": count} if count else {}
            res = self._session.get(f"{endpoint.rstrip('/')}/series/{query}", params=params, timeout=5)
            res.raise_for_status()
            series = res.json()
        except Exception as exc:
            logger.warning(f"Erro ao consultar history-api ({endpoint}) para '{query}': {exc}")
            return {**empty, "foundInBasyx": True}

        metrics: Dict[str, List[float]] = {}
        timestamps: List[str] = []
        for id_short, points in series.items():
            metrics[_METRIC_KEY_MAP.get(id_short, id_short)] = [p.get("value") for p in points]
            if not timestamps and points:
                timestamps = [p.get("time") for p in points]

        return {
            "globalId": global_id,
            "aasId": shell.get("id"),
            "idShort": shell.get("idShort"),
            "foundInBasyx": True,
            "type": "Inverter" if _INVERTER_ONLY_ID_SHORTS & series.keys() else "SolarPanel",
            "metrics": metrics,
            "timestamps": timestamps,
        }

    def _parse_submodel_elements(self, elements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Converte a estrutura genérica de elementos do BaSyx em dicionário {idShort: valor}.

        :param elements: Lista de elementos de submodelo no formato JSON do BaSyx.
        :return: Dicionário simplificado no formato {idShort: valor}.
        """
        parsed = {}
        for elem in elements:
            id_short = elem.get("idShort")
            val = elem.get("value")
            model_type = elem.get("modelType")

            if model_type == "Property":
                parsed[id_short] = val
            elif model_type in ("SubmodelElementCollection", "SubmodelElementList"):
                if isinstance(val, list):
                    parsed[id_short] = self._parse_submodel_elements(val)
                else:
                    parsed[id_short] = val
            else:
                parsed[id_short] = val
        return parsed
