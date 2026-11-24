# CostPilot

Serviço de routing que escolhe, para cada pedido, **o modelo mais barato que ainda resolve bem a tarefa**,
e mede o **custo por tarefa resolvida** (`custo_total / tarefas_correctas`), não o preço por token.

Estado: **protótipo de demo**. Todos os resultados de custo e qualidade são **simulados** (providers mock
com preços fictícios). Não há números de poupança reais. Ver `reports/ablation.md`.

## O que existe

- `POST /route`: decisão explicável sem chamar nenhum provider (candidatos, exclusões com motivo, custo esperado).
- `POST /execute`: execução em cascata com validação programática, orçamento atómico por tentativa e cache segura.
- `/admin/*`: equipas e interruptor do autopilot, catálogo, custos por equipa/provider/tarefa, benchmark. Exige token.
- Painel React em `frontend/` (custos, routing, motivos, custo vs qualidade, interruptor).
- Benchmark em `bench/costpilot/` (100 tarefas sintéticas, três políticas, relatório marcado como simulado).
- Documentação de aprendizagem em `docs/learn/` (pt-PT).

## Arranque local

Requisitos: Python 3.12 e Node 24. Sem Docker e sem Redis, a demo usa stores em memória.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"          # Windows; em Linux/macOS: .venv/bin/pip
.venv/Scripts/ruff check backend bench && .venv/Scripts/ruff format --check backend bench
.venv/Scripts/pytest -m "not redis"            # testes; os de Redis real são ignorados sem servidor
```

API (factory, para não construir nada ao importar):

```bash
COSTPILOT_ADMIN_TOKEN=troca-isto uvicorn app.main:create_app --factory --app-dir backend --port 8000
# A equipa e o tenant vêm da chave de API (DEMO: cp-demo-suporte-2026). O corpo NÃO aceita team/tenant_id.
curl -s -X POST http://127.0.0.1:8000/route \
  -H "content-type: application/json" -H "authorization: Bearer cp-demo-suporte-2026" \
  -d '{"task_type":"json_extraction","input_tokens":500,"requires_json":true,"cost_ceiling_usd":"0.002"}'
# Sem chave ou com chave inválida: 401. Com "team" ou "tenant_id" no corpo: 422.
```

Painel (proxy `/admin` para `127.0.0.1:8000`):

```bash
cd frontend && npm ci && npm run dev     # ou: npm run build
```

Benchmark em mock (gera `reports/ablation.md` e `.json`):

```bash
python bench/costpilot/runner.py
python bench/costpilot/counterfactual.py
```

## Configuração

- `config/models.yaml`: catálogo, capacidades declaradas e perfis de mock (os `mock-*` são fictícios).
- `config/prices.yaml`: tabela de preços versionada (`effective_date`, USD, fonte).
- `config/policy.yaml`: alvos de qualidade, prior, limites de tentativas.
- `config/teams.yaml`: orçamento por equipa, modelo fixo e valor inicial do autopilot.
- `config/clients.yaml`: chaves de API → (tenant, equipa), só com SHA-256. Chaves de demo:
  `cp-demo-suporte-2026`, `cp-demo-marketing-2026`, `cp-demo-dados-2026`, `cp-demo-bench-2026`
  (**só para demonstração**). Produção: `COSTPILOT_CLIENTS_FILE` aponta para um ficheiro fora do repositório.
  Gerar um digest: `python -m app.auth.clients hash <chave>`.
- Variáveis de ambiente com prefixo `COSTPILOT_` (ver `backend/app/config.py`). **Não há `.env.example` nesta versão**
  (escrita bloqueada por regra de permissões): as variáveis estão documentadas em `backend/app/config.py`.

## Limitações conhecidas

- **Orçamento verificado com Redis real.** Em 2026-11-24, `pytest -m redis` passou contra Redis
  7.4.11: 50 de 100 reservas concorrentes aceites para o teto de 1 USD. A cache Redis ainda não
  foi verificada contra um servidor real.
- **Painel não verificado no browser.** O build passa; a verificação visual ficou pendente.
- **Docker e docker-compose não testados localmente** (Docker não disponível).
- **Autenticação só por chave estática (demo).** A equipa e o tenant vêm da chave (`config/clients.yaml`, só
  SHA-256). Faltam gestão de chaves, rotação, RBAC e limites de taxa para produção. Ver `docs/security-review.md`.
- **Sem migrações Alembic.** O esquema é criado no arranque (`create_all`).
- **Sem reposição mensal de orçamento.** O orçamento é cumulativo.

## Documentação

- `docs/architecture.md`: componentes e fluxos.
- `docs/decisions.md`: o que OpenRouter, LiteLLM e ModelMesh já fazem vs a contribuição deste projecto.
- `docs/case-study.md`: resultados medidos e o que falta medir.
- `docs/security-review.md`: revisão de segurança e estado de cada achado.
- `docs/learn/`: 00 a 07, com exemplos verificados por testes.
- `openspec/changes/bootstrap-costpilot/`: proposta, design, especificações e tarefas.
