"""Módulo do Pipeline de Conversão 3D e Mapeamento Geométrico IFC.

Contém as funções de pré-processamento para conversão offline de modelos IFC em
arquivos tridimensionais GLB via o binário IfcConvert (v0.8.5), além de mapear os
Express IDs das representações de malhas diretamente aos seus ativos IFC pai.
"""

import logging
from pathlib import Path
import subprocess
import sys

# Garantir import de config.py a partir de src/visualization
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import IFCCONVERT_BIN

logger = logging.getLogger(__name__)

def convert_ifc_to_glb(input_ifc_path: Path, output_glb_path: Path, force: bool = False, timeout_sec: int = 600) -> bool:
    """Converte um arquivo .ifc em malha tridimensional .glb usando o binário bin/IfcConvert.

    Executa o processo de conversão offline preservando o arquivo original IFC como
    leitura estrita. Após a conversão, aciona automaticamente a geração do arquivo
    express_map.json de mapeamento de IDs de malha para GlobalIds do BaSyx.

    :param input_ifc_path: Caminho para o arquivo .ifc de origem.
    :param output_glb_path: Caminho para o arquivo .glb de destino.
    :param force: Se True, força a re-conversão sobrescrevendo o GLB existente.
    :param timeout_sec: Limite de tempo em segundos para a conversão (padrão 10 min).
    :return: True se a conversão/geração ocorreu com sucesso, False em caso de erro.
    """
    if not input_ifc_path.exists():
        logger.error(f"Arquivo IFC de origem não encontrado: {input_ifc_path}")
        return False

    if not IFCCONVERT_BIN.exists():
        logger.error(f"Executável IfcConvert não encontrado em: {IFCCONVERT_BIN}")
        return False

    output_glb_path.parent.mkdir(parents=True, exist_ok=True)

    if output_glb_path.exists() and not force:
        logger.info(f"Artefato GLB otimizado já existe em: {output_glb_path}. Pulando conversão.")
        return True

    cmd = [
        str(IFCCONVERT_BIN),
        str(input_ifc_path),
        str(output_glb_path),
        "--use-world-coords"
    ]

    logger.info(f"Executando conversão de {input_ifc_path.name} -> {output_glb_path.name}...")

    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=timeout_sec,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.info(f"Conversão concluída com sucesso: {output_glb_path}")
        map_json_path = output_glb_path.parent.parent / "express_map.json"
        generate_express_map(input_ifc_path, map_json_path)
        return True
    except subprocess.TimeoutExpired as exc:
        logger.error(f"Timeout ({exc.timeout}s) atingido durante conversão de {input_ifc_path.name}")
        return False
    except subprocess.CalledProcessError as exc:
        logger.error(f"Falha na conversão de {input_ifc_path.name} (código {exc.returncode}):\n{exc.stderr}")
        return False
    except Exception as exc:
        logger.error(f"Erro inesperado na conversão de {input_ifc_path.name}: {exc}")
        return False

def generate_express_map(input_ifc_path: Path, output_json_path: Path) -> bool:
    """Gera um dicionário JSON de mapeamento Express ID -> GlobalId IFC.

    Varre a estrutura de representação geométrica (`IfcShapeRepresentation` e `IfcProductDefinitionShape`)
    associando cada ID numérico de malha no Three.js diretamente ao `GlobalId` do produto IFC pai.
    Permite busca imediata de metadados no BaSyx sem latência.

    :param input_ifc_path: Caminho para o arquivo IFC a ser varrido.
    :param output_json_path: Caminho de destino para gravação do arquivo express_map.json.
    :return: True se a gravação do mapa obteve êxito, False em caso de falha.
    """
    try:
        import json
        import ifcopenshell

        logger.info(f"Gerando express_map.json a partir de {input_ifc_path.name}...")
        f = ifcopenshell.open(input_ifc_path)
        express_map = {}
        for prod in f.by_type("IfcProduct"):
            global_id = getattr(prod, "GlobalId", None)
            if not global_id:
                continue
            express_map[str(prod.id())] = global_id
            shape_rep = getattr(prod, "Representation", None)
            if shape_rep:
                visited = set()
                queue = [shape_rep]
                while queue:
                    curr = queue.pop(0)
                    if not hasattr(curr, "id") or curr.id() in visited:
                        continue
                    visited.add(curr.id())
                    express_map[str(curr.id())] = global_id
                    if curr.is_a("IfcProductDefinitionShape"):
                        for r in getattr(curr, "Representations", []) or []:
                            queue.append(r)
                    elif curr.is_a("IfcShapeRepresentation"):
                        for item in getattr(curr, "Items", []) or []:
                            queue.append(item)

        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as out:
            json.dump(express_map, out)
        logger.info(f"Mapeamento de {len(express_map)} Express IDs gravado em: {output_json_path}")
        return True
    except Exception as exc:
        logger.warning(f"Erro ao gerar express_map para {input_ifc_path.name}: {exc}")
        return False
