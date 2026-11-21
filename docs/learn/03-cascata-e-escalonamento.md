# 03 — Cascata e escalonamento

## O problema

A política escolhe o modelo barato com base numa estimativa. A estimativa falha: a resposta pode não ser
válida (JSON mal formado, label errada, resposta final ausente). Sem um mecanismo de recuperação, o pedido
falha ou exige um operador. A cascata tenta o modelo seguinte da cadeia quando a validação programática falha.
Este padrão é o "cascade" do FrugalGPT.

## O que entra e o que sai

Entra um pedido com `validation` (critério programático) e a cadeia ordenada por custo. Sai um resultado com
todas as tentativas, cada uma com estado, motivo e custo.

Números reais dos testes de execução (`backend/tests/test_execute.py`), com modelos mock controlados:

```text
test_invalid_json_escalates_and_both_attempts_are_counted
  attempts: [validation_failed (mock-cheap), ok (mock-mid)]
  total_cost_usd = soma das duas tentativas; orçamento gasto = mesmo valor (em micro-USD)

test_escalation_without_budget_returns_budget_exceeded_with_spent_cost   (orçamento 150 micro-USD)
  1.ª tentativa: reserva 53 micro-USD (pior caso), custo real 4 micro-USD
  2.ª tentativa: reserva 197 micro-USD -> 4 + 197 = 201 > 150  -> 402 budget_exceeded, spent_usd = 0.000004
```

## Como funciona por dentro

- `_run_chain` (`backend/app/routing/executor.py:228`) percorre a cadeia. Para no primeiro resultado validado.
- `_attempt` (`executor.py:330`) faz a reserva do pior caso, chama o provider, reconcilia com o custo real e valida.
- `validate_output` (`backend/app/routing/validators.py:66`) decide se a resposta conta. Recebe texto do modelo
  (dados não confiáveis): nunca lança excepção por causa do conteúdo.
- `_over_request_ceiling` (`executor.py:312`) impede escalar se o pior caso da próxima tentativa ultrapassa o tecto de custo
  pedido. O resultado indica `stop_reason: over_cost_ceiling`.
- Limite duro: `policy.max_attempts` (3 no `config/policy.yaml`) corta a cadeia.

### Regra de custo quando há falha do provider

`failure_charge_micro` (`backend/app/routing/accounting_rules.py:23`):

- `unavailable`, `rate_limited`, `auth`, `model_not_found`, `bad_request`: custo 0, porque o provider não processou o pedido.
- `timeout`, `upstream_error`, `invalid_response`: cobra-se a reserva inteira, marcada como estimada. Pode ter havido
  processamento e cobrança, e subestimar seria pior do que sobrestimar.

## Porquê esta escolha

- A validação é programática e barata. Um juiz LLM seria mais flexível, mas o `proposal.md` exige calibração antes de contar.
- Escalar só após falha de validação (e não após qualquer resposta) evita pagar duas vezes quando o barato acerta.
- Cada tentativa reserva e reconcilia separadamente (`reservation = f"{task_id}:{index}"`), para que um escalonamento
  recusado pelo orçamento não deixe reservas órfãs.

## Alternativas

- **Escalar sempre para o modelo forte**: é a baseline `always_expensive`; descartado por custo.
- **Votação entre modelos**: custa várias tentativas por pedido; fora de âmbito.
- **Juiz LLM como validador**: exige calibração com labels humanos (ver `06-contrafactual-e-ablacao.md`).

## Como falha

- Um validador demasiado permissivo deixa passar respostas erradas, e a cascata nunca escala. Por isso cada
  tipo tem um critério exacto: label normalizado, schema tipado, `FINAL:` exacto, citação literal.
- Um validador demasiado restrito escala sem necessidade e aumenta o custo. Mede-se na taxa de escalonamentos do benchmark.
- Testes: `test_validators.py` (inclui entradas hostis que não lançam excepção), `test_execute.py` (escalonamento,
  orçamento na escalada, falha de provider, tecto de custo).

## Perguntas de entrevista

**Porque é que a reserva é do pior caso e não do custo esperado?**
Porque o limite tem de ser garantido antes da chamada. O custo esperado pode ser excedido por uma resposta longa;
o pior caso (`input * preço_in + max_output * preço_out`) nunca é excedido, salvo se o provider reportar mais
tokens do que o máximo pedido. Esse caso fica documentado como limitação.

**Se a 2.ª tentativa for recusada pelo orçamento, o que acontece à resposta da 1.ª?**
Não é devolvida como sucesso: a resposta é 402 com o custo já gasto e as tentativas. O cliente sabe o que foi gasto
e porquê, e a 1.ª resposta (inválida) não é apresentada como resultado.

**Porque é que um timeout cobra a reserva?**
Porque não sabemos se o provider processou o pedido. A regra é conservadora: sobrestimar o gasto protege o
orçamento; subestimar cria dívida invisível.
