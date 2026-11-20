"""Sondas de capacidade: verificam que um modelo declarado com JSON mode o cumpre de facto.

Uma sonda barata (um pedido de poucos tokens) não prova capacidade geral, mas apanha o caso
perigoso: capacidade declarada que não existe. O resultado vai para um registo em memória.

Resultado `ok=None` significa indeterminado (falha do provider durante a sonda). Não conta como
divergência, mas também não confirma a capacidade, e a sonda deve ser repetida.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from app.catalog.catalog import Catalog
from app.providers.base import ChatRequest, ProviderAdapter, ProviderFailure

JSON_CAPABILITY = "json_mode"
PROBE_MESSAGES = [{"role": "user", "content": 'Responde apenas com o JSON {"ok": true}.'}]


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    model: str
    capability: str
    ok: bool | None
    detail: str


class ProbeRegistry:
    def __init__(self) -> None:
        self._outcomes: dict[str, dict[str, ProbeOutcome]] = {}

    def record(self, outcome: ProbeOutcome) -> None:
        self._outcomes.setdefault(outcome.model, {})[outcome.capability] = outcome

    def mismatches(self, model: str) -> frozenset[str]:
        """Capacidades que a sonda desmentiu (ok is False). Indeterminado não entra aqui."""
        found = self._outcomes.get(model, {})
        return frozenset(cap for cap, outcome in found.items() if outcome.ok is False)

    def outcomes(self) -> list[ProbeOutcome]:
        return [o for per_model in self._outcomes.values() for o in per_model.values()]


async def probe_json_mode(adapter: ProviderAdapter, model: str) -> ProbeOutcome:
    request = ChatRequest(
        model=model,
        messages=PROBE_MESSAGES,
        temperature=0.0,
        max_tokens=32,
        json_mode=True,
        task_type="probe",
    )
    result = await adapter.chat(request)
    if isinstance(result, ProviderFailure):
        return ProbeOutcome(model, JSON_CAPABILITY, None, f"indeterminado: {result.kind}")
    try:
        parsed: object = json.loads(result.text)
    except ValueError:
        return ProbeOutcome(model, JSON_CAPABILITY, False, "resposta não é JSON")
    if not isinstance(parsed, dict):
        return ProbeOutcome(model, JSON_CAPABILITY, False, "JSON não é um objecto")
    return ProbeOutcome(model, JSON_CAPABILITY, True, "ok")


async def run_capability_probes(
    catalog: Catalog,
    adapters: Mapping[str, ProviderAdapter],
    registry: ProbeRegistry,
    only_providers: frozenset[str] | None = None,
) -> list[ProbeOutcome]:
    """Corre a sonda de JSON para os modelos que a declaram. Adaptadores em falta são ignorados."""
    results: list[ProbeOutcome] = []
    for spec in catalog.models():
        if not spec.supports_json_mode or not spec.enabled:
            continue
        if only_providers is not None and spec.provider not in only_providers:
            continue
        adapter = adapters.get(spec.provider)
        if adapter is None:
            continue
        outcome = await probe_json_mode(adapter, spec.id)
        registry.record(outcome)
        results.append(outcome)
    return results
