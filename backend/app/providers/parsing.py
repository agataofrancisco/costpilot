"""Interpretação defensiva das respostas dos providers.

Tudo o que vem de um provider é dados não confiáveis: estas funções nunca lançam
excepções para formatos inesperados; devolvem uma falha `invalid_response`.
"""

from __future__ import annotations

from app.providers.base import ChatResponse, FailureKind, ProviderFailure, Usage


def as_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_usage(raw: object) -> Usage:
    empty = Usage(input_tokens=0, output_tokens=0, reported=False)
    if not isinstance(raw, dict):
        return empty
    prompt = as_non_negative_int(raw.get("prompt_tokens"))
    completion = as_non_negative_int(raw.get("completion_tokens"))
    if prompt is None or completion is None:
        return empty
    details = raw.get("completion_tokens_details")
    reasoning = None
    if isinstance(details, dict):
        reasoning = as_non_negative_int(details.get("reasoning_tokens"))
    prompt_details = raw.get("prompt_tokens_details")
    cached = None
    if isinstance(prompt_details, dict):
        cached = as_non_negative_int(prompt_details.get("cached_tokens"))
    return Usage(
        input_tokens=prompt,
        output_tokens=completion,
        reasoning_tokens=reasoning or 0,
        cached_tokens=cached or 0,
        reported=True,
    )


def parse_chat_completion(
    payload: object, *, requested_model: str, provider: str, latency_ms: float
) -> ChatResponse | ProviderFailure:
    invalid = ProviderFailure(
        FailureKind.INVALID_RESPONSE, "resposta do provider fora do formato esperado", latency_ms
    )
    if not isinstance(payload, dict):
        return invalid
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return invalid
    message = choices[0].get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        return invalid
    reported = payload.get("model")
    reported_model = reported if isinstance(reported, str) and reported else None
    return ChatResponse(
        model=requested_model,
        provider=provider,
        text=text,
        usage=parse_usage(payload.get("usage")),
        latency_ms=latency_ms,
        reported_model=reported_model,
    )


def classify_http_status(status: int) -> FailureKind:
    if status in (401, 403):
        return FailureKind.AUTH
    if status == 404:
        return FailureKind.MODEL_NOT_FOUND
    if status == 408:
        return FailureKind.TIMEOUT
    if status == 429:
        return FailureKind.RATE_LIMITED
    if status >= 500:
        return FailureKind.UPSTREAM_ERROR
    return FailureKind.BAD_REQUEST
