"""Esquemas de pedido da API. A validação de fronteira acontece aqui, antes de qualquer decisão."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth.clients import Principal
from app.routing.task import Sensitivity, TaskSpec, TaskType
from app.routing.validators import REQUIRED_FIELD_BY_TASK, ValidationSpec, spec_matches_task


class TaskRequest(BaseModel):
    """Corpo de pedido de tarefa. NÃO inclui `team` nem `tenant_id`: a identidade vem da chave.

    `extra="forbid"`: enviar `team` ou `tenant_id` no corpo devolve 422.
    """

    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    input_tokens: int = Field(ge=0, le=2_000_000)
    requires_json: bool = False
    requires_tools: bool = False
    latency_sla_ms: int | None = Field(default=None, gt=0, le=600_000)
    sensitivity: Sensitivity = "low"
    cost_ceiling_usd: Decimal | None = Field(default=None, ge=0, le=1000)

    def to_task(self, principal: Principal) -> TaskSpec:
        return TaskSpec(
            **self.model_dump(),
            team=principal.team,
            tenant_id=principal.tenant_id,
        )


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=200_000)


class PolicyOverride(BaseModel):
    """Baseline fixo (benchmark). Só é aceite quando `COSTPILOT_ALLOW_POLICY_OVERRIDE=true`."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(pattern=r"^[A-Za-z0-9._/:-]{1,120}$")


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskRequest
    messages: list[Message] = Field(min_length=1, max_length=50)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1, le=8192)
    cache: bool = False
    task_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    validation: ValidationSpec | None = None
    policy_override: PolicyOverride | None = None

    @model_validator(mode="after")
    def _validation_matches_task_type(self) -> ExecuteRequest:
        if self.validation is not None and not spec_matches_task(
            self.task.task_type, self.validation
        ):
            field = REQUIRED_FIELD_BY_TASK[self.task.task_type]
            raise ValueError(f"validation: o tipo {self.task.task_type} exige '{field}'")
        return self


class AutopilotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
