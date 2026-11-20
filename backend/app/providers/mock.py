"""Provider mock com perfis de qualidade e de falhas (simulação, nunca dados reais).

Cada decisão do mock é determinística: depende de (seed, modelo, task_id, tentativa, mensagens),
por isso o mesmo benchmark reproduz os mesmos números. Os resultados que usam este mock
são sempre marcados como `simulated` nos relatórios.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from app.providers.base import (
    ChatRequest,
    ChatResponse,
    FailureKind,
    ProviderFailure,
    ProviderResult,
    Usage,
)

Oracle = Callable[[ChatRequest], str | None]


@dataclass(frozen=True, slots=True)
class MockProfile:
    quality: Mapping[str, float] = field(default_factory=dict)
    failure_rate: float = 0.0
    latency_ms: float = 50.0
    json_mode_honest: bool = True
    reports_usage: bool = True


class MockAdapter:
    name = "mock"

    def __init__(
        self,
        profiles: Mapping[str, MockProfile],
        *,
        seed: int,
        oracle: Oracle | None = None,
    ) -> None:
        self._profiles = dict(profiles)
        self._seed = seed
        self._oracle = oracle

    async def chat(self, request: ChatRequest) -> ProviderResult:
        profile = self._profiles.get(request.model)
        if profile is None:
            return ProviderFailure(FailureKind.MODEL_NOT_FOUND, "modelo mock desconhecido")
        fail_draw, kind_draw, quality_draw = self._draws(request)
        if fail_draw < profile.failure_rate:
            kind = FailureKind.TIMEOUT if kind_draw < 0.5 else FailureKind.UPSTREAM_ERROR
            return ProviderFailure(kind, "falha simulada do mock", profile.latency_ms)
        correct = quality_draw < profile.quality.get(request.task_type, 0.0)
        text = self._answer(request, profile, correct)
        usage = _estimated_usage(request, text, profile.reports_usage)
        return ChatResponse(
            model=request.model,
            provider=self.name,
            text=text,
            usage=usage,
            latency_ms=profile.latency_ms,
            reported_model=request.model,
        )

    def _answer(self, request: ChatRequest, profile: MockProfile, correct: bool) -> str:
        if request.json_mode and not profile.json_mode_honest:
            return "Aqui está o resultado: {nao-e-json"
        if not correct:
            return (
                '{"erro": "resposta incorrecta simulada"'
                if request.json_mode
                else "RESPOSTA_ERRADA"
            )
        if self._oracle is not None:
            expected = self._oracle(request)
            if expected is not None:
                return expected
        return '{"ok": true}' if request.json_mode else "OK"

    def _draws(self, request: ChatRequest) -> tuple[float, float, float]:
        material = json.dumps(
            [self._seed, request.model, request.task_id, request.attempt, request.messages],
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        values = [int.from_bytes(digest[i * 8 : (i + 1) * 8], "big") / 2**64 for i in range(3)]
        return values[0], values[1], values[2]


def _estimated_usage(request: ChatRequest, text: str, reports_usage: bool) -> Usage:
    if not reports_usage:
        return Usage(input_tokens=0, output_tokens=0, reported=False)
    prompt_chars = sum(len(m.get("content", "")) for m in request.messages)
    return Usage(
        input_tokens=math.ceil(prompt_chars / 4),
        output_tokens=math.ceil(len(text) / 4),
        reported=True,
    )
