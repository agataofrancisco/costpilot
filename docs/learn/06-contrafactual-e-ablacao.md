# 06 — Contrafactual e ablação

## O problema

Para justificar uma política de routing é preciso comparar com alternativas simples sobre **as mesmas
tarefas**: sempre o modelo caro, sempre o barato, e a política híbrida. Sem isso, qualquer poupança
é uma afirmação sem prova. Um segundo problema é honestidade: com providers mock, os números são
simulados, e publicá-los como poupança real seria enganador.

## O que entra e o que sai

Entra um dataset de 100 tarefas sintéticas (25 por tipo) com critério de correcção programático.
Sai `reports/ablation.md` e `reports/ablation.json`, com uma tabela por política e tipo de tarefa.

Resultados do run de 2026-11-21 (modo **mock, simulado**; commit `d397900` com alterações não commitadas):

| Política | Resolvidas | Custo total (sim.) USD | Custo / tarefa correcta (sim.) USD | Escalonamentos |
|---|---|---|---|---|
| always_expensive (`mock-strong`) | 0.97 | 0.027750 | 0.000286 | 0 |
| always_cheap (`mock-cheap`) | 0.69 | 0.000910 | 0.000013 | 0 |
| hybrid (routing) | 0.97 | 0.013924 | 0.000144 | 7 |

Leitura: o híbrido manteve a taxa de resolução do modelo caro com cerca de metade do custo simulado, e
o barato resolveu só 69%. Estes números dependem dos perfis de qualidade e dos preços fictícios; não são
uma medição de modelos reais.

Saída real do contrafactual (`python bench/costpilot/counterfactual.py`):

```text
"source": "synthetic: bench mock (reports/ablation.json)",
"alternative_policy": "always_expensive",
"requests": 100, "estimated": 100, "unknown": 0,
"actual_cost_usd_for_estimated": "0.013924",
"alternative_cost_usd_for_estimated": "0.027750",
"alternative_correct_for_estimated": 97
```

## Como funciona por dentro

- `runner.py` (`bench/costpilot/runner.py`) corre cada política numa base de dados **nova**
  (`run_policy`), para o histórico de uma não contaminar a outra. Usa a API real via `TestClient`.
- As baselines são `policy_override` (`always_expensive` = `mock-strong`, `always_cheap` = `mock-cheap`).
  Só funcionam com `COSTPILOT_ALLOW_POLICY_OVERRIDE=true` (bench) e saltam o filtro de qualidade.
  Mantêm o filtro de preço e de provider, porque sem preço não há orçamento.
- O oráculo do mock (`make_oracle`) devolve a resposta esperada da tarefa. O mock decide se acerta com
  um sorteio determinístico (`MockAdapter._draws`, seed 7). Por isso o run é reproduzível.
- A correcção é programática: exacta para classificação, citação e `FINAL:`; F1 de pares campo=valor para JSON
  (`field_f1`). Não há juiz LLM, por isso nenhuma métrica depende de juízo não calibrado.
- `summarize` calcula o custo por tarefa resolvida como `custo_total / tarefas_correctas`, a métrica central
  (`02-custo-por-tarefa-resolvida.md`).
- `counterfactual.simulate` (`bench/costpilot/counterfactual.py`) estima o custo da política alternativa **só** onde
  existe observação para a mesma tarefa. Sem observação, conta `unknown` e não extrapola.

## Porquê esta escolha

- **Mesmas tarefas, mesma validação, mesmo oráculo** para as três políticas: a única variável é a política.
- **Base de dados nova por política**: sem isto, o histórico do híbrido herdaria resultados das baselines.
- **Simulação marcada**: o relatório começa com um aviso e as métricas de portefólio ficam `TODO: medir`.
  Isto segue a regra da especificação: nenhuma poupança sem logs reais.

## Alternativas

- **Juiz LLM calibrado** para respostas abertas: é opcional na spec e não foi implementado. Sem amostra
  com labels humanos, não contaria para as métricas principais de qualquer forma.
- **Logs reais de produção**: o único caminho para uma poupança publicável. Depende de chaves e de orçamento
  (`--max-usd`), que não existem nesta execução.

## Como falha

- **O resultado é o dos perfis de qualidade**. Se `mock-cheap` for declarado com 0.9 e na realidade acertar 0.5,
  o híbrido escolhe-o mal. Por isso o relatório diz que valida a mecânica, não o modelo.
- **Latência é simulada**: vem do perfil mock, não de tempo de rede. Por isso aparece com `(sim.)`.
- **Contrafactual com observação própria é uma comparação, não uma previsão**: onde a observação existe, mede
  o que aconteceu; não estima o que aconteceria noutra distribuição de tarefas.
- Testes: `backend/tests/test_bench.py` (dataset com 100 tarefas e critério, rejeição de dataset inválido, F1,
  correcção de JSON e de `FINAL:`, `unknown` no contrafactual).

## Perguntas de entrevista

**Porque é que o híbrido resolve tanto como o caro, se o barato só resolve 69%?**
Porque a política escolhe o barato quando a sua crença de sucesso está acima do alvo para aquele tipo de tarefa
(classificação, por exemplo), e escala para o forte nos tipos em que o barato falha (raciocínio multi-passo). A
conta é por tipo, não global.

**Porque é que `always_cheap` tem custo por tarefa correcta baixo mas resolve pouco?**
Porque o custo por tarefa correcta divide por menos tarefas correctas. Um sistema barato e errado parece barato
no preço por token, mas o custo por resposta correcta revela a falha. Por isso a métrica é o custo por resolvida.

**Como sabes que o resultado não é um acidente do seed?**
O run é determinístico com seed 7. Não há intervalo de confiança porque é uma única execução com um dataset fixo; um
relatório final exigiria várias seeds e tamanhos de amostra maiores, e isso ficou como trabalho futuro.
