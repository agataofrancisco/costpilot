# Relatório de ablação — CostPilot

> **SIMULADO.** Todos os valores de custo e qualidade vêm de providers **mock** com preços
> e perfis fictícios. Não são poupanças reais e não devem ser usados como prova de portefólio.

- Data: 2026-11-21
- Commit: d397900 (árvore com alterações não commitadas: sim)
- Modo: mock (simulated)
- Modelos: mock-cheap, mock-liar, mock-mid, mock-strong, openai/gpt-4o-mini
- Dataset: `bench/costpilot/tasks.jsonl` (100 tarefas sintéticas, seed 42)
- Seed do mock: 7

## Resultados por tipo de tarefa

| Política | Tipo | n | Resolvidas | Exact match | F1 campos | Custo total (sim.) USD | Custo / tarefa correcta (sim.) USD | p50 lat. (sim.) ms | p95 lat. (sim.) ms | Retries | Escalonamentos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| always_expensive | all | 100 | 0.97 | 0.97 | 1.0 | 0.027750 | 0.000286 | 2000.0 | 2000.0 | 1 | 0 |
| always_expensive | classification | 25 | 0.96 | 0.96 | — | 0.007320 | 0.000305 | 2000.0 | 2000.0 | 1 | 0 |
| always_expensive | json_extraction | 25 | 1.0 | 1.0 | 1.0 | 0.007818 | 0.000313 | 2000.0 | 2000.0 | 0 | 0 |
| always_expensive | multi_step_reasoning | 25 | 0.92 | 0.92 | — | 0.004350 | 0.000189 | 2000.0 | 2000.0 | 0 | 0 |
| always_expensive | doc_qa | 25 | 1.0 | 1.0 | — | 0.008262 | 0.000330 | 2000.0 | 2000.0 | 0 | 0 |
| always_cheap | all | 100 | 0.69 | 0.69 | 0.7083 | 0.000910 | 0.000013 | 300.0 | 300.0 | 2 | 0 |
| always_cheap | classification | 25 | 0.84 | 0.84 | — | 0.000229 | 0.000011 | 300.0 | 300.0 | 1 | 0 |
| always_cheap | json_extraction | 25 | 0.68 | 0.68 | 0.7083 | 0.000309 | 0.000018 | 300.0 | 300.0 | 1 | 0 |
| always_cheap | multi_step_reasoning | 25 | 0.52 | 0.52 | — | 0.000150 | 0.000012 | 300.0 | 300.0 | 0 | 0 |
| always_cheap | doc_qa | 25 | 0.72 | 0.72 | — | 0.000222 | 0.000012 | 300.0 | 300.0 | 0 | 0 |
| hybrid | all | 100 | 0.97 | 0.97 | 1.0 | 0.013924 | 0.000144 | 1100.0 | 2000.0 | 1 | 7 |
| hybrid | classification | 25 | 0.96 | 0.96 | — | 0.006985 | 0.000291 | 2000.0 | 2000.0 | 1 | 3 |
| hybrid | json_extraction | 25 | 1.0 | 1.0 | 1.0 | 0.000930 | 0.000037 | 800.0 | 800.0 | 0 | 1 |
| hybrid | multi_step_reasoning | 25 | 0.92 | 0.92 | — | 0.004350 | 0.000189 | 2000.0 | 2000.0 | 0 | 0 |
| hybrid | doc_qa | 25 | 1.0 | 1.0 | — | 0.001659 | 0.000066 | 800.0 | 2800.0 | 0 | 3 |

## Métricas de portefólio

- Redução de custo por tarefa resolvida face a `always_expensive`: TODO: medir (com modelos reais)
- Latência p95 medida em providers reais: TODO: medir
- Custo real com `--max-usd`: TODO: medir

## Limitações

- Os perfis de qualidade dos mocks determinam o resultado; estas tabelas validam a mecânica, não o modelo.
- A latência é a do perfil mock (`sim.`), não tempo de rede.
- Não há juiz LLM: a correcção é programática (exacta ou F1 de campos).
