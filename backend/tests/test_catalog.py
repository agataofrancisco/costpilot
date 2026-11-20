from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from app.catalog.catalog import Catalog
from app.catalog.models import parse_models
from app.catalog.pricing import ConfigError
from app.catalog.probes import ProbeRegistry, probe_json_mode, run_capability_probes
from app.providers.mock import MockAdapter
from app.providers.openai_compatible import OpenAICompatibleAdapter

from tests.fakes.fake_openai import FakeOpenAIServer


def _model(**overrides) -> dict:
    base = {
        "id": "m-test",
        "provider": "openai_compatible",
        "context_window": 1000,
        "supports_json_mode": True,
        "supports_tools": False,
        "typical_latency_ms": 100,
        "allow_sensitive": False,
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_repository_config_loads_and_real_model_has_no_price(repo_config_dir: Path):
    catalog = Catalog.load(repo_config_dir)

    assert catalog.get("mock-cheap") is not None
    assert catalog.price("mock-cheap", date(2026, 6, 1)) is not None
    # Modelo real sem preço verificado: excluído na política com pricing_missing.
    assert catalog.price("openai/gpt-4o-mini", date(2026, 6, 1)) is None


def test_mock_models_have_profiles_and_prices_for_every_mock_model(repo_config_dir: Path):
    catalog = Catalog.load(repo_config_dir)
    profiles = catalog.mock_profiles()

    assert set(profiles) == {"mock-cheap", "mock-mid", "mock-strong", "mock-liar"}
    for model_id in profiles:
        assert catalog.price(model_id, date(2026, 6, 1)) is not None, model_id


def test_unknown_provider_is_rejected():
    with pytest.raises(ConfigError, match="provider desconhecido"):
        parse_models({"models": [_model(provider="azure")]})


def test_duplicate_model_ids_are_rejected():
    with pytest.raises(ConfigError, match="duplicado"):
        parse_models({"models": [_model(), _model()]})


def test_mock_provider_requires_a_profile():
    with pytest.raises(ConfigError, match="exige o bloco 'mock'"):
        parse_models({"models": [_model(provider="mock")]})


@pytest.mark.parametrize(
    "bad",
    [
        {"context_window": True},
        {"context_window": "1000"},
        {"typical_latency_ms": -1},
        {"prior_success": {"classification": 1.5}},
        {"prior_success": {"tarefa-inventada": 0.5}},
        {"supports_json_mode": "sim"},
        {"id": "com espaços"},
    ],
)
def test_invalid_model_fields_fail_at_load_time(bad):
    with pytest.raises(ConfigError):
        parse_models({"models": [_model(**bad)]})


def test_ensure_known_rejects_models_missing_from_catalog(repo_config_dir: Path):
    catalog = Catalog.load(repo_config_dir)
    with pytest.raises(ConfigError, match="desconhecidos"):
        catalog.ensure_known(["mock-cheap", "modelo-fantasma"])


def test_honest_mock_passes_json_probe_and_liar_is_flagged(repo_config_dir: Path):
    catalog = Catalog.load(repo_config_dir)
    adapter = MockAdapter(catalog.mock_profiles(), seed=1)
    registry = ProbeRegistry()

    asyncio.run(run_capability_probes(catalog, {"mock": adapter}, registry))

    assert registry.mismatches("mock-cheap") == frozenset()
    assert registry.mismatches("mock-liar") == frozenset({"json_mode"})


def test_probe_against_real_protocol_detects_false_json_claim(fake_openai: FakeOpenAIServer):
    adapter = OpenAICompatibleAdapter(
        name="openai_compatible", base_url=fake_openai.base_url, api_key=None, timeout_seconds=5
    )

    async def run():
        try:
            honest = await probe_json_mode(adapter, "jsonok")
            liar = await probe_json_mode(adapter, "jsonlie")
            broken = await probe_json_mode(adapter, "badjson")
            return honest, liar, broken
        finally:
            await adapter.aclose()

    honest, liar, broken = asyncio.run(run())

    assert honest.ok is True
    assert liar.ok is False and liar.detail == "resposta não é JSON"
    # Falha do provider durante a sonda: indeterminado, não é divergência.
    assert broken.ok is None


def test_indeterminate_probe_is_not_a_mismatch():
    registry = ProbeRegistry()
    from app.catalog.probes import ProbeOutcome

    registry.record(ProbeOutcome("m", "json_mode", None, "indeterminado: timeout"))

    assert registry.mismatches("m") == frozenset()
