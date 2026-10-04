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
| pnpm | **12.8.1** | Used only inside `apps/web` |
| Docker | 29.x + Compose | |

## Repository layout

What exists today, and what arrives later:

```
specs/shared/        the stack-agnostic specification — copied verbatim from #8
n8n/workflows/       the four demo workflows — copied unchanged
progress/            the agent harness's external memory, including the effort records
.claude/agents/      the seven subagents (leader, spec author, implementer, reviewer, …)
docs/PROCESS.md      how this project is built — the process guide
                     — from phase 4: infra/ and the compose files
                     — from phase 5: pyproject.toml (uv workspace), packages/, services/, apps/web/
```

## How this is being built

The development **process is a deliverable**, not a footnote: Spec-Driven Development plus an agent harness with a backlog state machine (`feature_list.json`, max one feature in progress), external memory (`progress/`), a specification that precedes the code, and separate leader / spec-author / implementer / reviewer subagents each with an explicitly declared model. Every large feature passes a human approval gate at its specification, and every phase is tested by a human before its commit. `docs/PROCESS.md` explains all of it; the git history is the evidence, and for this repository it reads **harness first, specification copy second, code after**.

## Build progress

| Phase | What | Status |
|-------|------|--------|
| 1 | Environment & repository | ✅ Python 3.14 via uv; the whole backend dependency set and an Analog web stack verified in throwaway probes; account-explicit remote; `.gitignore` proven both ways |
| 2 | Harness layer, copied from #8 and re-pointed | ✅ 43-feature backlog with #8's review findings as acceptance criteria; `init.sh` verified to exit 1 on 16 break cases; copy cost measured per file |
| 3 | Shared specification, copied verbatim from #8 | ✅ six of seven files byte-identical to #8's **and** #7's (`cmp`-proven); `test-matrix.md` reset by the `SA-1` recipe, columns 1–4 identical on all 63 rows; zero stack leaks |
| 4 | Infrastructure compose + Kafka topics & NATS subjects | ⬜ |
| 5 | uv workspace scaffold, shared kernel, contracts, architecture contracts, web scaffold | ⬜ |
| 6 | SQLAlchemy models + Alembic migrations for the four write databases | ⬜ |
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
