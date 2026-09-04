"""Módulo de Configuração e Constantes Globais do Visualizador Web.

Define caminhos absolutos do sistema (binários, diretórios de assets e assets web),
endpoints das APIs do Eclipse BaSyx no Docker e funções de validação de segurança
contra ataques de navegação (Directory Traversal).
"""

import os
import pathlib

# Caminho raiz do repositório digital_twin_asset_forge
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Diretórios principais de recursos e executáveis
BIN_DIR = PROJECT_ROOT / "bin"
IFCCONVERT_BIN = BIN_DIR / "IfcConvert"
ASSETS_DIR = PROJECT_ROOT / "assets"
WEB_DIR = PROJECT_ROOT / "src" / "visualization" / "web"

# Endpoints padrão do ambiente Eclipse BaSyx Docker
BASYX_AAS_ENV_HOST = os.getenv("BASYX_AAS_ENV_HOST", "http://localhost:8081")
BASYX_REGISTRY_HOST = os.getenv("BASYX_REGISTRY_HOST", "http://localhost:8082")

def is_safe_path(requested_path: str | pathlib.Path, base_path: pathlib.Path) -> bool:
    """Verifica se o caminho solicitado reside com segurança dentro do diretório base.

    Impede vulnerabilidades de Directory Traversal (ex: `../../etc/passwd`).

    :param requested_path: Caminho relativo ou absoluto solicitado.
    :param base_path: Diretório base permitido para resolução.
    :return: True se o caminho for estritamente interno ao base_path, False caso contrário.
    """
    try:
        resolved_requested = pathlib.Path(base_path / requested_path).resolve()
        resolved_base = base_path.resolve()
        return os.path.commonpath([resolved_base, resolved_requested]) == str(resolved_base)
    except Exception:
        return False
