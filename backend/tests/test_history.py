from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from app.accounting.db import init_schema, make_engine, make_session_factory
from app.accounting.repository import UsageEntry, UsageRepository
from app.catalog.history import beta_posterior, build_stats, p95_nearest_rank


@dataclass(frozen=True)
class Row:
    success: bool
    latency_ms: float


def _stats(rows, prior=0.9, strength=4.0, min_samples=5, typical=300.0):
    return build_stats(
        model="m",
        task_type="classification",
        prior=prior,
        strength=strength,
        samples=rows,
        min_latency_samples=min_samples,
        typical_latency_ms=typical,
    )


def test_without_data_the_estimate_is_the_prior():
    stats = _stats([])

    assert stats.p_success == pytest.approx(0.9)
    assert stats.latency_source == "typical"


def test_failures_lower_the_estimate_below_a_quality_target():
    rows = [Row(success=False, latency_ms=100.0) for _ in range(10)]

    stats = _stats(rows, prior=0.9, strength=4.0)

    # alpha = 4*0.9 = 3.6 ; beta = 4*0.1 + 10 = 10.4  ->  p = 3.6 / 14 ~ 0.257
    assert stats.alpha == pytest.approx(3.6)
    assert stats.beta == pytest.approx(10.4)
    assert stats.p_success == pytest.approx(3.6 / 14.0)
    assert stats.p_success < 0.85


def test_successes_raise_the_estimate_and_prior_weight_is_small():
    rows = [Row(success=True, latency_ms=50.0) for _ in range(40)]

    stats = _stats(rows, prior=0.5, strength=4.0)

    assert stats.p_success > 0.95


def test_latency_switches_to_observed_p95_after_enough_samples():
    rows = [Row(True, float(v)) for v in range(1, 11)]  # 10 amostras, 1..10 ms

    stats = _stats(rows, min_samples=5, typical=300.0)

    assert stats.latency_source == "observed_p95"
    assert stats.latency_ms == 10.0  # nearest-rank: ceil(0.95*10)=10


def test_latency_falls_back_to_typical_with_few_samples():
    stats = _stats([Row(True, 12.0), Row(True, 14.0)], min_samples=5, typical=300.0)

    assert stats.latency_source == "typical"
    assert stats.latency_ms == 300.0


def test_p95_ignores_non_numeric_latencies_defensively():
    values = [10.0, None, "20", True, float("nan"), -5.0, 30.0]  # type: ignore[list-item]

    assert p95_nearest_rank(values) == 30.0  # type: ignore[arg-type]
    assert p95_nearest_rank([]) is None


def test_p95_nearest_rank_on_one_hundred_values():
    assert p95_nearest_rank(float(v) for v in range(1, 101)) == 95.0


@pytest.mark.parametrize(("prior", "strength"), [(1.2, 4.0), (-0.1, 4.0), (0.5, 0.0)])
def test_invalid_prior_parameters_are_rejected(prior, strength):
    with pytest.raises(ValueError):
        beta_posterior(prior, strength, 0, 0)


def test_history_is_updated_from_the_usage_ledger(tmp_path: Path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'hist.db').as_posix()}")
    init_schema(engine)
    repo = UsageRepository(make_session_factory(engine))
    base = dict(
        tenant_id="default",
        team="suporte",
        task_type="classification",
        model="mock-cheap",
        provider="mock",
        reason="autopilot",
    )
    for index in range(6):
        repo.record(
            UsageEntry(task_id=f"ok-{index}", attempt=1, status="ok", latency_ms=40.0, **base)
        )
    for index in range(4):
        repo.record(
            UsageEntry(
                task_id=f"bad-{index}",
                attempt=1,
                status="validation_failed",
                latency_ms=55.0,
                **base,
            )
        )

    samples = repo.judged_samples("mock-cheap", "classification")
    stats = build_stats(
        model="mock-cheap",
        task_type="classification",
        prior=0.9,
        strength=4.0,
        samples=samples,
        min_latency_samples=5,
        typical_latency_ms=300.0,
    )

    assert stats.judged == 10
    assert stats.successes == 6
    # alpha = 3.6 + 6 = 9.6 ; beta = 0.4 + 4 = 4.4 -> p = 9.6 / 14
    assert stats.p_success == pytest.approx(9.6 / 14.0)
    assert stats.latency_source == "observed_p95"
