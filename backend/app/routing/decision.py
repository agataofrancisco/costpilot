"""Tipos de saída da decisão. Imutáveis: o que a política decidiu é o que fica registado."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CandidateView:
    model_id: str
    eligible: bool
    reasons: tuple[str, ...]
    p_success: float
    latency_ms: float
    attempt_cost_usd: float | None
    expected_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class Decision:
    mode: str  # autopilot | fixed | policy_override
    reason: str  # autopilot | autopilot_disabled | policy_override
    chosen: str | None
    expected_cost_usd: float | None
    escalation_chain: tuple[str, ...]
    candidates: tuple[CandidateView, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cascade_allowed(self) -> bool:
        return self.mode == "autopilot"
