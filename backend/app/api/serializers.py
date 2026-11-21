"""Conversão de resultados internos para JSON. Montantes saem sempre como string decimal em USD."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from app.budget.money import micro_to_usd
from app.routing.decision import CandidateView, Decision
from app.routing.executor import AttemptRecord, ExecutionResult


def usd(micro: int) -> str:
    return str(micro_to_usd(micro))


def _score(value: float | None) -> float | None:
    return None if value is None else round(value, 10)


def candidate_json(view: CandidateView) -> dict[str, Any]:
    return {
        "model": view.model_id,
        "eligible": view.eligible,
        "reasons": list(view.reasons),
        "p_success": round(view.p_success, 4),
        "latency_ms": view.latency_ms,
        "attempt_cost_usd": _score(view.attempt_cost_usd),
        "expected_cost_usd": _score(view.expected_cost_usd),
    }


def decision_json(decision: Decision) -> dict[str, Any]:
    return {
        "mode": decision.mode,
        "reason": decision.reason,
        "chosen": decision.chosen,
        "expected_cost_usd": _score(decision.expected_cost_usd),
        "escalation_chain": list(decision.escalation_chain),
        "conflicts": list(decision.conflicts),
        "candidates": [candidate_json(c) for c in decision.candidates],
    }


def attempt_json(record: AttemptRecord) -> dict[str, Any]:
    return {
        "attempt": record.attempt,
        "model": record.model,
        "status": record.status,
        "reason": record.reason,
        "cost_usd": usd(record.cost_micro),
        "cost_estimated": record.cost_estimated,
        "latency_ms": record.latency_ms,
        "failure_kind": record.failure_kind,
        "tokens_estimated": record.tokens_estimated,
    }


def result_json(result: ExecutionResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "team": result.team,
        "resolved": result.resolved,
        "status": result.status,
        "validated": result.validated,
        "output": result.output,
        "model": result.model,
        "cache": result.cache,
        "stop_reason": result.stop_reason,
        "total_cost_usd": usd(result.total_cost_micro),
        "cost_estimated": result.cost_estimated,
        "attempts": [attempt_json(a) for a in result.attempts],
        "decision": decision_json(result.decision),
    }


def to_jsonable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value
