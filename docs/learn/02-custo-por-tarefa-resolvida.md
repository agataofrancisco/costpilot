# 02 — Custo por tarefa resolvida

## O problema

O preço por token diz quanto custa uma chamada, não quanto custa uma resposta correcta. Um modelo barato
que falha 40% das vezes obriga a retries e a um modelo mais caro no fim; o custo real por resposta
correcta pode ser maior do que o de um modelo caro e fiável. A métrica do projecto é:

    custo por tarefa resolvida = custo_total / tarefas_correctas

onde `custo_total` inclui **todas** as tentativas (retries e escalonamentos) e `tarefas_correctas` conta só
as que passaram a validação programática.

## O que entra e o que sai

Entra um candidato com preço por milhão de tokens e uma crença de sucesso `p`. Sai um custo esperado
por tarefa, que a política usa para escolher.

Números reais dos testes (`backend/tests/test_policy.py::test_short_json_extraction_picks_cheapest_model_that_meets_quality`),
para um pedido `json_extraction` com 500 tokens de entrada e 128 de saída:

```text
custo de uma tentativa:  mock-cheap = 1.012e-4 USD   mock-mid = 4.42e-4 USD   mock-strong = 3.42e-3 USD
mock-strong excluído por over_cost_ceiling (tecto 0.002 USD)
E_cheap = 1.012e-4 + (1 - 0.8) * 4.42e-4 = 1.896e-4 USD   -> escolhido: mock-cheap
```

## Como funciona por dentro

- `attempt_cost_usd` (`backend/app/routing/policy.py:31`) calcula o custo de uma tentativa com os preços em vigor.
- `hard_exclusions` (`backend/app/routing/policy.py:41`) aplica os filtros duros; cada um devolve um motivo.
- `_autopilot_decision` (`backend/app/routing/policy.py:156`) calcula `E_k` do último candidato elegível para o primeiro,
  recursivamente: `E_k = c_k + (1 - p_k) * E_{k+1}`. Depois escolhe o `k` com menor `E_k`.
- A cadeia de escalonamento é o `k` escolhido seguido dos candidatos mais caros (`escalation_chain`).

A função `decide` (`policy.py:117`) não faz I/O. Recebe factos e devolve uma decisão, por isso o mesmo
código serve `/route`, `/execute` e a simulação contrafactual.

### Porque a recursão e não só o custo da tentativa

Escolher pelo custo da tentativa ignora a probabilidade de falhar. Com `E_k` um modelo barato com `p` alto ganha;
com `p` baixo perde para um intermédio, mesmo que este seja mais caro por tentativa. Um exemplo com números
(`test_expected_cost_prefers_stronger_model_when_cheap_one_is_unreliable`):

```text
p_cheap = 0.4 -> excluído por low_success_rate (abaixo do alvo 0.8)
p_cheap = 0.8 -> E_cheap = 1.896e-4 < E_mid = 4.42e-4 -> barato
```

## Porquê esta escolha

- O custo esperado é uma soma simples e explicável: um auditor consegue refazer a conta à mão.
- A restrição de qualidade (`p >= alvo`) é separada do custo: primeiro garante-se qualidade, depois minimiza-se custo.
  Um modelo sem qualidade nunca ganha só por ser barato.

## Alternativas

- **Minimizar só o custo da tentativa**: ignora retries; descartado.
- **Maximizar a qualidade**: sempre o modelo caro; é a baseline `always_expensive`.
- **Classificador aprendido (RouteLLM-like)**: citado no `design.md` como alternativa; fora de âmbito.

## Como falha

- Se `p` estiver mal calibrado (prior errado), a conta está errada. Por isso o histórico corrige o prior
  (`04-priors-beta-e-historico.md`).
- O custo esperado usa o tamanho de entrada declarado pelo cliente. Se estiver subestimado, a estimativa é baixa.
  A execução usa o máximo entre o declarado e o estimado a partir das mensagens.
- Testes: `backend/tests/test_policy.py` (escolha, exclusões, cadeia, `no_eligible_model`).

## Perguntas de entrevista

**Porque é que `E_cheap` inclui `(1 - p) * E_next` e não só `c_cheap`?**
Porque uma falha do barato obriga a pagar a tentativa seguinte. Sem esse termo, o barato parece sempre mais
barato, mesmo quando falha metade das vezes.

**O que é que a métrica não mede?**
Latência e qualidade fora da validação programática. Por isso a latência entra como filtro duro (SLA) e a
qualidade é medida com validadores e com o benchmark, não com juízes LLM não calibrados.

**Porque é que o custo esperado é `float` e o custo registado é inteiro?**
A decisão é uma comparação de scores; errar na 10.ª casa decimal não muda a escolha. O registo tem de ser exacto
para o orçamento, por isso usa micro-USD inteiros (`01-gateway-minimo-e-orcamento-atomico.md`).
