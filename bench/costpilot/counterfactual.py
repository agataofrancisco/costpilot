"""Simulação contrafactual offline sobre registos de uso (sem executar pedidos novos).

Pergunta: o que teria custado a política alternativa para os mesmos pedidos?

Só se estima um resultado quando existe uma observação real desse modelo para a MESMA tarefa
(o run do benchmark). Sem observação, o pedido fica `unknown` e NÃO é extrapolado.

Os registos de entrada são sempre marcados: `source` vem do ficheiro de origem e nunca é omitido.
Execução: python bench/costpilot/counterfactual.py   (lê reports/ablation.json)
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

REPORT = Path(__file__).resolve().parents[2] / "reports" / "ablation.json"


def simulate(
    logged: Iterable[Mapping[str, Any]],
    observations: Iterable[Mapping[str, Any]],
    *,
    alternative_policy: str,
    source: str,
) -> dict[str, Any]:
    """`logged`: registos da política real (uma linha por tarefa).
    `observations`: registos de execução da política alternativa (mesma tarefa, mesmo id)."""
    alt_by_task = {r["task_id"]: r for r in observations}
    logged_rows = list(logged)
    actual_cost = Decimal(0)
    alt_cost = Decimal(0)
    estimated = unknown = 0
    alt_resolved = 0
    for row in logged_rows:
        actual_cost += Decimal(row["cost_usd"])
        alt = alt_by_task.get(row["task_id"])
        if alt is None:
            unknown += 1
            continue
        estimated += 1
        alt_cost += Decimal(alt["cost_usd"])
        alt_resolved += 1 if alt["correct"] else 0
    return {
        "source": source,
        "alternative_policy": alternative_policy,
        "requests": len(logged_rows),
        "estimated": estimated,
        "unknown": unknown,
        "actual_cost_usd_for_estimated": str(
            sum(
                (Decimal(r["cost_usd"]) for r in logged_rows if r["task_id"] in alt_by_task),
                Decimal(0),
            )
        ),
        "alternative_cost_usd_for_estimated": str(alt_cost),
        "alternative_correct_for_estimated": alt_resolved,
        "assumptions": [
            "mesma tarefa, mesma validação e mesmo modelo produzem o mesmo resultado",
            "custos com os preços fictícios de config/prices.yaml (mock)",
            "pedidos sem observação alternativa ficam unknown e não são extrapolados",
        ],
    }


def main() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    hybrid = payload["records"]["hybrid"]
    expensive = payload["records"]["always_expensive"]
    result = simulate(
        hybrid,
        expensive,
        alternative_policy="always_expensive",
        source="synthetic: bench mock (reports/ablation.json)",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
