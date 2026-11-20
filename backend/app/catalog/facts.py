"""Factos por candidato, prontos para a política.

O catálogo decide o que é factual; a política decide o que é aceitável para ESTE pedido
(sensibilidade, latência, custo, qualidade).

Motivos que dependem só do catálogo (`disabled`, `pricing_missing`) ficam em `catalog_exclusions`.
Divergências de capacidade (`capability_mismatch`) só excluem quando o pedido exige essa capacidade,
por isso ficam como facto (`probe_mismatches`) e não como exclusão.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.catalog.catalog import Catalog
from app.catalog.history import Outcome, build_stats
from app.catalog.probes import ProbeRegistry


class SamplesSource(Protocol):
    def __call__(self, model: str, task_type: str) -> Iterable[Outcome]: ...


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    model_id: str
    provider: str
    context_window: int
    supports_json_mode: bool
    supports_tools: bool
    allow_sensitive: bool
    price_input_per_mtok: Decimal | None
    price_output_per_mtok: Decimal | None
    p_success: float
    judged: int
    latency_ms: float
    latency_source: str
    probe_mismatches: frozenset[str] = field(default_factory=frozenset)
    catalog_exclusions: tuple[str, ...] = ()


def build_candidates(
    catalog: Catalog,
    *,
    registry: ProbeRegistry,
    samples_for: SamplesSource,
    task_type: str,
    when: date,
    prior_strength: float,
    min_latency_samples: int,
) -> list[CandidateFacts]:
    facts: list[CandidateFacts] = []
    for spec in catalog.models():
        exclusions: list[str] = []
        if not spec.enabled:
            exclusions.append("disabled")
        price = catalog.price(spec.id, when)
        if price is None:
            exclusions.append("pricing_missing")
        stats = build_stats(
            model=spec.id,
            task_type=task_type,
            prior=spec.prior_for(task_type),
            strength=prior_strength,
            samples=samples_for(spec.id, task_type),
            min_latency_samples=min_latency_samples,
            typical_latency_ms=spec.typical_latency_ms,
        )
        facts.append(
            CandidateFacts(
                model_id=spec.id,
                provider=spec.provider,
                context_window=spec.context_window,
                supports_json_mode=spec.supports_json_mode,
                supports_tools=spec.supports_tools,
                allow_sensitive=spec.allow_sensitive,
                price_input_per_mtok=None if price is None else price.input_per_mtok,
                price_output_per_mtok=None if price is None else price.output_per_mtok,
                p_success=stats.p_success,
                judged=stats.judged,
                latency_ms=stats.latency_ms,
                latency_source=stats.latency_source,
                probe_mismatches=registry.mismatches(spec.id),
                catalog_exclusions=tuple(exclusions),
            )
        )
    return facts
