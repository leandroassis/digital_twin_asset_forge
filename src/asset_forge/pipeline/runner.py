"""PlantPipeline: runs a list of Stages over every entity of an IFC model."""

from typing import Any, Iterable, List, Optional

from loguru import logger

from asset_forge.exceptions import PipelineExecutionError
from asset_forge.pipeline.stage import Record, Stage


class PlantPipeline:
    """Owns an opened ifcopenshell.file and drives Stage objects over it.

    A run() call builds one fresh Record per entity and pushes it through
    every stage in order; the first stage that returns False (or that calls
    record.reject()) stops the chain for that entity and excludes it from
    the accepted results. Records from the most recent run() are kept on
    `self.records` as the join point later pipeline phases (linking, export)
    read from.
    """

    def __init__(self, model: Any) -> None:
        self.model = model
        self._records: List[Record] = []

    @property
    def records(self) -> List[Record]:
        return list(self._records)

    def run(
        self,
        stages: List[Stage],
        entities: Optional[Iterable[Any]] = None,
        show_progress: bool = False,
    ) -> List[Record]:
        entities = list(entities) if entities is not None else self.model.by_type("IfcRoot")

        iterator: Iterable[Any] = entities
        if show_progress:
            from rich.progress import track

            iterator = track(entities, description="Processing elements")

        accepted: List[Record] = []
        for entity in iterator:
            record = Record(model=self.model, entity=entity)
            kept = True
            for stage in stages:
                try:
                    kept = stage(record)
                except Exception as exc:
                    raise PipelineExecutionError(
                        f"stage {type(stage).__name__} failed on entity "
                        f"#{getattr(entity, 'id', lambda: entity)()}: {exc}"
                    ) from exc
                if not kept or not record.accepted:
                    kept = False
                    break
            if kept:
                accepted.append(record)

        logger.debug(f"PlantPipeline.run: {len(accepted)}/{len(entities)} entities accepted")
        self._records = accepted
        return accepted
