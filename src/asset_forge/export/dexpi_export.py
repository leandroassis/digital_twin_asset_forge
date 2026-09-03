"""Serializes a pydexpi DexpiModel to JSON, GraphML and Proteus XML."""

from dataclasses import dataclass
from pathlib import Path

import networkx as nx
from loguru import logger
from pydexpi.dexpi_classes.dexpiModel import DexpiModel
from pydexpi.loaders.graph_loader import GraphLoader
from pydexpi.loaders.json_serializer import JsonSerializer
from pydexpi.loaders.proteus_serializer.proteus_serializer import ProteusSerializer

from asset_forge.ingestion.loader import PathLike


@dataclass
class DexpiExportSummary:
    json_path: Path
    graphml_path: Path
    proteus_xml_path: Path
    piping_item_count: int
    connection_count: int


def export_dexpi(model: DexpiModel, output_dir: PathLike, filename: str = "model") -> DexpiExportSummary:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    JsonSerializer().save(model, output_dir, filename)

    graph = GraphLoader().dexpi_to_graph(model)
    graphml_path = output_dir / f"{filename}.graphml"
    nx.write_graphml(graph, graphml_path)

    ProteusSerializer().save(model, output_dir, filename)

    systems = model.conceptualModel.pipingNetworkSystems if model.conceptualModel else []
    piping_item_count = sum(len(segment.items) for system in systems for segment in system.segments)
    connection_count = sum(len(segment.connections) for system in systems for segment in system.segments)

    if piping_item_count or connection_count:
        logger.warning(
            "DEXPI Proteus XML export uses pydexpi's stock ProteusSerializer, "
            "which only writes taggedPlantItems/metaData -- the piping network "
            f"topology ({piping_item_count} item(s), {connection_count} "
            "connection(s)) is present in model.json/model.graphml but will "
            "not appear in model.xml."
        )

    return DexpiExportSummary(
        json_path=output_dir / f"{filename}.json",
        graphml_path=graphml_path,
        proteus_xml_path=output_dir / f"{filename}.xml",
        piping_item_count=piping_item_count,
        connection_count=connection_count,
    )
