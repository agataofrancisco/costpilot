"""Histórico de sucesso por (modelo, tipo de tarefa) com prior Beta. Funções puras.

Modelo: sucesso ~ Bernoulli(p), com prior p ~ Beta(alpha, beta):
    alpha = k * prior + sucessos
    beta  = k * (1 - prior) + falhas
    p_hat = alpha / (alpha + beta)  (média posterior)

`k` (prior_strength) é a pseudo-contagem: com k=4 e prior=0,9, a prior vale como 4 amostras.
Com poucos dados p_hat fica perto do prior; com muitos dados domina o histórico.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class Outcome(Protocol):
    success: bool
    latency_ms: float


@dataclass(frozen=True, slots=True)
class SuccessStats:
    model: str
    task_type: str
    alpha: float
    beta: float
    judged: int
    successes: int
    latency_ms: float
    latency_source: str  # "observed_p95" | "typical"

    @property
    def p_success(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def beta_posterior(
    prior: float, strength: float, successes: int, failures: int
) -> tuple[float, float]:
    if not 0.0 <= prior <= 1.0:
        raise ValueError("a prior tem de estar em [0, 1]")
    if strength <= 0:
        raise ValueError("prior_strength tem de ser positivo")
    if successes < 0 or failures < 0:
        raise ValueError("contagens negativas não são válidas")
    return strength * prior + successes, strength * (1.0 - prior) + failures


def _usable_latencies(values: Iterable[float]) -> list[float]:
    usable: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if math.isfinite(value) and value >= 0:
            usable.append(float(value))
    return usable


def p95_nearest_rank(values: Iterable[float]) -> float | None:
    usable = sorted(_usable_latencies(values))
    if not usable:
        return None
    rank = math.ceil(0.95 * len(usable))
    return usable[rank - 1]


def build_stats(
    *,
    model: str,
    task_type: str,
    prior: float,
    strength: float,
    samples: Iterable[Outcome],
    min_latency_samples: int,
    typical_latency_ms: float,
) -> SuccessStats:
    rows = list(samples)
    successes = sum(1 for row in rows if row.success)
    failures = len(rows) - successes
    alpha, beta = beta_posterior(prior, strength, successes, failures)
    observed = p95_nearest_rank(row.latency_ms for row in rows if row.success)
    if observed is not None and len(rows) >= min_latency_samples:
        latency, source = observed, "observed_p95"
    else:
        latency, source = typical_latency_ms, "typical"
    return SuccessStats(
        model=model,
        task_type=task_type,
        alpha=alpha,
        beta=beta,
        judged=len(rows),
        successes=successes,
        latency_ms=latency,
        latency_source=source,
    )
