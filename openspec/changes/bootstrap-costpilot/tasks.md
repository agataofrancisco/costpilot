# Tasks

## 1. Fundações e gateway mínimo

- [x] 1.1 Criar `backend/app/{api,routing,catalog,providers,budget,cache,accounting}`, `bench/`, `reports/`, `frontend/` e `docs/learn/`; verificar com `git status`
- [x] 1.2 Confirmar e fixar versões (FastAPI, Pydantic v2, httpx, redis, SQLAlchemy, Alembic, pytest, fakeredis, Ruff); `Settings`, `.env.example`, `/health`; verificar que `ruff check` e `pytest` passam
- [x] 1.3 Implementar os adaptadores (`openai_compatible`, `modelmesh`, `mock` com perfis de qualidade e de falhas) e a taxonomia de erros; verificar com testes por tipo de falha
- [ ] 1.4 Implementar a tabela de preços versionada, o registo de uso e a reserva/reconciliação atómica do orçamento em Redis; verificar com o teste de 100 pedidos concorrentes contra 1 USD em Redis real (`-m redis`)
- [x] 1.5 Escrever `docs/learn/00-visao-geral.md` e `01-gateway-minimo-e-orcamento-atomico.md`; verificar o diagrama e a referência ao teste de concorrência

## 2. Catálogo

- [x] 2.1 Implementar o catálogo por configuração ligado à tabela de preços e a exclusão `pricing_missing`; verificar com testes
- [x] 2.2 Implementar as sondas de capacidade (mock/real) e `capability_mismatch`; verificar com teste de JSON mode falso
- [ ] 2.3 Implementar o histórico por `(modelo, task_type)` com prior Beta a partir do registo de uso; verificar com teste de actualização e de `low_success_rate`

## 3. Política e execução

- [ ] 3.1 Implementar `decide()` puro (filtros, custo esperado, alvo de qualidade, SLA) e `POST /route` com explicação; verificar com testes de escolha, exclusões e `no_eligible_model`
- [ ] 3.2 Implementar os validadores por tipo de tarefa e `POST /execute` com escalonamento, hard-limit por tentativa e contabilidade completa (retries, reasoning tokens, caching); verificar com testes de JSON inválido → escalonamento, escalonamento sem orçamento e custo das 2 tentativas
- [ ] 3.3 Implementar o interruptor por equipa, a restrição de sensibilidade e o comportamento com ModelMesh indisponível; verificar com testes
- [ ] 3.4 Escrever `docs/learn/02-custo-por-tarefa-resolvida.md`, `03-cascata-e-escalonamento.md` e `04-priors-beta-e-historico.md`; verificar os exemplos numéricos com testes

## 4. Cache

- [ ] 4.1 Implementar a cache com elegibilidade, isolamento, TTL e cabeçalho de hit; verificar com testes de temperatura > 0, equipas diferentes e hit com custo 0
- [ ] 4.2 Escrever `docs/learn/05-cache-segura.md`; verificar que os riscos têm testes

## 5. Benchmark e contrafactual

- [ ] 5.1 Criar o dataset de ≥100 tarefas (4 tipos) com critérios de correcção e validador; verificar com o validador
- [ ] 5.2 Implementar o runner das 3 políticas com as métricas da spec e o juiz opcional calibrado; verificar que gera o relatório em mock marcado `simulated`
- [ ] 5.3 Implementar a simulação contrafactual sobre logs, com `source` e `unknown` quando não há observação; verificar com teste
- [ ] 5.4 Correr o benchmark em mock e gravar `reports/ablation.md`; verificar que os campos de portefólio estão como `TODO: medir`
- [ ] 5.5 Escrever `docs/learn/06-contrafactual-e-ablacao.md`; verificar que os números citados vêm do relatório

## 6. Painel e entrega

- [ ] 6.1 Criar o painel (custo por equipa/provider/tarefa, gráfico custo vs qualidade, distribuição de routing, motivos, interruptor); verificar no browser
- [ ] 6.2 Testes de integração: orçamento sob concorrência com escalonamento, preço desactualizado, model mismatch, tokens não reportados, multi-tenant e provider indisponível; verificar que passam
- [ ] 6.3 Dockerfile, `docker-compose.yml` (marcado como não testado localmente) e CI (Ruff, pytest, `-m redis` com service, benchmark mock); verificar a validade
- [ ] 6.4 `README.md`, `docs/architecture.md`, `docs/decisions.md` (o que o OpenRouter/LiteLLM/ModelMesh já fazem vs a contribuição) e `docs/case-study.md`; verificar os comandos
- [ ] 6.5 `docs/learn/07-perguntas-de-entrevista.md` (≥25); verificar a consistência com o código
- [ ] 6.6 Revisão de segurança (orçamento, cache cross-tenant, chaves); verificar que os achados estão resolvidos ou documentados

## Workflow follow-up

- Execução real do benchmark com `--max-usd` para obter os números do portefólio.
- Arquivar a change após revisão.
