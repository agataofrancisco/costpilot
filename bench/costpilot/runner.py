"""Benchmark: always_expensive, always_cheap e hybrid sobre exactamente as mesmas tarefas.

Corre contra a API real (TestClient, in-process) com providers MOCK. Todos os resultados de custo
e qualidade são SIMULADOS: preços e perfis de qualidade dos mocks são fictícios. Por isso o relatório
marca tudo como `simulated` e deixa as métricas de portefólio como `TODO: medir`.

Execução: python bench/costpilot/runner.py   (gera reports/ablation.md e reports/ablation.json)
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.container import build_container  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers.base import ChatRequest  # noqa: E402
from app.providers.mock import MockAdapter  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TASKS_PATH = BENCH_DIR / "tasks.jsonl"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR = REPO_ROOT / "data" / "bench"
SEED = 7
TEAM = "bench"
POLICIES: dict[str, str | None] = {
    "always_expensive": "mock-strong",
    "always_cheap": "mock-cheap",
    "hybrid": None,
}
REQUIRED_TYPES = ("classification", "json_extraction", "multi_step_reasoning", "doc_qa")


class DatasetError(ValueError):
    pass


def load_tasks(path: Path = TASKS_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate_dataset(tasks: Iterable[dict[str, Any]]) -> None:
    """Falha se alguma tarefa não tiver tipo válido nem critério de correcção."""
    rows = list(tasks)
    for row in rows:
        if row.get("task_type") not in REQUIRED_TYPES:
            raise DatasetError(f"{row.get('id')}: tipo de tarefa inválido")
        if not row.get("validation") or row.get("expected") in (None, ""):
            raise DatasetError(f"{row.get('id')}: falta critério de correcção ou resposta esperada")
    counts = {t: sum(1 for r in rows if r["task_type"] == t) for t in REQUIRED_TYPES}
    if len(rows) < 100 or min(counts.values()) < 25:
        raise DatasetError(f"dataset insuficiente: {len(rows)} tarefas, por tipo {counts}")


def expected_output(task: dict[str, Any]) -> str:
    expected = task["expected"]
    if task["task_type"] == "json_extraction":
        return json.dumps(expected, ensure_ascii=False)
    if task["task_type"] == "multi_step_reasoning":
        return f"FINAL: {expected}"
    if task["task_type"] == "doc_qa":
        return f"Segundo {expected}, o prazo é de 10 dias úteis."
    return str(expected)


def make_oracle(tasks: Iterable[dict[str, Any]]):
    answers = {t["id"]: expected_output(t) for t in tasks}

    def oracle(request: ChatRequest) -> str | None:
        return answers.get(request.task_id)

    return oracle


def is_correct(task: dict[str, Any], output: str | None) -> tuple[bool, float | None]:
    """Correcção exacta; para JSON devolve também o F1 de campos (pares campo=valor)."""
    if output is None:
        return False, None
    if task["task_type"] == "json_extraction":
        predicted = _json_or_none(output)
        f1 = field_f1(predicted, task["expected"])
        return f1 == 1.0, f1
    if task["task_type"] == "multi_step_reasoning":
        finals = [
            line.split("FINAL:", 1)[1].strip() for line in output.splitlines() if "FINAL:" in line
        ]
        return bool(finals) and finals[-1].rstrip(".") == str(task["expected"]), None
    if task["task_type"] == "doc_qa":
        return str(task["expected"]) in output, None
    return output.strip().rstrip(".").lower() == str(task["expected"]).lower(), None


def _json_or_none(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def field_f1(predicted: dict | None, expected: dict) -> float:
    if not predicted:
        return 0.0
    pred_pairs = {(k, str(v)) for k, v in predicted.items()}
    gold_pairs = {(k, str(v)) for k, v in expected.items()}
    true_positive = len(pred_pairs & gold_pairs)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(pred_pairs)
    recall = true_positive / len(gold_pairs)
    return round(2 * precision * recall / (precision + recall), 6)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, round(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def run_policy(name: str, override: str | None, tasks: list[dict[str, Any]]) -> list[dict]:
    """Corre todas as tarefas com uma política, numa base de dados nova (sem histórico herdado)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DATA_DIR / f"{name}.db"
    if db_path.exists():
        db_path.unlink()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{db_path.as_posix()}",
        config_dir=REPO_ROOT / "config",
        admin_token=None,
        allow_policy_override=True,
        probe_on_startup=True,
        mock_seed=SEED,
        provider_timeout_seconds=5,
        reservation_ttl_seconds=60,
    )
    from app.catalog.catalog import Catalog

    catalog = Catalog.load(settings.config_dir)
    adapter = MockAdapter(catalog.mock_profiles(), seed=SEED, oracle=make_oracle(tasks))
    container = build_container(settings, adapters={"mock": adapter})
    app = create_app(settings, container)
    records: list[dict] = []
    with TestClient(app) as client:
        for task in tasks:
            body: dict[str, Any] = {
                "task": {
                    "task_type": task["task_type"],
                    "input_tokens": task["input_tokens"],
                    "requires_json": task["requires_json"],
                    "team": TEAM,
                },
                "messages": task["messages"],
                "max_output_tokens": 256,
                "task_id": task["id"],
                "validation": task["validation"],
            }
            if override is not None:
                body["policy_override"] = {"model": override}
            started = time.perf_counter()
            response = client.post("/execute", json=body)
            wall_ms = (time.perf_counter() - started) * 1000
            records.append(_record(task, response, wall_ms, name))
    return records


def _record(task: dict, response, wall_ms: float, policy: str) -> dict:
    payload = response.json()
    attempts = payload.get("attempts", [])
    if response.status_code == 200:
        output = payload.get("output")
        cost = Decimal(payload["total_cost_usd"])
        resolved = bool(payload.get("resolved"))
    else:
        output = None
        cost = sum((Decimal(a["cost_usd"]) for a in attempts), Decimal(0))
        resolved = False
    correct, f1 = is_correct(task, output)
    return {
        "policy": policy,
        "task_id": task["id"],
        "task_type": task["task_type"],
        "http_status": response.status_code,
        "resolved": resolved,
        "correct": correct,
        "field_f1": f1,
        "cost_usd": str(cost),
        "attempts": len(attempts),
        "escalations": max(0, len(attempts) - 1),
        "provider_failures": sum(1 for a in attempts if a["status"] == "provider_error"),
        "final_model": payload.get("model"),
        "sim_latency_ms": round(sum(a.get("latency_ms", 0.0) for a in attempts), 3),
        "wall_ms": round(wall_ms, 3),
    }


def summarize(records: list[dict]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    groups: dict[str, list[dict]] = {t: [] for t in REQUIRED_TYPES}
    for row in records:
        groups[row["task_type"]].append(row)
    groups["all"] = records
    for label, rows in groups.items():
        total_cost = sum(Decimal(r["cost_usd"]) for r in rows)
        correct = sum(1 for r in rows if r["correct"])
        f1_values = [r["field_f1"] for r in rows if r["field_f1"] is not None]
        latencies = [r["sim_latency_ms"] for r in rows]
        result[label] = {
            "n": len(rows),
            "resolved_rate": round(sum(1 for r in rows if r["resolved"]) / len(rows), 4),
            "exact_match_rate": round(correct / len(rows), 4),
            "field_f1": round(statistics.fmean(f1_values), 4) if f1_values else None,
            "total_cost_usd": str(total_cost),
            "cost_per_correct_usd": (
                str((total_cost / correct).quantize(Decimal("0.000001"))) if correct else None
            ),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
            "retries": sum(r["provider_failures"] for r in rows),
            "escalations": sum(r["escalations"] for r in rows),
        }
    return result


def git_info() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido", True
    return commit, dirty


def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    lines = [
        "# Relatório de ablação — CostPilot",
        "",
        "> **SIMULADO.** Todos os valores de custo e qualidade vêm de providers **mock** com preços",
        "> e perfis fictícios. Não são poupanças reais e não devem ser usados como prova de portefólio.",
        "",
        f"- Data: {meta['date']}",
        f"- Commit: {meta['commit']} (árvore com alterações não commitadas: {'sim' if meta['dirty'] else 'não'})",
        f"- Modo: {meta['mode']}",
        f"- Modelos: {', '.join(meta['models'])}",
        f"- Dataset: `bench/costpilot/tasks.jsonl` ({meta['tasks']} tarefas sintéticas, seed {meta['dataset_seed']})",
        f"- Seed do mock: {meta['mock_seed']}",
        "",
        "## Resultados por tipo de tarefa",
        "",
        "| Política | Tipo | n | Resolvidas | Exact match | F1 campos | Custo total (sim.) USD | Custo / tarefa correcta (sim.) USD | p50 lat. (sim.) ms | p95 lat. (sim.) ms | Retries | Escalonamentos |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for policy, summary in payload["policies"].items():
        for label in ("all", *REQUIRED_TYPES):
            row = summary[label]
            lines.append(
                f"| {policy} | {label} | {row['n']} | {row['resolved_rate']} | "
                f"{row['exact_match_rate']} | {row['field_f1'] if row['field_f1'] is not None else '—'} | "
                f"{row['total_cost_usd']} | {row['cost_per_correct_usd'] or '—'} | "
                f"{row['latency_p50_ms']} | {row['latency_p95_ms']} | {row['retries']} | "
                f"{row['escalations']} |"
            )
    lines += [
        "",
        "## Métricas de portefólio",
        "",
        "- Redução de custo por tarefa resolvida face a `always_expensive`: TODO: medir (com modelos reais)",
        "- Latência p95 medida em providers reais: TODO: medir",
        "- Custo real com `--max-usd`: TODO: medir",
        "",
        "## Limitações",
        "",
        "- Os perfis de qualidade dos mocks determinam o resultado; estas tabelas validam a mecânica, não o modelo.",
        "- A latência é a do perfil mock (`sim.`), não tempo de rede.",
        "- Não há juiz LLM: a correcção é programática (exacta ou F1 de campos).",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    tasks = load_tasks()
    validate_dataset(tasks)
    summaries: dict[str, Any] = {}
    raw: dict[str, list[dict]] = {}
    for name, override in POLICIES.items():
        records = run_policy(name, override, tasks)
        raw[name] = records
        summaries[name] = summarize(records)
        print(
            f"{name}: {summaries[name]['all']['resolved_rate']} resolvidas, "
            f"custo sim. {summaries[name]['all']['total_cost_usd']} USD"
        )
    commit, dirty = git_info()
    from app.catalog.catalog import Catalog

    models = sorted(m.id for m in Catalog.load(REPO_ROOT / "config").models())
    payload = {
        "meta": {
            "date": datetime.now(UTC).date().isoformat(),
            "commit": commit,
            "dirty": dirty,
            "mode": "mock (simulated)",
            "models": models,
            "tasks": len(tasks),
            "dataset_seed": 42,
            "mock_seed": SEED,
        },
        "policies": summaries,
        "records": raw,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "ablation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORTS_DIR / "ablation.md").write_text(render_markdown(payload), encoding="utf-8")
    print(f"relatório escrito em {REPORTS_DIR / 'ablation.md'}")


if __name__ == "__main__":
    main()
