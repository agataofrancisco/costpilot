from __future__ import annotations

import pytest
from app.routing.validators import ValidationSpec, validate_output


def test_classification_accepts_only_exact_labels_ignoring_case_and_final_dot():
    spec = ValidationSpec(labels=["positivo", "negativo", "neutro"])

    assert validate_output("classification", "Positivo.", spec).ok is True
    assert validate_output("classification", "  negativo ", spec).ok is True
    assert validate_output("classification", "muito positivo", spec).ok is False


def test_json_extraction_requires_object_with_typed_fields():
    spec = ValidationSpec(required_fields={"nome": "string", "idade": "number"})

    assert validate_output("json_extraction", '{"nome": "Ana", "idade": 31}', spec).ok is True
    assert validate_output("json_extraction", '{"nome": "Ana"}', spec).ok is False
    assert validate_output("json_extraction", '{"nome": "Ana", "idade": "31"}', spec).ok is False


@pytest.mark.parametrize(
    "text",
    ["", "não é json", '["lista"]', '{"nome": "Ana", "idade": true}', "[" * 5000],
)
def test_json_extraction_never_raises_on_hostile_or_malformed_output(text):
    spec = ValidationSpec(required_fields={"nome": "string", "idade": "number"})

    result = validate_output("json_extraction", text, spec)

    assert result.ok is False


def test_json_bool_is_not_accepted_as_number():
    spec = ValidationSpec(required_fields={"ativo": "number"})
    assert validate_output("json_extraction", '{"ativo": true}', spec).ok is False


def test_multi_step_uses_last_final_line():
    spec = ValidationSpec(expected_answer="42")

    assert validate_output("multi_step_reasoning", "passos...\nFINAL: 41\nFINAL: 42.", spec).ok
    assert not validate_output("multi_step_reasoning", "FINAL: 42\nFINAL: 41", spec).ok
    assert not validate_output("multi_step_reasoning", "a resposta é 42", spec).ok


def test_doc_qa_requires_the_citation_in_the_answer():
    spec = ValidationSpec(expected_citation="manual-cap3#regras")

    assert validate_output("doc_qa", "Segundo manual-cap3#regras, ...", spec).ok is True
    assert validate_output("doc_qa", "Segundo o manual, ...", spec).ok is False


def test_non_string_output_is_a_failed_validation_not_an_exception():
    spec = ValidationSpec(labels=["a"])
    assert validate_output("classification", None, spec).ok is False
    assert validate_output("classification", 123, spec).reason == "saida_nao_textual"


def test_missing_spec_means_unvalidated_and_passes():
    result = validate_output("classification", "qualquer coisa", None)
    assert result.ok is True
    assert result.reason == "sem_validacao"


def test_spec_with_extra_fields_is_rejected_at_the_boundary():
    with pytest.raises(ValueError):
        ValidationSpec(labels=["a"], codigo_inventado="x")  # type: ignore[call-arg]
