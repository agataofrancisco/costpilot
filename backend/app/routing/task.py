"""Pedido de routing (fronteira da API): validado antes de chegar à política."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskType = Literal["classification", "json_extraction", "multi_step_reasoning", "doc_qa"]
Sensitivity = Literal["low", "medium", "high"]


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    input_tokens: int = Field(ge=0, le=2_000_000)
    requires_json: bool = False
    requires_tools: bool = False
    latency_sla_ms: int | None = Field(default=None, gt=0, le=600_000)
    sensitivity: Sensitivity = "low"
    cost_ceiling_usd: Decimal | None = Field(default=None, ge=0, le=1000)
    team: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    tenant_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,64}$")
