"""Builds and writes the single merged, decorated plant IFC for a project."""

from pathlib import Path
from typing import Sequence

import ifcopenshell
from loguru import logger

from asset_forge.elements.classification import ClassificationStage
from asset_forge.ingestion.federation import federate
from asset_forge.ingestion.loader import PathLike
from asset_forge.pipeline import PlantPipeline


def build_plant(paths: Sequence[PathLike], show_progress: bool = False) -> ifcopenshell.file:
    """Federate `paths` (one project's source .ifc file(s)) into a single
    model and run the classification passthrough/fallback stage over every
    IfcElement. Returns the resulting ifcopenshell.file, ready to write or
    to feed into DEXPI/AAS export.

    This is the extension point the design calls for: additional per-project
    stages (a future dedup/connection-detection pass, a source-specific
    reclassification rule table, ...) plug in here as more Stage instances
    in the list passed to PlantPipeline.run(), without changing this
    function's shape.
    """
    model = federate(paths)

    pipeline = PlantPipeline(model)
    elements = model.by_type("IfcElement")
    accepted = pipeline.run([ClassificationStage()], entities=elements, show_progress=show_progress)
    logger.info(f"classification: processed {len(accepted)}/{len(elements)} element(s)")

    return model


def write_plant(model: ifcopenshell.file, output_path: PathLike) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output_path))
    logger.info(f"wrote {output_path} ({len(list(model))} entities)")
    return output_path
