"""Consulta as falhas solicitadas pela interface do visualizador."""

import base64
from typing import Dict, Optional

import requests
from loguru import logger

from fault_injection import SUPPORTED_FAULT_TYPES


def global_id_from_submodel_id_b64(
    submodel_id_b64: str,
) -> Optional[str]:
    """Extrai o GlobalId de um identificador de submodelo codificado."""

    try:
        padding = "=" * ((4 - len(submodel_id_b64) % 4) % 4)
        decoded = base64.urlsafe_b64decode(
            submodel_id_b64 + padding
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None

    marker = "/aas/ifc/"

    if marker not in decoded or "/sm/" not in decoded:
        return None

    return decoded.split(marker, 1)[1].split("/sm/", 1)[0]


def fetch_active_faults(
    viz_url: str,
    session: Optional[requests.Session] = None,
) -> Dict[str, str]:
    """Retorna as falhas ativas no formato GlobalId -> tipo de falha.

    Se o visualizador estiver indisponível, retorna um dicionário vazio.
    Nesse caso, os painéis continuam operando normalmente.
    """

    request_get = session.get if session is not None else requests.get

    try:
        response = request_get(
            f"{viz_url.rstrip('/')}/api/faults",
            timeout=3,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            f"Não foi possível consultar as falhas em {viz_url}: {exc}"
        )
        return {}

    if not isinstance(payload, dict):
        logger.warning("Resposta inválida recebida de /api/faults")
        return {}

    faults = payload.get("faults", [])

    if not isinstance(faults, list):
        logger.warning("O campo 'faults' da resposta não é uma lista")
        return {}

    active_faults: Dict[str, str] = {}

    for fault in faults:
        if not isinstance(fault, dict):
            continue

        element_id = fault.get("element_id")
        fault_type = fault.get("fault_type")

        if (
            isinstance(element_id, str)
            and fault_type in SUPPORTED_FAULT_TYPES
        ):
            active_faults[element_id] = fault_type

    return active_faults