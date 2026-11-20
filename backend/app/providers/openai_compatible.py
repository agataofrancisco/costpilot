"""Adaptador para qualquer API compatível com `POST {base_url}/chat/completions`.

Serve para OpenRouter/OpenAI e, com outro `base_url` e chave virtual, para o ModelMesh.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.providers.base import ChatRequest, FailureKind, ProviderFailure, ProviderResult
from app.providers.parsing import classify_http_status, parse_chat_completion


def build_payload(request: ChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": request.messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


class OpenAICompatibleAdapter:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(self, request: ChatRequest) -> ProviderResult:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = time.perf_counter()
        try:
            response = await self._client.post(
                self._endpoint, json=build_payload(request), headers=headers
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Falha antes de o pedido chegar ao provider: sem custo, falha de disponibilidade.
            return ProviderFailure(
                FailureKind.UNAVAILABLE, "provider inacessível", _elapsed(started)
            )
        except httpx.TimeoutException:
            return ProviderFailure(FailureKind.TIMEOUT, "timeout do provider", _elapsed(started))
        except httpx.HTTPError:
            return ProviderFailure(FailureKind.UNAVAILABLE, "erro de transporte", _elapsed(started))

        latency_ms = _elapsed(started)
        if response.status_code >= 400:
            kind = classify_http_status(response.status_code)
            return ProviderFailure(kind, f"HTTP {response.status_code}", latency_ms)
        try:
            payload: object = response.json()
        except ValueError:
            return ProviderFailure(
                FailureKind.INVALID_RESPONSE, "corpo de resposta não é JSON", latency_ms
            )
        return parse_chat_completion(
            payload, requested_model=request.model, provider=self.name, latency_ms=latency_ms
        )


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
