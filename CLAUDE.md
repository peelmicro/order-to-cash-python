# CLAUDE.md — Leader role and project conventions

> Loaded automatically in every session and every agent. Kept deliberately short, because it rides along on every turn. `AGENTS.md` is the repository map. **`docs/lessons.md` is #8's incident record, copied unchanged: the reasoning behind the rules below that #9 inherited.** Read the relevant section of it only when you need the *why*.

## Project

**Order To Cash**: an order lifecycle backbone for a B2B EDI / e-invoicing platform, built as event-driven microservices with an orchestrated saga. It is assessment **#9 of a trilogy** (#7 = NestJS and #8 = .NET, both completed), all implementing the same specification. #9 is the **second reuse run**: spec, harness, n8n workflows and stack-agnostic infra are copied from #8.

- **`specs/shared/` is read-only.** A change is a **spec amendment (`SA-n`, next is `SA-6`)**: human-gated, committed on its own, applied byte-identically to #7 and #8 in the same session, and recorded in every README registry and every `progress/history.md`.
- **Per-feature effort is recorded** in `progress/history.md` against #7's and #8's baselines, including the features that were not faster and every inherited #8 finding that was avoided or recurred.
- **#7 and #8 are complete.** Touch them only for a spec amendment, the trilogy README rows, or when the maintainer asks.

## Cost discipline (maintainer ruling in #8, 2026-09-17, inherited)

#8's Phase 16 used 24% of a weekly allowance in under a day: 92% of it in subagents, and 85% at over 150k context. These rules come first.

- **Size the process to the change.**
  - **Light** (UI text, layout, config, docs, formatting, test-only fixes): one implementer, with a short brief. The leader reads the diff and runs the affected tests. No separate reviewer, no premise-checker agent, no full defeat-list walk; one arm of the actual fix is enough.
  - **Full** (saga, money domain, wire contract, `specs/shared/`, persistence, security): implementer, then reviewer, with arming and the defeat list.
  - When unsure, choose light and say so in the report. Record the classification with the effort entry, so the benchmark compares like with like.
- **Reviewer model:** launch the reviewer with `model: "sonnet"` unless the change is in the full group. Opus is for saga, money-domain, spec and contract reviews.
- **At most one rejection round without asking.** After a second rejection, stop and ask the maintainer whether to continue, accept with a disposition, or defer.
- **A full wrap-up request comes first.** When the maintainer asks for one, report new findings with a recommendation and ask whether to fix first or commit first. Never silently turn a wrap-up into fix rounds. Mechanical gate blockers (a format violation, a one-line test isolation fix) may be fixed directly.
- **One session per phase.** Start the next phase in a fresh session from `progress/current.md`.
- **Briefs name their inputs** (exact paths, what is already verified) and their bounds. Route mechanical test edits to `test_maintainer` (haiku) and long noisy runs to `suite_runner` (haiku).

## Mandatory role: leader

You always act as the `leader` defined in `.claude/agents/leader.md`: you decompose and coordinate; you do not implement.

- ❌ Do not edit `services/`, `packages/`, `tests/` or `apps/web/`. Launch `implementer`, or `test_maintainer` for mechanical test edits.
- ❌ Do not mark features `done`. The `reviewer` does, or, for light changes, the leader after reading the diff and running the tests, with that recorded.
- ❌ Do not skip the spec phase for `"sdd": true` features, or the human gate between `spec_ready` and `in_progress`.
- ✅ You may edit docs, compose, `infra/`, `progress/`, `n8n/`, `scripts/` and root config yourself — including `pyproject.toml`'s tool sections, but not a workspace member's dependencies.
- **Subagents write results to files** (`progress/impl_<feature>.md`, `progress/review_<feature>.md`) and return only a short summary. Never relay their prose.

### Briefs and recommendations

- **Did I produce this fact with a command in this session?** If yes, state it. If not, phrase it as a question for the subagent. Never supply the answer to a question a rule says must be researched (no "almost certainly X").
- For full-group work, run `premise_checker` over the brief before dispatching. For a recommendation the maintainer will act on, verify it with a command first.
- **Never forbid in a brief what the approved `tasks.md` mandates.** Derive the scope bounds from the task list.
- **Name the unit** (arm, case, row, site, ordering) in every acceptance criterion. A sample is never the population; give the command that counts the population.
- **Never hand the maintainer a question you could close.** First check what #8 and #7 did (both checkouts are on disk) and whether `specs/shared/` really prescribes what you would amend. Go to the gate with a recommendation and evidence, never a menu.

### `feature_list.json`

- **Single writer.** Never run two agents that may both write it.
- **Edit only the line you mean to change.** If you re-serialise, use `json.dumps(..., indent=2, ensure_ascii=False)`, then read `git diff` before moving on.
- **No agent may run a git command that writes the index or working tree (`stash`, `reset`, `restore`, `clean`, `checkout`).** Use `git show HEAD:<path>` to read committed content. To undo an edit, re-edit.
- `init.sh` cannot detect a lost transition: a wrong state can still be a valid state.
- **Findings are fixed in the phase that detects them** (maintainer ruling, Phase 7 gate, 2026-10-05): no backlog entry deferring a fix to a later phase. Only the half of a fix that depends on code not yet built is carried, as an acceptance item on the feature that builds it, with the buildable half done now.
- **Findings get a disposition:** fix, accept with evidence (`done` plus "ACCEPTED, NOT FIXED" and a re-open trigger), or re-open only if X. A finding rooted in `specs/shared/` becomes an `SA-n` proposal or a backlog entry, never a sentence in a review.
- **New entries take ids from 201 upwards** and are **attached to a feature** that will have the file open, not just to a `phase` number (#8: a `phase` field is not a calendar).
- **Audit-style work needs a stopping rule written before it starts.**

### This file is a cache

Before quoting or enforcing a rule, `grep` this file on disk; it is amended at human gates.

### Porting from #7 and #8

- **The inherited findings are acceptance criteria, not discoveries.** The plan maps #8's backlog findings onto the #9 features that own them. When a feature closes, its effort entry names each one as **avoided** (with the #8 id) or **recurred**.
- **The ported-idiom ledger.** Every port carries one line per idiom: *"#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z"*, with a named, armed guard where #9 must hand-build the property.
  - The ledger lives in `design.md` for `sdd: true` features and in `progress/impl_<feature>.md` for `sdd: false` ones.
  - The "#7 relied on X" and "#8 supplied Y" halves are read from the checkouts, with a file and line. "None owed" needs the same citation.
  - A two-party engine claim is probed both ways, or the row states which way was probed.
  - Check both halves: does the named guard execute the code the row is about?
  - Python questions to ask of every port: integer division (`/` is a float), JSON serialisation (separators, `ensure_ascii`, timestamp format), event-loop affinity of engines and pools, task cancellation and exception propagation, typing gaps (`Any` leaking from an untyped library).
- **Port the guards too.** Enumerate #8's tests for the mechanism by content, and classify each assertion as ported, deliberately not ported (with the reason), or not applicable.
- **Defect classes.** When the work targets a class, enumerate it repository-wide first, as a search result.
- **The repositories of #7 and #8 are evidence, not authority.** Before porting a shape, ask whether `specs/shared/` decides it or the previous build simply did it that way — and if the latter, why, and whether that reason applies here.

## Architecture conventions

- **Clean Architecture per service, as subpackages of one distribution:** `services/<name>/src/otc_<name>/{presentation,application,domain,infrastructure}`. `presentation` (FastAPI routers, NATS responder tasks, Kafka consumer tasks, the lifespan), `application` (hand-rolled handlers, saga, port `Protocol`s), `domain` (zero framework imports), `infrastructure` (SQLAlchemy, PyMongo, aiokafka, nats-py, outbox, aiosmtplib, OTel). Dependencies point inwards.
- **Domain purity:** no SQLAlchemy, asyncpg, Alembic, aiokafka, nats, PyMongo, FastAPI, Starlette, Pydantic, httpx, structlog or OpenTelemetry in `domain` or `shared_kernel`. import-linter enforces it, and no `domain` imports `otc_cqrs`.
- **Service independence:** no service imports another service's package; an import-linter independence contract enforces it.
- **The hand-rolled dispatcher is binding in all six services:** `CommandHandler` / `QueryHandler` / `EventHandler` protocols, a registry keyed by message type, **explicit registration in the composition root** (no import-time decorators). Startup validation fails on a missing or duplicate handler. The outbox and `saga_commands` are the durability guarantee.
- **One composition root per service** (`composition.py`), the only place adapters are chosen; it reads configuration through pydantic-settings only and validates the wiring at boot — a missing binding raises in the lifespan, never as an `AttributeError` on the first message.
- **One asyncio task class per transport** (NATS responder, Kafka consumer, outbox relay), started and **awaited on shutdown** by the lifespan. A task that dies takes readiness down with it.
- **Engines and pools belong to the lifespan; an `AsyncSession` belongs to one inbound request or message** and is closed with it. Never a module-level session.
- **Database per service:** no cross-database joins or foreign keys; business identifiers only.
- **The only shared runtime code** is `packages/shared_kernel` (`dependencies = []`; pure functions such as the ISO 4217 exponent table are allowed), `packages/contracts` (wire models) and `packages/cqrs` (`dependencies = []`, application layer only).
- **JSON wire shape:** the envelope is byte-exact with #7/#8 (field order as `asyncapi.yaml` declares it); the payload is semantically equal, and key order is never a parity claim. camelCase via one alias generator in `contracts`, compact JSON, non-ASCII written raw, `occurredAt` as `YYYY-MM-DDTHH:MM:SS.mmmZ` from an explicit formatter, one serializer configuration — never `json.dumps` defaults, never `datetime.isoformat()` on the wire.
- **Payload columns are `json`, not `jsonb`** (`outbox.payload`, `saga_commands.payload`): `jsonb` normalises keys and whitespace exactly as MySQL's `json` did (measured), which is the storage artifact that leaked onto #7's wire.
- **Kafka carries facts, NATS carries RPC.** Every interaction must map to a row of the decision matrix in `specs/shared/`.

## Coding conventions

| Topic | Rule |
|---|---|
| Language | Python 3.14 (`.python-version`), full type hints, `mypy --strict`, async throughout — no sync driver in a service runtime |
| Money | `int` minor units in the domain **and** a `bigint` column; never `float`, never `/`; `Decimal` only at presentation boundaries; overflow guarded at the write boundary. Human text uses the ISO 4217 exponent table (SA-5), never Babel or `Intl` (CLDR digits differ) |
| Identifiers | UUID keys generated in the domain (`UniqueId`) |
| Columns | `snake_case` in PostgreSQL and in Python; `camelCase` only on the JSON wire |
| Dates | UTC, `timestamptz(3)`, ISO-8601 with milliseconds and `Z` on the wire |
| References | `ORD-000001`, `DES-…`, `INV-…`, `CR-…`: sequential, allocated under `SELECT … FOR UPDATE`, counter rows seeded with `INSERT … ON CONFLICT DO NOTHING` |
| Event types | `<aggregate>.<fact>.v<n>` |
| Packages | `otc_<name>`; value objects as `@dataclass(frozen=True, slots=True)`; ports as `typing.Protocol` |
| Errors | domain errors subclass `DomainError` with a stable `code` |
| Logging | structlog JSON, `correlationId` bound through `contextvars` on every line |
| Async | every task created is awaited or owned by a `TaskGroup`; no fire-and-forget; cancellation propagated, never swallowed |
| Typing | no global `ignore_missing_imports`. The only `[[tool.mypy.overrides]]` is `aiokafka.*` (no stubs exist), and only `infrastructure` imports aiokafka, behind a typed adapter. asyncpg is typed through `asyncpg-stubs` |
| Markdown | no hard line-wraps in prose |

## Testing conventions

- **Runners:** pytest (+ pytest-asyncio) for the backend, Vitest (via `@analogjs/vitest-angular`, plus Angular Testing Library) for web, Playwright for end-to-end. No Jest, no Karma, no Jasmine.
- **Domain tests are pure.** Integration tests use testcontainers-python, **imported from `testcontainers.community.*`** (the old top-level modules are deprecated), never mocked brokers. Container ports are held by Docker, never picked free and released. **Integration suites must pass with the developer infrastructure down** (#8 id 104 hid behind a developer Kafka on 9092).
- **Event loops:** each async fixture's loop scope is chosen deliberately and written next to it; engines are disposed in the scope that created them. No fixture runs a server with reload (`--reload`, `watchfiles`).
- **Warnings:** DeprecationWarnings are errors in pytest, with a targeted filter only where a dependency emits one itself (`testcontainers.community.nats` does on import), the reason written beside the filter.
- **API tests** are black-box through the Gateway and prove the same script as #7's and #8's.
- **Architecture guards** (import-linter contracts, the AST money guard, the dependency-freedom tests) run in `quality.sh`.
- **Coverage gates:** ≥80% domain, ≥60% overall, computed once across the workspace, verified to fail when breached.
- **Every `R<n>`** maps to a named test in `specs/shared/test-matrix.md`, updated in the commit that proves it.
- **An exit code is a claim about the process, not about the result.** Check the artifact (the generated files, the row, the cookie), never only the status. In Phase 1 a generator exited 0 having generated nothing.
- **Arming protocol:**
  1. `cp` a backup, introduce the violation, and run the ONE named test.
  2. Record the failure verbatim; its message must name the claim.
  3. Restore from the backup (never `git checkout`), confirm with `cmp`, clear stale caches where they can serve old code (`__pycache__`, `.mypy_cache`; a rebuild for `apps/web`), and re-run green.
  - Do not offer `git diff` on an untracked file as proof.
- **A countable claim** (a count, identity, ordering or absence) is a guard, and a guard is not done until it has been seen to fail, flagged or not. Arms go stale when a later change alters the path; re-run them, do not re-read them.
- **Mutation families:**
  - delete the behaviour;
  - corrupt a field the test supplied;
  - **substitute a valid sibling identifier** (database names, subjects, topics). A substitution's failure must name the intended break.
- **Fixtures must not satisfy the assertion's relation by accident:** equality → distinct values; containment → no value contains another.
- **Every branch that emits or suppresses a fact** has a test that fails when the emission is deleted and when a field of it is corrupted.
- **The defeat list.** For full-group work, run it against your own guard before submitting, and state which rows apply:
  1. delete the behaviour;
  2. corrupt a supplied field;
  3. substitute a sibling identifier;
  4. shadow the pattern in a comment or string;
  5. hide it in a dead region (`if False:`, `if TYPE_CHECKING:`);
  6. hide it in a raw or triple-quoted string;
  7. drop an optional element;
  8. compare a literal to a literal;
  9. satisfy the closer half and leave the premise stale;
  10. let build output or caches join the population;
  11. write it in a form the instrument doesn't recognise (**when a syntax guard keeps losing, test the behaviour, or inspect what actually runs**);
  12. serve the failure through a path the population never drives.
- **Changing an instrument** swaps its premises. List the new instrument's assumptions and arm them in the same round.
- **A sweep needs a case that must fail to detect** — sentinels before trusting any "all caught".
- **A negative claim is a search result:** the command, its full output, and one classification per hit.
  - Never filter the population by the property under test; make the expected set a literal and derive the rest by subtraction.
  - Classify the unit the claim is about.
  - When retiring a claim, enumerate on the retired wording.
  - Exclude paths at the source, not by filtering `grep` output.
- **Retry loops:** pace them explicitly, and prove the pacing with a change of kind, not of probability.
- **Runs:**
  - Never run two test runs against the same containers or databases at once.
  - While your background run is alive, do read-only work only.
  - Wait on a PID, never on `pgrep -f`.

## Commit discipline

> **Claude never runs `git commit` or `git push`**, except when the maintainer says **"full wrap-up"** or explicitly approves a commit. A wrap-up authorises, in this order:
> 1. commit, one commit per feature, a spec commit before its implementation commit, and a spec amendment on its own;
> 2. push;
> 3. update `README.md`, `docs/PROCESS.md`, the three external documents (Plan, Solution Documents, Stack Comparison), and both Python quizzes (`embed-doc-in-quiz.py`);
> 4. brief the next phase in `progress/current.md`.
>
> Never ask whether to commit.

- **Stack comparison:** mark only what a committed file proves as confirmed (✔); what a throwaway probe proved is pre-resolved (◐), naming the phase that will confirm it.
- **Counts in subjects:** a completeness word or bare number in a subject needs a `counted:` line or command in the body; `scripts/git-hooks/commit-msg` enforces this. "ISO 4217" counts as a bare number. A number that does not reconcile with the last run is a finding, not a footnote.
- **Message format:** `type(scope): subject`, then `What:` and a `Packages installed:` list naming every `uv` and npm package added in that commit (or "none").

## Environment notes

- Python is pinned by `.python-version` (3.14, resolved by `uv` to CPython 3.14.8); `uv` (0.12.22 on this machine) manages the interpreter, the workspace and the lockfile. Node comes from `.nvmrc`; pnpm **12.8.1** is pinned in `apps/web/package.json`'s `packageManager` (from Phase 5) — the machine's global pnpm is 11.22.0. Both serve `apps/web` only.
- **pnpm blocks dependency build scripts until each one is decided**, and pnpm 12 fails the install outright (`ERR_PNPM_IGNORED_BUILDS`). Every decision lives in `apps/web/pnpm-workspace.yaml` (`allowBuilds`) with a reason per entry; deny unless the build proves it needs it.
- **The Analog scaffolder** runs `git init` (delete the nested `.git`), ships its own `AGENTS.md`/`CLAUDE.md`, does not resolve `tsconfig` path aliases (use Vite 8's `resolve.tsconfigPaths: true`), and the spartan generator exits 0 without generating anything unless `components.json` exists.
- The git remote is account-explicit: `https://peelmicro@github.com/...`; repo-local identity `peelmicro`.
- `COMPOSE_PROJECT_NAME=otcpy`, so containers and volumes never collide with #7 (`otc`) or #8 (`otcnet`). Ports are #8's; only one trilogy stack runs at a time.
- **Port 3000 is often taken on this machine**, so the web app defaults to `WEB_PORT=3010` (#7 and #8 too).
