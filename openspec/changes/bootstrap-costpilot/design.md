# Design

## Context

O repositório está vazio e o projecto é independente. Motivação: ver `proposal.md`. Requisitos: ver `specs/`. O ModelMesh é um provider opcional, não uma dependência. Por isso o CostPilot tem o seu próprio gateway mínimo (adaptadores, preços, orçamento e registo de uso), deliberadamente mais simples do que o do ModelMesh: sem circuit breaker nem rate limiting.

## Goals / Non-Goals

**Goals:**
- Uma política simples, determinística e explicável, que bate as baselines **com medição**.
- A métrica central é o custo por tarefa resolvida (`custo_total / tarefas_correctas`).

**Non-Goals:**
- Routing por embeddings ou modelos de preferência aprendidos (como o RouteLLM). Ficam citados como alternativa.
- A cache semântica.

## Decisions

### D0 — Gateway mínimo próprio
- **Adaptadores:** a interface `ProviderAdapter.chat(request) -> Response | ProviderError`, com as implementações `openai_compatible`, `modelmesh` (aponta o `base_url` para o ModelMesh com uma chave virtual) e `mock` (perfis de qualidade e de falhas por "modelo", com seed).
- **Preços:** tabela `prices` carregada de YAML, com lookup pelo maior `effective_date <= agora`.
- **Orçamento:** um script Lua no Redis faz `spent + reserved + estimate <= budget` e incrementa `reserved` de forma atómica. A reconciliação acontece após a resposta e há TTL nas reservas. É a mesma técnica do ModelMesh, reimplementada de forma compacta e explicada no learn, com a referência ao ModelMesh para a versão completa.
- **Registo de uso:** em Postgres/SQLite, com tentativa, modelo, tokens, custo, motivo e `task_id`.
- *Porquê não depender do ModelMesh:* cada repositório tem de correr e ser avaliado sozinho. Com o ModelMesh configurado, o orçamento continua a ser verificado aqui (defesa dupla) e lá.

### D1 — Política como função pura com pontuação
`decide(task, catalog, history, constraints) -> Decision`:
1. **Filtro duro:** capacidades, sensibilidade, contexto, preço em vigor e circuito aberto.
2. **Custo esperado** por candidato: `E[custo] = custo_tentativa + (1 - p_sucesso) * E[custo_escalonamento]`, com `p_sucesso` do histórico por `(modelo, task_type)` e um prior quando não há dados.
3. **Restrição de qualidade:** `p_sucesso >= alvo[task_type]`.
4. Escolher o menor `E[custo]` que cumpre o SLA de latência p95.

É uma função pura, por isso é testável com fixtures e reutilizada pela simulação contrafactual.
- *Alternativa:* classificador ML (complexidade → modelo). Opcional e só depois de existirem dados. Exige uma avaliação holdout antes de ser activado.

### D2 — Escalonamento em cascata
É o padrão "cascade" (citado na literatura como FrugalGPT). A cadeia ordenada por custo é percorrida até a validação programática passar ou o tecto ser atingido. A validação é por tipo: schema Pydantic para JSON, label exacto para classificação, asserts para raciocínio, e citação/referência para perguntas de documentação.

### D3 — Prior de sucesso
Beta(α, β) por `(modelo, task_type)`, iniciado com um prior fraco, que dá `p = α/(α+β)`. É actualizado a partir do registo de uso. Isto evita confiar em 3 amostras e é uma boa pergunta de entrevista sobre exploração vs aproveitamento (explore/exploit).

### D4 — Cache
Redis com a chave `sha256(tenant|team|model|params_canonicos|messages_canonicas)` e um TTL. A elegibilidade é verificada antes de ler. Nunca se guardam respostas a pedidos sensíveis.

### D5 — Contrafactual
Reaproveita `decide()` sobre os logs: para cada pedido registado, calcula o modelo que a política alternativa escolheria. Só estima resultado quando existe uma observação desse modelo para a mesma tarefa (dataset de benchmark). Caso contrário marca `unknown` e não extrapola.

### D6 — Benchmark
`bench/costpilot/tasks.jsonl` e um runner que chama `/execute` com cada política fixada. Em mock, os mocks têm perfis de qualidade por "modelo" (por exemplo, o barato falha 25% em multi-step), declarados no relatório como simulação. Em real, usa modelos configurados e o tecto `--max-usd`.

### D7 — Documentação pedagógica
`docs/learn/` tem: `00-visao-geral`, `01-gateway-minimo-e-orcamento-atomico`, `02-custo-por-tarefa-resolvida`, `03-cascata-e-escalonamento`, `04-priors-beta-e-historico`, `05-cache-segura`, `06-contrafactual-e-ablacao` e `07-perguntas-de-entrevista`.

## Risks / Trade-offs

- [Os perfis de qualidade dos mocks determinam o resultado] → O resultado em mock serve só para validar a mecânica. As conclusões de portefólio exigem a execução real.
- [Poucos dados tornam o histórico enviesado] → Prior Beta e um mínimo de amostras antes de confiar.
- [O escalonamento aumenta a latência no pior caso] → Medido em p95 e limitado pelo SLA.
- [Uma cache mal configurada fuga dados] → Isolamento por chave e testes cross-tenant obrigatórios.

## Migration Plan

Projecto novo. O autopilot é activado por flag por equipa (por omissão desligado). Rollback: desligar a flag, e a equipa volta ao modelo fixo configurado.
