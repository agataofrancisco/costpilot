# Proposal

## Why

Usar sempre o modelo caro desperdiça dinheiro. Usar sempre o barato degrada a qualidade e pode sair mais caro por causa dos retries e das falhas. O CostPilot é um serviço de routing que escolhe, para cada pedido, **o modelo mais barato que ainda resolve bem a tarefa**, e mede o **custo por tarefa resolvida** em vez do preço por token. O OpenRouter e o LiteLLM já fazem routing; a contribuição aqui é uma política calibrada com um dataset, com restrições de qualidade mensuráveis e uma prova experimental contra baselines simples.

Funciona sozinho (com um gateway mínimo compatível com OpenAI e providers mock) e pode usar o **ModelMesh** como provider, quando estiver disponível, para herdar as quotas, os orçamentos e o failover de lá.

Domínio fictício: a equipa de plataforma da **Órbita Tech** (as equipas `suporte`, `marketing` e `dados`), o mesmo do ModelMesh, para que os dois projectos se liguem numa demo.

## What Changes

- Projecto novo em `projects/costpilot`: FastAPI, PostgreSQL (logs e custos; SQLite em demo), Redis (orçamentos e cache) e painel React ou Streamlit.
- `POST /route` (decisão explicável sem executar) e `POST /execute` (executa através de um adaptador de provider, com hard-limit de orçamento).
- Adaptadores de provider: compatível com OpenAI (OpenRouter/OpenAI), ModelMesh (opcional) e mocks com perfis de qualidade e de falhas.
- Catálogo de modelos com capacidades (JSON mode, tool use, contexto máximo) validadas no arranque e uma tabela de preços versionada própria (`effective_date`, moeda e fonte).
- Política determinística inicial baseada em `task_type`, tamanho do input, requisitos de JSON/ferramentas, SLA, sensibilidade, histórico de sucesso e tecto de custo. Um classificador ML é opcional e só entra depois de avaliado.
- Escalonamento em cascata: tentar um modelo barato e subir para um mais forte quando uma validação programática falha. O custo de todas as tentativas é contado.
- Cache de respostas apenas para pedidos seguros e determinísticos, isolada por tenant.
- Simulação contrafactual offline sobre logs anonimizados ou sintéticos, sempre marcados como tal.
- Benchmark com 100 ou mais tarefas em 4 tipos, comparando `always_expensive`, `always_cheap` e a política híbrida. Relatório `reports/ablation.md` só com valores medidos.
- Painel: custo por equipa/provider/tarefa, gráfico custo vs qualidade, distribuição de routing, motivos das decisões e interruptor do autopilot.
- Documentação de aprendizagem em `docs/learn/`.

## Capabilities

### New Capabilities
- `cost-aware-routing`: decisão de modelo por restrições e custo, explicação, execução, escalonamento, orçamento e interruptor.
- `model-catalog`: capacidades dos modelos validadas, preços versionados e histórico de sucesso.
- `response-cache`: cache segura, isolada por tenant e com regras de elegibilidade.
- `cost-quality-benchmark`: dataset de tarefas, baselines, simulação contrafactual e relatório de ablação.

### Modified Capabilities
<!-- Nenhuma: projecto novo. -->

## Impact

- **Código novo**: `backend/app/{api,routing,catalog,providers,budget,cache,accounting}`, `bench/`, `reports/`, `frontend/` e `docs/`.
- **Dependências** (confirmar versões): FastAPI, Pydantic v2, httpx, redis-py, SQLAlchemy/Alembic, pytest e Ruff. scikit-learn só se o classificador opcional for avaliado.
- **Integração opcional**: o ModelMesh como provider. Sem ele, o CostPilot usa o seu próprio gateway mínimo e o seu controlo de orçamento.
- **Infraestrutura**: Redis para a atomicidade dos orçamentos (testes `-m redis`). Sem Docker local, os testes unitários usam fakes.
- **Fora de âmbito**: routing semântico com embeddings, cache semântica, failover multi-provider avançado (é o papel do ModelMesh).
