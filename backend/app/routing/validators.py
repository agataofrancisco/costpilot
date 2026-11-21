"""Validadores programáticos por tipo de tarefa.

Decidem se uma resposta conta como correcta e, portanto, se a cascata escala. Recebem texto de
um modelo (dados não confiáveis): nunca lançam excepção por causa do conteúdo; um formato
inesperado é simplesmente uma validação falhada.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.routing.task import TaskType

FieldType = Literal["string", "number", "boolean", "array", "object"]
_FINAL = re.compile(r"FINAL:\s*(.+)")


class ValidationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[str] | None = Field(default=None, min_length=1, max_length=50)
    required_fields: dict[str, FieldType] | None = Field(default=None, max_length=50)
    expected_answer: str | None = Field(default=None, max_length=2000)
    expected_citation: str | None = Field(default=None, max_length=500)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    reason: str


REQUIRED_FIELD_BY_TASK: dict[str, str] = {
    "classification": "labels",
    "json_extraction": "required_fields",
    "multi_step_reasoning": "expected_answer",
    "doc_qa": "expected_citation",
}


def spec_matches_task(task_type: TaskType, spec: ValidationSpec) -> bool:
    return getattr(spec, REQUIRED_FIELD_BY_TASK[task_type]) is not None


def _normalize(text: str) -> str:
    return " ".join(text.strip().rstrip(".").lower().split())


def _is_type(value: object, expected: FieldType) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    return isinstance(value, dict)


def validate_output(
    task_type: TaskType, text: object, spec: ValidationSpec | None
) -> ValidationResult:
    if spec is None:
        return ValidationResult(True, "sem_validacao")
    if not isinstance(text, str):
        return ValidationResult(False, "saida_nao_textual")

    if task_type == "classification":
        if not spec.labels:
            return ValidationResult(False, "criterio_em_falta")
        allowed = {_normalize(label) for label in spec.labels}
        return ValidationResult(_normalize(text) in allowed, "label")

    if task_type == "json_extraction":
        if not spec.required_fields:
            return ValidationResult(False, "criterio_em_falta")
        try:
            parsed: object = json.loads(text)
        except (ValueError, RecursionError):
            return ValidationResult(False, "json_invalido")
        if not isinstance(parsed, dict):
            return ValidationResult(False, "json_nao_objecto")
        for name, expected in spec.required_fields.items():
            if name not in parsed or not _is_type(parsed[name], expected):
                return ValidationResult(False, f"campo_invalido: {name}")
        return ValidationResult(True, "schema")

    if task_type == "multi_step_reasoning":
        if spec.expected_answer is None:
            return ValidationResult(False, "criterio_em_falta")
        matches = _FINAL.findall(text)
        if not matches:
            return ValidationResult(False, "sem_resposta_final")
        return ValidationResult(
            _normalize(matches[-1]) == _normalize(spec.expected_answer), "resposta_final"
        )

    if spec.expected_citation is None:
        return ValidationResult(False, "criterio_em_falta")
    return ValidationResult(spec.expected_citation in text, "citacao")
