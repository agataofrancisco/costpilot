from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from app.catalog.pricing import ConfigError, PriceTable, cost_usd, parse_price_rows
from app.providers.base import ChatRequest, ChatResponse, FailureKind, ProviderFailure, Usage
from app.providers.mock import MockAdapter, MockProfile


def _mock(profile: MockProfile, seed: int = 1, oracle=None) -> MockAdapter:
    return MockAdapter({"m": profile}, seed=seed, oracle=oracle)


def _req(task_id: str = "t1", task_type: str = "classification", attempt: int = 1, json_mode=False):
    return ChatRequest(
        model="m",
        messages=[{"role": "user", "content": "classifica este texto"}],
        task_id=task_id,
        task_type=task_type,
        attempt=attempt,
        json_mode=json_mode,
    )


def _run(adapter: MockAdapter, request: ChatRequest):
    return asyncio.run(adapter.chat(request))


def test_mock_is_deterministic_for_the_same_request():
    adapter = _mock(MockProfile(quality={"classification": 0.5}, failure_rate=0.2))
    first = _run(adapter, _req())
    second = _run(adapter, _req())
    assert first == second


def test_mock_quality_one_is_always_correct_and_zero_always_wrong():
    always = _mock(MockProfile(quality={"classification": 1.0}), oracle=lambda r: "POSITIVO")
    never = _mock(MockProfile(quality={"classification": 0.0}), oracle=lambda r: "POSITIVO")
    for index in range(20):
        assert _run(always, _req(task_id=f"t{index}")).text == "POSITIVO"
        assert _run(never, _req(task_id=f"t{index}")).text == "RESPOSTA_ERRADA"


def test_mock_failure_rate_produces_typed_failures():
    adapter = _mock(MockProfile(quality={"classification": 1.0}, failure_rate=1.0))
    result = _run(adapter, _req())
    assert isinstance(result, ProviderFailure)
    assert result.kind in {FailureKind.TIMEOUT, FailureKind.UPSTREAM_ERROR}


def test_mock_unknown_model_is_model_not_found():
    adapter = MockAdapter({}, seed=1)
    result = _run(adapter, _req())
    assert isinstance(result, ProviderFailure)
    assert result.kind is FailureKind.MODEL_NOT_FOUND


def test_dishonest_json_mode_returns_non_json():
    adapter = _mock(MockProfile(quality={"classification": 1.0}, json_mode_honest=False))
    result = _run(adapter, _req(json_mode=True))
    assert isinstance(result, ChatResponse)
    with pytest.raises(ValueError):
        import json

        json.loads(result.text)


def test_mock_without_usage_reporting_marks_usage_unreported():
    adapter = _mock(MockProfile(quality={"classification": 1.0}, reports_usage=False))
    result = _run(adapter, _req())
    assert isinstance(result, ChatResponse)
    assert result.usage.reported is False


def test_price_lookup_uses_the_row_in_force_on_the_request_date(repo_config_dir: Path):
    table = PriceTable.from_yaml(repo_config_dir / "prices.yaml")

    old = table.price_at("mock-cheap", date(2025, 6, 1))
    new = table.price_at("mock-cheap", date(2026, 6, 1))

    assert old is not None and old.input_per_mtok == Decimal("0.20")
    assert new is not None and new.input_per_mtok == Decimal("0.10")


def test_price_lookup_before_first_row_returns_none(repo_config_dir: Path):
    table = PriceTable.from_yaml(repo_config_dir / "prices.yaml")
    assert table.price_at("mock-cheap", date(2024, 1, 1)) is None
    assert table.price_at("modelo-sem-preco", date(2026, 1, 1)) is None


def test_cost_counts_cache_and_output_without_double_counting_reasoning(repo_config_dir: Path):
    table = PriceTable.from_yaml(repo_config_dir / "prices.yaml")
    entry = table.price_at("mock-cheap", date(2026, 6, 1))
    assert entry is not None
    # 1000 tokens de entrada, 200 deles em cache; 500 de saída (já inclui 300 de raciocínio).
    usage = Usage(input_tokens=1000, output_tokens=500, reasoning_tokens=300, cached_tokens=200)

    cost = cost_usd(entry, usage)

    # 800*0.10 + 200*0.05 + 500*0.40 = 80 + 10 + 200 = 290 por milhão
    assert cost == Decimal("290") / Decimal(1_000_000)


def test_invalid_price_rows_fail_at_load_time():
    with pytest.raises(ConfigError):
        parse_price_rows({"currency": "EUR", "prices": []})
    with pytest.raises(ConfigError):
        parse_price_rows({"prices": [{"model": "x", "input_per_mtok": "abc"}]})
    with pytest.raises(ConfigError):
        parse_price_rows(
            {
                "prices": [
                    {
                        "model": "x",
                        "input_per_mtok": -1,
                        "output_per_mtok": 1,
                        "effective_date": "2026-01-01",
                    }
                ]
            }
        )
