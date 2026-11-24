"""Execução em cascata com orçamento por tentativa e contabilidade completa.

Para cada tentativa: reserva atómica do pior caso -> chamada ao provider -> reconciliação com o
custo real -> validação programática. Se a validação falha e a política permite, escala para o
modelo seguinte da cadeia. O custo de todas as tentativas é registado e conta para o orçamento.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.accounting.repository import UsageEntry, UsageRepository
from app.budget.money import usd_to_micro_ceil
from app.budget.store import BudgetStore
from app.cache.eligibility import cache_eligibility
from app.cache.keys import cache_key as build_cache_key
from app.cache.store import ResponseCache
from app.catalog.pricing import cost_usd
from app.config import Settings
from app.providers.base import (
    ChatRequest,
    ChatResponse,
    FailureKind,
    ProviderAdapter,
    ProviderFailure,
    Usage,
)
from app.routing.accounting_rules import (
    estimate_tokens,
    failure_charge_micro,
    prompt_chars,
    worst_case_micro,
)
from app.routing.decision import Decision
from app.routing.errors import (
    BudgetExceeded,
    NoEligibleModel,
    PolicyOverrideDisabled,
    ToolsNotSupported,
    UpstreamUnavailable,
)
from app.routing.router import Router
from app.routing.task import TaskSpec
from app.routing.validators import ValidationSpec, validate_output

MessageDict = dict[str, str]


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt: int
    model: str
    status: str
    reason: str
    cost_micro: int
    cost_estimated: bool
    latency_ms: float
    failure_kind: str | None
    tokens_estimated: bool


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    task_id: str
    team: str
    resolved: bool
    status: str  # ok | validation_failed | cache_hit
    validated: bool
    output: str | None
    model: str | None
    decision: Decision
    attempts: tuple[AttemptRecord, ...]
    total_cost_micro: int
    cost_estimated: bool
    cache: str  # hit | miss | not_eligible
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Outcome:
    record: AttemptRecord
    text: str | None
    ok: bool


def attempt_to_dict(record: AttemptRecord) -> dict[str, Any]:
    return asdict(record)


@dataclass(frozen=True, slots=True)
class ExecuteCall:
    task: TaskSpec
    messages: list[MessageDict]
    temperature: float
    max_output_tokens: int | None
    cache_requested: bool
    task_id: str | None
    validation: ValidationSpec | None
    model_override: str | None


class Executor:
    def __init__(
        self,
        *,
        router: Router,
        adapters: Mapping[str, ProviderAdapter],
        budget: BudgetStore,
        usage: UsageRepository,
        cache: ResponseCache,
        settings: Settings,
        clock: Callable[[], datetime],
    ) -> None:
        self._router = router
        self._adapters = dict(adapters)
        self._budget = budget
        self._usage = usage
        self._cache = cache
        self._settings = settings
        self._clock = clock

    async def execute(self, call: ExecuteCall, *, allow_override: bool) -> ExecutionResult:
        task = call.task
        if task.requires_tools:
            raise ToolsNotSupported("ferramentas ainda não são executadas por /execute")
        if call.model_override is not None and not allow_override:
            raise PolicyOverrideDisabled("policy_override desactivado nesta instância")

        when = self._clock()
        team = self._router.team(task.team)
        if call.model_override is not None:
            decision = self._router.override(task, when, call.model_override)
        else:
            decision = self._router.route(task, when)
        if decision.chosen is None:
            raise NoEligibleModel(
                "nenhum modelo cumpre as restrições",
                conflicts=list(decision.conflicts),
                mode=decision.mode,
            )

        chain = decision.escalation_chain
        if decision.cascade_allowed:
            chain = chain[: self._router.policy.max_attempts]
        max_out = call.max_output_tokens or self._settings.default_max_output_tokens
        task_id = call.task_id or uuid4().hex
        reservation_scope = uuid4().hex

        eligibility = cache_eligibility(
            requested=call.cache_requested,
            temperature=call.temperature,
            requires_tools=task.requires_tools,
            sensitivity=task.sensitivity,
        )
        entry_key: str | None = None
        if eligibility.eligible:
            entry_key = build_cache_key(
                tenant_id=task.tenant_id,
                team=task.team,
                model=chain[0],
                temperature=call.temperature,
                max_tokens=max_out,
                json_mode=task.requires_json,
                messages=call.messages,
            )
            hit = self._cache_hit(entry_key, task, task_id, decision)
            if hit is not None:
                return hit

        return await self._run_chain(
            call=call,
            chain=chain,
            decision=decision,
            team_name=team.name,
            limit_micro=team.budget_micro,
            max_out=max_out,
            task_id=task_id,
            reservation_scope=reservation_scope,
            when=when,
            entry_key=entry_key,
            cache_state="miss" if entry_key else "not_eligible",
        )

    def _cache_hit(
        self, entry_key: str, task: TaskSpec, task_id: str, decision: Decision
    ) -> ExecutionResult | None:
        raw = self._cache.get(entry_key)
        if raw is None:
            return None
        try:
            stored: object = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(stored, dict) or not isinstance(stored.get("output"), str):
            return None
        model = stored.get("model") if isinstance(stored.get("model"), str) else None
        self._usage.record(
            UsageEntry(
                task_id=task_id,
                attempt=0,
                tenant_id=task.tenant_id,
                team=task.team,
                task_type=task.task_type,
                model=model or decision.chosen or "",
                provider="cache",
                status="cache_hit",
                reason="cache_hit",
            )
        )
        return ExecutionResult(
            task_id=task_id,
            team=task.team,
            resolved=True,
            status="cache_hit",
            validated=True,
            output=stored["output"],
            model=model,
            decision=decision,
            attempts=(),
            total_cost_micro=0,
            cost_estimated=False,
            cache="hit",
        )

    async def _run_chain(
        self,
        *,
        call: ExecuteCall,
        chain: tuple[str, ...],
        decision: Decision,
        team_name: str,
        limit_micro: int,
        max_out: int,
        task_id: str,
        reservation_scope: str,
        when: datetime,
        entry_key: str | None,
        cache_state: str,
    ) -> ExecutionResult:
        task = call.task
        attempts: list[AttemptRecord] = []
        output: str | None = None
        total_micro = 0
        estimated_any = False
        stop_reason: str | None = None
        last_model: str | None = None
        for index, model in enumerate(chain, start=1):
            if index > 1 and self._over_request_ceiling(task, attempts, model, when, max_out):
                stop_reason = "over_cost_ceiling"
                break
            try:
                outcome = await self._attempt(
                    call=call,
                    team_name=team_name,
                    limit_micro=limit_micro,
                    model=model,
                    index=index,
                    reason=_reason(decision, index),
                    max_out=max_out,
                    task_id=task_id,
                    reservation_scope=reservation_scope,
                    when=when,
                )
            except BudgetExceeded as error:
                error.details["attempts"] = tuple(attempts)
                raise
            attempts.append(outcome.record)
            total_micro += outcome.record.cost_micro
            estimated_any = estimated_any or outcome.record.cost_estimated
            if outcome.text is not None:
                output = outcome.text
            if outcome.ok:
                if entry_key is not None:
                    self._store_cache(entry_key, outcome.text or "", model)
                return ExecutionResult(
                    task_id=task_id,
                    team=task.team,
                    resolved=True,
                    status="ok",
                    validated=call.validation is not None,
                    output=output,
                    model=model,
                    decision=decision,
                    attempts=tuple(attempts),
                    total_cost_micro=total_micro,
                    cost_estimated=estimated_any,
                    cache=cache_state,
                )
            last_model = model

        if output is None:
            raise UpstreamUnavailable(
                "nenhum provider respondeu", attempts=tuple(attempts), task_id=task_id
            )
        return ExecutionResult(
            task_id=task_id,
            team=task.team,
            resolved=False,
            status="validation_failed",
            validated=False,
            output=output,
            model=last_model,
            decision=decision,
            attempts=tuple(attempts),
            total_cost_micro=total_micro,
            cost_estimated=estimated_any,
            cache=cache_state,
            stop_reason=stop_reason,
        )

    def _over_request_ceiling(
        self,
        task: TaskSpec,
        attempts: list[AttemptRecord],
        model: str,
        when: datetime,
        max_out: int,
    ) -> bool:
        """Escalar não pode ultrapassar o tecto de custo pedido (pior caso da próxima tentativa)."""
        if task.cost_ceiling_usd is None:
            return False
        price = self._router.catalog.price(model, when.date())
        if price is None:
            return True
        spent = sum(a.cost_micro for a in attempts)
        next_worst = worst_case_micro(price, task.input_tokens, max_out)
        return spent + next_worst > usd_to_micro_ceil(task.cost_ceiling_usd)

    async def _attempt(
        self,
        *,
        call: ExecuteCall,
        team_name: str,
        limit_micro: int,
        model: str,
        index: int,
        reason: str,
        max_out: int,
        task_id: str,
        reservation_scope: str,
        when: datetime,
    ) -> _Outcome:
        task = call.task
        catalog = self._router.catalog
        spec = catalog.get(model)
        price = catalog.price(model, when.date())
        if spec is None or price is None:
            raise NoEligibleModel(f"{model}: sem preço ou fora do catálogo", conflicts=[model])

        chars = prompt_chars(call.messages)
        reserve_micro = worst_case_micro(
            price, max(task.input_tokens, estimate_tokens(chars)), max_out
        )
        reservation = f"{reservation_scope}:{index}"
        outcome = self._budget.reserve(
            team_name,
            reservation,
            reserve_micro,
            limit_micro,
            int(when.timestamp() * 1000),
            self._settings.reservation_ttl_seconds * 1000,
        )
        if not outcome.accepted:
            self._record(
                task=task,
                task_id=task_id,
                index=index,
                model=model,
                provider=spec.provider,
                status="budget_rejected",
                reason="budget_exceeded",
                cost_micro=0,
                cost_estimated=False,
                latency_ms=0.0,
                tokens_estimated=False,
                model_mismatch=False,
            )
            raise BudgetExceeded(
                "orçamento da equipa esgotado",
                team=team_name,
                spent_micro=outcome.spent_micro,
                reserved_micro=outcome.reserved_micro,
                budget_micro=limit_micro,
                attempt_reserved_micro=reserve_micro,
                attempts=(),
            )

        result = await self._call_provider(call, spec.provider, model, max_out, task_id, index)
        if isinstance(result, ProviderFailure):
            charged = failure_charge_micro(result.kind, reserve_micro)
            self._budget.reconcile(team_name, reservation, charged)
            record = self._record(
                task=task,
                task_id=task_id,
                index=index,
                model=model,
                provider=spec.provider,
                status="provider_error",
                reason=reason,
                failure_kind=result.kind.value,
                cost_micro=charged,
                cost_estimated=charged > 0,
                latency_ms=result.latency_ms,
                tokens_estimated=False,
                model_mismatch=False,
            )
            return _Outcome(record, None, False)

        billed = _billed_usage(result, chars)
        tokens_estimated = not result.usage.reported
        actual_micro = usd_to_micro_ceil(cost_usd(price, billed))
        self._budget.reconcile(team_name, reservation, actual_micro)
        verdict = validate_output(task.task_type, result.text, call.validation)
        record = self._record(
            task=task,
            task_id=task_id,
            index=index,
            model=model,
            provider=spec.provider,
            status="ok" if verdict.ok else "validation_failed",
            reason=reason,
            cost_micro=actual_micro,
            cost_estimated=tokens_estimated,
            latency_ms=result.latency_ms,
            tokens_estimated=tokens_estimated,
            model_mismatch=result.model_mismatch,
            usage=billed,
        )
        return _Outcome(record, result.text, verdict.ok)

    async def _call_provider(
        self,
        call: ExecuteCall,
        provider: str,
        model: str,
        max_out: int,
        task_id: str,
        index: int,
    ) -> ChatResponse | ProviderFailure:
        adapter = self._adapters.get(provider)
        if adapter is None:
            return ProviderFailure(FailureKind.UNAVAILABLE, "provider não configurado")
        return await adapter.chat(
            ChatRequest(
                model=model,
                messages=call.messages,
                temperature=call.temperature,
                max_tokens=max_out,
                json_mode=call.task.requires_json,
                task_id=task_id,
                task_type=call.task.task_type,
                attempt=index,
            )
        )

    def _record(
        self,
        *,
        task: TaskSpec,
        task_id: str,
        index: int,
        model: str,
        provider: str,
        status: str,
        reason: str,
        cost_micro: int,
        cost_estimated: bool,
        latency_ms: float,
        tokens_estimated: bool,
        model_mismatch: bool,
        failure_kind: str | None = None,
        usage: Usage | None = None,
    ) -> AttemptRecord:
        tokens = usage or Usage(input_tokens=0, output_tokens=0, reported=False)
        self._usage.record(
            UsageEntry(
                task_id=task_id,
                attempt=index,
                tenant_id=task.tenant_id,
                team=task.team,
                task_type=task.task_type,
                model=model,
                provider=provider,
                status=status,
                reason=reason,
                failure_kind=failure_kind,
                input_tokens=tokens.input_tokens,
                output_tokens=tokens.output_tokens,
                reasoning_tokens=tokens.reasoning_tokens,
                cached_tokens=tokens.cached_tokens,
                tokens_estimated=tokens_estimated,
                cost_micro_usd=cost_micro,
                cost_estimated=cost_estimated,
                latency_ms=latency_ms,
                model_mismatch=model_mismatch,
            )
        )
        return AttemptRecord(
            attempt=index,
            model=model,
            status=status,
            reason=reason,
            cost_micro=cost_micro,
            cost_estimated=cost_estimated,
            latency_ms=latency_ms,
            failure_kind=failure_kind,
            tokens_estimated=tokens_estimated,
        )

    def _store_cache(self, entry_key: str, output: str, model: str) -> None:
        payload = json.dumps({"output": output, "model": model}, ensure_ascii=False)
        self._cache.set(entry_key, payload, self._settings.cache_ttl_seconds)


def _reason(decision: Decision, index: int) -> str:
    if decision.mode == "policy_override":
        return "policy_override"
    if decision.mode == "fixed":
        return "autopilot_disabled"
    return "autopilot" if index == 1 else "escalation"


def _billed_usage(result: ChatResponse, prompt_char_count: int) -> Usage:
    """Usa os tokens reportados; se faltarem, estima por caracteres (marcado como estimado)."""
    if result.usage.reported:
        return result.usage
    return Usage(
        input_tokens=estimate_tokens(prompt_char_count),
        output_tokens=estimate_tokens(len(result.text)),
        reported=False,
    )
