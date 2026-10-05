# How this project is built — the process guide

> **What this is:** the complete explanation of the development process used in this repository — the concepts, the cast of agents, the workflow, and a registry of every process artifact. If you cloned this repo and want to understand *how* it was built (or replicate the pattern), start here.
>
> **Maintenance rule:** this document is updated at the end of every phase — the artifact registry (§9) and "Where the project is right now" (§10) must always reflect reality. A stale process guide is a defect.
>
> **About this repository specifically:** this is assessment **#9** of a three-stack trilogy. The process described here was *built* in [#7 (`order-to-cash-nestjs`)](https://github.com/peelmicro/order-to-cash-nestjs), reused and hardened in [#8 (`order-to-cash-dotnet`)](https://github.com/peelmicro/order-to-cash-dotnet), and is **reused here a second time** — the specification, the harness, the agent definitions and the demo workflows were copied from #8. That makes this repository the trilogy's closing measurement: §10 tracks effort against two baselines, and §11 starts empty because #7's and #8's findings belong to them.

---

## 1. The premise

This repository is built almost entirely by AI agents (Claude Code), with a human making the judgment calls, testing every phase, and owning every commit. **The development process is itself a deliverable**: the assessment behind this project scores not only the software but whether the process artifacts show real use and whether a stranger could replicate the pattern.

For this repository there are two questions on top: **does reusing a mature process actually help?**, which #8 already asked, and **does a second reuse go differently from the first** — in particular, are the previous run's *review findings*, inherited as acceptance criteria from day one, worth more than its specification? The honest answer requires recording effort per feature against #7's and #8's numbers — including the features where reuse saved nothing, and every inherited finding that was avoided or recurred — which is what `progress/history.md` exists for here.

The process combines two ideas that are often confused. They stack — the harness is the foundation, SDD sits on top.

---

## 2. Layer 1 — The harness

### The problem it solves

An AI agent has two structural weaknesses: **it has no memory between sessions**, and **it will do the wrong thing very fast and very confidently**. Left alone, agent-built projects rot in predictable ways — three features each 70% finished, tests that assert nothing, state that silently contradicts itself, a README describing software that does not exist.

The harness is a set of plain files that give the agent an external brain and a set of rails. None of it is magic; all of it is discipline made mechanical.

### The parts, and why each exists

**External memory** (`progress/`). Between sessions the agent remembers nothing, so everything worth remembering is written to disk *while working, not at the end*: what is in flight (`current.md`), what was finished and what it cost (`history.md`), and each agent's own report of what it did (`impl_*.md`, `review_*.md`, `spec_*.md`). A new session reads these and continues as if it had never stopped. This was proven mid-build: a session died between a review rejection and the fix; the next session resumed exactly where the loop stopped, from the files alone.

**A backlog with a state machine** (`feature_list.json`). Work is decomposed into features, each with a status:

```
pending → spec_ready → in_progress → in_review → done
                                          ↓
                                       blocked
```

Two rules carry most of the value. **Max one feature `in_progress`** — because parallel half-finished work is how agent projects rot; one-at-a-time makes "finished" mean something. And **only the reviewer sets `done`** — the agent that wrote the code never gets to declare it correct.

**A circuit breaker** (`init.sh`). Run at the start of every session. It checks that the environment is sane (uv runs the Python pinned in `.python-version`, the lockfile matches the workspace, Node and pnpm for the web app, Docker), the harness files exist, every agent declares its model, the backlog parses and obeys its own rules, and — crucially — that any spec-required feature past `pending` actually has its spec on disk. **If it exits non-zero, the session must not advance.** Its checks were adversarially verified: the state was deliberately broken four different ways and each was caught. A check that has never been seen failing is a convention, not a gate.

**Conventions that are enforced, not requested** (`CLAUDE.md` + tooling). The rules that matter are backed by machinery: domain purity is an import-linter contract that fails the build, not a paragraph; money as integer minor units is a value object that throws, not a guideline; "no Jest" is greppable. When an agent violates house style, the fix is usually to make the rule more explicit or more mechanical — not to correct the agent by hand and hope.

**Objective completion criteria** (`CHECKPOINTS.md`). "Am I done?" is a feeling; the checkpoints are yes/no questions a reviewer walks: harness complete? state coherent? architecture respected? verification real? session closed cleanly? SDD followed? artifacts reusable? A session does not close with an applicable box unchecked.

**Specialised agents** (`.claude/agents/`) — see §3.

### What the harness is *not*

It is not specific to this project, this stack, or even to SDD. The harness layer alone is worth adopting in any AI-assisted repository. It is also not tooling-heavy: every artifact is markdown, JSON or bash, readable in an editor, diffable in git.

---

## 3. Layer 2 — SDD (Spec-Driven Development)

### The problem it solves

For large features, the expensive mistakes are made **before any code is written** — a wrong invariant, a missing compensation path, an ambiguous contract between services. Code review catches coding mistakes; nothing catches *specification* mistakes unless the specification exists as an artifact someone can review.

SDD inverts the usual order: write the specification first, in a notation precise enough to be testable, get a human to approve it, and only then implement. The spec — not the code — is the source of truth. When code and spec disagree, the code is wrong (or the spec gets amended *first*, visibly).

### How it works here

- **`specs/shared/`** holds the system-wide specification, written in Phase 3 before any application code: the domain model and its invariants, the saga with both compensation paths, 63 EARS requirements, an AsyncAPI document (every event and RPC message), an OpenAPI document (the REST contract), a test matrix mapping every requirement to the test that proves it, and the functional spec of the demo workflows. It is deliberately **stack-agnostic**: written in #7, reused verbatim by #8 and now by this repository, with every amendment (`SA-n`) applied to all three.
- **`specs/<feature>/`** (from Phase 8 onward) holds a per-feature triple-doc for the 8 *large* features only — `requirements.md` (EARS), `design.md` (the stack-specific how), `tasks.md` (an ordered checklist the implementer ticks). These features carry `"sdd": true` in the backlog.
- **The human approval gate**: a spec-required feature stops at `spec_ready` until the human has reviewed the spec's *decisions* (see §6) and approved. No code before approval — and the git history proves the ordering, because the spec commit precedes the implementation commit.

### The honesty clause

SDD costs real ceremony, and for a 50-line feature the ceremony is decorative paperwork. That is why only 8 of this project's 43 planned features carry `"sdd": true` — the aggregates and state machines, the saga and its compensation, the outbox and idempotency, the read-model projection, and the observability wiring. Everything else skips the triple-doc but still travels the backlog state machine. The spec-becomes-infrastructure moments (Kafka topics derived from the AsyncAPI file, Pydantic models and TypeScript types generated from both API documents) are where the spec pays for itself even on small features.

---

## 4. The cast — who does what

Eight roles: seven agents defined in `.claude/agents/`, plus the human. Each agent definition declares which Claude model it runs on (or documents that it deliberately inherits the session's model) and which tools it may use — both are design decisions, not defaults.

| Role | Model | Tools (the deliberate part) | Job |
|---|---|---|---|
| **The human** | — | everything, including the only `git commit` | Approves specs, adjudicates judgment calls, tests every phase, owns the git history |
| `leader` | unpinned — inherits the session model | has the **Agent** tool; never edits `services/`, `packages/` or `apps/` | Decomposes work, launches the other agents, maintains the backlog and session state, stops at every human gate |
| `spec_author` | unpinned | Read/Write, **no code execution focus** | Writes `specs/` — EARS requirements, designs, task lists. Never writes application code or tests |
| `implementer` | `sonnet` | full edit + bash | Implements **one** feature against its approved spec, writes its tests, self-verifies |
| `reviewer` | unpinned | **read-only — no Write, no Edit** | Approves or rejects the implementer's work; the only role that sets `done` on full-group work |
| `premise_checker` | `sonnet` | Bash, Read — **no edit** | Fact-checks every claim in a brief or recommendation *before* it is acted on, one VERIFIED / FALSE / UNVERIFIABLE line per claim. Added in #8, where a wrong brief cost a whole implementer cycle |
| `test_maintainer` | `haiku` | edit but **no bash** | Mechanical test updates after landed changes — retitles, flips assertions, fixes flaky timeouts. Never touches source |
| `suite_runner` | `haiku` | Bash, Read — **no edit** | Runs one long, noisy command and returns exit code, counts and verbatim failure blocks. Interprets nothing — which is why delegating to it does not weaken the do-not-trust-reports rule |

### The reasoning behind the model pinning

- `leader`, `spec_author`, `reviewer` are unpinned so they get the strongest available tier: decomposition, specification and adversarial review are the highest-judgment work, and the spec is inherited by two more assessments.
- `implementer` runs on a mid-tier model *because the thinking has already been done* — the spec or the acceptance list is the decision; implementation is faithful execution, and it happens ~30 times across the build.
- `test_maintainer` and `suite_runner` run on the cheapest tier because their work is bounded and pattern-following by construction; `premise_checker` on the mid tier because it must be cheap enough that running it is never a budget decision.

### Two design choices that are easy to miss

**The reviewer cannot write.** It has no Edit/Write tool *by design*. A reviewer that can fix what it finds becomes a second implementer — and nobody reviews the reviewer. Its only outputs are a verdict file and status changes. This had teeth in #7 and #8, where the reviewer rejected features the implementer reported as fully verified, by probing the running system and finding the report wrong. Whether it keeps them here is recorded in §11 as this build produces its own reviews.

**Agents write to files, not to chat** (the anti-telephone-game rule). A subagent's deliverable is a file (`specs/<feature>/`, `progress/impl_*.md`); what returns to the leader is only a reference. Every hop through a chat summary loses detail; a file does not degrade, survives the session, and becomes the audit trail the process is scored on.

---

## 5. The loop — a feature's life, concretely

What actually happens when a large (`"sdd": true`) feature is built:

```
 1. leader: ./init.sh green? read current.md + feature_list.json
    │
 2. leader launches spec_author
    │    writes specs/<feature>/{requirements,design,tasks}.md
    │    sets status: spec_ready
    │    returns only: "spec_ready → specs/<feature>/"
    │
 3. ⏸ HUMAN GATE — the human reviews the spec's DECISIONS (§6) and
    │  approves or asks for changes. Nothing proceeds without this.
    │
 4. leader sets in_progress, launches implementer
    │    implements from the spec (not from its own idea of the feature)
    │    writes the tests INSIDE the feature — green before handover
    │    writes progress/impl_<feature>.md
    │    sets status: in_review
    │
 5. leader launches reviewer
    │    probes the running system — never trusts the report
    │    walks CHECKPOINTS.md, verifies requirement→test traceability
    │    writes progress/review_<feature>.md
    │    APPROVED → done + effort record in history.md
    │    REJECTED → in_progress, back to step 4 with a precise defect list
    │
 6. ⏸ HUMAN GATE — the leader reports what was done and how to test it
    │  manually. The human tests. Only then is the phase closed and committed.
```

Small features (`"sdd": false`) skip steps 2–3 and implement directly from their acceptance list — but never skip the review or either human gate.

The rejection path is not theoretical — #8's reviewer rejected a large share of its features at least once, almost always for a guard that could not fail rather than for wrong code. The loop's value *is* those catches; this repository's own count is kept in §11.

---

## 6. EARS — the requirements notation

EARS (Easy Approach to Requirements Syntax) constrains every requirement to one of five shapes, which makes vagueness structurally difficult:

| Pattern | Shape | Used for |
|---|---|---|
| Ubiquitous | THE SYSTEM SHALL … | invariants, always true |
| Event-driven | WHEN ‹trigger›, THE SYSTEM SHALL … | reactions to facts/commands |
| State-driven | WHILE ‹state›, THE SYSTEM SHALL … | behaviour during a condition |
| Unwanted | IF ‹condition›, THEN THE SYSTEM SHALL … | error and edge cases |
| Optional | WHERE ‹feature present›, THE SYSTEM SHALL … | configuration-dependent behaviour |

A real one from this project's spec:

> **R27.** WHEN a `credit.rejected.v1` fact is received for an order in status `stock_reserved`, THE SYSTEM SHALL issue a stock release command, and SHALL NOT set the order to `cancelled` until `stock.released.v1` has been observed.

What makes it good: a named trigger, a named precondition, an explicit prohibition with ordering — every clause is something a test can fail on. Contrast: *"the system shall handle credit rejection gracefully"* — nothing can fail that; it is a wish, not a requirement.

Every requirement carries a stable id (`R1`…`R61`), and `specs/shared/test-matrix.md` maps each id to the named test that proves it. A feature is not `done` while its matrix rows are red or missing. This is the traceability chain: requirement → test → green.

---

## 7. What "reviewing a spec" actually means

The most misunderstood human task in the whole process, so it gets its own section.

When an agent writes a specification from a task document, it repeatedly hits places where the source is **ambiguous**, and it must *decide*. Those decisions then bind every downstream phase. Reviewing the spec means **reviewing those decisions — not proof-reading the prose**. If the decisions are right, the prose follows.

The mechanism: the spec author records every ambiguity it resolved in a table (what was unclear → what was decided → why → where it is recorded). In #7, the original spec pass surfaced **13 such decisions** (its `progress/spec_shared_passA.md` §4) — which fact drives `paid` vs `completed`, whether compensation releases stock before or after cancelling, whether an RPC reply may ever advance the saga (it may not — only facts do). The human read a 13-row table, not 7,500 lines, and pushed back where it mattered.

A useful instinct for the human: pay most attention to decisions that **add** something the source document never mentioned — that is where an agent has invented policy. (Here: what happens when an operator cancels an order after stock is reserved and credit is held. The task document was silent; the spec author designed the unwind rule; the human approved it knowingly.)

---

## 8. The rhythm of a phase, and common confusions

### The rhythm

Every phase runs the same shape:

1. `./init.sh` — refuse to start from a broken state.
2. Do the work through the loop (§5), one feature at a time.
3. **Stop.** The leader reports *what was done* and *how to test it manually* — exact commands, expected output.
4. The human runs the commands and verifies.
5. The human authorises the close. Only then:
6. **The phase-close ritual**: commit (one commit per phase/feature, message naming every package installed and why) → update the private build-plan document → refresh `README.md` → update this document (§9 registry + §10 status) → brief the next phase.

The agents never run `git commit` or `git push` of their own accord. The commit history is reviewed process evidence; every commit is something the human personally verified. That is also why the history reads spec-first: the ordering is the proof.

### Common confusions

**"Why is there a spec *and* a plan?"** The plan (kept outside this repository) is the build order — phases, sequencing, decisions log. The spec (`specs/shared/`) is the system's definition — what the software must do, independent of schedule. The plan changes as the build learns; the spec changes only when requirements change, and visibly.

**"Why can't the agent just commit?"** Because a commit is a claim that something works, and only the person who tested it can make that claim — on a public portfolio repository, under their own name.

**"Why max one feature in progress?"** An agent will cheerfully leave three features 70% done. One at a time makes "finished" meaningful and keeps the effort records honest.

**"Does the human read everything the agents produce?"** No. The human reads the *decision tables* and the *verdicts*, spot-tests the system, and trusts the adversarial loop for the rest. The full artifacts exist for when they are needed — and for the assessor.

**"What happens when an agent is wrong?"** The reviewer rejects with a precise defect list and the loop repeats. If the same class of mistake recurs, the fix goes into `CLAUDE.md` or the agent's own definition — the process is corrected, not just the instance.

**"Is any of this specific to Claude?"** The file formats assume Claude Code's subagent mechanism (`.claude/agents/`), but the pattern — external memory, backlog state machine, circuit breaker, spec gate, adversarial review, human commit gate — is tool-agnostic.

---

## 9. The artifact registry

Every process artifact in this repository: what it is for, and where it came from. The **Origin** column records whether an artifact was copied from #8, copied and re-pointed, or genuinely written here, because that distinction is the measurement. ("Updated" means meaningful content change, not status ticks.)

| Artifact | The problem it solves | Useful to know | Origin | Created | Last updated |
|---|---|---|---|---|---|
| `AGENTS.md` | "Where does an agent start?" — the entry map | Read order, hard rules, the SDD flow, session-close procedure | Copied from #8, re-pointed (repository map rows and hard rules) | Phase 2 | Phase 2 |
| `CLAUDE.md` | "How do we do things here?" — binding conventions | Leader role, cost discipline, porting rules, architecture, coding/testing conventions, commit discipline. Amended at human gates, so nothing may quote the copy injected into its context | Copied from #8, **rewritten for Python** — structure and stack-agnostic rules kept, every stack rule replaced, phase 1's findings added as conventions | Phase 2 | Phase 2 |
| `docs/lessons.md` | "Why does this rule exist?" — the incident record | #8's archived full `CLAUDE.md`, with the evidence behind each inherited rule. Read only for the *why* | **Copied unchanged from #8** | Phase 2 | never |
| `feature_list.json` | "What is happening right now?" — the backlog state machine | 43 planned features, 8 `sdd: true`. Ids and names are #8's so the three-way benchmark joins on them; new entries start at 200. Max one `in_progress`, enforced by `init.sh` | #8's planned features **reset to `pending`**, acceptance criteria adapted, #8's review findings written in as criteria; one new feature (`public_readme`) | Phase 2 | every feature transition |
| `init.sh` | "Is the world sane?" — the session circuit breaker | Exit ≠ 0 ⇒ do not advance. Environment (uv, Python, lockfile, Node, pnpm, Docker), harness files, agent model declarations, backlog and SDD coherence, session-file lockstep, superseded rules, backlog tripwire, commit-msg hook, shared-spec parity | Copied from #8; environment section rewritten for uv; backlog validator **byte-identical**; the shared-spec parity check now compares against **#8 and #7** and refuses to report OK on an empty population | Phase 2 | Phase 2 |
| `CHECKPOINTS.md` | "Am I actually done?" — objective close criteria | C1–C7; the reviewer walks them | Copied from #8; C3–C4 re-pointed to Python; **C7 rewritten** for the second reuse — adds the inherited-findings and three-way benchmark boxes | Phase 2 | Phase 2 |
| `.claude/agents/*.md` (×7) | Role separation with different powers and cost tiers | Each declares model + tools; reviewer deliberately read-only; test_maintainer deliberately bash-less | Copied from #8 with **model lines byte-identical**; conventions re-pointed to Python | Phase 2 | Phase 2 |
| `.superseded-rules` | "Did the amendment actually finish?" — retired rule phrasings | `init.sh` fails if any appears outside `progress/` | **Copied unchanged from #8** — the phrasings #8 retired are wrong here too | Phase 2 | never |
| `scripts/git-hooks/commit-msg` | "Do not assert a quantity you have not counted" | Refuses a commit subject with a totality or scale claim unless the body carries the enumeration; installed by `init.sh` | **Copied unchanged from #8** | Phase 2 | never |
| `progress/current.md` | Working memory of the active session | Updated at every status transition, in lockstep with the backlog — `init.sh` checks this | Template from #8, content fresh | Phase 2 | every session |
| `progress/history.md` | Append-only log + **per-feature effort records** | Carries a `#7 baseline`, a `#8 baseline` and an `Inherited #8 findings` field per entry; this is the benchmark | Template from #8, extended to three columns; **only #9's own records** | Phase 2 | every feature close |
| `docs/PROCESS.md` | This document | Updated at the end of every phase — registry + status | Copied from #8, re-pointed; §10–11 reset | Phase 2 | Phase 2 |
| `specs/shared/` (7 files) | The system's definition, before the code | **Read-only.** A change is a spec amendment (`SA-n`): explicit, human-gated, applied to all three repositories in the same session | **Copied verbatim from #8** — six files byte-identical to #8's **and** #7's, `cmp`-proven, and kept so by `init.sh` §5d | Phase 3 | never (amendments only) |
| `specs/shared/test-matrix.md` | Requirement → test traceability | Columns 1–4 are the trilogy's; column 5 (Status) and the coverage counts are this assessment's | Copied; reset by its own `SA-1` recipe — 63 rows to `TODO`, counts 0/0/63, #8's narration removed; columns 1–4 identical on all 63 rows against both siblings | Phase 3 | as features land |
| `n8n/workflows/*.json` | The demo's "external world" | Gateway REST API only — which is why they port at all | **Reused unchanged** — byte-identical to #8's and #7's | Phase 3 | never |
| `README.md` + `LICENSE` | Honest front door at every commit | Grows each phase; never describes software that does not exist yet. `LICENSE` arrived in the same commit as the README that names it | Written here (shape of #8's early README) | Phase 3 | every phase |
| `docker-compose.infra.yml` | The infrastructure every later phase connects to | 15 services, project `otcpy` so no volume collides with #7 (`otc`) or #8 (`otcnet`); the PostgreSQL healthcheck connects over TCP **and** counts the four databases, both halves armed; one YAML anchor gives `n8n` and `n8n-init` the same database | **Derived from #8's** by targeted edits — `postgres:18.6` replaces MS-SQL, n8n moves from SQLite to PostgreSQL | Phase 4 | Phase 4 |
| `infra/postgres/init/01-create-databases.sh` | Database-per-service, created before anything connects | Four `otc_*` owned by `otc_app`, `n8n` owned by `otc_n8n`, `CONNECT` revoked from `PUBLIC` — n8n's role cannot open an application database at all (armed) | Written here — #7's `/docker-entrypoint-initdb.d` mechanism, which #8's engine lacked | Phase 4 | Phase 4 |
| `infra/{kafka,otel-collector,prometheus,grafana,n8n}/` (9 files) | Topic creation from the spec, telemetry pipeline, dashboard, workflow import | The topic script parses `asyncapi.yaml` and fails unless the broker's set is exactly the spec's (armed with a planted topic) | **Copied from #8, `cmp`-identical** (eight also identical to #7; the dashboard is #8's phase-22 version) | Phase 4 | never |
| `.env.example` | Every variable the compose file reads, with a dev default | Complete by enumeration: 73 read, all declared except the documented `OTC_GATEWAY_URL` override; grows with the services | Shape of #8's phase-4 file; PostgreSQL section new | Phase 4 | as services land |
| `pyproject.toml` + `uv.lock` | One resolution for the whole workspace, and every tool's configuration | uv workspace over `packages/*` and `services/*`; `mypy --strict` with exactly one override (`aiokafka.*`, asserted by a test); pytest loop scope `function`, written beside it; DeprecationWarnings **and Starlette's own deprecation class** as errors; coverage ≥60% overall; **10 import-linter contracts** (domain and kernel purity, layers per service, service independence), each seen failing | Written here — the Python enforcement of what #7 did with an ESLint path glob and #8 with NetArchTest | Phase 5 | as dependencies land |
| `tests/architecture/` | The guards a contract file cannot express | AST money guard (`float`, `/`, `decimal`, `fractions`, the truediv family, `**` with a non-literal exponent) and an **import allowlist** for every domain and the kernel, over one walker with a literal non-vacuity set; dependency-freedom of `shared_kernel` and `cqrs`; mypy and warning policies | Written here; each shape armed at a nested domain path and in the kernel | Phase 5 | as guards are added |
| `quality.sh` | The single gate | ruff format and check, mypy, import-linter, contracts drift, pytest with the overall gate, the ≥80% domain gate, then the web app's install, Vitest and build; `set -euo pipefail`, exit propagation armed | Shape of #8's script | Phase 5 | as gates are added |
| `packages/shared_kernel/` | The value objects every service shares | `Money` (int minor units, int64-bounded, no division, a literal allowlist of its members), `Quantity`, `GLN` (mod-10, exhaustive single-digit sweep), four business references, `UniqueId`, `Entity`, `AggregateRoot`, the ISO 4217 table with `apps/web/src/lib/currency-exponents.json` kept equal by a two-way test | Written here from `domain-model.md` §2; table identical to #7's and #8's | Phase 5 | as the domain needs |
| `packages/contracts/` + `scripts/generate_contracts.py` | The wire, generated from the spec | datamodel-code-generator over `asyncapi.yaml` (99 schemas) and `openapi.yaml`; one `WireModel` base (camelCase, strict integers, frozen, `.mmmZ` instants on every JSON path); `--check` drift gate | Written here — #7 generated, #8 hand-wrote; #9 generates again | Phase 5 | when the spec changes |
| `tests/fixtures/golden_envelopes/` (12 files) | The wire-parity oracle | Real #7 envelopes; envelope compared byte-exact, payload semantically and type-strictly | **Copied from #8, `cmp`-identical** | Phase 5 | never |
| `apps/web/` | The Analog app, scaffolded early | Analog 2.8.0 / Angular 22 under pnpm 12.8.1; four dependency build scripts denied with a reason each; the template's `AGENTS.md`/`CLAUDE.md` kept (they point at the installed framework's own guidance) | Scaffolded here, **in phase 5 rather than #8's phase 16** — an approved departure | Phase 5 | Phase 16 |
| `services/{orders,fulfillment,billing,notifications}/alembic/` | One schema history per database, owned by its service | Async template (no sync driver), hand-written `0001` with every constraint and index named; types, foreign keys (8 / 2 / 3), indexes and relations asserted as **closed sets from the live catalogs**, never from SQLAlchemy metadata; `json` payloads read back byte-identical (armed with `jsonb`) | Written here; #8's EF migrations and #7's drizzle SQL cited row by row in each `impl_db_*.md` ledger | Phase 6 | Phase 6 |
| `services/*/src/otc_*/infrastructure/persistence/range_guards.py` (3 copies) + `tests/architecture/test_range_guard_parity.py` | Python ints never overflow; `integer`/`bigint` columns do — a value out of range must be a domain refusal, not a driver error | An ORM attribute listener on every integer column (the live catalog is the population); **copied per service** because it is SQLAlchemy-bound (so not `shared_kernel`) and no other shared runtime package is allowed; the parity guard has three members and a census of every copy under `services/*/src`. ORM-enabled DML and raw SQL bypass it — a named residual (backlog 204, 207) | Written here — #8 had `int` columns and C# `checked`; #7 had JS doubles | Phase 6 | Phase 6 |
| `conftest.py` (repository root) | Integration tests that need a real PostgreSQL, fast and independent of the developer stack | One Docker-held `postgres:18.6` per session (no free-port picker, #8 id 85), a migrated template database per service, a fresh database per test (isolation pinned by `tests/database_templates/`); loop scopes written beside each fixture. The gate passes with the stack stopped (#8 id 104) | Written here — #8 gave each suite its own container and its gate grew from 67 s to 159 s | Phase 6 | Phase 6 |
| `tests/database_parity/` | "The reliability tables are identical in every database" as a fact about the engine | `outbox` (3 databases) and `processed_events` (4) compared from `information_schema`/`pg_attribute`/`pg_index` — identity and sequence parameters included — against literal population sizes; neutral location, importing no service package | Written here — #7 compared migration SQL text; #8 compared six column properties inside the Billing suite | Phase 6 | Phase 6 |
| `.gitignore` / `.editorconfig` / `.python-version` / `.nvmrc` | Toolchain and style pins | `.python-version` is resolved by uv on every run; no bare `data/`, `lib/`, `build/` or `dist/` entries, verified both ways with `git check-ignore` | Written here (`.editorconfig` keeps #7/#8's baseline) | Phase 1 | Phase 1 |

---

## 10. Where the project is right now

> Maintained at the end of every phase. History of *how* each phase went lives in `progress/history.md`; this is only the current position.

**Position: Phase 7 complete — 25 of 55 features done** (43 planned plus twelve findings filed by this run, every one of them now closed or carried as an acceptance item of the feature that builds its missing code). The repository holds its toolchain pins, its agent harness, the shared specification, the public README, a running infrastructure stack, the workspace every later phase builds into, the four write databases' schemas proven against the engine rather than the ORM, and a deterministic seed whose rows were diffed against #8's live databases. The git history reads **harness → specification → code**, because a process claimed after the fact is not evidence.

Two maintainer rulings at the Phase 7 gate change how later phases run: **findings are fixed in the phase that detects them** (CLAUDE.md) — no backlog entry defers a fix whose code already exists — and the `quality.sh` wall-clock threshold is **~125 s** (stack stopped; 103 s at the Phase 7 wrap-up, 1 290 tests).

| Phase | What | State |
|---|---|---|
| 1 | Environment & repository — Python 3.14 via uv, the backend set and an Analog probe verified, account-explicit remote, `.gitignore` proven both ways | ✅ |
| 2 | Harness layer — copied from #8 and re-pointed to Python; backlog reset with #8's findings as criteria; C7 rewritten | ✅ |
| 3 | Shared specification — copied **verbatim** from #8, `cmp`-proven against #8 and #7; public README | ✅ |
| 4 | Infrastructure compose (PostgreSQL) + spec-derived Kafka topology | ✅ |
| 5 | `uv` workspace scaffold, shared kernel, contracts, import-linter contracts, `apps/web` scaffold | ✅ |
| 6 | SQLAlchemy models + Alembic migrations for the four write databases | ✅ |
| 7 | Deterministic seed job, row-diffed against #8's dataset | ✅ |
| 8 | Orders service — aggregate, dispatcher, outbox/idempotency, acceptance, saga orchestrator | ⬜ |
| 9 | Fulfillment — stock reservations and DESADV creation | ⬜ |
| 10 | Billing — buyer credit, the `.99` simulator, invoicing, remittance intake | ⬜ |
| 11 | Notifications — aiosmtplib into Mailpit, durable idempotency ledger | ⬜ |
| 12 | Projector — the MongoDB read model | ⬜ |
| 13 | Gateway / BFF — REST, JWT, login rate limiting, SSE | ⬜ |
| 14 | Reliability + observability — retry, DLQ, OTel propagation, health checks | ⬜ |
| 15 | End-to-end saga verification | ⬜ |
| 16 | Web app (Analog / Angular) with its Nitro BFF | ⬜ |
| 17 | Web component tests (Vitest + Angular Testing Library) | ⬜ |
| 18 | API tests — the same black-box script #7's and #8's prove | ⬜ |
| 19 | Playwright end-to-end tests | ⬜ |
| 20 | n8n demo workflows, reused unchanged | ⬜ |
| 21 | Quality gates — ruff, mypy, import-linter, coverage proven to bite | ⬜ |
| 22 | Prometheus, Grafana, Jaeger verification | ⬜ |
| 23 | Full Docker Compose | ⬜ |
| 24 | Documentation, demo, and the **three-way benchmark** | ⬜ |
| 25 | Final checkpoint | ⬜ |

---

## 11. What this process actually caught

> In #7 and #8 this section grew into long catalogues of real findings — guards that guarded nothing, claims that did not survive being checked, defects only the real system could reveal. **Those catalogues belong to #7 and #8, and they stay there.** Reprinting them here would be claiming another build's evidence, which is the precise failure this section exists to guard against.

### 11.1 Inherited as prevention, not rediscovered

| What | Cost where it was found | Cost in #9 |
|---|---|---|
| Two GitHub accounts on one machine, `credential.helper=store` serving the wrong token for a `peelmicro` repo | #7: a failed first push (HTTP 403) and the investigation behind it | One account-explicit remote URL before the first push, which succeeded first time (as in #8) |
| A bare `data/` in `.gitignore` silently matching a source directory | #7: 11 source files untracked, undetected until its Phase 8 | `/data/` anchored, the same reasoning extended to GitHub's Python template (`lib/`, `build/`, `parts/` not copied), verified both ways with `git check-ignore` |
| A comparison check reporting OK over an empty population | #8: a parity guard compared one copy with itself for three phases | `init.sh` §5d warns instead of passing when `specs/shared/` has nothing to compare, and compares against both siblings |
| A database healthcheck that passes before the bootstrap has run | #7 (MySQL socket ping) and #8 (MS-SQL `SELECT 1`): services released onto a server with no databases | Probed on PostgreSQL before trusting the plan's "less likely here" — the trap applies (see 11.2); the healthcheck connects over TCP and counts the databases, armed both ways |
| `/varz \| grep jetstream` offered as proof that NATS runs core-only — it matches with JetStream on and off | #8: caught by the human at the gate, not by the agent that wrote it | Verified by asking for the refused operation (`stream add` → *no responders*), and that check itself armed against a throwaway JetStream server |
| A plan table listing 14 NATS subjects where the spec declares 15 | #8: found only by checking against the spec | 15/15 by set difference in both directions, against a literal list |
| A domain-purity selector that covers flat namespaces only | #8: a rejection round — a live `ObjectId` in a nested `Domain.*` namespace passed all six purity rules | Nested `domain/value_objects/` packages exist in every service from the scaffold, and every guard is armed there |
| Purity and money rules that never scanned the shared kernel, and a money rule that banned `decimal` but not `double`/`float` | #8: a leader reopen and a rejection, every defect in a guard | `shared_kernel` is in both the contract and the AST walk from the first commit; six float/division/decimal shapes armed |
| A coverage figure printed beside a green tick without gating | #7: an inert gate for twenty phases | The domain gate stayed a marked TODO naming its owner while it could only pass vacuously, then was wired and armed by that owner |
| `datetime` written with seven fraction digits and an offset instead of `.mmmZ` | #8: found before its goldens were asserted | **Recurred** — handled on the main writer but not on `model_dump_json`, `model_dump(mode="json")` or a FastAPI response, until review round 1 |

| Foreign keys declared in the plan but absent from the migration, with a green suite | #8: 7 of 8 missing in `db_orders`, a rejection round | A closed-set FK assertion from `pg_constraint` in every database from the first commit, armed by deletion and by substitution |
| Money columns as `int`, with a narrowing cast at every boundary | #8 id 44: a correction across 13 columns three phases late | `bigint` from the first migration; 6 + 7 = 13 money columns asserted from the live catalog |
| A counter seed that checks then inserts, racing on the first ever call | #8 id 45: a primary-key violation surfaced to the caller | `INSERT … ON CONFLICT DO NOTHING`; 16 concurrent first callers per counter, with #8's shape kept as a sentinel that loses every round |
| Index checks that were presence-only; a parity test without identity; a parity test owned by one service; read-back timestamps never asserted | #8 `db_fulfillment`/`db_billing` advisories, carried for three features | Folded into the first feature's brief: index sets closed, identity compared, parity in a neutral directory, timestamps asserted aware-UTC on read-back |
| One database container per suite | #8: the gate grew from 67 s to 159 s across three features | One container per session from the first database feature; a template database per service when the gate approached 90 s |
| `order_timeline` documents tested for shape, not values: blanked `causationId`s and corrupted totals passed a green suite | #8: its Phase 7 rejection (D1) | The expected documents produced by **executing #7's own code**, checked in before any writer existed, and compared leaf by leaf with types; 17 unpublished reviewer mutations each failed by name |
| A parity claim against the previous build's live database, deferred and never closed | #8: "parity against #7's live MySQL" stayed open after its Phase 7 | Run at the gate: #8's SQL Server and MongoDB started read-only beside #9's stack, the seeded subset dumped row per line from both and diffed — 19 of 20 files identical, the 20th #8's own demo traffic |
| A counter seeded from `MAX(reference)` that scans the orders table on **every** allocation | #8 id 47: found and fixed in its Phase 21 | A single statement whose `MAX` sits in an InitPlan behind a one-time filter; `EXPLAIN (ANALYZE)` pinned in a test (`never executed` with the counter present), armed by the unconditional aggregate |

### 11.2 Found here

| What | What produced it |
|---|---|
| A recorded claim that PostgreSQL's `jsonb` reorders keys "differently from MySQL" was false: the outputs are byte-identical | Running the same document through both engines in throwaway containers, instead of reasoning about it — it decided the payload column type (`json`) |
| The spartan/ui generator exits 0 having generated nothing when its config file is missing | Checking the generated files after a green exit code, not the exit code (Phase 1 probe) |
| pnpm fails the install outright on undecided dependency build scripts | Running the install under the pnpm version actually adopted, before adopting it |
| The live timelines of #7 and #8 show "caused by" only on facts Orders emits: responder facts cite the **command** that produced them (R12 allows it), and the command is never in the timeline. Seeded orders link everywhere because the seed's chain is "one link shorter than a live saga's" — #8's own comment | Following an observation in the publication plan (a demo GIF looked different from the screenshots) into the contract and both repositories' code, instead of filing it as a UI bug. Backlog id 201, decided at the phase 12 gate |
| PostgreSQL's temporary init server refuses TCP but **accepts socket connections**, so the default `pg_isready` reports "accepting connections" throughout the bootstrap — and over the socket the four databases already count as present while later init scripts still run. #7's MySQL trap, same shape, on the engine the plan called safer | A throwaway container with a deliberately slow init script, polled every 2 s over TCP and over the socket |
| An `n8n-init` without the database variables falls back to SQLite, imports all four workflows there and **exits 0**, while the server reads PostgreSQL and sees none | Running the importer with the variable removed — which is why one YAML anchor now feeds both containers |
| A first enumeration of `asyncapi.yaml` keyed on `bindings` counted **0** NATS subjects: only Kafka channels carry bindings; transport is declared by each channel's `servers` reference | Printing the unclassified bucket instead of dropping it (defeat-list row 11) |
| Two arming probes failed **for the wrong reason** before failing for the right one — a probe container without `POSTGRES_DB_*` counted empty names, then one without `POSTGRES_USER` connected as `root` | Printing stderr, so the failure named its cause; only the third run is recorded as the arm |
| A case-insensitive leak sweep of the spec finds `neSt` inside `TimelineStreamEntry` — a false-positive class #8's sweep never had | Classifying every hit by the word it sits in, rather than assuming every `nest` is inside `honest` |
| import-linter matches imported **module** names, and a distribution's module names are not its package name: `from bson import ObjectId` (PyMongo's) in a nested domain left all 10 contracts green — the very probe #8's reviewer used, now against a new instrument | The leader re-asking #8's reviewer probe in the new instrument's terms before closing the scaffold; fixed with an allowlist (stdlib + kernel + own domain) |
| A "no major-unit surface" test on `Money` that checked public names and a deny-list of dunders: a `__format__` printing `1242.50 EUR` with `//` and `%`, or a private `_major`, passed all 66 tests | The Opus reviewer's independent arming (64 runs); fixed with a literal allowlist over `vars(Money)` plus a class-body scan and a text-form test |
| One serializer configuration that was not the only path to bytes: a mutated or `model_construct`ed instance wrote `true` or `89.34` into a money field, and the model's own JSON paths wrote `.442000Z` | The reviewer asking "is this the only path to the wire?"; fixed with frozen models, write-time re-validation and a JSON-mode instant serializer |
| Starlette's deprecations subclass `UserWarning`, so `error::DeprecationWarning` let one through and the run stayed green | Reading the one warning line a green run printed instead of ignoring it; the filter was armed against the import that triggered it |
| An implementer silenced pnpm's supply-chain release-age gate (`minimumReleaseAgeExclude`) to install a jsdom published the day before | Reading the diff of a light change rather than only its test result |
| A range guard installed as an ORM listener covers the unit of work only: `session.execute(insert(Model), rows)`, `update(Model)` and `bulk_*_mappings` — SQLAlchemy 2's recommended bulk paths — reach the driver unguarded, and the first fix (letting SQL expressions through) let PostgreSQL silently round `units * 0.5` | The Opus reviewer's write-path probes (9, then 10 paths) in `db_orders` and `db_fulfillment`; filed as backlog 204 and 207 |
| `populate_by_name=True` on a pydantic-settings class lets the shell's bare `USER`, `HOST`, `PORT` and `PASSWORD` become the database URL | The `db_fulfillment` implementer, measuring its own settings; widened by the reviewer; filed as 204(e) |
| `timestamptz(3)` rounds sub-millisecond instants (`.123987` → `.124`) while the wire formatter truncates (`.123`) | Measuring the read-back instead of assuming it; filed as 205 |
| Closed-set instruments blind to attributes a substitution can change: `ON UPDATE`, deferrability, `MATCH`, index access method, sort order, `INCLUDE` columns, and objects outside the `public` schema | Each reviewer arming against the previous feature's instrument; widened in the next feature each time (206, 208, 209) |
| `sqlcmd` refuses `-W` together with `-y 0` before connecting — and each one-flag fix is a trap: without `-y 0` an `nvarchar(max)` payload is cut at 256 characters, without `-W` every row is padded | The reviewer running the script's exact argv against #8's own SQL Server image in a throwaway container; the parser's unit tests fed canned output and could not see it |
| #9's counters seeded the constant `1`, so on a seeded database the first order would collide with `ORD-000001`, roll back its own advance, and **no order could ever be placed** | The seed review asking how #7 and #8 avoid the collision (both seed from the numeric `MAX` of existing references); fixed in the same phase (211) |
| `WHERE NOT EXISTS` on an aggregate `SELECT MAX(…) FROM t` skips the scan but still emits one row, so the insert still attempts a conflict | `EXPLAIN (ANALYZE)` on a populated table, both shapes, instead of reasoning about the plan |
| A test helper that derived the order reference from the despatch/invoice number made a counter reading the **wrong column** pass every guard | The reviewer's sibling-identifier substitution (defeat-list row 3) — "distinct values" applies to the column a statement must *not* read |
| A deny-list money guard lost three review rounds in a row — `math.pow`, aliased `operator` functions, `getattr`, `statistics.mean`, `pow` as a value | Fixed by changing the kind of instrument: a literal import allow-list re-derived from a census of the 35 domain files (seven stdlib modules), with a stopping rule agreed with the maintainer before the round |
| A reviewer's mutation left a stray file in the shared kernel; its own `rm` was refused, and it asked the leader to delete it | The leader declined (permission laundering) and asked the maintainer, who authorised it; later review requests plant only in existing files or scratchpad copies and end on a `git status` snapshot |
