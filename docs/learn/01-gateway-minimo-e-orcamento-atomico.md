# 01 — Gateway mínimo e orçamento atómico

## O problema

Uma equipa não pode gastar mais do que o orçamento, mesmo com 100 pedidos a chegar ao mesmo tempo.
Um check-then-act clássico (ler o saldo, decidir, gravar o gasto) falha sob concorrência: dois
pedidos leem o mesmo saldo e ambos passam. O orçamento tem de ser uma operação atómica.

## O que entra e o que sai

Entra uma reserva: `(equipa, id da reserva, montante máximo estimado, limite)`.
Sai `accepted` e o estado (`spent`, `reserved`). Depois da resposta do provider, entra a
reconciliação com o custo real, e sai o novo `spent`.

Saída real do teste de concorrência (100 pedidos de 0,02 USD contra um orçamento de 1 USD, 16 threads,
executado com `fakeredis` que corre o Lua via `lupa`):

```text
memoria: aceites=50 recusados=50 spent_micro=1000000 (1.000000 USD) reserved_micro=0
fakeredis+Lua: aceites=50 recusados=50 spent_micro=1000000 (1.000000 USD) reserved_micro=0
```

Os 50 recusados não consumiram nada: a recusa acontece antes de qualquer gasto.

## Como funciona por dentro

```mermaid
sequenceDiagram
    participant C as Pedido (thread)
    participant R as Redis (script Lua)
    participant P as Provider
    C->>R: RESERVE(limite, montante_max, rid, agora, expira)
    R->>R: remove reservas expiradas
    alt spent + reserved + montante_max > limite
        R-->>C: accepted=0 (nada é gasto)
    else cabe no orçamento
        R->>R: reserved += montante_max; regista rid
        R-->>C: accepted=1
        C->>P: chamada ao modelo
        P-->>C: resposta com usage
        C->>R: RECONCILE(rid, custo_real)
        R->>R: reserved -= montante_max; spent += custo_real
    end
```

- O montante é em **micro-USD inteiros** (`budget/money.py:15`, `usd_to_micro_ceil`). Sem floats, a
  soma das reservas é exacta, e o arredondamento para cima é conservador.
- A reserva e a verificação acontecem no mesmo script Lua (`budget/redis_store.py:20`, `RESERVE_LUA`).
  O Redis executa scripts sem intercalação, por isso não há janela entre o `GET` e o `INCRBY`.
- A reconciliação (`budget/redis_store.py:51`, `RECONCILE_LUA`) liberta a reserva e soma o custo real.
  Se a reserva já tiver expirado, o custo real é cobrado na mesma: o dinheiro foi gasto.
- O store em memória (`budget/store.py:56`, `InMemoryBudgetStore`) segue a mesma regra com um `Lock`.
  Um contrato único (`backend/tests/test_budget.py`) corre contra as duas implementações.
- O hash tag `{equipa}` mantém as chaves de uma equipa no mesmo nó num cluster Redis.

### Adaptadores e taxonomia de erros

`providers/openai_compatible.py:47` (`chat`) traduz cada falha para um tipo da taxonomia
(`providers/base.py`): `timeout`, `rate_limited`, `upstream_error`, `unavailable`, `auth`,
`model_not_found`, `bad_request`, `invalid_response`. Só as falhas transitórias são `retriable`.
Uma falha de ligação (`ConnectError` ou `ConnectTimeout`) é `unavailable`: o pedido nunca chegou ao
provider, por isso não há custo. Um `ReadTimeout` é `timeout`: o provider pode ter processado o pedido.

A resposta é interpretada por `providers/parsing.py` sem confiança: qualquer campo com formato
inesperado vira `invalid_response` em vez de exceção. Os tokens são `reported=False` quando faltam,
e o custo fica marcado como estimado.

Saída real dos testes de adaptadores (servidor HTTP falso em socket real):

```text
test_each_failure_type_is_classified[rate-rate_limited] PASSED
test_each_failure_type_is_classified[server-upstream_error] PASSED
test_each_failure_type_is_classified[auth-auth] PASSED
test_each_failure_type_is_classified[notfound-model_not_found] PASSED
test_each_failure_type_is_classified[badreq-bad_request] PASSED
test_each_failure_type_is_classified[badjson-invalid_response] PASSED
test_each_failure_type_is_classified[emptychoices-invalid_response] PASSED
test_timeout_is_reported_as_timeout PASSED
test_unreachable_provider_is_unavailable PASSED
```

## Porquê esta escolha

- **Lua em vez de transacções Redis (`WATCH`/`MULTI`)**: um script é uma única operação do ponto de
  vista do servidor e não há retry de optimistic locking sob contenção.
- **Reserva pelo máximo estimado**: é a única forma de garantir o limite antes de saber o custo real.
  O preço do pior caso é `input * preço_in + max_output * preço_out`.
- **TTL nas reservas**: se o processo cair a meio, o orçamento não fica bloqueado para sempre. A
  configuração obriga `reservation_ttl >= provider_timeout + 5 s` (`config.py`), porque uma reserva que
  expira antes da resposta do provider permite sobre-comprometer o orçamento.
- **IDs das reservas**: cada tentativa usa `task_id:index`. O `task_id` tem de ser único enquanto
  uma reconciliação atrasada ainda puder chegar. O store recusa uma segunda reserva com o mesmo ID
  enquanto a primeira estiver ativa. Após o TTL, o ID já não está ativo; se for reutilizado antes
  de a chamada antiga terminar, uma reconciliação tardia pode atingir a reserva nova. Por isso,
  clientes que fornecem `task_id` devem enviar um identificador globalmente único, e não um número
  sequencial reiniciado por processo.

## Alternativas

- **Check-then-act com lock distribuído**: mais lento e mais frágil (lock sem fencing token pode
  expirar com um cliente ainda a trabalhar).
- **Contadores eventualmente consistentes**: admitem ultrapassar o limite por uma margem não limitada.
- **Só cobrar depois da resposta**: deixa passar todos os pedidos concorrentes que chegam antes da
  primeira reconciliação.

## Como falha

Os testes em `backend/tests/test_budget.py` cobrem: recusa sem efeitos colaterais, reconciliação que
liberta orçamento, reserva expirada libertada, reconciliação tardia que ainda cobra, isolamento entre
equipas, valores negativos rejeitados e 100 pedidos concorrentes (`test_hundred_concurrent_requests_never_exceed_one_dollar`).

**Verificado contra Redis real em 2026-11-24.** O teste
`backend/tests/test_budget_redis_real.py`, marcado com `-m redis`, passou contra Redis 7.4.11
local (`1 passed, 174 deselected`). Cem reservas concorrentes de 0,02 USD contra 1 USD
resultaram em 50 aceites, gasto final de 1 USD e zero reservas pendentes. Sem
`COSTPILOT_TEST_REDIS_URL`, o teste continua a ser ignorado.

## Perguntas de entrevista

**Porque é que a reconciliação não pode simplesmente subtrair a reserva e somar o custo?**
Porque a reserva pode já ter expirado e sido libertada pela purga. A reconciliação procura a reserva:
se existir, liberta-a; se não existir, cobra só o custo real. Em ambos os casos o `spent` fica certo.

**O que acontece se um pedido morrer depois de reservar e antes de reconciliar?**
A reserva expira ao fim do TTL e é libertada na próxima operação do orçamento. Se o provider chegou
a processar o pedido, o custo pode ficar por reconciliar: é um risco conhecido. O `task_id` não deve
ser reutilizado enquanto essa chamada antiga ainda puder terminar, para impedir que uma reconciliação
tardia seja confundida com uma reserva nova.

**Porque é que os montantes são inteiros?**
Floats acumulam erro de arredondamento e o Lua trabalha com doubles. Micro-USD inteiros dão soma exacta
para qualquer número de pedidos no intervalo típico, e o arredondamento para cima garante que nunca se
subestima o custo.
