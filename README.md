# Order To Cash — Python

> 🚧 **In progress.** This repository is being built phase by phase; the table at the bottom tracks exactly how far it has got. Everything described as done is done and verified — nothing here is aspirational.

An **order-to-cash lifecycle backbone** for a B2B EDI / e-invoicing platform, built as event-driven microservices. It models the classic EDI exchange as a distributed workflow:

**Order (ORDERS) → Stock reservation → Credit check → Order confirmation (ORDRSP) → Despatch advice (DESADV) → Invoice (INVOIC) → Payment (remittance)**

— with an orchestrated **saga** coordinating the flow across services and **compensating** when a step fails. Deliberately B2B in shape: the retailer never pays at order time; a credit check gates despatch, and payment arrives at the end of the cycle, within payment terms.

## The trilogy, and what makes this repository different

This is **assessment #9 of three**, all implementing the *same* specification on different stacks:

| # | Backend | Frontend | Write DB | Repository |
|---|---------|----------|----------|------------|
| 7 | NestJS 11 | Nuxt 4 + shadcn-vue | MySQL 8 | [`peelmicro/order-to-cash-nestjs`](https://github.com/peelmicro/order-to-cash-nestjs) — complete |
| 8 | .NET 10 | Next.js + shadcn/ui | MS-SQL Server | [`peelmicro/order-to-cash-dotnet`](https://github.com/peelmicro/order-to-cash-dotnet) — complete |
| **9** | **Python 3.14 (FastAPI)** | **Angular 22 (Analog) + spartan/ui** | **PostgreSQL 18** | **this repository** — in progress |

#7 wrote the stack-agnostic specification and the AI agent harness. #8 reused both and measured what that was worth: the specification removed design time, but verification could not be reused, and what transferred most completely was not code but **#7's review findings**. **#9 is the second reuse run.** It copies the specification, the harness, the four n8n demo workflows and the stack-agnostic infrastructure from #8 — and it writes #8's review findings into its backlog as **acceptance criteria from day one**, instead of waiting to rediscover them. So this repository asks the question only a second reuse can answer:

> Does a second re-implementation go differently from the first — and is what it inherits mostly specification, or mostly the previous run's review findings?

Per-feature effort (sessions, wall-clock) is recorded in `progress/history.md` against **both** #7's and #8's baselines, together with every inherited finding that was avoided or recurred. The README will close with the three-way comparison and an honest reading of it, including what was **not** faster.

## Spec amendments

Where an implementation proves the shared specification wrong or incomplete, the change is an **amendment**: explicit, committed on its own, and applied to every repository of the trilogy in the same session — never a silent fork. Each carries a stable `SA-n` id and an entry in the `progress/history.md` of every repository it touches. #9 inherits the five raised during #8, already applied to #7 and #8 and therefore present in the copy this repository started from:

| Id | Raised | Touches | In one line |
|---|---|---|---|
| `SA-1` | #8, Phase 3 | `test-matrix.md` — the reset recipe | The recipe described the paragraphs to delete by listing them in one copy, which made it false once followed; reworded to describe the class |
| `SA-2` | #8, Phase 13 | `asyncapi.yaml` — `OrderCancelledPayload` | The REST contract promised the operator's cancellation note would reach the timeline, but the fact had no field to carry it; an optional `note` added |
| `SA-3` | #8, Phase 14 | `asyncapi.yaml` — dead-letter headers | `x-first-failed-at` and `x-failed-at` were undefined, and #7 and #8 filled the silence differently; both defined |
| `SA-4` | #8, Phase 14 | `saga.md`, `openapi.yaml`, `asyncapi.yaml` — operator cancel | An operator cancel released the credit hold before the stock a despatch could still consume; the order of compensation was corrected |
| `SA-5` | #8, Phase 16 | `openapi.yaml` — money formatting | Clients were told to format money from a field no REST response carries; the ISO 4217 exponent named instead |

Any amendment raised here will be `SA-6` onwards, applied to #7, #8 and #9 together.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend runtime | Python 3.14 with full type hints (`mypy --strict`), managed with `uv` as a workspace |
| Web framework | FastAPI, async throughout — consumers, responders and the outbox relay run as asyncio tasks from each app's lifespan |
| CQRS (in-process) | Hand-rolled command/query dispatcher with startup validation — no DI framework, explicit composition roots |
| Inter-service transport | aiokafka (domain facts) + nats-py (request-reply RPC, core only — no JetStream) |
| Write databases | PostgreSQL 18 — `otc_orders`, `otc_fulfillment`, `otc_billing`, `otc_notifications` |
| Persistence | SQLAlchemy 2 (async) + asyncpg, Alembic migrations per service |
| Read model | MongoDB through PyMongo's async API — the denormalised `order_timeline` collection |
| Saga orchestrator | Hand-rolled, in the Orders service, with the same command and ignored-fact tables as #7 and #8 |
| Observability | OpenTelemetry Python → OTel Collector → Jaeger (traces) + Prometheus → Grafana; structlog JSON logs |
| Email | aiosmtplib → Mailpit container; console adapter behind the same port for tests |
| Frontend | Angular 22 on Analog, spartan/ui + Tailwind CSS v4, TanStack Query, SSE with reconnect; the browser never talks to the Gateway (a Nitro server BFF does) |
| Backend testing | pytest + testcontainers-python (real PostgreSQL / Kafka / NATS / MongoDB — brokers are never mocked) + httpx |
| Web testing | Vitest + Angular Testing Library (components), Playwright (end-to-end) — no Jest, Karma or Jasmine |
| Architecture enforcement | import-linter — `domain` may not import SQLAlchemy, Kafka, NATS, MongoDB, FastAPI or Pydantic, and no service may import another |
| Demo automation | n8n — the same four workflow JSONs as #7 and #8, Gateway REST API only |
| Infrastructure | Docker Compose |

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| uv | **0.12.22** | Installs the interpreter too: `uv python install 3.14` |
| Python | **3.14** (resolved to 3.14.8) | Pinned in `.python-version` |
| Node.js | **24.19.0** (LTS) | Pinned in `.nvmrc` — `nvm use`. **Web app only**; the backend has no Node dependency |
| pnpm | **12.8.1** | Used only inside `apps/web`, pinned by its `packageManager`; `quality.sh` runs it as `npx pnpm@12.8.1`, so a different global pnpm does not matter |
| Docker | 29.x + Compose | |

## Repository layout

What exists today, and what arrives later:

```
specs/shared/        the stack-agnostic specification — copied verbatim from #8
n8n/workflows/       the four demo workflows — copied unchanged
progress/            the agent harness's external memory, including the effort records
.claude/agents/      the seven subagents (leader, spec author, implementer, reviewer, …)
docs/PROCESS.md      how this project is built — the process guide
docker-compose.infra.yml   the infrastructure stack (15 services, compose project `otcpy`)
infra/               PostgreSQL bootstrap, Kafka topic script, OTel Collector, Prometheus, Grafana, n8n import
.env.example         every variable the compose file reads, with dev defaults
pyproject.toml, uv.lock   the uv workspace: dev tools, ruff, mypy --strict, pytest, coverage, import-linter contracts
packages/            shared_kernel (Money, GLN, …, zero dependencies), contracts (generated wire models), cqrs (placeholder)
services/            gateway, orders, fulfillment, billing, notifications, projector, seed — each domain/application/infrastructure/presentation;
                     orders, fulfillment, billing and notifications also carry alembic/ (one migration history per database)
conftest.py          the shared integration fixture: one Docker-held postgres:18.6 per test session, a template database per service, a fresh database per test
tests/               architecture guards; database_parity/ (outbox/processed_events identical across the four databases, read from the live catalogs);
                     fixtures/golden_envelopes/ (the wire-parity oracle, copied from #8)
apps/web/            the Analog (Angular 22) app — scaffold only until phase 16
scripts/             generate_contracts.py (models from asyncapi.yaml/openapi.yaml, --check for drift), git hooks
quality.sh           the single quality gate
```

## Running what exists so far

The quality gate runs today — format, lint, `mypy --strict`, import-linter, the contracts drift check, pytest with coverage gates (≥60% overall, ≥80% domain) and the web app's install, Vitest and build:

```bash
uv sync
./quality.sh            # exit 0 = every gate passed; otherwise the first failing step's exit code
```

Integration tests start their own PostgreSQL container through testcontainers, so the gate needs Docker but **not** the development stack — it passes with the stack stopped.

The infrastructure runs too; the services arrive from phase 8.

```bash
cp .env.example .env
docker compose -f docker-compose.infra.yml --profile n8n up -d
docker compose -f docker-compose.infra.yml --profile n8n ps      # 12 healthy; kafka-init and n8n-init exit 0
```

| What | Where |
|---|---|
| PostgreSQL 18 — `otc_orders`, `otc_fulfillment`, `otc_billing`, `otc_notifications`, plus n8n's own `n8n` database | `localhost:5432` |
| MongoDB (read model) | `localhost:27017` |
| Kafka (KRaft) — 3 fact topics + 3 `.dlq`, created from `asyncapi.yaml` | `localhost:9092`; Redpanda Console at http://localhost:8080 |
| NATS, core only (no JetStream) | `localhost:4222`; monitoring at http://localhost:8222 |
| Mailpit | SMTP `localhost:1025`; inbox at http://localhost:8025 |
| Jaeger / Prometheus / Grafana | http://localhost:16686 · http://localhost:9090 · http://localhost:3030 |
| n8n (the four workflows, imported inactive) | http://localhost:5678 |

The stack uses #8's host ports, so only one of the three trilogy stacks can run at a time. `down -v` wipes it.

The four write databases get their schema from each service's Alembic history (async template, no sync driver; the credentials come from `.env`):

```bash
for s in orders fulfillment billing notifications; do uv run alembic -c services/$s/alembic.ini upgrade head; done
docker exec otcpy-postgres psql -U postgres -d otc_notifications -c '\d'    # processed_events and alembic_version only
```

## How this is being built

The development **process is a deliverable**, not a footnote: Spec-Driven Development plus an agent harness with a backlog state machine (`feature_list.json`, max one feature in progress), external memory (`progress/`), a specification that precedes the code, and separate leader / spec-author / implementer / reviewer subagents each with an explicitly declared model. Every large feature passes a human approval gate at its specification, and every phase is tested by a human before its commit. `docs/PROCESS.md` explains all of it; the git history is the evidence, and for this repository it reads **harness first, specification copy second, code after**.

## Build progress

| Phase | What | Status |
|-------|------|--------|
| 1 | Environment & repository | ✅ Python 3.14 via uv; the whole backend dependency set and an Analog web stack verified in throwaway probes; account-explicit remote; `.gitignore` proven both ways |
| 2 | Harness layer, copied from #8 and re-pointed | ✅ 43-feature backlog with #8's review findings as acceptance criteria; `init.sh` verified to exit 1 on 16 break cases; copy cost measured per file |
| 3 | Shared specification, copied verbatim from #8 | ✅ six of seven files byte-identical to #8's **and** #7's (`cmp`-proven); `test-matrix.md` reset by the `SA-1` recipe, columns 1–4 identical on all 63 rows; zero stack leaks |
| 4 | Infrastructure compose + Kafka topics & NATS subjects | ✅ PostgreSQL 18.6 replaces MS-SQL; healthy from empty volumes in 39–44 s; the database healthcheck proven unable to pass during bootstrap; n8n isolated in its own database by permissions; 6 Kafka topics and 15 NATS subjects verified against the spec |
| 5 | uv workspace scaffold, shared kernel, contracts, architecture contracts, web scaffold | ✅ seven services in four layers under 10 import-linter contracts plus an import allowlist for every domain; an AST guard against `float`, `/`, `decimal` and `fractions` in domain code; `Money` in integer minor units with no major-unit surface; wire models generated from the spec with a drift check, proven against #8's 12 golden envelopes (envelope byte-exact, payload semantically equal); the Analog web app building under pnpm 12; every guard seen failing before it was trusted |
| 6 | SQLAlchemy models + Alembic migrations for the four write databases | ✅ four Alembic histories; types, foreign keys (8 / 2 / 3), indexes and relations asserted as closed sets from the live catalogs, never from the ORM; `json` payloads read back byte-identical; `bigint` money from the first migration (#8 id 44 avoided); counters seeded with `ON CONFLICT DO NOTHING` under 16 concurrent first callers (#8 id 45 avoided — its racy seed, kept as a sentinel, loses every round); outbox/processed_events parity across all four databases; a write-boundary range check on every integer column; every feature approved on its first review |
| 7 | Deterministic seed job | ⬜ |
| 8 | Orders service + saga orchestrator | ⬜ |
| 9 | Fulfillment service | ⬜ |
| 10 | Billing service | ⬜ |
| 11 | Notifications service | ⬜ |
| 12 | Projector service + MongoDB read model | ⬜ |
| 13 | Gateway / BFF | ⬜ |
| 14 | Health checks, OTel propagation, retry + DLQ | ⬜ |
| 15 | End-to-end saga verification | ⬜ |
| 16 | Angular (Analog) web app | ⬜ |
| 17 | Web component tests | ⬜ |
| 18 | API tests through the Gateway | ⬜ |
| 19 | Playwright end-to-end tests | ⬜ |
| 20 | n8n demo workflows, reused unchanged | ⬜ |
| 21 | Quality gates (ruff, mypy, import-linter, coverage) | ⬜ |
| 22 | Prometheus, Grafana, Jaeger verification | ⬜ |
| 23 | Full Docker Compose | ⬜ |
| 24 | Documentation, demo recording, **#7 vs #8 vs #9 benchmark** | ⬜ |
| 25 | Final checkpoint | ⬜ |

## Licence

[MIT](LICENSE).
