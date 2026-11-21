"""Benchmark: validação do dataset, correcção programática e simulação contrafactual."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[2] / "bench" / "costpilot"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load("runner")


@pytest.fixture(scope="module")
def counterfactual():
    return _load("counterfactual")


def test_dataset_has_at_least_100_tasks_in_four_types(runner):
    tasks = runner.load_tasks()
    runner.validate_dataset(tasks)  # não levanta excepção

    assert len(tasks) >= 100
    for task_type in runner.REQUIRED_TYPES:
        assert sum(1 for t in tasks if t["task_type"] == task_type) == 25


def test_every_task_has_a_correction_criterion(runner):
    for task in runner.load_tasks():
        assert task["validation"], task["id"]
        assert task["expected"] not in (None, ""), task["id"]


def test_validation_fails_when_a_task_has_no_criterion(runner):
    tasks = runner.load_tasks()
    broken = [dict(t) for t in tasks]
    broken[3]["validation"] = {}

    with pytest.raises(runner.DatasetError, match="critério"):
        runner.validate_dataset(broken)


def test_validation_fails_on_unknown_task_type(runner):
    tasks = [dict(t) for t in runner.load_tasks()]
    tasks[0]["task_type"] = "tradução"
    with pytest.raises(runner.DatasetError, match="tipo"):
        runner.validate_dataset(tasks)


def test_field_f1_counts_matching_pairs(runner):
    expected = {"nome": "Ana", "idade": 31, "cidade": "Porto"}
    assert runner.field_f1({"nome": "Ana", "idade": 31, "cidade": "Porto"}, expected) == 1.0
    assert runner.field_f1(
        {"nome": "Ana", "idade": 30, "cidade": "Porto"}, expected
    ) == pytest.approx(0.6667, abs=1e-4)
    assert runner.field_f1(None, expected) == 0.0


def test_json_correctness_rejects_non_object_output(runner):
    task = {
        "task_type": "json_extraction",
        "expected": {"nome": "Ana", "idade": 31, "cidade": "Porto"},
    }
    assert runner.is_correct(task, "não é json") == (False, 0.0)
    assert runner.is_correct(task, None) == (False, None)


def test_multi_step_uses_the_last_final_line(runner):
    task = {"task_type": "multi_step_reasoning", "expected": "42"}
    assert runner.is_correct(task, "passos\nFINAL: 41\nFINAL: 42")[0] is True
    assert runner.is_correct(task, "FINAL: 42\nFINAL: 41")[0] is False


def test_counterfactual_marks_unknown_without_observation(counterfactual):
    logged = [
        {"task_id": "a", "cost_usd": "0.001"},
        {"task_id": "b", "cost_usd": "0.002"},
    ]
    observations = [{"task_id": "a", "cost_usd": "0.004", "correct": True}]

    result = counterfactual.simulate(
        logged, observations, alternative_policy="always_expensive", source="synthetic: teste"
    )

    assert result["source"] == "synthetic: teste"
    assert result["estimated"] == 1
    assert result["unknown"] == 1
    assert result["alternative_cost_usd_for_estimated"] == "0.004"
    assert result["actual_cost_usd_for_estimated"] == "0.001"
    assert any("unknown" in a for a in result["assumptions"])
