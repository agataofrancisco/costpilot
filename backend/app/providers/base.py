"""Contrato dos adaptadores de provider e taxonomia de falhas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    UNAVAILABLE = "unavailable"
    AUTH = "auth"
    MODEL_NOT_FOUND = "model_not_found"
    BAD_REQUEST = "bad_request"
    INVALID_RESPONSE = "invalid_response"


RETRIABLE_FAILURES = frozenset(
    {
        FailureKind.TIMEOUT,
        FailureKind.RATE_LIMITED,
        FailureKind.UPSTREAM_ERROR,
        FailureKind.UNAVAILABLE,
    }
)


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model: str
    messages: list[dict[str, str]]
    temperature: float = 0.0
    max_tokens: int = 512
    json_mode: bool = False
    task_id: str = ""
    task_type: str = ""
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class Usage:
    """Contagens reportadas pelo provider. `reported=False` quando o provider não as devolveu."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    reported: bool = True


@dataclass(frozen=True, slots=True)
class ChatResponse:
    model: str
    provider: str
    text: str
    usage: Usage
    latency_ms: float
    reported_model: str | None = None

    @property
    def model_mismatch(self) -> bool:
        return self.reported_model is not None and self.reported_model != self.model


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    kind: FailureKind
    message: str
    latency_ms: float = 0.0
    retriable: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "retriable", self.kind in RETRIABLE_FAILURES)


ProviderResult = ChatResponse | ProviderFailure


class ProviderAdapter(Protocol):
    name: str

    async def chat(self, request: ChatRequest) -> ProviderResult: ...
