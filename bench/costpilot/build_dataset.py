"""Gera `tasks.jsonl`: 100 tarefas SINTÉTICAS (25 por tipo), determinísticas (seed fixa).

Cada tarefa traz o critério de correcção programático (validação + resposta esperada). Os
dados são inventados: não há logs reais nem dados pessoais. Execução: `python build_dataset.py`.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

SEED = 42
PER_TYPE = 25
OUT = Path(__file__).resolve().parent / "tasks.jsonl"

POSITIVE = [
    "O serviço foi excelente e resolveram tudo em minutos.",
    "Adorei a rapidez da entrega, recomendo.",
    "A equipa foi simpática e muito prestável.",
]
NEGATIVE = [
    "O produto chegou partido e ninguém responde ao email.",
    "Esperei três semanas e a encomenda nunca apareceu.",
    "A app está sempre a falhar, é frustrante.",
]
NEUTRAL = [
    "A encomenda foi enviada na terça-feira.",
    "O relatório tem doze páginas e um anexo.",
    "A reunião está marcada para as dez horas.",
]
NAMES = ["Ana Costa", "Bruno Lima", "Carla Dias", "Diogo Reis", "Eva Santos", "Filipe Gomes"]
CITIES = ["Lisboa", "Porto", "Braga", "Coimbra", "Faro", "Évora"]


def _message(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def _tokens(messages: list[dict[str, str]]) -> int:
    return math.ceil(sum(len(m["content"]) for m in messages) / 4)


def _record(
    task_id: str, task_type: str, text: str, requires_json: bool, validation: dict, expected
) -> dict:
    messages = _message(text)
    return {
        "id": task_id,
        "task_type": task_type,
        "messages": messages,
        "input_tokens": _tokens(messages),
        "requires_json": requires_json,
        "validation": validation,
        "expected": expected,
        "criterion": next(iter(validation)),
    }


def classification(rng: random.Random) -> list[dict]:
    rows = []
    pools = [("positivo", POSITIVE), ("negativo", NEGATIVE), ("neutro", NEUTRAL)]
    for index in range(PER_TYPE):
        label, pool = pools[index % 3]
        sentence = rng.choice(pool)
        text = (
            "Classifica o sentimento da frase como positivo, negativo ou neutro. "
            f"Responde só com a label.\nFrase: {sentence}"
        )
        rows.append(
            _record(
                f"cls-{index:03d}",
                "classification",
                text,
                False,
                {"labels": ["positivo", "negativo", "neutro"]},
                label,
            )
        )
    return rows


def json_extraction(rng: random.Random) -> list[dict]:
    rows = []
    for index in range(PER_TYPE):
        name, city = rng.choice(NAMES), rng.choice(CITIES)
        age = rng.randint(18, 80)
        text = (
            f"{name} tem {age} anos e vive em {city}. "
            "Extrai nome, idade e cidade e responde só com JSON "
            '{"nome": ..., "idade": ..., "cidade": ...}.'
        )
        expected = {"nome": name, "idade": age, "cidade": city}
        rows.append(
            _record(
                f"json-{index:03d}",
                "json_extraction",
                text,
                True,
                {"required_fields": {"nome": "string", "idade": "number", "cidade": "string"}},
                expected,
            )
        )
    return rows


def multi_step(rng: random.Random) -> list[dict]:
    rows = []
    for index in range(PER_TYPE):
        a, days, removed = rng.randint(3, 20), rng.randint(2, 9), rng.randint(1, 30)
        answer = a * days - removed
        text = (
            f"Uma equipa resolve {a} tarefas por dia durante {days} dias e depois "
            f"remove {removed} tarefas. Quantas tarefas restam? Raciocina passo a passo "
            "e termina com uma linha 'FINAL: <número>'."
        )
        rows.append(
            _record(
                f"multi-{index:03d}",
                "multi_step_reasoning",
                text,
                False,
                {"expected_answer": str(answer)},
                str(answer),
            )
        )
    return rows


def doc_qa(rng: random.Random) -> list[dict]:
    rows = []
    sections = ["regras", "prazos", "excepções", "reembolsos", "contactos"]
    for index in range(PER_TYPE):
        chapter = rng.randint(1, 9)
        section = rng.choice(sections)
        citation = f"manual-cap{chapter}#{section}"
        text = (
            f"Segundo a documentação interna ({citation}), qual é o prazo de resposta a um "
            "pedido de reembolso? Indica a referência do documento que usaste."
        )
        rows.append(
            _record(
                f"doc-{index:03d}", "doc_qa", text, False, {"expected_citation": citation}, citation
            )
        )
    return rows


def build() -> list[dict]:
    rng = random.Random(SEED)
    rows = classification(rng) + json_extraction(rng) + multi_step(rng) + doc_qa(rng)
    return rows


def main() -> None:
    rows = build()
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} tarefas escritas em {OUT}")


if __name__ == "__main__":
    main()
