"""Política pura: decide() e decide_override() com factos sintéticos e custos calculados à mão."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app.catalog.facts import CandidateFacts
from app.routing.config_loader import load_policy
from app.routing.policy import decide, decide_override
from app.routing.task import TaskSpec

PROVIDERS = frozenset({"mock"})


def facts(
    model: str, p: float, price_in: str | None = "0.10", price_out: str | None = "0.40", **kw
):
    base = dict(
        model_id=model,
        provider="mock",
        context_window=32000,
        supports_json_mode=True,
        supports_tools=True,
        allow_sensitive=True,
        price_input_per_mtok=None if price_in is None else Decimal(price_in),
        price_output_per_mtok=None if price_out is None else Decimal(price_out),
        p_success=p,
        judged=0,
        latency_ms=300.0,
        latency_source="typical",
        probe_mismatches=frozenset(),
        catalog_exclusions=(),
    )
    base.update(kw)
    return CandidateFacts(**base)


def task(**kw) -> TaskSpec:
    base = dict(task_type="json_extraction", input_tokens=500, requires_json=True, team="suporte")
    base.update(kw)
    return TaskSpec(**base)


@pytest.fixture
def policy(repo_config_dir: Path):
    return load_policy(repo_config_dir / "policy.yaml")


def _cheap_mid_strong():
    return [
        facts("mock-cheap", 0.8, "0.10", "0.40"),
        facts("mock-mid", 0.9, "0.50", "1.50"),
        facts("mock-strong", 0.97, "3.00", "15.00"),
    ]


def test_short_json_extraction_picks_cheapest_model_that_meets_quality(policy):
    decision = decide(
        task(cost_ceiling_usd=Decimal("0.002")),
        _cheap_mid_strong(),
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )

    assert decision.chosen == "mock-cheap"
    assert decision.reason == "autopilot"
    # E_mid = 4.42e-4 ; E_cheap = 1.012e-4 + (1 - 0.8) * 4.42e-4 = 1.896e-4
    assert decision.expected_cost_usd == pytest.approx(1.896e-4)
    # mock-strong fica fora da cadeia: excedeu o tecto de custo, por isso não pode ser escalado.
    assert decision.escalation_chain == ("mock-cheap", "mock-mid")
    strong = next(c for c in decision.candidates if c.model_id == "mock-strong")
    assert strong.eligible is False
    assert strong.reasons == ("over_cost_ceiling",)


def test_expected_cost_prefers_stronger_model_when_cheap_one_is_unreliable(policy):
    candidates = [
        facts("mock-cheap", 0.8, "0.10", "0.40"),
        facts("mock-mid", 0.99, "0.50", "1.50"),
    ]
    # E_mid = 4.42e-4 ; E_cheap = 1.012e-4 + 0.2 * 4.42e-4 = 1.896e-4 -> cheap continua a ganhar
    decision = decide(
        task(),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.chosen == "mock-cheap"

    # Com p=0.4 o barato é excluído pela qualidade; a decisão tem de ir para o mais forte.
    candidates = [facts("mock-cheap", 0.4, "0.10", "0.40"), facts("mock-mid", 0.99, "0.50", "1.50")]
    decision = decide(
        task(),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.chosen == "mock-mid"
    cheap = next(c for c in decision.candidates if c.model_id == "mock-cheap")
    assert cheap.reasons == ("low_success_rate",)


def test_low_success_rate_excludes_model_below_quality_target(policy):
    candidates = [
        facts("mock-cheap", 0.6),
        facts("mock-mid", 0.75),
        facts("mock-strong", 0.95),
    ]
    decision = decide(
        task(task_type="multi_step_reasoning", requires_json=False),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )

    assert decision.chosen == "mock-strong"
    reasons = {c.model_id: c.reasons for c in decision.candidates}
    assert reasons["mock-cheap"] == ("low_success_rate",)
    assert reasons["mock-mid"] == ("low_success_rate",)


def test_pricing_missing_and_disabled_are_never_chosen(policy):
    candidates = [
        facts("sem-preco", 0.99, None, None, catalog_exclusions=("pricing_missing",)),
        facts("desactivado", 0.99, catalog_exclusions=("disabled",)),
        facts("mock-mid", 0.9),
    ]
    decision = decide(
        task(),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.chosen == "mock-mid"
    reasons = {c.model_id: c.reasons for c in decision.candidates}
    assert reasons["sem-preco"] == ("pricing_missing",)
    assert reasons["desactivado"] == ("disabled",)


def test_capability_mismatch_excludes_only_tasks_that_need_json(policy):
    liar = facts("mock-liar", 0.95, probe_mismatches=frozenset({"json_mode"}))
    json_decision = decide(
        task(),
        [liar],
        policy,
        autopilot_enabled=True,
        fixed_model="mock-liar",
        available_providers=PROVIDERS,
    )
    assert json_decision.chosen is None
    assert json_decision.conflicts == ("mock-liar: capability_mismatch: json_mode",)

    plain = decide(
        task(task_type="classification", requires_json=False, input_tokens=50),
        [liar],
        policy,
        autopilot_enabled=True,
        fixed_model="mock-liar",
        available_providers=PROVIDERS,
    )
    assert plain.chosen == "mock-liar"


def test_declared_no_json_mode_is_excluded_for_json_tasks(policy):
    decision = decide(
        task(),
        [facts("sem-json", 0.95, supports_json_mode=False)],
        policy,
        autopilot_enabled=True,
        fixed_model="sem-json",
        available_providers=PROVIDERS,
    )
    assert decision.conflicts == ("sem-json: no_json_mode",)


def test_high_sensitivity_only_considers_authorized_models(policy):
    candidates = [
        facts("publico", 0.99, "0.01", "0.01", allow_sensitive=False),
        facts("privado", 0.9, "3.00", "15.00", allow_sensitive=True),
    ]
    decision = decide(
        task(sensitivity="high"),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="privado",
        available_providers=PROVIDERS,
    )
    assert decision.chosen == "privado"
    publico = next(c for c in decision.candidates if c.model_id == "publico")
    assert publico.reasons == ("not_authorized_sensitive",)


def test_latency_sla_excludes_slow_models(policy):
    candidates = [facts("lento", 0.95, latency_ms=2000.0), facts("rapido", 0.9, latency_ms=200.0)]
    decision = decide(
        task(latency_sla_ms=500),
        candidates,
        policy,
        autopilot_enabled=True,
        fixed_model="rapido",
        available_providers=PROVIDERS,
    )
    assert decision.chosen == "rapido"
    assert decision.candidates[0].reasons == ("over_latency_sla",)


def test_no_model_meeting_all_constraints_returns_conflicts(policy):
    decision = decide(
        task(cost_ceiling_usd=Decimal("0.0000001")),
        _cheap_mid_strong(),
        policy,
        autopilot_enabled=True,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.chosen is None
    assert all("over_cost_ceiling" in conflict for conflict in decision.conflicts)
    assert len(decision.conflicts) == 3


def test_autopilot_disabled_uses_fixed_model_without_cascade(policy):
    decision = decide(
        task(),
        _cheap_mid_strong(),
        policy,
        autopilot_enabled=False,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.mode == "fixed"
    assert decision.reason == "autopilot_disabled"
    assert decision.chosen == "mock-mid"
    assert decision.escalation_chain == ("mock-mid",)
    assert decision.cascade_allowed is False


def test_fixed_model_that_is_not_eligible_is_reported_not_silently_replaced(policy):
    decision = decide(
        task(),
        [facts("mock-mid", 0.2)],
        policy,
        autopilot_enabled=False,
        fixed_model="mock-mid",
        available_providers=PROVIDERS,
    )
    assert decision.chosen is None
    assert decision.conflicts == ("mock-mid: low_success_rate",)


def test_provider_without_adapter_is_excluded(policy):
    decision = decide(
        task(),
        [facts("mm-model", 0.99, provider="modelmesh")],
        policy,
        autopilot_enabled=True,
        fixed_model="mm-model",
        available_providers=PROVIDERS,
    )
    assert decision.conflicts == ("mm-model: provider_not_configured",)


def test_override_forces_model_without_quality_filter(policy):
    candidates = [facts("mock-cheap", 0.1), facts("mock-strong", 0.99)]
    decision = decide_override(task(), candidates, "mock-cheap", available_providers=PROVIDERS)
    assert decision.mode == "policy_override"
    assert decision.chosen == "mock-cheap"
    assert decision.escalation_chain == ("mock-cheap",)


def test_override_still_refuses_models_without_price(policy):
    candidates = [facts("sem-preco", 0.9, None, None, catalog_exclusions=("pricing_missing",))]
    decision = decide_override(task(), candidates, "sem-preco", available_providers=PROVIDERS)
    assert decision.chosen is None
    assert decision.conflicts == ("sem-preco: pricing_missing",)
