# 05 — Cache segura

## O problema

Pedidos repetidos pagam duas vezes e demoram o mesmo. Uma cache resolve isso, mas cria riscos novos:
servir a resposta de um tenant a outro, servir uma resposta que devia variar (temperatura > 0), ou guardar
respostas de dados sensíveis. Uma cache mal configurada é pior do que nenhuma.

## O que entra e o que sai

Entra um pedido com `cache: true`. Sai um hit (custo 0, cabeçalho `x-modelmesh-cache: hit`) ou um miss
(execução normal, e a resposta validada é guardada).

Saída real do teste de TTL e chaves (`backend/tests/test_cache.py`, 5 testes passam): chaves diferentes
para equipa, tenant, modelo, `max_tokens` e mensagens diferentes; a fronteira entre campos não colide
(`team="a|b", tenant="c"` ≠ `team="a", tenant="b|c"`); a entrada expira exactamente em `ttl`.

## Como funciona por dentro

- `cache_eligibility` (`backend/app/cache/eligibility.py:14`) é verificada **antes de ler**, não só antes de gravar.
  Ordem: pedido não pede cache -> temperatura diferente de 0 -> ferramentas -> sensibilidade alta.
- A equipa e o tenant **não vêm do corpo**: vêm do principal associado à chave de API (`backend/app/api/auth.py`).
  Um corpo com `team` ou `tenant_id` é rejeitado com 422. Assim, a chave de um cliente não consegue escolher
  a partição de cache de outro, nem sequer quando o corpo mente.
- `cache_key` (`backend/app/cache/keys.py:21`) faz SHA-256 sobre tenant, equipa, modelo, parâmetros e mensagens
  canónicas (JSON com chaves ordenadas). Os campos são separados por U+001F, que não aparece no JSON canónico.
- No executor (`backend/app/routing/executor.py`, método `execute`), a chave usa o **primeiro** modelo da cadeia.
  Um pedido escalado é guardado sob a chave do modelo que a próxima leitura pediria.
- Só se guardam respostas `ok`. Uma resposta inválida nunca entra na cache.
- Um hit regista uma linha `cache_hit` com custo 0 (`_cache_hit`) e não cria tentativas.

## Porquê esta escolha

- **Tenant e equipa sempre na chave**: o isolamento é uma propriedade da chave, não de uma verificação posterior.
  Se a verificação fosse posterior, um erro de código serviria respostas cruzadas.
- **Elegibilidade estrita**: só temperatura 0 é determinística o suficiente para reutilizar uma resposta.
- **TTL**: limita o tempo em que uma resposta pode estar desactualizada.

## Alternativas

- **Cache semântica** (embeddings): mais hits, mas aproximações podem servir respostas erradas. Fora de âmbito.
- **Verificação do tenant depois da leitura**: rejeitada, pelo motivo acima.

## Como falha

Riscos e testes correspondentes:

| Risco | Mitigação | Teste |
|---|---|---|
| Resposta de uma equipa servida a outra | tenant e equipa na chave, vindos da chave de API | `test_cache_is_not_shared_between_teams`, `test_cache_is_not_shared_between_tenants_of_the_same_team` (`test_auth.py`) |
| Corpo que afirma outra equipa para usar a cache dela | `team`/`tenant_id` rejeitados no corpo (422) | `test_team_in_body_is_rejected_with_422` (`test_auth.py`) |
| Temperatura > 0 reutilizada | elegibilidade estrita | `test_non_zero_temperature_is_never_cached` |
| Hit com custo | hit não cria tentativa; custo 0 | `test_cache_hit_is_marked_and_costs_nothing` |
| Colisão entre campos da chave | separador fora do JSON | `test_field_boundaries_cannot_collide` |
| Expiração ignorada | TTL na entrada | `test_entries_expire_after_ttl` |
| Dados sensíveis guardados | `sensitivity=high` não é elegível | `test_eligibility_is_strict` |

**Limitação conhecida**: a cache Redis não foi verificada contra Redis real (ver `01-gateway-minimo-e-orcamento-atomico.md`).
O código usa `SET ... EX`, que é padrão, mas o comportamento de TTL só está verificado em memória.

## Perguntas de entrevista

**Porque é que a elegibilidade é verificada antes da leitura?**
Porque ler uma entrada de cache que não devia ser lida já é um vazamento se a resposta for devolvida
ou registada. A decisão tem de ser antes do acesso.

**Porque é que a chave inclui `max_tokens`?**
Mudar o limite de tokens muda a resposta (uma resposta truncada não é igual a uma completa). Incluí-lo evita
servir uma resposta truncada a um pedido que pedia mais.

**Porque é que o cabeçalho se chama `x-modelmesh-cache`?**
É o nome definido na especificação (`specs/response-cache`), herdado do ModelMesh. Não é um erro de copia para este
projecto; fica documentado para que quem integre não se surpreenda.
