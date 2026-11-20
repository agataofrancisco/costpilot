"""Acesso ao registo de uso. É a única camada que escreve em `usage_records`."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.accounting.tables import UsageRecord

JUDGED_STATUSES = ("ok", "validation_failed")


@dataclass(frozen=True, slots=True)
class UsageEntry:
    task_id: str
    attempt: int
    tenant_id: str
    team: str
    task_type: str
    model: str
    provider: str
    status: str
    reason: str
    failure_kind: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    tokens_estimated: bool = False
    cost_micro_usd: int = 0
    cost_estimated: bool = False
    latency_ms: float = 0.0
    model_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class OutcomeSample:
    success: bool
    latency_ms: float


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class UsageRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def record(self, entry: UsageEntry) -> None:
        row = UsageRecord(created_at=utc_now_naive(), **asdict(entry))
        with self._sessions() as session, session.begin():
            session.add(row)

    def judged_samples(self, model: str, task_type: str, limit: int = 500) -> list[OutcomeSample]:
        """Tentativas com resposta do provider, mais recentes primeiro (sucesso = validação ok)."""
        statement = (
            select(UsageRecord.status, UsageRecord.latency_ms)
            .where(
                UsageRecord.model == model,
                UsageRecord.task_type == task_type,
                UsageRecord.status.in_(JUDGED_STATUSES),
            )
            .order_by(UsageRecord.id.desc())
            .limit(limit)
        )
        with self._sessions() as session:
            rows = session.execute(statement).all()
        return [
            OutcomeSample(success=status == "ok", latency_ms=latency) for status, latency in rows
        ]
