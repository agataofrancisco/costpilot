"""Esquemas de pedido da API. A validação de fronteira acontece aqui, antes de qualquer decisão."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.routing.task import TaskSpec
from app.routing.validators import REQUIRED_FIELD_BY_TASK, ValidationSpec, spec_matches_task


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

    task: TaskSpec
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
