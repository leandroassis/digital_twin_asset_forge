from asset_forge.exceptions import PipelineExecutionError
from asset_forge.pipeline import PlantPipeline, Record, Stage
import pytest


class FakeModel:
    """Stand-in for ifcopenshell.file: just needs by_type()."""

    def __init__(self, entities):
        self._entities = entities

    def by_type(self, _ifc_class):
        return list(self._entities)


class FakeEntity:
    def __init__(self, ident):
        self._id = ident

    def id(self):
        return self._id


class TagStage(Stage):
    """Writes its own name onto record.data — used to prove data isn't shared."""

    def __init__(self, key, value):
        self.key = key
        self.value = value

    def __call__(self, record: Record) -> bool:
        record[self.key] = self.value
        return True


class RejectEvenStage(Stage):
    def __call__(self, record: Record) -> bool:
        return record.entity.id() % 2 != 0


class BoomStage(Stage):
    def __call__(self, record: Record) -> bool:
        raise ValueError("boom")


def test_record_data_defaults_are_not_shared_between_instances():
    a = Record(model=None, entity=FakeEntity(1))
    b = Record(model=None, entity=FakeEntity(2))

    a["k"] = "from a"

    assert "k" not in b.data
    assert b.data == {}


def test_pipeline_runs_stages_in_order_and_collects_data_per_record():
    model = FakeModel([FakeEntity(1), FakeEntity(2), FakeEntity(3)])
    pipeline = PlantPipeline(model)

    records = pipeline.run([TagStage("seen_by", "stage-a"), TagStage("seen_by_2", "stage-b")])

    assert len(records) == 3
    for record in records:
        assert record["seen_by"] == "stage-a"
        assert record["seen_by_2"] == "stage-b"
    # each record keeps its own dict
    records[0]["only_mine"] = True
    assert "only_mine" not in records[1].data


def test_pipeline_excludes_rejected_records_and_short_circuits_later_stages():
    model = FakeModel([FakeEntity(1), FakeEntity(2), FakeEntity(3), FakeEntity(4)])
    pipeline = PlantPipeline(model)

    seen = []

    class RecordSeen(Stage):
        def __call__(self, record: Record) -> bool:
            seen.append(record.entity.id())
            return True

    records = pipeline.run([RejectEvenStage(), RecordSeen()])

    accepted_ids = [r.entity.id() for r in records]
    assert accepted_ids == [1, 3]
    # RecordSeen never runs for the rejected (even) entities
    assert seen == [1, 3]
    assert pipeline.records == records


def test_pipeline_wraps_stage_exceptions_in_pipeline_execution_error():
    model = FakeModel([FakeEntity(1)])
    pipeline = PlantPipeline(model)

    with pytest.raises(PipelineExecutionError):
        pipeline.run([BoomStage()])


def test_record_reject_via_method_also_excludes_from_results():
    class SelfRejecting(Stage):
        def __call__(self, record: Record) -> bool:
            record.reject()
            return True  # even though it returns truthy, reject() should win

    model = FakeModel([FakeEntity(1)])
    pipeline = PlantPipeline(model)

    records = pipeline.run([SelfRejecting()])

    assert records == []
