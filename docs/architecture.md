# Arquitectura

## Componentes

```mermaid
flowchart TB
    subgraph API[backend/app/api]
        R[POST /route]
        E[POST /execute]
        A[/admin/*]
    end
    subgraph ROUT[backend/app/routing]
        RT[Router: factos + decide]
        P[policy.decide puro]
        X[Executor: cascata]
        V[validators]
    end
    subgraph CAT[backend/app/catalog]
        C[Catalog + prices]
        F[facts]
        H[history Beta]
        PR[probes JSON mode]
    end
    subgraph BUD[backend/app/budget]
        B[(Redis Lua / memória)]
    end
    subgraph CACHE[backend/app/cache]
        K[(Redis / memória)]
    end
    subgraph PROV[backend/app/providers]
        M[mock]
        O[openai_compatible]
        MM[modelmesh = openai_compatible + chave virtual]
    end
    subgraph ACC[backend/app/accounting]
        U[(SQLite / PostgreSQL usage_records)]
    end
    R --> RT --> P
    E --> X --> RT
    X --> V
    X --> B
    X --> K
    X --> PROV
    X --> U
    RT --> F --> C
    F --> H --> U
    F --> PR
    A --> U
    A --> B
```

## Fluxo de um pedido `/execute`

1. Autenticação: `Authorization: Bearer <chave>` -> SHA-256 -> principal fixo `(tenant, equipa)` em `config/clients.yaml`.
   Chave em falta, mal formada ou desconhecida: `401 unauthorized`, antes de qualquer leitura do orçamento.
2. Validação de fronteira (Pydantic): corpo sem `team` nem `tenant_id` (`extra="forbid"`, senão `422`), tipos, tamanhos,
   critério de validação compatível com o tipo. A equipa e o tenant são acrescentados a partir do principal (`TaskRequest.to_task`).
3. `Router.route`: factos por candidato (preço em vigor, capacidades, sondas, histórico Beta) e a política `decide`.
4. Sem candidato elegível: `422 no_eligible_model` com os conflitos.
5. Cache (só se elegível): chave por tenant, equipa, modelo, parâmetros e mensagens. Hit: custo 0.
6. Para cada modelo da cadeia (máximo `max_attempts`):
   - reserva atómica do pior caso (`budget.reserve`); recusa -> `402 budget_exceeded` e registo `budget_rejected`;
   - chamada ao provider (adaptador);
   - falha: cobra-se 0 ou a reserva, conforme a regra de `accounting_rules.py`; passa ao seguinte;
   - sucesso: custo real (tokens reportados ou estimados), reconciliação, validação;
   - validação ok: resposta, cache (se elegível), `200`.
7. Sem sucesso: `503 upstream_unavailable` se nenhum provider respondeu; `200` com `resolved: false` se a validação falhou.

## Invariantes

- `spent + reserved <= limite` salvo quando uma reserva expira antes da reconciliação (TTL > timeout do provider).
- Toda a tentativa gera exactamente uma linha em `usage_records`.
- Montantes em micro-USD inteiros; a conversão para USD é só na apresentação.
- Nenhuma resposta de cache cruza tenant ou equipa.

## Persistência

| Dado | Onde | Notas |
|---|---|---|
| Orçamento e reservas | Redis (Lua) ou memória | Hash tag `{equipa}` |
| Cache de respostas | Redis ou memória | TTL configurável |
| Registo de uso | SQLite (demo) / PostgreSQL | Única fonte para histórico e painel |
| Interruptor do autopilot | SQLite | Sobrepõe `config/teams.yaml` |

Migrações Alembic não estão geradas: o esquema é criado com `create_all` no arranque. **TODO**.
