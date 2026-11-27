# CostPilot

**Route each LLM request to the cheapest model that still gets it right, and measure cost per
*solved* task, not price per token.**

Always using the expensive model wastes money. Always using the cheap one degrades quality and can
end up costing more per correct answer once retries and failures are counted. CostPilot picks a
model for each request with an explainable cascade policy. It validates the output
programmatically, escalates only when validation fails, and charges every attempt against an atomic
per-team budget. The headline metric is `total_cost / correct_tasks`.

> Prototype for demonstration. Providers are mocks with fictional prices, so the numbers below are
> simulated and are **not** real savings.

## Highlights

- **Explainable routing.** `POST /route` returns the decision without calling any provider: the
  candidates, the exclusions with reasons, and the expected cost.
- **Cascade with validation.** `POST /execute` tries the cheapest suitable model, validates the
  result (JSON schema and task checks), and escalates only on failure. Every attempt is recorded.
- **Atomic budgets.** Each attempt reserves budget before it calls the model, then reconciles the
  real cost. 100 concurrent requests never exceed the cap, verified against a real Redis.
- **Safe cache.** Cache keys are scoped so entries never cross teams or tenants (tested).
- **Counterfactual benchmark.** The same 100 synthetic tasks run under three policies, plus a
  counterfactual ablation.
- **Admin dashboard.** A React panel shows cost by team, provider and task, cost against quality,
  the routing distribution, exclusion reasons and the autopilot switch.

## Results (simulated, mock providers)

From [`reports/ablation.md`](reports/ablation.md), seed 7:

| Policy | Tasks solved | Total cost (sim.) | Escalations |
|---|---|---|---|
| always_expensive | 97/100 | $0.027750 | 0 |
| always_cheap | 69/100 | $0.000910 | 0 |
| **hybrid (CostPilot)** | **97/100** | **$0.013924** | 7 |

In this simulation, the hybrid policy matches the expensive model's quality at about half the cost.
The cheap-only policy fails 28 more tasks. **Read with care:** the quality profiles and prices are
fictional. This shows the mechanism works (the cascade escalates exactly where the cheap model
fails, and the budget counts every attempt). It doesn't show what real models would do. Real
savings, p95 latency and real spend are `TODO: measure`.

**Real-infrastructure proof:** 100 concurrent reservations of $0.02 against a $1 budget on real
Redis gave exactly 50 accepted, $1.00 final spend and no dangling reservations. This was measured
against Redis 7.4.11 and re-verified on 2026-11-27 against 7.4.12.

## How a request flows

```mermaid
flowchart LR
    C[Client<br/>API key] --> R[Routing policy<br/>quality target + prior]
    R --> CA{Cache<br/>scoped per team}
    CA -->|hit| OUT[Response]
    CA -->|miss| B[Reserve budget<br/>atomic]
    B --> M1[Cheapest model]
    M1 --> V{Validate}
    V -->|ok| REC[Reconcile cost] --> OUT
    V -->|fail| B2[Reserve again] --> M2[Next model up]
    M2 --> V
```

## Tech stack

Python 3.12 · FastAPI · Redis (atomic reservation) · SQLAlchemy · Pydantic v2 · React 19 + Vite ·
pytest + fakeredis · Ruff · Docker Compose

## Run it locally (no Docker, no Redis needed)

Without Redis, the demo uses in-memory stores.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
COSTPILOT_ADMIN_TOKEN=change-me uvicorn app.main:create_app --factory --app-dir backend --port 8000
```

```bash
curl -s -X POST http://127.0.0.1:8000/route \
  -H "content-type: application/json" -H "authorization: Bearer cp-demo-suporte-2026" \
  -d '{"task_type":"json_extraction","input_tokens":500,"requires_json":true,"cost_ceiling_usd":"0.002"}'
```

The team and tenant come from the API key, never from the request body. A body that includes
`team` gets a 422 response.

```bash
cd frontend && npm ci && npm run dev          # dashboard
python bench/costpilot/runner.py              # benchmark -> reports/ablation.md
python bench/costpilot/counterfactual.py
```

Demo API keys, for demonstration only: `cp-demo-suporte-2026`, `cp-demo-marketing-2026` and
`cp-demo-dados-2026`. Only their SHA-256 digests are stored.

**Docker with real Postgres and Redis.** Verified on 2026-11-27: `/health` reports
`budget_backend: redis` and `database: postgresql`, and `/route` answers. That run also caught and
fixed a missing PostgreSQL driver in the image.

```bash
COSTPILOT_ADMIN_TOKEN=change-me docker compose up --build
```

## Quality checks

```bash
ruff check backend bench && ruff format --check backend bench
pytest -m "not redis"                                       # 174 tests
COSTPILOT_TEST_REDIS_URL=redis://localhost:6379/15 pytest -m redis
```

## Known limitations

- **Mock providers only:** no real model has been called.
- **Partial Redis coverage:** the Redis cache and the full HTTP path haven't been verified against
  a real Redis. Only the budget path has.
- **Demo auth only:** static API keys, with no rotation, RBAC or rate limiting
  ([`docs/security-review.md`](docs/security-review.md)).
- **Simple schema handling:** no Alembic migrations (`create_all`), and budgets accumulate with no
  monthly reset.

## Documentation

- [`docs/architecture.md`](docs/architecture.md), [`docs/case-study.md`](docs/case-study.md)
- [`docs/decisions.md`](docs/decisions.md): how this differs from OpenRouter, LiteLLM and ModelMesh.
- [`docs/learn/`](docs/learn/) (Portuguese): the minimal gateway and atomic budgets, cost per
  solved task, cascades, Beta priors, safe caching, and counterfactual ablation, plus interview
  questions.
