"""Core per-element pipeline abstractions.

Deliberately independent of ifcopenshell at import time (`model`/`entity` are
typed `Any`) so pipeline logic can be unit-tested with plain Python objects.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Record:
    """Carrier for one element as it moves through a pipeline run.

    `data` must never default to a shared mutable object: each Record gets
    its own dict, created fresh in `__init__`. A `data: Dict = {}` default
    argument would silently share one dict across every Record built without
    an explicit `data=`, which is every Record a PlantPipeline creates.
    """

    def __init__(
        self,
        model: Any,
        entity: Any,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.model = model
        self.entity = entity
        self.data: Dict[str, Any] = data if data is not None else {}
        self._accepted = True

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def reject(self) -> None:
        """Mark this record as rejected: excluded from the run's accepted results."""
        self._accepted = False

    @property
    def accepted(self) -> bool:
        return self._accepted


class Stage(ABC):
    """One step of a pipeline, processing a single Record at a time."""

    @abstractmethod
    def __call__(self, record: Record) -> bool:
        """Process `record` in place. Return False to reject it, which stops
        the pipeline for this element and excludes it from the accepted
        results of the current run."""
        raise NotImplementedError
