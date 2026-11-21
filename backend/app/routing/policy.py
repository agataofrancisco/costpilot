"""Política de routing como função pura (sem I/O).

decide(tarefa, factos, política) -> Decision

1. Filtro duro: capacidades, sensibilidade, contexto, latência, qualidade, tecto de custo, preço,
   provider configurado. Cada exclusão leva um motivo.
2. Custo esperado em cascata, do candidato mais barato para o mais caro (elegíveis apenas):
       E_k = c_k + (1 - p_k) * E_{k+1}      com E_último = c_último
   onde c_k é o custo de uma tentativa e p_k a crença de sucesso.
3. Escolhe o k com menor E_k. A cadeia de escalonamento é o próprio k seguido dos mais caros.

Os scores usam float; os montantes registados são Decimal/micro-USD (ver accounting).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.catalog.facts import CandidateFacts
from app.catalog.pricing import MILLION
from app.routing.config_loader import RoutingPolicy
from app.routing.decision import CandidateView, Decision
from app.routing.task import TaskSpec

EPS = 1e-9

Row = tuple[CandidateFacts, list[str], float | None]


def attempt_cost_usd(facts: CandidateFacts, input_tokens: int, output_tokens: int) -> float | None:
    if facts.price_input_per_mtok is None or facts.price_output_per_mtok is None:
        return None
    total = (
        Decimal(input_tokens) * facts.price_input_per_mtok
        + Decimal(output_tokens) * facts.price_output_per_mtok
    ) / MILLION
    return float(total)


def hard_exclusions(
    task: TaskSpec,
    facts: CandidateFacts,
    *,
    policy: RoutingPolicy,
    output_tokens: int,
    available_providers: frozenset[str],
    attempt_cost: float | None,
) -> list[str]:
    reasons = list(facts.catalog_exclusions)
    if facts.provider not in available_providers:
        reasons.append("provider_not_configured")
    if task.requires_json and not facts.supports_json_mode:
        reasons.append("no_json_mode")
    if task.requires_json and "json_mode" in facts.probe_mismatches:
        reasons.append("capability_mismatch: json_mode")
    if task.requires_tools and not facts.supports_tools:
        reasons.append("no_tools")
    if task.input_tokens + output_tokens > facts.context_window:
        reasons.append("context_too_small")
    if task.sensitivity == "high" and not facts.allow_sensitive:
        reasons.append("not_authorized_sensitive")
    if task.latency_sla_ms is not None and facts.latency_ms > task.latency_sla_ms:
        reasons.append("over_latency_sla")
    if facts.p_success + EPS < policy.quality_targets[task.task_type]:
        reasons.append("low_success_rate")
    if (
        task.cost_ceiling_usd is not None
        and attempt_cost is not None
        and attempt_cost > float(task.cost_ceiling_usd)
    ):
        reasons.append("over_cost_ceiling")
    return reasons


def _conflicts(rows: Sequence[Row]) -> tuple[str, ...]:
    return tuple(
        sorted(f"{facts.model_id}: {reason}" for facts, reasons, _ in rows for reason in reasons)
    )


def _view(row: Row, expected: float | None) -> CandidateView:
    facts, reasons, cost = row
    return CandidateView(
        model_id=facts.model_id,
        eligible=not reasons,
        reasons=tuple(reasons),
        p_success=facts.p_success,
        latency_ms=facts.latency_ms,
        attempt_cost_usd=cost,
        expected_cost_usd=expected if not reasons else None,
    )


def evaluate_rows(
    task: TaskSpec,
    candidates: Sequence[CandidateFacts],
    policy: RoutingPolicy,
    available_providers: frozenset[str],
) -> list[Row]:
    output_tokens = policy.default_output_tokens[task.task_type]
    rows: list[Row] = []
    for facts in candidates:
        cost = attempt_cost_usd(facts, task.input_tokens, output_tokens)
        reasons = hard_exclusions(
            task,
            facts,
            policy=policy,
            output_tokens=output_tokens,
            available_providers=available_providers,
            attempt_cost=cost,
        )
        rows.append((facts, reasons, cost))
    return rows


def decide(
    task: TaskSpec,
    candidates: Sequence[CandidateFacts],
    policy: RoutingPolicy,
    *,
    autopilot_enabled: bool,
    fixed_model: str,
    available_providers: frozenset[str],
) -> Decision:
    rows = evaluate_rows(task, candidates, policy, available_providers)
    if not autopilot_enabled:
        return _fixed_decision(rows, fixed_model)
    return _autopilot_decision(rows)


def _fixed_decision(rows: list[Row], fixed_model: str) -> Decision:
    views = tuple(_view(row, row[2]) for row in rows)
    target = [row for row in rows if row[0].model_id == fixed_model]
    if not target:
        conflicts: tuple[str, ...] = (f"{fixed_model}: modelo fixo fora do catálogo",)
        chosen, expected, chain = None, None, ()
    else:
        facts, reasons, cost = target[0]
        conflicts = _conflicts(target) if reasons else ()
        ok = not reasons and cost is not None
        chosen = fixed_model if ok else None
        expected = cost if ok else None
        chain = (fixed_model,) if ok else ()
    return Decision(
        mode="fixed",
        reason="autopilot_disabled",
        chosen=chosen,
        expected_cost_usd=expected,
        escalation_chain=chain,
        candidates=views,
        conflicts=conflicts,
    )


def _autopilot_decision(rows: list[Row]) -> Decision:
    eligible = [(row[0], row[2]) for row in rows if not row[1] and row[2] is not None]
    if not eligible:
        return Decision(
            mode="autopilot",
            reason="autopilot",
            chosen=None,
            expected_cost_usd=None,
            escalation_chain=(),
            candidates=tuple(_view(row, None) for row in rows),
            conflicts=_conflicts(rows),
        )

    eligible.sort(key=lambda item: (item[1], -item[0].p_success, item[0].model_id))
    expected = [0.0] * len(eligible)
    for index in range(len(eligible) - 1, -1, -1):
        facts, cost = eligible[index]
        if index == len(eligible) - 1:
            expected[index] = cost
        else:
            expected[index] = cost + (1.0 - facts.p_success) * expected[index + 1]

    best = min(
        range(len(eligible)),
        key=lambda i: (expected[i], -eligible[i][0].p_success, eligible[i][0].model_id),
    )
    expected_by_model = {facts.model_id: expected[i] for i, (facts, _) in enumerate(eligible)}
    views = tuple(_view(row, expected_by_model.get(row[0].model_id)) for row in rows)
    return Decision(
        mode="autopilot",
        reason="autopilot",
        chosen=eligible[best][0].model_id,
        expected_cost_usd=expected[best],
        escalation_chain=tuple(facts.model_id for facts, _ in eligible[best:]),
        candidates=views,
    )


def decide_override(
    task: TaskSpec,
    candidates: Sequence[CandidateFacts],
    model: str,
    *,
    available_providers: frozenset[str],
) -> Decision:
    """Baseline fixo (benchmark): força um modelo, sem cascata e sem filtro de qualidade.

    Mantém apenas as exclusões que impedem qualquer execução: modelo desactivado, sem preço
    (o orçamento não se consegue calcular) ou provider não configurado.
    """
    rows: list[Row] = []
    for facts in candidates:
        reasons = [r for r in facts.catalog_exclusions if r in ("disabled", "pricing_missing")]
        if facts.provider not in available_providers:
            reasons.append("provider_not_configured")
        rows.append((facts, reasons, attempt_cost_usd(facts, task.input_tokens, 0)))
    target = [row for row in rows if row[0].model_id == model]
    views = tuple(_view(row, row[2]) for row in rows)
    if not target:
        return Decision(
            mode="policy_override",
            reason="policy_override",
            chosen=None,
            expected_cost_usd=None,
            escalation_chain=(),
            candidates=views,
            conflicts=(f"{model}: modelo fora do catálogo",),
        )
    facts, reasons, cost = target[0]
    if reasons:
        return Decision(
            mode="policy_override",
            reason="policy_override",
            chosen=None,
            expected_cost_usd=None,
            escalation_chain=(),
            candidates=views,
            conflicts=_conflicts(target),
        )
    return Decision(
        mode="policy_override",
        reason="policy_override",
        chosen=model,
        expected_cost_usd=cost,
        escalation_chain=(model,),
        candidates=views,
    )
