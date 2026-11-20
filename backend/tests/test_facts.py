from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.catalog.catalog import Catalog
from app.catalog.facts import build_candidates
from app.catalog.probes import ProbeRegistry, run_capability_probes
from app.providers.mock import MockAdapter


def _facts(repo_config_dir: Path, registry: ProbeRegistry, samples=None):
    catalog = Catalog.load(repo_config_dir)
    return {
        f.model_id: f
        for f in build_candidates(
            catalog,
            registry=registry,
            samples_for=samples or (lambda model, task: []),
            task_type="json_extraction",
            when=date(2026, 6, 1),
            prior_strength=4.0,
            min_latency_samples=5,
        )
    }


def test_real_model_without_price_carries_pricing_missing(repo_config_dir: Path):
    facts = _facts(repo_config_dir, ProbeRegistry())

    assert "pricing_missing" in facts["openai/gpt-4o-mini"].catalog_exclusions
    assert facts["openai/gpt-4o-mini"].price_input_per_mtok is None
    assert facts["mock-cheap"].catalog_exclusions == ()


def test_price_in_force_is_attached_to_each_candidate(repo_config_dir: Path):
    facts = _facts(repo_config_dir, ProbeRegistry())

    assert facts["mock-cheap"].price_input_per_mtok == Decimal("0.10")
    assert facts["mock-strong"].price_output_per_mtok == Decimal("15")


def test_probe_mismatch_is_a_fact_not_a_global_exclusion(repo_config_dir: Path):
    catalog = Catalog.load(repo_config_dir)
    registry = ProbeRegistry()
    adapter = MockAdapter(catalog.mock_profiles(), seed=1)
    asyncio.run(run_capability_probes(catalog, {"mock": adapter}, registry))

    facts = _facts(repo_config_dir, registry)

    assert facts["mock-liar"].probe_mismatches == frozenset({"json_mode"})
    # Não é exclusão global: a política só exclui se o pedido exigir JSON.
    assert facts["mock-liar"].catalog_exclusions == ()


def test_latency_source_reports_typical_before_observations(repo_config_dir: Path):
    facts = _facts(repo_config_dir, ProbeRegistry())

    assert facts["mock-mid"].latency_source == "typical"
    assert facts["mock-mid"].latency_ms == 800.0
