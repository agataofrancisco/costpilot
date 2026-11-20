from __future__ import annotations

from pathlib import Path

from app.accounting.db import init_schema, make_engine, make_session_factory
from app.accounting.repository import UsageEntry, UsageRepository


def _repo(tmp_path: Path) -> UsageRepository:
    engine = make_engine(f"sqlite:///{(tmp_path / 'usage.db').as_posix()}")
    init_schema(engine)
    return UsageRepository(make_session_factory(engine))


def _entry(**overrides) -> UsageEntry:
    values = {
        "task_id": "t-1",
        "attempt": 1,
        "tenant_id": "default",
        "team": "suporte",
        "task_type": "classification",
        "model": "mock-cheap",
        "provider": "mock",
        "status": "ok",
        "reason": "autopilot",
    }
    values.update(overrides)
    return UsageEntry(**values)


def test_recorded_attempts_are_visible_as_judged_samples(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.record(_entry(status="ok", latency_ms=40.0))
    repo.record(_entry(status="validation_failed", latency_ms=55.0, attempt=2))
    repo.record(_entry(status="provider_error", failure_kind="timeout"))

    samples = repo.judged_samples("mock-cheap", "classification")

    # provider_error não é julgamento de qualidade: não entra no histórico de sucesso.
    assert len(samples) == 2
    assert {s.success for s in samples} == {True, False}


def test_samples_are_filtered_by_model_and_task_type(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.record(_entry(model="mock-cheap", task_type="classification"))
    repo.record(_entry(model="mock-strong", task_type="classification"))
    repo.record(_entry(model="mock-cheap", task_type="doc_qa"))

    assert len(repo.judged_samples("mock-cheap", "classification")) == 1
    assert len(repo.judged_samples("mock-strong", "doc_qa")) == 0
