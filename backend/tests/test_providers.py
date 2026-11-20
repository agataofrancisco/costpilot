"""Adaptador OpenAI-compatível contra um servidor HTTP falso a correr em socket real."""

from __future__ import annotations

import asyncio
import socket

import pytest
from app.providers.base import ChatRequest, ChatResponse, FailureKind, ProviderFailure
from app.providers.openai_compatible import OpenAICompatibleAdapter

from tests.fakes.fake_openai import FakeOpenAIServer


def _request(model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[{"role": "user", "content": "olá"}],
        task_id="t-1",
        task_type="classification",
    )


def _call(fake: FakeOpenAIServer, model: str, timeout: float = 5.0):
    adapter = OpenAICompatibleAdapter(
        name="openai_compatible",
        base_url=fake.base_url,
        api_key="chave-de-teste",
        timeout_seconds=timeout,
    )

    async def run():
        try:
            return await adapter.chat(_request(model))
        finally:
            await adapter.aclose()

    return asyncio.run(run())


def test_successful_response_is_parsed_and_sends_bearer_key(fake_openai: FakeOpenAIServer):
    result = _call(fake_openai, "ok")

    assert isinstance(result, ChatResponse)
    assert result.text == "OK"
    assert result.usage.reported is True
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 2)
    assert result.model_mismatch is False
    sent = fake_openai.requests[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer chave-de-teste"


def test_json_mode_is_forwarded_as_response_format(fake_openai: FakeOpenAIServer):
    adapter = OpenAICompatibleAdapter(
        name="openai_compatible", base_url=fake_openai.base_url, api_key=None, timeout_seconds=5
    )
    request = ChatRequest(model="ok", messages=[], json_mode=True)

    asyncio.run(adapter.chat(request))
    asyncio.run(adapter.aclose())

    assert fake_openai.requests[-1]["body"]["response_format"] == {"type": "json_object"}
    assert "Authorization" not in fake_openai.requests[-1]["headers"]


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("rate", FailureKind.RATE_LIMITED),
        ("server", FailureKind.UPSTREAM_ERROR),
        ("auth", FailureKind.AUTH),
        ("notfound", FailureKind.MODEL_NOT_FOUND),
        ("badreq", FailureKind.BAD_REQUEST),
        ("badjson", FailureKind.INVALID_RESPONSE),
        ("emptychoices", FailureKind.INVALID_RESPONSE),
    ],
)
def test_each_failure_type_is_classified(fake_openai: FakeOpenAIServer, model, expected):
    result = _call(fake_openai, model)

    assert isinstance(result, ProviderFailure)
    assert result.kind is expected


def test_retriable_flag_follows_the_taxonomy(fake_openai: FakeOpenAIServer):
    assert _call(fake_openai, "rate").retriable is True
    assert _call(fake_openai, "server").retriable is True
    assert _call(fake_openai, "auth").retriable is False
    assert _call(fake_openai, "badreq").retriable is False


def test_timeout_is_reported_as_timeout(fake_openai: FakeOpenAIServer):
    result = _call(fake_openai, "timeout", timeout=0.3)

    assert isinstance(result, ProviderFailure)
    assert result.kind is FailureKind.TIMEOUT
    assert result.retriable is True


def test_unreachable_provider_is_unavailable():
    # Porta livre que acabou de ser fechada: a ligação é recusada imediatamente.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    adapter = OpenAICompatibleAdapter(
        name="modelmesh",
        base_url=f"http://127.0.0.1:{closed_port}/v1",
        api_key=None,
        timeout_seconds=2,
    )

    async def run():
        try:
            return await adapter.chat(_request("ok"))
        finally:
            await adapter.aclose()

    result = asyncio.run(run())
    assert isinstance(result, ProviderFailure)
    assert result.kind is FailureKind.UNAVAILABLE


def test_missing_usage_is_marked_as_not_reported(fake_openai: FakeOpenAIServer):
    result = _call(fake_openai, "nousage")

    assert isinstance(result, ChatResponse)
    assert result.usage.reported is False


def test_reasoning_and_cached_tokens_are_parsed(fake_openai: FakeOpenAIServer):
    result = _call(fake_openai, "reasoning")

    assert isinstance(result, ChatResponse)
    assert result.usage.reasoning_tokens == 40
    assert result.usage.cached_tokens == 20
    assert result.usage.output_tokens == 50


def test_reported_model_mismatch_is_detected(fake_openai: FakeOpenAIServer):
    result = _call(fake_openai, "wrongmodel")

    assert isinstance(result, ChatResponse)
    assert result.model_mismatch is True
