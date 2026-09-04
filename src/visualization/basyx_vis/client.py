"""Módulo Legado do Cliente de Integração BaSyx para Visualização.

Fornece a classe `VisualizationBasyxClient` para comunicação com a API REST do BaSyx.
"""

import base64
import logging
from typing import Any, Dict, List, Optional
import requests
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import BASYX_AAS_ENV_HOST, BASYX_REGISTRY_HOST

logger = logging.getLogger(__name__)

def b64url(value: str) -> str:
    """Codifica uma string URI em base64url sem padding '='.

    :param value: String URI original.
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

class VisualizationBasyxClient:
    """Cliente HTTP REST para consulta a Shells AAS e Submodelos do Eclipse BaSyx.

    :param aas_env_host: Host do ambiente AAS (padrão `http://localhost:8081`).
    :param registry_host: Host do registry AAS (padrão `http://localhost:8082`).
    """

    def __init__(self, aas_env_host: str = BASYX_AAS_ENV_HOST, registry_host: str = BASYX_REGISTRY_HOST):
        self.aas_env_url = aas_env_host.rstrip("/")
        self.registry_url = registry_host.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def is_alive(self) -> bool:
        """Testa se o servidor BaSyx está respondendo.

        :return: True se online, False em erro.
        """
        try:
            res = self._session.get(f"{self.aas_env_url}/shells?limit=1", timeout=2)
            return res.status_code == 200
        except Exception:
            return False

    def get_all_shells(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Consulta e retorna a lista de todas as Shells ativas.

        :param limit: Limite de registros.
        :return: Lista de Shells cadastradas.
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

    def get_shell_by_global_id(self, global_id: str) -> Optional[Dict[str, Any]]:
        """Busca uma Shell por seu globalAssetId, idShort ou id.

        :param global_id: Identificador a pesquisar.
        :return: Dicionário da Shell ou None.
        """
        shells = self.get_all_shells()
        for shell in shells:
            asset_info = shell.get("assetInformation", {})
            g_id = asset_info.get("globalAssetId") or shell.get("globalAssetId")
            if g_id == global_id or shell.get("idShort") == global_id or shell.get("id") == global_id:
                return shell
            if shell.get("id", "").endswith(global_id):
                return shell
        return None

    def get_submodel_elements(self, submodel_id: str) -> List[Dict[str, Any]]:
        """Retorna os elementos de um submodelo do BaSyx.

        :param submodel_id: ID do submodelo.
        :return: Lista de submodel elements.
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
        """Obtém os metadados agregados para um GlobalId IFC.

        :param global_id: Identificador do elemento.
        :return: Dicionário com Nameplate, TechnicalData e OPC UA.
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

    def _parse_submodel_elements(self, elements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Converte a estrutura de elementos do BaSyx em dicionário simplificado.

        :param elements: Lista de elementos de submodelo.
        :return: Dicionário {idShort: valor}.
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
