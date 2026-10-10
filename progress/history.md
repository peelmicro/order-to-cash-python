# History — append-only log

> One entry per completed feature. **The effort record is mandatory**: this file is assessment #9's measurement against the #7 and #8 baselines, and the trilogy's closing answer to how much a mature spec plus a mature harness — and, the first time, a previous run's review findings — accelerate a full re-implementation.
>
> **Record what was NOT faster with the same care as what was.** An all-green benchmark is not a result, it is a lack of measurement. The baselines live in `peelmicro/order-to-cash-nestjs` and `peelmicro/order-to-cash-dotnet`, each in its own `progress/history.md`, feature by feature. **Quote them from those files, never from memory or from a plan table.**

Entry format:

```markdown
## <feature_name> (id <n>, phase <n>) — <date>

**Effort:** <n> session(s), ~<n>h wall-clock — process: light | full
**#7 baseline:** <n> session(s), ~<n>h | no counterpart
**#8 baseline:** <n> session(s), ~<n>h | no counterpart
**Spec:** specs/<name>/ | n/a (sdd: false) | reused from specs/shared/ (R<n>…)
**Tests:** <what was added, and the R<n> requirements they prove>
**Inherited #8 findings:** <#8 id → avoided | recurred, one per line> | none for this feature

**What was built:**

**Deviations from the spec/plan:**

**Rejections:** <for each: what, and whether #7's / #8's review standard would have caught it> | none

**What the reuse saved — and what it did not:**
```

---

## repo_bootstrap (id 1, phase 1) — 2026-10-03

**Effort:** 1 session, ~0.7h wall-clock (17:40 → commit 18:18, including the wait for the GitHub repository to be created) — process: light
**#7 baseline:** 1 session, ~0.5h
**#8 baseline:** 1 session, ~0.5h
**Spec:** n/a (sdd: false)
**Tests:** n/a — toolchain phase. Probe evidence: 22/22 backend probe tests on 3.14 (one against a real `postgres:18.6`), 3/3 Vitest and 1/1 Playwright in the Analog probe, the Playwright BFF assertion armed (`httpOnly: false` → fails); `.gitignore` 28 must-ignore / 15 must-track paths, 0 failures, armed with a bare `data/`
**Inherited #8 findings:** none for this feature (the two-account 403 and the `/data/` trap are #7 findings, inherited through #8's plan)

**What was built:**

`uv` 0.8.0 → 0.12.22 and CPython 3.14.8 installed. The whole backend dependency set resolved together on 3.14, every compiled package from a `cp314` wheel. Analog 2.8 / Angular 22 probed end to end under pnpm 12.8.1, including #7's BFF mechanism (h3 `useSession` sealed `httpOnly` cookie) on Analog's production server. Repository cloned empty, repo-local `peelmicro` identity and account-explicit remote set before the first push. `.gitignore`, `.editorconfig`, `.python-version`, `.nvmrc` committed as the root commit `396c296`.

**Deviations from the spec/plan:**

- No README in this phase — #9's prompt makes it step 5 (phase 3).
- The Analog probe went further than the plan's bullet (spartan generator, TanStack Query, Testing Library, Playwright, the h3 cookie) because the pnpm decision was "latest only if 100% compatible".

**Rejections:** none (no review — light process)

**What the reuse saved — and what it did not:**

**Saved:** the first push succeeded at the first attempt for the second run in a row — #7's 403 cost #7 a debugging session, #8 one line, #9 the same line. The `/data/` gitignore trap was avoided by construction and the same reasoning was extended to GitHub's Python template (`lib/`, `build/`, `parts/` not copied).

**Did not save:** everything stack-specific was new work, and slightly more of it than #8's — two throwaway probes instead of one (backend and web), because #8's web toolchain was the same as #7's and #9's is not. Effort came out ~40% above both baselines, almost entirely in the Analog probe, which bought five findings for phase 5 (nested `.git`, template agent files, unresolved path aliases, a generator that exits 0 having generated nothing, pnpm's build-script gate) that would otherwise surface there.

**Notes for later phases:** see the plan's phase 1 "Findings that change later phases": `pydantic-core` 2.46.5, `testcontainers.community.*`, `asyncpg-stubs` + the aiokafka-only mypy override, pnpm `allowBuilds`, the Analog scaffolder's hidden behaviour, Playwright 1.63.0.

## harness_layer (id 2, phase 2) — 2026-10-03

**Effort:** 1 session, ~0.2h wall-clock (≈18:22 → 18:34, reconstructed from file timestamps) — process: light, closed by the leader
**#7 baseline:** 1 session, ~1.5h
**#8 baseline:** 1 session, ~1h
**Spec:** n/a (sdd: false)
**Tests:** `init.sh` exits 0 on the fresh tree and **exits 1 on all 15 break cases** (#8 tested 8), each restore confirmed with `cmp`: two features `in_progress`; an invalid status; a duplicate id; an `sdd` feature past `pending` without its triple-doc; invalid JSON; a missing harness file; six agents; an agent that neither pins nor documents its model; `current.md` naming the wrong feature; a superseded rule reintroduced; a feature id disappearing and a `done` reverting (tripwire); `.python-version` pinning an unavailable interpreter; a shared-spec file edited; a sibling's spec file missing here. The installed `commit-msg` hook rejects "closes all four Billing features" without a `counted:` line and accepts it with one. **Addendum (phase 3 commit):** a 16th case was armed during phase 2's wrap-up, after the commit above had been written — the tracked `scripts/git-hooks/commit-msg` missing → exit 1 (*"the tracked copy of the commit-message guard"*); the installed hook missing is reinstalled with a WARN, by design, and is not a failure case.
**Inherited #8 findings:** the empty-population comparison (#8's parity guard over a population of one) → **avoided**: `init.sh` §5d warns instead of passing when there is nothing to compare

**What was built:**

The seven agent definitions, `AGENTS.md`, `CHECKPOINTS.md`, `init.sh`, `CLAUDE.md`, `docs/PROCESS.md`, `docs/lessons.md`, `scripts/git-hooks/commit-msg` and `.superseded-rules` copied from #8 at `79dc89b` and re-pointed to Python, with every agent's `model:` line byte-identical to #8's. `CLAUDE.md` rewritten for Python, carrying phase 1's findings as conventions (testcontainers' `community` modules, the aiokafka-only mypy override, `asyncpg-stubs`, pnpm's `allowBuilds`, the Analog scaffolder's hidden behaviour, `json` payload columns). `CHECKPOINTS.md` C7 rewritten for the second reuse (inherited findings, three-way benchmark). `init.sh`'s environment section rewritten for uv, and section 5d now compares against **#8 and #7**, in both directions, and refuses to report OK on an empty population. `feature_list.json` reset: 43 features (8 `sdd: true`), #8's ids and names, #8's review findings written in as acceptance criteria, `public_readme` (id 200) new. Fresh `progress/`, with `history.md`'s entry format extended to a `#8 baseline` and an `Inherited #8 findings` field. `docs/PROCESS.md` built from #8's final §1–8, cast table corrected to seven agents (#8's still said six), registry and status rewritten, §11 reset.

**Deviations from the spec/plan:**

- `docs/PROCESS.md` was built from #8's **final** version rather than #8's phase-2 copy: §1–8 had only changed in counts, and the final cast table needed a fix anyway.
- `.superseded-rules` was copied although the plan's list did not name it: the five phrasings #8 retired are just as wrong here, and copying the file makes `init.sh` §5 active from the first commit.
- The plan's phase-2 item "create the derived documents" is done in this phase's wrap-up (step 6), where #8's ritual puts it.

**Rejections:** none (light process, no reviewer)

**What the reuse saved — and what it did not:**

Measured by diffing each file against #8's original (lines new or changed in the #9 file):

| Artifact | #8 lines | #9 lines | New/changed | % |
|---|---|---|---|---|
| `leader.md` | 76 | 76 | 1 | 1% |
| `premise_checker.md` | 62 | 62 | 1 | 2% |
| `suite_runner.md` | 45 | 45 | 5 | 11% |
| `test_maintainer.md` | 39 | 39 | 5 | 13% |
| `reviewer.md` | 91 | 92 | 13 | 14% |
| `spec_author.md` | 117 | 120 | 24 | 20% |
| `implementer.md` | 67 | 69 | 18 | 26% |
| `AGENTS.md` | 82 | 83 | 11 | 13% |
| `init.sh` | 362 | 390 | 85 | 22% |
| `docs/PROCESS.md` (§10–11 reset) | 758 | 285 | 64 | 22% |
| `CHECKPOINTS.md` | 70 | 71 | 21 | 30% |
| `CLAUDE.md` | 164 | 175 | 72 | 41% |
| `docs/lessons.md`, `commit-msg`, `.superseded-rules` | 502 | 502 | 0 | 0% |
| **Total** | **2 435** | **2 009** | **320** | **16%** |

**Saved:** the same split #8 measured — orchestration ports almost free (1–26%), conventions do not (30–41%) — but `CLAUDE.md` cost **41% against #8's 68%**. The plausible reason, stated as a reading and not a measurement: #8's `CLAUDE.md` had already been cut down and separated into stack-agnostic rules (kept verbatim here) and stack rules (replaced), so a second port touched only the second half.

**Did not save:** the cost moved rather than disappeared. Nearly all the thinking went into the parts that are new by construction — the three-column ledger, C7, init.sh's two-sibling parity check — and into deciding which of #8's ~70 findings become #9 acceptance criteria, which #8 never had to do. And the wall-clock figure needs its caveat: **an agent-driven phase's wall-clock measures throughput, not difficulty** — the same is true of #8's ~1h and #7's ~1.5h, so the comparison is fair across the three, but none of the three numbers is human effort.

## shared_spec (id 3, phase 3) — 2026-10-04

**Effort:** 1 session, ~0.2h wall-clock (≈05:18 → 05:30, including the end-to-end re-read of `requirements.md`, `domain-model.md` and `saga.md`) — process: light, closed by the leader
**#7 baseline:** 1 session, ~2.5h (authoring)
**#8 baseline:** 1 session, ~0.75h (copy)
**Spec:** this feature *is* the spec copy — `specs/shared/` from #8 at `a9a2f8d`
**Tests:** six files `cmp`-identical to #8's **and** to #7's (same SHA-256 in all three); the four n8n workflow JSONs identical to both; `test-matrix.md` columns 1–4 identical on 63/63 rows against both, by script, **armed** (altering R7's requirement text drops it to 62/63); `init.sh` §5d → OK against both siblings across 6 files each
**Inherited #8 findings:** #8's SA-1 (a reset recipe that described one copy's paragraphs) → **avoided** — the recipe as amended was followed, and the paragraphs to remove were found by diffing #7's and #8's final matrices rather than by reading

**What was built:**

The seven files of `specs/shared/` and the four `n8n/workflows/*.json` copied from #8 byte for byte. `test-matrix.md` reset by its own four-step recipe: all 63 Status cells → `TODO`; coverage counts → 0 / 0 / 63; no per-assessment aside to delete (#8's copy carries none — the two "per-assessment aside" hits are the rule that defines them); the two paragraphs under the coverage table that narrate #8's own realisation record deleted. The result differs from #8's file only in the counts and those two paragraphs — the same shape #8's own reset left (`b6c6506`: nothing after the Total row).

**Leak sweep, as an enumeration** — `grep -noiE` over the seven files with #7's, #8's and #9's stack terms (NestJS…, .NET…, Python, FastAPI, SQLAlchemy, Postgres, Angular, Analog, Pydantic, pytest, asyncpg, aiokafka, `uv`, file extensions, `apps/`, `packages/`, `src/`): **13 hits, 0 leaks** — 9 × `nest` in `honest`/`honesty`/`honestly`, 3 × `neSt` in `TimelineStreamEntry` (a false-positive class new to this sweep, because it is case-insensitive), 1 × `react` in `reacted` (from a term #9 added). Sentinel: a planted "implemented with FastAPI" line is caught.

**Deviations from the spec/plan:**

- Copied from #8's current HEAD `a9a2f8d`, not the harness's `79dc89b`: the only change between them is three lines of #8's README, so the spec is the same.
- No per-assessment aside existed to delete — recorded rather than assumed, by diffing the prose of #7's and #8's final matrices.

**Rejections:** none (light process, no reviewer)

**Notes for later phases (from the re-read):**

- **Phase 12:** `R50`, `domain-model.md` §7.1 and `saga.md` §6 all say the timeline is ordered by `occurredAt`; #7's amendment A1 (folded into #8's first projector draft) orders by the recorded causal edge. A1 therefore lives in the projector's per-feature design, not in `specs/shared/` — the phase 12 design must read #8's and state how the two reconcile.
- The spec catalogues **fourteen** facts (`order.saga_failed.v1` included); the Task's Part A still says thirteen. The spec wins.
- `domain-model.md` M3: *"Division is not offered — it would reintroduce rounding"* — the shared-kernel rule behind #9's `/` guard is in the spec itself.

**What the reuse saved — and what it did not:**

**Saved:** a second copy costs about what the first did minus its learning — #8 spent most of its 0.75h reading; #9's 0.2h included the same reading, made faster because the recipe was already correct (`SA-1`) and #8's own reset was available as a reference shape.

**Did not save:** the reading itself, which the plan requires and which surfaced the three notes above. And the recipe still needed judgement where it claims to need none: "delete every per-assessment aside" can only be executed by first finding them, and the reliable way was a diff of two assessments' copies, not the recipe's prose.

## public_readme (id 200, phase 3) — 2026-10-04

**Effort:** 1 session, ~0.1h wall-clock (≈05:22 → 05:30) — process: light, closed by the leader
**#7 baseline:** no counterpart (README grew from phase 1)
**#8 baseline:** no counterpart (minimal README written in phase 1)
**Spec:** n/a (sdd: false)
**Tests:** n/a — documentation. Every claim in the README checked against this session's own verification (phase table, amendment summaries against #8's README registry, prerequisites against the installed versions)
**Inherited #8 findings:** README naming a licence with no `LICENSE` file (#8, closed late in `79dc89b`) → **avoided** — `LICENSE` ships in the same commit

**What was built:**

`README.md` for a public repository: what the system is, the trilogy table (#9 in progress), the second-reuse question, the inherited `SA-1`…`SA-5` table with one line each, the tech stack, prerequisites with the verified versions, the repository layout (what exists now and what arrives later), how it is being built, the 25-row phase table with phases 1–3 done, and the licence. `LICENSE` (MIT) copied from #8. The #9 row in #7's and #8's READMEs updated with the link, the current stack versions and "in progress" — one commit in each sibling.

**Deviations from the spec/plan:** none.

**Rejections:** none (light process, no reviewer)

**What the reuse saved — and what it did not:** #8's early README was the template, so the structure cost nothing; the content is new by construction (the second-reuse question, the inherited amendments table).

**Also filed this phase — backlog id 201** (`live_timeline_causation_names_commands_not_facts`, attached to `projector_read_model`): the "caused by" gap in #7's and #8's live timelines, diagnosed from the LinkedIn y Web plan's observation. R12 lets a responder fact cite the command that produced it, and the command is never in the timeline; #8's seed cites the triggering fact instead (*"one link shorter than a live saga's causal chain"*, `SagaFixtures.cs`), which is why seeded orders link and live ones do not. Disposition: decided at the phase 12 gate.

## infra_compose (id 4, phase 4) — 2026-10-04

**Effort:** 1 session, ~0.2h wall-clock (≈06:33 → 06:47, shared session with `messaging_topology`) — process: light, implemented and closed by the leader (compose and `infra/` are leader-editable)
**#7 baseline:** 1 session, ~4h (implementation ~1.5h, then two review rounds)
**#8 baseline:** 1 session, ~1.25h
**Spec:** n/a (sdd: false)
**Tests:** no code yet. The running stack, cold-started twice from empty volumes, plus four armed guards — the PostgreSQL healthcheck (init-window probe: rc=1 *connection refused* until init completes; sibling database name → rc=1), n8n's role isolation (`GRANT CONNECT … TO PUBLIC` → `otc_n8n` gets in; restored → *permission denied*), and the n8n-init hazard the shared anchor prevents (`DB_TYPE=sqlite` → imports 4 workflows into a fresh SQLite, rc=0). Detail in `progress/impl_infra_compose.md`
**Inherited #8 findings:**
- healthcheck that passes before the bootstrap (#7's MySQL socket, #8's MS-SQL `SELECT 1`) → **avoided**, and the plan's "less likely here" was probed rather than trusted: PostgreSQL's init server refuses TCP but accepts the socket, so the default `pg_isready` *does* pass during init — the trap applies
- `retries` copied from another repository's shape (#8, 30 → 10) → **avoided**: start measured (1.8 s / 2.15 s), `start_period` set from it
- unidentifiable image tag (#8, `2022-latest`) → **avoided**: `postgres:18.6` pinned, digest recorded
- n8n pointed at an application database (Retail Order Tracker) / an n8n database nothing connects to (#7 D4) → **avoided**, and made structural: own role, `CONNECT` revoked from `PUBLIC`

**What was built:**

`docker-compose.infra.yml` derived from #8's by targeted edits — 15 services, `name: otcpy` — with `postgres:18.6` (volume at `/var/lib/postgresql`, server timezone UTC, TCP-and-count healthcheck) in place of MS-SQL, and n8n on PostgreSQL through one YAML anchor shared by `n8n` and `n8n-init`. `infra/postgres/init/01-create-databases.sh`: four `otc_*` databases owned by `otc_app`, `n8n` owned by `otc_n8n`, `CONNECT` revoked from `PUBLIC`, all names from the environment as psql variables, idempotent via `\gexec`. Nine files copied `cmp`-identical from #8 (eight also identical to #7; the Grafana dashboard is #8's phase-22 version). `.env.example` scoped to phase 4, complete by enumeration (73 variables read, all declared except the documented `OTC_GATEWAY_URL` override).

**Deviations from the spec/plan:**

- A dedicated `otc_n8n` role (the plan names only `otc_app`): without it n8n logs in as a role that can create tables in every `otc_*` database.
- `otc_app` **owns** its databases instead of being granted privileges — on PostgreSQL ≥15 only the owner may create in `public`, so ownership is the equivalent of #7's `GRANT ALL`.
- Server `timezone=UTC` (one `command:` line, not in the plan).

**Rejections:** none (light process, no reviewer)

**What the reuse saved — and what it did not:**

| | #7 | #8 | #9 |
|---|---|---|---|
| Cold start to all-healthy | 35–42 s | 36 s | **39.3 s / 44.0 s** |
| Database container RAM | MySQL ~400 MB | MS-SQL 1.04 GiB | **PostgreSQL 47.8 MiB** |
| Stack RAM | — | 2 492 MiB / 12 | **1 277 MiB / 12** |
| Engine to bootstrapped | — | 4–9 s + ~3 s | **1.8–2.15 s** |

**Saved:** #8's note held — PostgreSQL has `/docker-entrypoint-initdb.d`, so the piece that cost #8 most of its 1.25h (an entrypoint for an engine with no hook) did not exist here. The nine reused files, the topic script's self-check and every comment carrying #7's review defects cost nothing.

**Did not save:** the engine-specific questions are new each time, and three of them needed a probe that #8's file could not answer: whether the init server listens on TCP (it does not, but the socket does), what `pg_hba` trusts inside the container (127.0.0.1 — so a password in the healthcheck would have been decoration), and who may create in `public` on PostgreSQL ≥15 (only the owner). And two of this session's own probes **failed for the wrong reason before they failed for the right one** — the init-window arm ran in a container without `POSTGRES_DB_*` (counted empty names), then without `POSTGRES_USER` (connected as `root`). Printing stderr in the third run is what made the failure name its claim. The lesson is already in `CLAUDE.md` ("its message must name the claim"); this is a second instance of it, recorded rather than smoothed over.

## messaging_topology (id 5, phase 4) — 2026-10-04

**Effort:** 1 session, ~0.1h wall-clock (≈06:47 → 06:51, shared session) — process: light, closed by the leader
**#7 baseline:** 1 session, ~3h (implementation ~1h, then two review rounds)
**#8 baseline:** 1 session, ~0.25h
**Spec:** n/a (sdd: false) — the topology is `specs/shared/asyncapi.yaml`
**Tests:** `kafka-init`'s exact-set assertion armed (planted `otc.orders.facts.v2` → rc=1 `FATAL: the broker's topic set does not match the spec exactly.`; removed → rc=0); NATS core-only verified by refusal (`nats stream add` → `no responders available`) and the check armed against a throwaway `-js` server (`Stream PROBE was created`), with a core request/reply round trip as the control. Detail in `progress/impl_messaging_topology.md`
**Inherited #8 findings:**
- `/varz | grep jetstream` as proof of core-only (matches either way; caught at #8's human gate) → **avoided**
- the plan's NATS table with 14 subjects (#8) → **avoided**: 15/15 by set difference, both directions

**What was built:** nothing new — the reused script created the 3 fact topics and 3 `.dlq` companions; spec, broker and Redpanda Console agree on the same 6.

**Deviations from the spec/plan:** none.

**Rejections:** none (light process, no reviewer)

**What the reuse saved — and what it did not:**

**Saved:** as #8 predicted, "the topic script ports untouched — budget nothing for it". The verification commands came from #8's finding, already in their corrected form.

**Did not save:** the enumeration of the spec is not a reused artifact, and its first version was wrong in an instructive way — it classified channels by `bindings`, which only the Kafka channels carry, so all 30 NATS channels landed in an unclassified bucket and the request count read 0. The spec declares transport through each channel's `servers` reference. Listing the unclassified bucket instead of dropping it is what exposed it (defeat-list row 11: the instrument did not recognise the form).

## monorepo_scaffold (id 6, phase 5) — 2026-10-05

**Effort:** 1 session, ~0.25h wall-clock (05:29 → 05:44: implementation ~10 min, leader review + one fix round ~5 min) — process: **light** (scaffold/config), every guard armed; closed by the leader after reading the diff and re-running `./quality.sh`
**#7 baseline:** 1 session, ~3.5h (a ~1h TypeScript-7 spike, approved first pass)
**#8 baseline:** 1 session, ~3h (one rejection: the domain-purity selector missed nested namespaces)
**Spec:** n/a (sdd: false)
**Tests:** 75 pytest (architecture guards, dependency-freedom, mypy and warning policies, seven health/CLI smoke tests), 10 import-linter contracts, 1 Vitest; `./quality.sh` exit 0, overall coverage 91%. Arming table in `progress/impl_monorepo_scaffold.md`.
**Inherited #8 findings:**
- domain-purity selector scoped to flat namespaces (#8 `monorepo_scaffold` D1) → **avoided**: nested `domain.value_objects` packages exist in all seven services from the start and every guard is armed there
- purity and no-`decimal` rules never scanned `SharedKernel` (#8 `shared_kernel` reopen) → **avoided**: `shared_kernel` is in both the import-linter contract and the AST walk, armed in each
- `typeof(decimal)` only, `double`/`float` missed (#8 `shared_kernel` D1) → **avoided**: six shapes armed (`float` literal, `float(...)`, `/`, `/=`, `import decimal`, `from decimal import`) plus `operator.truediv` and dynamic imports
- selector-based rule without a non-vacuity test (#8 note) → **avoided**: the walked population is asserted against a literal expected set
- coverage printed beside a green tick without gating (#8 note) → **avoided**: overall gate armed; the domain gate is a marked TODO owned by `shared_kernel`, because it passes vacuously on zero statements (measured)
- **recurred, in a new form:** the guard lost scope in translation again. import-linter forbids *module* names, and a deny-list of distributions does not cover the top-level modules a distribution installs under another name: `from bson import ObjectId` (PyMongo's) in a nested domain left all 10 contracts kept — the exact probe #8's reviewer used. Caught by the leader before close; fixed with an allowlist (stdlib + `otc_shared_kernel` + own domain tree) on the money guard's walker.

**What was built:** root `pyproject.toml` (uv workspace, dev group at the plan's pinned versions, ruff, `mypy --strict` with only `aiokafka.*` overridden, pytest with `function` loop scope written beside it and one measured DeprecationWarning filter for `testcontainers.community.nats`, coverage, import-linter), `uv.lock`; `packages/{shared_kernel,contracts,cqrs}` placeholders; seven services with four layers, a nested domain subpackage and a FastAPI lifespan app with `/health/live` (seed: a CLI); `tests/architecture/`; `apps/web` (Analog 2.8.0, Angular 22.2.1, pnpm 12.8.1, four build scripts denied with reasons, `resolve.tsconfigPaths`, jsdom 30.1.1 within pnpm's release-age gate); `quality.sh`.

**Deviations from the spec/plan:**
- `quality.sh` runs pnpm as `npx pnpm@<packageManager version> -C apps/web`: the global corepack pnpm 11.22.0 refuses the project, so the plan's `pnpm -C apps/web` fails on this machine (`init.sh`'s hint updated to name `quality.sh`).
- The layers contract is `presentation > infrastructure > application > domain`, so presentation may import infrastructure; the composition root sits outside the layers. To be revisited by `orders_acceptance` if presentation should reach adapters only through `composition.py`.
- The web lint step is `--if-present`: the Analog template ships no lint script.

**Rejections:** none (light process); one leader fix round (allowlist, a comment that counted five build scripts above four, and a `minimumReleaseAgeExclude` block that bypassed pnpm's supply-chain age gate for a jsdom published the day before).

**What the reuse saved — and what it did not:**

**Saved:** almost the whole of #8's ~3h. The defect #8 paid a rejection round for (nested scope) and the two #8 found one feature later (kernel not scanned, `float` missed) were written into this feature's brief as acceptance criteria, so they cost an arm each instead of a review round. The Phase 1 Analog probe had already found every scaffolder trap (nested `.git`, build-script gate, tsconfig paths), so `apps/web` took minutes.

**Did not save:** the instrument is new, so the scope question is new. #7's glob and #8's namespace predicate both matched *where the code is*; import-linter matches *what is imported, by module name*, and a distribution's module names are not its package name. No inherited finding could name `bson`. What found it was asking the #8 reviewer's question again in the new instrument's terms — the finding transferred as a *probe*, not as a rule.

## shared_kernel (id 7, phase 5) — 2026-10-05

**Effort:** 1 session, ~0.65h wall-clock, from the leader's `date` at each transition: dispatched 05:45, implementation to 05:57, review round 1 written 06:11 (**REJECTED**: 1 major, 5 minor, 2 nits), fix round finished 06:16, review round 2 approved 06:24 (**APPROVED**). (The reviewer first estimated ~0.8h from file timestamps; corrected by the leader to the measured clock.) Process: **full** (money domain). The review rounds took about two-thirds of the wall-clock; the domain code took the rest.
**#7 baseline:** 1 session, ~1.5h; approved first pass, zero defects.
**#8 baseline:** 1 session, ~1.25h; one reopen and one rejection (six defects), every defect in a guard.
**Spec:** n/a (`sdd: false`). The contract is feature 7's acceptance array, plus R1–R4, `domain-model.md` §2 and `CLAUDE.md`.
**Tests:** `./quality.sh` exit 0, 390 pytest passed (was 75 after feature 6), mypy clean on 82 files, 10 import-linter contracts kept. Coverage: domain and kernel 100% over 267 statements and 54 branches, overall 98.04%. The 6b ≥80% domain gate is wired and armed in both include halves (a service domain and the kernel). Arming tables: `progress/impl_shared_kernel.md` (implementer) and `progress/review_shared_kernel.md` (an independent re-arm: 64 runs in round 1, 20 in round 2, and 10 + 5 premise probes).
**Test-matrix flips:**
- R2, R3 and R4 → DONE.
- R1 → **SCOPED (ratified)**. Ratification record: the R1 split (domain half green; the API half, money in every Gateway response, is deferred) **was accepted by the leader in the phase 5 session, 2026-10-05**. That is not the row's author, so it meets matrix rule 3(b). The closer is feature 31 `api_tests`, whose acceptance names R1's API half.
- Summary counts 3 / 1 / 59.

**Inherited #8 findings:**
- **Guards never scanned the kernel** (#8 `shared_kernel` reopen) → **avoided**. The AST guard, the import allowlist and import-linter all cover `otc_shared_kernel`, and each is armed there.
- **#8 `shared_kernel` D1** (the float/double surface guarded by one word) → **recurred, in a new form**, and was caught by the reviewer in round 1. The member guard allowlisted *public* names and deny-listed dunders, so `__format__`/`__repr__` printing `1242.50 EUR` and a private `_major` property passed all 66 Money tests.
  - Fixed with three independent layers: a literal `vars(Money)` allowlist of every kind, an AST class-body allowlist that also sees `if TYPE_CHECKING:`, and a behaviour test over every text form.
  - Exactly the probe #8's closing note asked for ("which member kinds does it inspect … dunder methods? … arm one of each"). The note transferred as a probe for the reviewer, not as a property of the first draft.
- **D5** (sibling references not built) → **avoided**. `OrderNumber`, `DespatchReference`, `InvoiceReference` and `CreditLineReference` share one generic shape.
- **D6** (stale build after a restore) → **avoided**. Every arm cleared `__pycache__` and `.mypy_cache` and ran with `-B`, and every restore was `cmp`-checked. One near miss: the implementer's fix-round harness crashed with a mutant planted, the mutant was removed by hand, and the leader and reviewer then `cmp`-confirmed all seven kernel sources against the reviewer's backups.
- **D7** (exemption keyed too loosely) → **avoided**, because no float-accepting entry point and no exemption exist.
- **`0000000000000` GLN as the only evidence** → **avoided**. Seven real vectors are checked by an independent left-to-right oracle, with a swapped-weights discrimination test and #7's exhaustive single-digit sweep (gcd(3,10)=1).

**What was built:** `packages/shared_kernel` (`dependencies = []`) containing:
- `Money`: `int` minor units, bounded to int64 at construction (#8 `long` + `checked`, #7 `isSafeInteger`); `type(...) is int` refuses `bool` and integral floats; ordering refuses across currencies while `==` returns False; no division or conversion surface.
- `Quantity`: a strictly positive `int`, with no float entry point.
- `GLN`: ASCII digits only.
- The four business references: canonical, growing past six digits.
- `UniqueId`: v4 generation; parse accepts any non-nil UUID, as #8 does.
- `Entity` (type + id equality), `AggregateRoot` (pull/clear), `DomainError`, plus eight named errors.
- The SA-5 ISO 4217 exponent table: 26 entries, identical to #7's, #8's and #8's JSON, with `apps/web/src/lib/currency-exponents.json` and a two-way parity test.

The new guards are `test_kernel_surface.py` and the AST money guard extended with `fractions`, the truediv family and `**`/`pow`.

**Deviations, all disclosed:**
- **Canonical references** refuse `ORD-0000001` and `ORD-000000`. #8's regex and the wire pattern `^ORD-[0-9]{6,}$` admit them, and #7's SO8 test publishes `ORD-000000`. Routed to feature 16's acceptance.
- **`Quantity` is unbounded**; the write-boundary range check is routed to feature 9's acceptance.
- **Domain error codes** `unique_id.invalid` (#8: `unique_id.empty`) and three new reference codes. None of these codes appears in `specs/shared/`.

**Rejections:** one (round 1). #8's review standard would have caught it: it is #8's D1 class, and #8's closing note names the exact probe. #7's would not have, because #7 approved its kernel first pass with 4/4 probes and never asked about member kinds.

**Open, accepted, not fixed** (`review_shared_kernel.md` Round 2, R2-1 to R2-3): the kernel-surface population is not recursive (a subpackage escapes); the module allowlist misses tuple, walrus, `for` and `globals()` bindings; and the pow family written as an attribute escapes the AST guard (backstop: the `Money` construction type check). A backlog entry is proposed, attached to feature 13 `orders_aggregate`, for the leader to file.

**What the reuse saved — and what it did not:**

**Saved:** the domain code, again. It was correct on the first pass, and no reviewer mutant against it survived in either round. Copying `specs/shared/` and #8's exponent table made it transcription. #8's six findings were written into the brief as acceptance criteria, and five of them cost an arm each instead of a review round.

**Did not save:** about 0.8h against #8's ~1.25h and #7's ~1.5h is faster, but the shape is #8's: the only rejection was a guard that inspected fewer member kinds than the invariant it guards. Python's version of the gap was new: dataclass-generated dunders (`__repr__`) cannot be guarded by name at all, so the fix needed a behaviour test beside the allowlist. Round 2 then found that each new instrument brought its own unstated premise (non-recursive population, binding forms), which is CLAUDE.md's "changing an instrument swaps its premises", observed again.

## contracts_package (id 8, phase 5) — 2026-10-05

**Effort:** 1 session, ~0.8h wall-clock (06:24 → 07:13), from the leader's `date` at each transition and the reviewer's own `date`:

| Step | Time | Outcome |
|---|---|---|
| Dispatched | 06:24 | |
| Implementation | to 06:43 | |
| Review round 1 | 06:44–06:54 | **REJECTED**: 2 major, 2 minor, 3 nits |
| Fix round | 06:56–07:07 | |
| Review round 2 | 07:07–07:13 | **APPROVED**; 2 minor residuals and 2 nits accepted |

Review round 2 started on the fix round's finished files before the leader's 07:07 mark. Process: **full** (wire contract). The review rounds and the fix took about 0.5h of the 0.8h; generation and the golden parity work took the rest.
**#7 baseline:** 1 session, ~2.5h: implementation ~2h, including two generator surprises; approved first pass; 22 tests.
**#8 baseline:** 1 session, ~2.7h: ~1.9h of oracle capture and gate work, ~0.25h implementation, ~0.5h review; approved first pass; 21 tests; four advisories.
**Spec:** n/a (`sdd: false`). The contract is feature 8's five-item `acceptance` array, `asyncapi.yaml`, `openapi.yaml` and `CLAUDE.md`'s "JSON wire shape" bullet. No `R<n>` is claimed. R11 stays with `outbox_and_idempotency`, as in #8. `test-matrix.md` is untouched by this feature.
**Tests:** `./quality.sh` exit 0 end to end (the reviewer's round-2 run):
- 579 pytest passed (contracts 189);
- mypy clean on 97 files (`scripts/` now included);
- 10 import-linter contracts kept;
- drift check green;
- coverage: overall 99%, domain 100%;
- web green.

Arming tables: `progress/impl_contracts_package.md` (implementer, 39 arms + 15 in the fix round) and `progress/review_contracts_package.md` (an independent re-arm: 30 runs in round 1; 15 arms and 18 premise probes in round 2).

**What was built:**
- `scripts/generate_contracts.py` extracts `components.schemas` into JSON Schema:
  - it flattens the 14 `allOf` events;
  - it turns `int64`/`int32` into explicit bounds;
  - it refuses unknown formats.
  
  It then runs the pinned `datamodel-code-generator==0.83.0` (`--no-alias`, `--snake-case-field`, base class `WireModel`), formats the output through the repository's ruff configuration, and writes `generated/{asyncapi,openapi,nullable}.py`. Each header carries the first 16 hex digits of the spec's SHA-256. `--check` (`quality.sh` section 5) names any drifted or missing file.
- `otc_contracts.wire` holds the one configuration:
  - one `to_camel` alias generator;
  - `strict=True` and `frozen=True`;
  - `None` → `null` only for the 9 spec-nullable fields (MRO-aware);
  - `.mmmZ` instants in JSON mode;
  - `to_wire_json`, which re-validates and writes compact JSON with raw non-ASCII.
- `otc_contracts.facts` is the 14-entry `eventType` registry.
- The 12 #8 goldens are under `tests/fixtures/golden_envelopes/`, `cmp`-identical to #8's and SHA-pinned.
- A type-strict JSON comparer (`strict_json.py`).

**Leader rulings:**
- **`None` handling follows #7, not #8.** Explicit `null` for the 9 spec-nullable fields, all RPC/REST; the spec says `paidAt` is "null while `issued`". #8 omitted every null.
- **`pyyaml` and `types-pyyaml` go in the root dev group.**

Both were endorsed by the reviewer.

**Inherited #7 and #8 findings:**
- **#7 root-interface `{}` regex bug** → **avoided**. No text parsing of generated code beyond two header lines that sit behind the drift check.
- **#7 `title` beats the key for naming** → **avoided**. Titles are stripped; class name = schema key is asserted for every named schema.
- **#8 "check the serialiser's default instant format before writing a single payload type"** → **recurred**, caught in review round 1 (D2). The explicit formatter covered `to_wire_json` only. `model_dump_json`, `model_dump(mode="json")` and FastAPI's `response_model` wrote Pydantic's `.442000Z`. It is fixed in the fix round for direct fields. List-held and `Any`-dict instants remain as accepted residual R2-2.
- **#8 thirteen vs fourteen facts** → **avoided**. 14 are read from the spec at test time, with a non-vacuity assertion.
- **#8 "a spec-side probe, not a code-side one"** → **avoided**. Both the implementer and the reviewer edited `asyncapi.yaml` itself and restored it with `cp` + `cmp`.
- **#8 A1 (envelope byte-exactness asserted token-wise)** → **avoided**. Serializer bytes are compared with golden bytes up to `"payload"`.
- **#8 A2 (an `R<n>` cited with no validation)** → **avoided**. A `grep` finds no `R<n>` in the package.
- **#8 A4 (nothing guards Contracts' dependencies)** → **avoided**. There is an import allowlist and a declared dependency list of exactly `pydantic==2.13.5`.
- **#8 "`stock.rejected.v1` has no golden"** → **recurred, inherent and disclosed**. `order.saga_failed.v1` also has no golden. Both are listed in a test. Their round trips now use the type-strict comparer (D4).

**Rejections:** one (round 1).
- **D1:** the writer trusted mutable models. Assignment, `model_copy(update=)` and `model_construct` put `true` and `89.34` into money fields.
- **D2:** the formatter was not the only path to the wire.
- **D3:** the alias-agreement guard sampled named schemas only. An inline `warehouseGLN` survived.
- **D4:** the no-golden round trips used Python `==`.

**Would the earlier review standards have caught it?**
- **#8's:** D2, yes, because #8's closing note names the exact check. D1 is #8-specific in reverse: C# records and `long` supplied immutability and integer typing for free, so #8 never had to ask.
- **#7's:** no. #7 approved first pass with its own generator and had no golden oracle.

**Open, accepted, not fixed** (`review_contracts_package.md` Round 2, R2-1 to R2-4):
- **R2-1:** write-time re-validation lives only in `to_wire_json`, so `model_dump_json`, `pydantic_core.to_json` and FastAPI still write a `model_copy(update=)`/`model_construct` instance unvalidated.
- **R2-2:** the JSON-mode instant formatter covers direct `datetime` fields only, not list-held or `Any`-dict instants. There are none in the spec today; the generic `Envelope.payload` is the likely first trigger.
- **R2-3:** a stale `wire.py` docstring.
- **R2-4:** dead lax `RootModel`s.

A backlog entry (proposed id 203) is attached to feature 14 `outbox_and_idempotency` for the leader to file.

**What the reuse saved, and what it did not:**

**Saved:**
- **The oracle.** #8 spent ~1.9h capturing the 12 goldens and ruling on payload key order; #9 copied both and spent minutes.
- **The types,** again near-free, this time generated as #7 did.
- **#7's generator surprises** (title naming, the regex) did not recur.

**Did not save:** the same thing it did not save in #8 and in `shared_kernel`, which is proving the new stack satisfies the rule.
- **Python-specific surfaces.** Both majors were surfaces .NET never had. A Pydantic model is mutable and has a second, idiomatic serializer (`model_dump_json`, used by FastAPI) that ignores a hand-written writer. #8's immutable records, `long` and one `JsonSerializerOptions` applied app-wide closed both by construction.
- **Round 2 showed the same pattern again.** Each fix moved the property into a new instrument with a new unstated premise: re-validation in the writer while the serializer became a writer too; a formatter that sees fields but not containers.
- **Overall:** ~0.8h against #7's ~2.5h and #8's ~2.7h. Faster on the clock because the oracle was inherited. Not faster at verification: half the time went to two review rounds over guards.

## db_orders (id 9, phase 6) — 2026-10-05

**Effort:** 1 session, ~0.6h wall-clock, from file mtimes and the agents' own `date`.
- 10:47: brief and premise check.
- 10:50 to 11:06: implementation, about 16 minutes.
- 11:06 to 11:22: review, about 16 minutes. **APPROVED on the first pass.**

Process: **full** (persistence).

**#7 baseline:** 1 session, ~1.5h (implementation ~1h, review ~0.5h); approved first pass; 9 tables. Source: `../order-to-cash-dotnet/progress/history.md:351`.

**#8 baseline:** 1 session, ~2.3h, with one rejection: 7 of 8 FKs undeclared with a green suite, and `next_value` widened to `bigint`. Source: `../order-to-cash-dotnet/progress/history.md:350`.

**Spec:** n/a (`sdd: false`). The contract is feature 9's 5-item acceptance array, plus `Order To Cash - Databases.EN.md` §4, the plan's type-delta table and lines 962–974. No `R<n>` is flipped: R62's storage leg is proven, and the behaviour stays TODO for Phase 8.

**Tests:**
- 28 orders tests (18 integration on one session-scoped Docker-held `postgres:18.6`, 10 unit).
- `./quality.sh` green with the otcpy stack **stopped**: 606 passed, 98.83 % overall, 100 % domain. The reviewer re-proved this.
- The reviewer ran 16 independent arms (`progress/review_db_orders.md`), each `cp`, mutate, one test, restore, `cmp`, green.
- A 9-path write-path probe of the range guard.

**Inherited #8 findings:**
- **id 44 (money column width) → avoided.** `bigint` from the first migration; the literal 6-column population was re-armed by the reviewer on a different column.
- **id 45 (counter seed race) → avoided.** The seed is `ON CONFLICT DO NOTHING`. A sentinel runs #8's `IF NOT EXISTS … INSERT` and loses the race 30 of 30 rounds. The main test fails 3 of 3 when the seed is swapped for it.
- **#8 db_orders review D1 (FKs undeclared, green suite) → avoided.** The FK set is closed from `pg_constraint`, armed by delete and by two different substitutions.
- **#8 review D2 (counter widened, undisclosed) → avoided** for `next_value`. The undisclosed-type-deviation class recurred, smaller: `country` is `varchar(2)` where §4.1 says `char(2)` (F4, accepted with a ledger line).
- **#8 review D4 (no column closure) → avoided.**
- **#8 review D6 (credential default in source) → recurred** (F5, routed).
- **id 85 (self-assigned ports) → avoided.**
- **id 104 (suite hid behind a developer service) → avoided.**
- **#8 db_fulfillment/db_billing A1, A2, A3** (timestamp read-back, diagnostic before count, index closure) → **avoided**. All three were in the leader's mid-run addendum.

**What was built:**
- An async Alembic environment and a hand-written `0001` migration: 11 tables, 8 FKs, 37 indexes, all names explicit.
- SQLAlchemy 2 models, and `RawJson`, a `json` column that is passthrough text in both directions.
- A write-boundary range guard: an ORM `set` listener on every integer column, raising `DomainError` subclasses with stable codes.
- The counter SQL.
- `OrdersDatabaseSettings`.
- A repository-root `conftest.py`: one Docker-held container per session and a fresh database per test, for features 10 and 11 to reuse.

Packages installed: sqlalchemy 2.1.3 (+ greenlet 3.5.6 via `[asyncio]`), asyncpg 0.31.0, alembic 1.20.0 (+ mako 1.4.3), pydantic-settings 2.15.0.

**Deviations from the spec/plan:**
- One index per FK column (8) beyond the spec's own indexes. PostgreSQL does not create them implicitly, as MySQL and EF Core do. Disclosed.
- `country` is `varchar(2)` rather than §4.1's `char(2)`. #8 also widened it, to `nvarchar(2)`. **Not** disclosed by the implementer; the review accepted it, and the leader adds the ledger line.

**Rejections:** none.

**Open, accepted, not fixed** (`review_db_orders.md`). Filed by the leader in `feature_list.json` as ids 204–206, and the F4 ledger line added to `impl_db_orders.md`:
- **204**, attached to feature 15:
  - The range guard covers the ORM unit of work only (constructor, assignment, merge). ORM-enabled `insert()`/`update()`, bulk inserts and raw SQL reach the driver (F1).
  - It refuses a valid `attempts = SagaCommand.attempts + 1` expression (F2).
  - The settings class has a password default (F5).
- **205**, attached to feature 14: the engine rounds sub-millisecond instants while `format_instant` truncates (F6).
- **206**, attached to feature 10: the FK and index closed-set tuples are blind to `ON UPDATE`/`DEFERRABLE` and to the index access method (F3, F7).

**What the reuse saved — and what it did not:**

**Saved:** almost all of #8's ~0.87h rejection round. #8's two blocking defects were transcription failures against a document that stated the answer.
- #9 was handed those defects, plus #8's three later advisories, as acceptance criteria.
- Each one became a guard that was armed before review: an FK closed set, column closure, `next_value int`, index closure, timestamp read-back and the diagnostic before the count.
- The reviewer's independent substitutions found no member missing.
- Against #8's ~2.3h and #7's ~1.5h, ~0.6h is the first phase-6 run approved on the first pass with every acceptance guard re-armed by a second party.

**Did not save:** the Python-specific surfaces, which #8's stack supplied for free. They are where every finding sits:
- **SQLAlchemy's write paths.** There is no single write chokepoint like EF Core's `SaveChanges`, so a write-boundary guard has to choose an instrument. The chosen one, an attribute event, covers 3 of the 9 probed paths and over-refuses SQL expressions.
- **The asyncpg dialect's `json` codec.** It silently `json.loads` on read, which forced `RawJson`.
- **Rounding.** PostgreSQL rounds sub-millisecond instants where the wire truncates.

None of these existed in #8 (`long` fields, one `SaveChanges`, `nvarchar` payloads). As in `shared_kernel` and `contracts_package`, the inherited findings transferred as guards; the new stack's own premises did not, and the reviewer found them by probing instruments, not by reading the report.

## db_fulfillment (id 10, phase 6) — 2026-10-05

**Effort:** 1 session, ~0.55h wall-clock, from file mtimes and the agents' own `date`.
- 11:24–11:25: brief and premise check.
- 11:26 to 11:40: implementation, about 14 minutes.
- 11:40 to 11:57: review, about 17 minutes. **APPROVED on the first pass.**

Process: **full** (persistence).

**#7 baseline:** ~1.25h, approved first pass (`../order-to-cash-nestjs/progress/history.md:549`).

**#8 baseline:** ~0.55h, approved first pass (`../order-to-cash-dotnet/progress/history.md:397`, `:482`).

**The comparison:** #9 matches #8's time and is ~2.3× faster than #7. In the same time it also did three things #8's run did not:
- back-ported two inherited fixes into the previous feature's code (204(b)(c), 206);
- added a parity guard over a copied module;
- had every guard re-armed by a second party.

**Spec:** n/a (`sdd: false`). The contract is feature 10's 3-item acceptance array, backlog 206, 204(b)(c), `Order To Cash - Databases.EN.md` §5/§4.3 and the plan's type-delta table. No `R<n>` is claimed.

**Tests:**
- 45 new tests: 27 fulfillment integration tests (on the shared root-`conftest.py` container), 15 fulfillment unit tests and 3 parity-guard tests. With the pre-existing health test, the fulfillment-plus-parity collection is 46, matching the report.
- `./quality.sh` green with the otcpy stack **stopped**: 655 passed, 98.99 % overall, 100 % domain, import-linter 10 kept. The reviewer re-proved it: 69.5 s wall-clock, and `docker events` shows **one** `postgres:18.6` container per run.
- The reviewer ran 22 independent arms and probes (`progress/review_db_fulfillment.md`), each `cp`, mutate, one test, restore, `cmp`, clear caches, green.
- A 10-path write-path probe plus a 9-expression pass-through probe.
- A 48-fact live-catalog parity dump of `outbox`/`processed_events`, `otc_orders` against `otc_fulfillment`: identical, with a sentinel.

**Inherited #8 findings:**
- **#8 db_fulfillment A1 (no timestamp read-back) → avoided.**
- **A2 (count before diagnostic) → avoided.**
- **A3 (index presence-only) → avoided.**
- **A4 (stale `current.md`) → avoided.**
- **#8 timing risk (one container per database suite) → avoided.** One container per run.
- **id 44 (money width) → not applicable.** There is no money column, asserted from the live catalog.
- **id 45 (seed race) → avoided.** Sentinel 30/30, and a sibling `DO UPDATE` seed caught.
- **#8 db_orders D1 (FKs undeclared) → avoided.**
- **D2 (undisclosed type deviation) → recurred, smaller:** two ledger lines missing, `reservations` code widths and `despatch_number_sequences.id` (N2).
- **D6 (credential default) → avoided** in fulfillment; it is still open in orders (204(d)).
- **ids 85 and 104 → avoided.**
- **#9 review_db_orders F1, F2, F3, F7 → closed here.** F1 and F2 as 204(b)(c), in both copies; F3 and F7 as 206, with a back-port to orders.

**What was built:**
- An async Alembic environment and a hand-written `0001`: 7 tables, 2 FKs, 18 indexes.
- SQLAlchemy models.
- `FulfillmentDatabaseSettings`, with no password default and without `populate_by_name`.
- The counter SQL.
- The range guard, **copied** byte-identically: its quantity map became a parameter of `install_range_guards`, so the two copies need no allowed differences.
- `tests/architecture/test_range_guard_parity.py`: a closed member list and a census.
- The FK tuple widened by `confupdtype`, `condeferrable`, `condeferred` and `confmatchtype`; the index tuple by `pg_am.amname`. Both widenings are in both services.

Packages installed: sqlalchemy 2.1.3 (+ greenlet 3.5.6 via `[asyncio]`), asyncpg 0.31.0, alembic 1.20.0 (+ mako 1.4.3), pydantic-settings 2.15.0 — the same pins as feature 9, now also in `otc-fulfillment`.

**Deviations from the spec/plan** (all type translations under the plan's delta table, or #7/#8-consistent widths):
- `uuid`, `timestamptz(3)`, identity `seq`;
- two FK-supporting indexes;
- `reservations` code widths 20/20/30, of which only `retailer_code` was disclosed;
- `despatch_number_sequences.id integer`, where #7 has `tinyint`.

**Rejections:** none.

**Open, accepted, not fixed** (`review_db_fulfillment.md`; proposed for the leader to file):
- **207**, attached to feature 17 `fulfillment_stock` (F1, minor). The 204(c) pass-through lets a non-integer expression through, and PostgreSQL silently rounds it: `literal(3.7)` stored 4, and `Stock.units * 0.5` stored 0.
- **208**, attached to feature 11 `db_billing`:
  - the index tuple is still blind to sort order (`DESC` stayed green), and conflates `INCLUDE` with key columns (F2, minor);
  - the settings test depends on the shell's `POSTGRES_HOST_PORT` (N4).
- **204, extended with (e)** (A1). Orders' `populate_by_name=True` lets bare `USER`, `HOST`, `PORT` and `PASSWORD` into the database URL. `HOST` leaks even with the repository `.env`, which defines no `POSTGRES_HOST`. Items (b)(c) were closed by this feature.
- **206 → done** (leader).
- **Nits:** ledger lines (N1, N2); a literal-vs-literal line (N3); the parity guard is line-equal and has a one-path census (N5); the residual pin covers 4 of 6 named paths (N6); the report gave the contract count as 9, where the run gives 10 (N7).

**What the reuse saved — and what it did not:**

**Saved:** the whole schema and every guard shape. Feature 9 paid for both, and its review's findings arrived as acceptance criteria. The proof took ~14 minutes of implementation:
- the closed FK, index and type sets;
- the timestamp read-back;
- the sentinel;
- the live population.

Nothing in the review was a transcription defect against the document.

**Did not save:**
- **The Python-specific surface.** It moved one step again. Fixing 204(c) as specified (pass SQL expressions through) opened a new, silent hole that #8's `long`-typed EF writes could never have: PostgreSQL's assignment cast rounds a numeric expression into an `integer` column.
- **The index instrument.** It needed a second widening that no inherited finding named.

As at `db_orders`, the new findings came from probing the instruments, not from reading the report.

## db_billing (id 11, phase 6) — 2026-10-05 — closes Phase 6

**Effort:** 1 session, ~0.85h wall-clock, from file mtimes and the agents' own `date`.
- 11:58–12:01: status set, brief, premise check (1 FALSE, a path, corrected before dispatch).
- 12:02 to 12:33: implementation, about 31 minutes (including a 95.2 s gate run that triggered the template mitigation, and a second gate run).
- 12:34 to 12:50: review, about 16 minutes. **APPROVED on the first pass.**

Process: **full** (persistence).

**#7 baseline:** 1 session, ~0.75h (implementation ~0.5h, review ~0.25h), approved first pass (`../order-to-cash-nestjs/progress/history.md:603-609`).

**#8 baseline:** 1 session, ~0.75h (implementation ~0.5h, review ~0.25h), approved first pass, six advisories (`../order-to-cash-dotnet/progress/history.md:439-443`).

**The comparison: not faster.** ~0.85h against ~0.75h and ~0.75h, about 1.1× slower than both. Where the time went: the gate crossed 90 s, so this feature also built and pinned a cross-cutting test-infrastructure change (the template databases, edited into all four services' conftests) that neither #7 nor #8 had; and its parity test covers four live databases with five permanent arms, where #7 compared migration text in three apps and #8 compared six column properties.

**Spec:** n/a (`sdd: false`). The contract is feature 11's 3-item acceptance array, backlog 208, `Order To Cash - Databases.EN.md` §6, §7 and §4.3, and the plan's type-delta table. No `R<n>` is claimed.

**Tests:**
- 72 tests in this feature's directories: billing 49 and notifications 12 (each including its pre-existing health test), the four-database parity test 8 (`tests/database_parity/`), the template isolation pin 3 (`tests/database_templates/`); the range-guard parity guard grew to 12 (billing a member, census at any depth over `range_guards.py` and `types.py`, CRLF).
- `./quality.sh` green with the otcpy stack **stopped**: 734 passed (655 at feature 10), 99.15 % overall, 100 % domain, import-linter 10 kept. The reviewer re-proved it: **84.6 s** wall clock, pytest 63.6 s.
- The reviewer ran 15 independent arms (`progress/review_db_billing.md`), each `cp`, mutate, one test, restore, `cmp`, clear caches, green. One escaped: a table in a non-`public` schema (M1, routed to 209).
- A timing experiment: the template mitigation saves ~7 s of 62 s on the integration subset.

**Inherited #8 findings:**
- **#8 db_billing A1 (index set presence-only) → avoided.** Closed set of 22, with sort options and key-column count.
- **A2 (parity omits identity) → avoided.** Identity kind and sequence parameters in the shape; the reviewer's BY DEFAULT-for-ALWAYS arm was named.
- **A3 (no timestamp read-back) → avoided.** Every round trip compares instants; `paid_at` and `value_date` rounding pinned.
- **A4 (parity test owned by one service) → avoided.** `tests/database_parity/`, no service package imported at source level.
- **A5 (`current.md` one transition stale) → avoided.**
- **A6 (coverage not gateable) → avoided.** One workspace coverage run, 60 % overall and 80 % domain gates.
- **id 44 (money width) → avoided.** 7 `bigint` money columns from `0001`; 6 + 7 + 0 = 13 reconciles #8's "all 13 money columns".
- **id 45 (seed race) → avoided.** `ON CONFLICT DO NOTHING`; sentinel lost 10 of 10 rounds; the reviewer's advance-by-2 arm caught.
- **ids 85, 104 → avoided.** Docker-held port; gate green with the stack down.
- **#8 db_orders D2 (undisclosed type deviation) → avoided.** Every deviation on the ledger line (N2 of feature 10 applied).
- **#8 db_orders D6 (credential default) → avoided** (no password default, no `populate_by_name`).
- **#9 review_db_fulfillment F2/N4 (backlog 208) → closed** as written; N5 (census hole) closed; A2 (wall clock) acted on.

**What was built:**
- Two async Alembic histories, hand-written `0001`s: `otc_billing` (8 tables, 3 FKs, 22 indexes) and `otc_notifications` (`processed_events` only).
- SQLAlchemy models; billing's copies of `range_guards.py` and `types.py`; notifications deliberately has neither (no integer or payload column).
- `BillingDatabaseSettings`, `NotificationsDatabaseSettings` (fulfillment's class), with 208(b)'s fixture and an alias-closure test.
- The counter SQL for `invoice_number_sequences`.
- The neutral four-database parity test and the root-`conftest.py` template databases with an isolation pin.
- 208(a) back-ported to orders and fulfillment.

Packages installed: sqlalchemy 2.1.3 (+ greenlet 3.5.6 via `[asyncio]`), asyncpg 0.31.0, alembic 1.20.0 (+ mako 1.4.3), pydantic-settings 2.15.0 — the same pins as features 9 and 10, now also in `otc-billing` and `otc-notifications`.

**Deviations from the spec/plan** (type translations under the plan's delta, or #7/#8-consistent widths, all on the ledger): `uuid`, `timestamptz(3)`, 7 `bigint` money columns, identity `seq`, `invoice_number_sequences.id integer` (#7 `tinyint`), NO ACTION on `credit_items`/`payments` FKs (#7's value), two FK-supporting indexes.

**Rejections:** none.

**Open, accepted, not fixed** (`review_db_billing.md`; proposed for the leader to file):
- **209**, attached to feature 23 `notifications_service` (M1, minor): the "nothing else" closed set is scoped to `public`; a schema-qualified table escapes it. May be taken earlier as a light test-only change.
- **210**, attached to feature 15 `orders_acceptance` (N1): fulfillment's settings test still fails with `POSTGRES_HOST_PORT` exported; converge all four settings tests with 204(d)(e).
- **208 → done.**
- Nits: ledger rows without a file:line (N2); the parity process loads four model modules through `env.py` (N3). Advisory: the gate is 84.6 s, 5.4 s under the threshold (A1).

**What the reuse saved — and what it did not:**

**Saved:** every guard shape and every one of #8's six db_billing advisories, which arrived as acceptance criteria and were avoided first time. The review found no transcription defect against the document, for the third feature running.

**Did not save:** time. #7 and #8 were both at their floor on this feature (~0.75h, their third database). #9's extra work was its own: a test-infrastructure change forced by its own gate, and parity proved from four live catalogs rather than from migration text (#7) or six column properties (#8). The new finding again came from probing the instrument (a namespace filter), not from reading the report.

### Phase 6 — closing assessment

| | #7 (NestJS) | #8 (.NET) | #9 (Python) |
|---|---|---|---|
| `db_orders` | ~1.5h, first pass | ~2.3h, **rejected** once | **~0.6h**, first pass |
| `db_fulfillment` | ~1.25h, first pass | ~0.55h, first pass | **~0.55h**, first pass |
| `db_billing` | ~0.75h, first pass | ~0.75h, first pass | **~0.85h**, first pass |
| **Phase 6 total** | **~3.5h** | **~3.6h** | **~2.0h** — ~1.75× faster than #7, ~1.8× faster than #8 |

Sources: #8's own closing table (`../order-to-cash-dotnet/progress/review_db_billing.md:332-341`) for #7 and #8; this file's three entries for #9.

**The saving is entirely in the first feature.** #9's db_orders was ~2.5× faster than #7's and ~3.8× faster than #8's, because it received #8's rejection (FKs undeclared with a green suite) and #8's later advisories as acceptance criteria, and passed first time. db_fulfillment matched #8. db_billing was slightly slower than both. That is #8's own curve, shifted one feature earlier: the reuse dividend is largest where a baseline was still learning, and it is gone once both baselines had learned the pattern. #8's phase-6 sentence was "the spec is free, the proof is not, and one rejection costs more than two clean features save". In #9 the inherited findings removed the rejection, and that removal *is* the phase's saving; on the two features where no rejection was there to remove, #9 ran at #8's pace or slower. The extra cost has one cause: the Python-specific surfaces (SQLAlchemy's write paths, asyncpg's json codec, PostgreSQL's rounding, now the template databases and the namespace scope). No inherited finding could name these, and every #9 review finding in the phase sits on one of them.

## Phase 6 — leader session log — 2026-10-05

One session, 10:47 → 12:50, three features, each approved on the first review round (full process, Opus reviewers, `premise_checker` over every brief). Archived from `progress/current.md` at close.

- 10:47 `db_orders` set `in_progress`. Brief (scratchpad) premise-checked: `progress/premise_db_orders.md`, 0 FALSE. Scope bounds: no repositories/relay/allocator (Phase 8); #8's later saga dead-letter columns not added (not in the plan's `saga_commands`); quantity column `integer` (#7 and #8 width) with a write-boundary DomainError.
- 10:50–11:06 implementer → `in_review` (`progress/impl_db_orders.md`). Mid-run addendum from #8's db_fulfillment/db_billing reviews: shared session-scoped postgres container (now root `conftest.py`), index-set closure, timestamp read-back, FK diagnostic first.
- 11:07 reviewer launched (Opus, full group).
- 11:22 `db_orders` APPROVED round 1 → `done` (`progress/review_db_orders.md`: 0 blocking, 5 minor, 1 advisory, 3 nits). Leader filed backlog 204 (→ 15), 205 (→ 14), 206 (→ 10) and the F4 ledger line.
- 11:25 `db_fulfillment` set `in_progress`. Ruling: `range_guards.py` is copied per service, not shared — the listener is SQLAlchemy-bound so it cannot live in `shared_kernel` (dependencies = []), and CLAUDE.md:82 allows no other shared runtime package; a parity guard over the copies replaces sharing. 204(b)(c) (docstring, ClauseElement pass-through) are pulled into feature 10 so the defect is not copied.
- 11:26–11:40 implementer → `in_review` (`progress/impl_db_fulfillment.md`); guard copies byte-identical under `tests/architecture/test_range_guard_parity.py`; `quality.sh` 61 s (stack stopped). Implementer finding: orders' settings `populate_by_name=True` lets a bare `$USER` become the DB user — candidate for 204(d), pending the reviewer's confirmation.
- 11:41 reviewer launched (Opus, full group).
- Wrap-up note: feature 10 edited `services/orders` (204(b)(c), 206 back-port); the `db_orders` commit will carry orders files in their final state — say so in its body.
- 11:57 `db_fulfillment` APPROVED round 1 → `done` (`progress/review_db_fulfillment.md`: 0 blocking, 2 minor, 2 advisory, 7 nits). Leader: 206 → `done`; 204 note ((b)(c) closed) + item (e) settings leak; filed 207 (→ 17) and 208 (→ 11); N1/N2 ledger lines added to `impl_db_fulfillment.md` (#8 citations re-checked by `grep`).
- 11:58 `db_billing` set `in_progress`.
- 12:01 `db_billing` brief premise-checked (`progress/premise_db_billing.md`: 1 FALSE — #7's parity test is `apps/seed/src/outbox-parity.spec.ts`; corrected in the brief before dispatch). Implementer launched ~12:02.
- ~12:02–12:33 implementer → `in_review` (`progress/impl_db_billing.md`). `quality.sh` 95.2 s crossed the 90 s threshold → template-database mitigation in root `conftest.py` → 85.5 s; it required a 4-line `migrated_db` edit in the orders and fulfillment integration conftests (outside the brief's bound, flagged by the implementer). 208(b) applied in billing/notifications only; fulfillment's settings test still env-dependent.
- 12:33 reviewer launched (Opus, full group).
- 12:50 `db_billing` APPROVED round 1 → `done` (`progress/review_db_billing.md`: 0 blocking, 1 minor, 3 nits, 1 advisory; template mitigation kept, the 4-line conftest edits ruled in bounds). Leader: 208 → `done`; filed 209 (→ 23) and 210 (→ 15); N2 #7 citation added to `impl_db_billing.md`. Phase 6 closed; `current.md` reset with the Phase 7 brief.
- 14:53–14:55 backlog **209** (`closed_set_namespace_scope`, review_db_billing M1) fixed before the commit at the maintainer's request, classified **light** (test-only): one implementer, the leader read the diff, re-ran the four lifecycle tests (9 passed) and ruff/mypy on them; armed once in notifications (`assert {'audit', 'public'} == {'public'}`). → `done`. Not re-run: the full `./quality.sh` (the maintainer's run at 14:46 predates this test-only change).

---

## seed_job (id 12, phase 7) — 2026-10-05 — closes Phase 7

**Effort:** 1 session, **~2.9h wall-clock** (≈15:55 → 18:49; the start is the leader's estimate, the first artifact is the premise check at 16:09), four implementation rounds and four reviews, plus two maintainer gates. From the agents' own `date` stamps and file mtimes:
- ≈15:55–16:09: leader research (#8's D1, the import-linter independence contract, the sentinel lever), brief, premise check (`progress/premise_seed_job.md`, 28/28 VERIFIED).
- 16:09–16:55: round 1 — Part A (sentinel cut, light) 16:09–16:20, Part B (the seed) 16:20–16:55, Part C (parity tooling) interleaved.
- 16:55–17:10: review round 1 (Opus) — **REJECTED**, B1: `dump8` passed `sqlcmd -W` with `-y 0`, which sqlcmd refuses before connecting; N1–N4.
- 17:11–17:19: round 2 (B1 proven on a throwaway SQL Server, N1–N4); 17:19–17:22 re-review **APPROVED, acceptance 5 open**.
- Gate (maintainer, ≈18:10): live #8 parity authorised; **findings are fixed in the phase that detects them** (CLAUDE.md amended); threshold ~105 s.
- 18:18–18:29: round 3 — live parity against #8 (met), backlog 211 (counters), 212 seed half; 18:30–18:37 review round 3 (fresh Opus) — **REJECTED**, B1: the DES/INV counter fixtures mirrored the ORD suffix, so a sibling-column MAX passed; B2: ledger rows missing.
- Second rejection → maintainer asked → "fix both". 18:45–18:47 round 4 (light); 18:47–18:49 re-check (Sonnet) **APPROVED** → 12, 211, 212 `done`.

Process: **full** for the seed and 211 (persistence, concurrency); Part A and round 4 **light** (test-only / report rows).

**#7 baseline:** 1 session, "~0.5h — implementation ~22 min (file timestamps 10:39–11:01), review ~1h", approved first pass (as #8 recorded it, `../order-to-cash-dotnet/progress/history.md:513`; the figure and its parts disagree — quoted, not reconciled).

**#8 baseline:** 1 session, ~1.9h, **REJECTED once** (D1, unguarded timeline values), approved on round 2 (`../order-to-cash-dotnet/progress/history.md:511-512`).

**The comparison: not faster.** ~2.9h against #8's ~1.9h and #7's ~0.5h/~1.5h. The scope is not like for like: #9's Phase 7 also (a) cut the gate time by a change of kind, (b) ran the live parity diff against #8's databases — #8 deferred its equivalent against #7 and never closed it — and (c) fixed the reference-counter seeding (211), which #8 needed two later features for (id 45 seed race, id 47 scan cost, phase 21). Excluding gate waits, the agents' time was ~2.2h.

**Tests:** 734 → 922 (`quality.sh`, round 3, stack stopped); seed: 137 unit + 31 integration; counters +18. `quality.sh` 108.86 s (threshold re-baselined to ~105 s; re-measure at wrap-up, >110 s is a finding). Parity evidence: `progress/evidence/seed_parity/` — 19 of 20 files row-identical to #8's live databases; the 20th (live stock) shows 5 rows of #8's own 2026-09-18 traffic.

**Inherited #8 / #7 findings:**
- #8 D1 (timeline values unguarded) — **avoided**: oracle checked in first (executed from #7's TS, equal to #8's), every leaf compared with its type; 17 unpublished reviewer arms failed by name.
- #8 D3 (weak counts) — **avoided** (exact counts, every-row comparison). #8 D6 (pure tests behind containers) — **avoided** (unit/integration split). #8 A2 (extra keys unseen) — **avoided** (key-set comparison).
- #8 D5 (report/filesystem mismatch) — **recurred in miniature** (round-1 N2: four stale docstring paths).
- #8 id 47 (MAX scan on every allocation) — **avoided**, EXPLAIN-pinned (`never executed` on the steady-state path). #8 id 45 (seed race) — avoided in Phase 6, still green on the new statement. #7 D6 (text MAX) — **avoided** (bigint MAX, `ORD-1000000` test).
- #8's never-closed "parity against the previous build's live database" — **avoided** (acceptance 5 met).
- The `MySQL GROUP_CONCAT` / `STRING_AGG` truncation class — avoided by design (rows dumped client-side); its sqlcmd cousin (256-char `nvarchar(max)` truncation without `-y 0`) was the round-1 blocker's trap.

**New in #9:** service independence forbids the seed importing the services' models (#8's seed referenced them), so the seed owns Core tables and a live-schema drift check; insert-if-missing instead of #7's/#8's upsert (accepted divergence, re-open triggers in `review_seed_job.md` round 1 point 4).

**Lessons:** (1) a test helper that derives one reference from another makes a sibling-column mutation invisible — "distinct values" applies to the columns a statement must NOT read; (2) a parser test fed canned output cannot see an argv error — the B1 of round 1 needed the real binary.

## Phase 7 — leader session log — 2026-10-05

One session, ≈15:55 → 18:49, one feature (`seed_job`) plus backlog 211 and 212, four rounds. Archived from `progress/current.md` at close.

- Process sized: Part A light, Part B full; one implementer for both; Opus reviewer for B. Brief premise-checked (28/28).
- Round 1 → REJECTED (B1 sqlcmd flags). Leader filed 211/212 from the review (later re-attached, see the gate). Round 2 (fresh implementer) → APPROVED with acceptance 5 open. Leader closed Part A after reading the diff and running the three sentinel files (`6 passed in 9.93s`).
- Gate: the maintainer authorised the live #8 parity (start #8's mssql + mongodb only, read-only, remove after), ruled that findings are fixed in the phase that detects them (CLAUDE.md amended; memory saved), and re-baselined the gate to ~105 s. Leader re-attached 211 and 212's seed half to `seed_job`, added 212's projector half to feature 24's acceptance.
- Round 3 (premise-checked: 1 FALSE line ref corrected; credentials note added) → parity met, 211 and 212 done; the leader removed the `otcnet-net` network the run left behind. Review round 3 → REJECTED (B1 mirrored fixtures, B2 ledger). Second rejection → maintainer: fix. Leader superseded 211's acceptance item 1 (the unconditional-aggregate shape) with the no-scan shape (review N1).
- Round 4 (light) → re-check APPROVED → 12, 211, 212 `done`.

## backlog sweep 202, 203, 204, 207, 210 (+ carries for 201, 205) — phase 7 — 2026-10-05

**Why it happened in Phase 7:** at the Phase 7 gate the maintainer ruled that findings are fixed in the phase that detects them (CLAUDE.md amended), then asked for the open backlog entries from Phases 3–6 to be fixed now ("please, fix them"). The leader split them by whether their code exists: 202, 203, 204, 207, 210 fixed; 201 (projector) and 205 (outbox) need unbuilt code and were carried as acceptance items — 201 → features 24 and 29 (its seed item done by seed_job), 205 → feature 14; 203 item 2's generic-Envelope half → feature 14.

**Effort:** ≈19:30 → 21:15, **~1.75h wall-clock**, five implementation rounds, four Opus reviews (one reviewer resumed across rounds 2–4), three maintainer gates (after the second, third rejection, and the stray file). Round 1 19:44–20:35 (premise check 19:44: 1 FALSE — 204(a)'s grep misses raw SQL strings), review 1 REJECTED (3 blocking: `from math import pow`; the write-path census keyed hits as a set; `to_wire_json` wrote an unvalidated model inside `Envelope.payload`). Round 2 → REJECTED (`operator.ipow`/`itruediv`/`getattr`; SQL comments, aliased DML classes, an unarmed premise). Round 3 (module ban) → REJECTED (`statistics.mean`, built-in `pow` as a value, `copy_to_table`). Round 4 — **change of kind approved by the maintainer**: a literal import ALLOW-list derived from the census (collections, dataclasses, datetime, hashlib, types, typing, uuid + first-party) and `pow`/`float`/`round` banned as names, with a **stopping rule written before the round** → APPROVED, 0 blocking. Round 5 (light, leader-closed): the allow-list test re-derives the census instead of comparing literals; a stale docstring corrected; leader read the diff and ran the file (`304 passed`).

**Classification:** full (money guard, wire contract, persistence, security); round 5 light.

**Baselines:** none comparable — #7 and #8 never ran a cross-phase sweep; these entries are #9's own Phase 3–6 findings (#8 analogues: the money AST guard's evolution over #8 ids 44/104; #8 review_db_orders D6 for 204(d)).

**Tests:** 922 → ~1 090 (quality.sh 117 s in round 4, threshold re-baselined by the maintainer to ~125 s after review measured 126.05 / 114.94 s — the growth was Phase 7's seed suites, the sweep added <1 s).

**Incident:** the round-1 reviewer created a stray untracked `packages/shared_kernel/src/otc_shared_kernel/currency.py` while planting a mutation; its own `rm` was refused by the permission classifier and it asked the leader to delete it. The leader did not (permission laundering) and asked the maintainer, who authorised the deletion. Later review requests required planting only in existing files or scratchpad copies and a `git status --short` snapshot check — no recurrence.

**Lessons:**
- **A deny-list guard loses by construction.** Three rounds closed every reported form and the reviewer found three new ones each time. The fix that ended it was a change of kind — an allow-list derived from a census — plus a stopping rule agreed with the maintainer before the round. CLAUDE.md already says "when a syntax guard keeps losing, test the behaviour"; the leader should have proposed the allow-list after the second rejection, not the third.
- **Census before design.** One AST command (35 files, 7 stdlib roots, zero uses of pow/float/round/math/operator) made the allow-list obviously cheap; it should have been run when 202 was first briefed.
- **Named residual with its backstop:** float-returning APIs of allowed modules (`datetime.timestamp()`, `timedelta.total_seconds()`) are caught where the value reaches `Money` (`type(...) is int`) and by `mypy --strict`, not in an untyped intermediate.

## orders_aggregate (id 13, phase 8) — 2026-10-06 — the first `"sdd": true` feature of #9

**Classification:** full group (money domain). Spec, then human gate, then implementer, then reviewer (opus), with arming and the defeat list.

**Effort:** 1 session, about **2.9 h elapsed** (06:58 to 09:51). That window includes the human-gate wait, so it is not effort. The figures below come from file mtimes and are estimates, not stopwatch times:

| Step | Time window | Duration |
|---|---|---|
| Spec pass | 06:58 to 07:29 (`requirements.md`); `design.md` / `tasks.md` finalised before the gate | about 0.5 h |
| Gate wait | 07:29 to 09:03 | idle, not counted |
| Implementation | 09:03 to 09:26, plus the arming script, 87 arms | about 0.4 h |
| Review round 1 | 09:27 to 09:38 | about 0.2 h |
| Rework | 09:39 to 09:44 (test-only, 3 tests, 12 arms) | about 0.1 h |
| Review round 2 | 09:44 to 09:51 | about 0.1 h |

**Active total: about 1.3 h. Review rounds: 2 (one rejection).**

**Baselines:**
- **#7:** about 1.5 h (spec about 0.5 h, implementation about 32 min, review about 25 min). Approved first pass, 6 minor defects, 1 survivor.
- **#8:** about 1.15 h of authoring and review, implementation about 0.7 h. Approved first pass, 1 defect (two Rehydrate checks survived deletion), 5 advisories.
- **#9:** about 1.3 h active. Its implementation was faster than both (about 0.4 h against #7's 0.53 h and #8's 0.7 h). It was not faster overall, because of one extra review round. **It was not cheaper at review:** this is the first of the three builds to reject this feature.

**Tests:**
- 124 pure domain tests in `services/orders/tests/unit/domain/` (11 files), 6 contract-parity tests, and 14 kernel `format_money` vectors.
- `quality.sh`: exit 0, **1436 passed** = 1290 (Phase 7) + 124 + 6 + 14 + 2 (`test_kernel_surface[money_text]` ×2). The run was implementer-reported with the `otcpy` stack **up**, at 139 s, which is not comparable with the about-125 s stack-stopped threshold. The leader re-times it stack-stopped at wrap-up.
- `lint-imports`: 10 kept, 0 broken. `mypy --strict`: 241 files clean.

**What was built:**
- `Order` with Table T-1 as a `frozenset[Edge]` (11 edges, no creation row).
- Eight transitions plus `cancel`, with no public method taking an `OrderStatus`.
- A single-writer `_transition_to`, and candidate-then-commit line mutation.
- Four frozen, keyword-only domain events.
- Twelve domain errors, one of them new in #9: `order.instant_not_utc`, a language-forced check for naive `datetime`s.
- A totals-free `rehydrate` with nine load checks.
- OP-1: `format_money` moved from the seed into `otc_shared_kernel`. The function body is byte-identical; only the import changed, to avoid a kernel import cycle.

**The rejection (round 1), and whether #7's or #8's standard would have caught it.**
- Unrequested reviewer probes found that ten field-level corruptions left the whole suite green. Four were on event payloads, two of them money fields: `OrderCompleted.total_amount`, and `OrderPlacedLine` price swapped with discount. Four were on `rehydrate`'s field mapping and two on `place`'s read model.
- The implementer had armed deletion on every emission branch, but field corruption only on reason, note and ids. This breaks CLAUDE.md's fact-emission rule (*"... and when a field of it is corrupted"*).
- **Neither #8's nor #7's review would have caught it.** #8's six probes were deletion and guard order, and #8's domain tests have the same gap. `OrderRehydrationTests` and `OrderEventsTests` assert no GLN, date or code fields.
- The rework was test-only: tasks 3.22, 4.17 and 5.12, with all 10 survivors killed in round 2.
- **One residual, F8, fixed after approval:** the non-money field mapping of `add_line` and `change_line` (U1 to U3 survived round 2). The reviewer accepted it (no fact emitted, no caller in the trilogy, `design.md` §6.1); the leader overrode that to **fix**, under the maintainer's fix-in-phase ruling (2026-10-05), as a light test-only follow-up: `test_order.py` › `test_r6_add_line_and_change_line_keep_every_non_money_field_supplied`, U1–U3 armed by the implementer (`progress/impl_orders_aggregate.md`, *F8 follow-up*), U2 re-armed by the leader on an out-of-tree copy of `otc_orders` (`assert 'Bravo widget' == 'SKU-ALPHA'`); orders unit suite 156 passed.

**Findings and dispositions:**
- **D1–D3:** fixed in round 2.
- **F4:** ruff 0.16 formats Python blocks in Markdown and had rewritten `design.md`. Fixed by the leader with `extend-exclude = ["specs"]`, armed both ways.
- **F5:** the wording of tasks 3.12 and 4.16 was corrected.
- **F6:** the writer scan is blind to `getattr(...).__set__`. ACCEPTED, NOT FIXED: the behaviour tests caught it. Re-open if `__set__` or `getattr(` appears in the domain.
- **F7:** `Order.__init__` is public with no outside caller. ACCEPTED, NOT FIXED, carried as an acceptance item on feature 15.
- **F8:** fixed, as above.

**Inherited #8 findings:**
- **Rehydrate-checks defect: avoided** (nine checks, each killed by its own test; also killed when weakened or substituted).
- **A1: avoided** (every count reconciled by the reviewer).
- **A2: avoided** (the reason is assigned inside the accepted branch; the event reads it from state).
- **A3: avoided** (`order.snapshot_invalid`).
- **A4: avoided** (12 classes equal the table, and the guard walks the package).
- **A5: avoided** (two spec-text imprecisions were reported, not silently resolved).
- **Recurred in class:** *"a load-path or payload property no test reads, found by a probe nobody asked for"* (#8's defect shape). It appeared at new sites (event payloads and the `rehydrate` mapping) and was fixed in phase.

**Note for the remaining Phase 8 features:** arm field corruption on **every** constructor call that maps values into a fact or an aggregate. To do that, enumerate the call sites (for example `OrderLine(` and each event class) and probe each one. One probe per emission branch is not enough. Feature 14's envelope mapping is the next place this applies.

## cqrs_dispatcher (id 43, phase 8) — 2026-10-06

**Classification:** full group (shared application runtime, every service binds to it). `sdd: false`: implementer, then reviewer (Opus), with arming and the defeat list; closed by the leader after a maintainer-approved light pass following the second rejection (CLAUDE.md, "at most one rejection round without asking").

**Effort:** 1 session, 09:54 → about 11:15 elapsed (≈1.35 h, including leader orchestration and one maintainer round-trip). Agent time from the run records: implementation ≈9 min, review round 1 ≈8 min, rework ≈7 min, review round 2 ≈6 min, light pass ≈2 min, plus five premise checks of ≈0.5 min each. **Passes: 1 implementation + 2 review rounds (2 rejections) + 1 leader-closed light pass.**

**Baselines:** #7 has **no counterpart** (it used `@nestjs/cqrs`); this row has no #7 figure and must not gain one. #8: ≈3 h, 4 passes, 2 rejections, four defects (D1, D7, D8, D9) and one advisory (D10). #9: ≈1.35 h elapsed, 2 rejections. Faster in wall-clock; the same number of rejections.

**Scope split (leader, with evidence):** as #8 did (`ece0f2e` the package alone; registration with each host's first handlers in `4c6ed34`, `5a84e81`, `17ce0d1`), this feature built `otc_cqrs` and proved explicit, decorator-free registration against test handlers. The per-service half (registration in each `composition.py`, validated in the lifespan, plus the behavioural registration guard of review round 2 §3) is an acceptance item on features 15, 17, 19, 23, 24 and 25.

**What was built:** `Command[R]` / `Query[R]` markers with a phantom result witness, `CommandHandler` / `QueryHandler` / `EventHandler` protocols, `HandlerRegistry` with `register_command` / `register_query` / `register_event` and a `build(*packages)` that walks submodules and nested classes, skips generic bases and fails on zero or duplicate command/query handlers (zero event handlers allowed, as #7's `EventBus` and #8), and a `Dispatcher` that creates the handler per call from the caller's scope. Guards: decorator allow-list from a census of `services/*/src` (seven names) with a population test, exact-path composition-root registration rules, `Dispatcher(` constructed only in `HandlerRegistry.build`, ruff `SLF001` (leader, `pyproject.toml`, tests exempt).

**Tests:** 69 new (`test_cqrs_dispatcher.py` 34, `test_cqrs_mypy_strict.py` 16, `test_cqrs_registration_explicit.py` 19); workspace headline 1506 (= 1436 after feature 13 + 1 F8 test + 69). **Leader close-out:** `./quality.sh` exit 0, **1506 passed**, coverage 98.59%, 2 m 22 s **with the `otcpy` stack up (12 containers)** — not comparable with the ~125 s stack-stopped threshold, which is re-timed at wrap-up. Marked `done` by the leader after the light pass (maintainer: "Yes, let's try"), having read the residual text, confirmed no leftover mutation or temp file, and re-armed the `send` path out of tree.

**#8's findings, avoided or recurred:**
- **D1 (root-scope capture): code avoided, guard recurred then fixed.** The dispatcher never held a scope (reviewer's throwaway consumer, round 1), but the guard exercised only `ask` until RC1; a capture on `send` or `publish` passed all 63 tests. Now parametrised over the three paths, six arms; the leader re-armed `send` out of tree (both cases fail; the retention case only when run alone, because the mutation's `setdefault` keeps the first scope it sees).
- **D7 (a guard reading the wrong source): recurred (F3), fixed by a change of kind.** Round 1's guard recognised decorators imported from `otc_cqrs` and `register_*` call syntax, and lost to a service-local `@handles` drained by a loop, alias, `partial`, `getattr` and a basename-sibling `composition.py`. Replaced by an allow-list from a census plus exact-path rules (Phase 7 gate rule 3), with a stopping rule. The residual rows (F-a, F-b, F-g, F-i, F-j) need a real composition root and are carried as a behavioural guard; F-c closed by `SLF001`, F-d by the construction-site guard.
- **D8 (a compile-time guarantee dropped): recurred (F1), fixed.** Registration left `R` free, so a `str` handler registered for a `Command[int]` passed `mypy --strict`. Now tied by a witness protocol; REJECTED mypy shapes for command and query, armed.
- **D9 (a stale rule in a rule-bearing file): avoided.** No rule file contradicts the design (reviewer, both rounds).
- **D10 (a hardcoded list): recurred in shape (F2), fixed.** The zero-handler universe was a hand-passed module list; now a package walk with nested classes, four escape routes each tested and armed.

**The benchmark reading:** #9 reproduced two of #8's four defects (D7, D8), the guard half of a third (D1), and the shape of its advisory D10, despite having all of them as named questions in the brief. Each brief question named the defect, and the first implementation still answered it with a mechanism that satisfied the wording and missed the property. What caught them was the same thing that caught #8's: an Opus reviewer probing from outside with shapes nobody had armed. The inherited findings shortened the review (the reviewer knew where to look) more than the implementation.

**Notes for the remaining Phase 8 features:** messages subclass `otc_cqrs.Command[R]` / `Query[R]`; the composition root passes its message package(s) to `HandlerRegistry.build`; a new decorator in `services/*/src` fails the census guard until it is added with a reason.

## outbox_and_idempotency (id 14, phase 8) — 2026-10-06

**Classification:** full group (persistence, wire contract). `sdd: true`: spec, human gate (G1 poison row, G2 no unit-of-work retry, both approved as recommended), implementer, reviewer (Opus) with arming and the defeat list; closed by the leader after a maintainer-approved light pass following the second rejection.

**Effort:** 1 session, 11:13 (spec brief) → about 15:45, ≈4.5 h elapsed including the gate wait and leader orchestration. Agent time from the run records: spec ≈28 min, implementation ≈2.6 h (243 tool calls; three survivor rounds of a 214-mutant constructor census), amendment A1 ≈1 min, review round 1 ≈15 min, rework ≈1.5 min, review round 2 ≈13 min, light pass ≈1 min, four premise checks ≈0.5 min each. **Passes: 1 implementation + A1 + 2 review rounds (2 rejections) + 1 leader-closed light pass.**

**Baselines:** #7 ≈2.4 h (spec 0.5, implementation 1, review 0.83), approved first pass, 10 defects none blocking. #8 ≈3.4 h, ≈1.4× #7, approved. **#9 ≈4.5 h elapsed, the slowest of the three**, almost all of it in the implementation pass, whose cost is the field-mapping mutation census feature 13's review made mandatory (214 mutants, 17 first-sweep survivors, 5 of them fixtures that could not tell two fields apart).

**Gates:** `./quality.sh` exit 0, **1652 passed**, coverage 98.55 %, **149 s with the developer stack down** (pytest 128 s), against Phase 7's ~125 s threshold. The reviewer timed the cause (Q6): the feature's 21 new test modules take 34.8 s alone — Kafka container start 4.5 s, the seed fixture ≈3 s, and the two deadlock tests ≈1.3 s each because PostgreSQL's 1 s `deadlock_timeout` must expire. A threshold decision for the maintainer at wrap-up, not a defect.

**What was built:** the transactional outbox (aggregate row and outbox rows in one transaction, rows flushed one at a time so `seq` follows append order), a relay claiming with `FOR UPDATE SKIP LOCKED` at a pinned READ COMMITTED (skip-versus-block measured, 0.037 s, armed both ways), stamping only after the broker acknowledges, a bounded publish, a deadlock-victim retry inside `run_once` (#8 87), poison rows handled per G1 (clean prefix published, then a loud stop), a self-scheduled interruptible `asyncio` loop, an idempotent consumer keyed `(event_id, consumer)` with insert-first dedupe and a four-case parity guard, the generic `Envelope[P]` (203 item 2) and millisecond agreement (205). Installed `aiokafka==0.14.0` (+ `async-timeout==5.0.1`).

**Decisions during implementation:** amendment A1 (leader, #8's shape): `ConsumerName` in a per-service `consumer_name.py`, one relative import, full-file parity scan — replacing the implementer's excluded enum region. The root `conftest.py` Postgres container gained the deployed `-c timezone=UTC` after task 2.3's test found `Etc/UTC` (accepted; bound widened). Carried to feature 15: the lifespan owns and awaits the relay; at most one relay per process, no multi-worker server while `OUTBOX_RELAY_ENABLED=true` (review Q2; the same limit #8 accepted).

**The two rejections — every one a missing test, never wrong code:**
- Round 1: F1 a cancellation during the inter-cycle sleep, F2 poll pacing (a `sleep(0)` busy loop stayed green), F3 the deadlock backoff, F4 the A1 scan blind to `importlib`/`__import__`.
- Round 2: R2-F1 — no test drove `producer.send` raising, so `break` → `continue` at `kafka_publisher.py:79` (a later fact sent ahead of the failed one, OI8/R15) passed all 17 publisher tests; the reviewer's own round-1 ordering answer had relied on that untested `break`. Closed by one test; re-armed by the leader on an out-of-tree copy (`assert [b'key-1', b'key-2', b'key-3'] == [b'key-1', b'key-2']`).
- Accepted by the reviewer (N1): a `while True` in the relay loop is caught only as a hang, because the repository has no per-test timeout. Re-open trigger in the review.

**Inherited findings:** #8 87, 111 (decided at G1), D1–D8, its history items 1–3 and id 104 (stack down for the run, bootstrap-at-9092 arm) — all **avoided**; #7 D1 not applicable, D2–D7, D9, D10 **avoided**, D8 already avoided by feature 9. **Recurred in class:** "a hand-built property no test drives" (defeat row 12) — four times in round 1 and once in round 2, every time on a branch of the asyncio loop or the adapter that #7's and #8's frameworks would have supplied (NestJS/BackgroundService scheduling, librdkafka batching).

**Note for features 15 and 16:** before review, list every branch of a hand-built loop or adapter (cancel, pace, retry backoff, send-raises, ack-fails) and name the test that drives each; the reviewer found exactly those, one round at a time.

## orders_acceptance (id 15, phase 8) — 2026-10-07

**Classification:** full group (wire contract, persistence, the first Orders host). `sdd: false`: implementer, Opus reviewer with arming and the defeat list; closed by the leader after a maintainer-approved light round 3 following the second rejection (2026-10-07, "Yes, please, go ahead").

**Effort:** 2 sessions (2026-10-06 → 2026-10-07, split by a session end mid-review). Agent time from the run records: implementation r1 ≈63 min, review r1 ≈51 min (REJECTED), implementation r2 ≈36 min, review r2 ≈5 min of verdict after a resume (REJECTED; its pre-break probing time is not recoverable from the record), light round 3 ≈13 min, leader closure ≈10 min (five re-arms + affected suites), one premise check ≈2 min. **Passes: 3 implementation + 2 review rounds (2 rejections) + 1 leader-closed light pass.**

**Baselines:** #7 ~4 h, 2 implementation sessions, 2 review passes, approved with 6 non-blocking open (incl. N2, N3). #8 ≈5.5 h, 3 implementation sessions, 3 review passes, 7 defects all of the class "correct and nothing notices its reversion". **#9: 3 implementation passes and 2 review rounds, ≈3.6 h of agent time** — the same pass count as #8, and the same defect class in every round: not one finding across both reviews was a wrong line of shipped behaviour except D-1 (a boot that fails with Kafka down leaked the responder task and the producer) and the latent R2-D4.

**Gates:** `./quality.sh` exit 0, **1883 passed, 193 s with the developer stack down** (r1 193 s / 1867, r2 198 s / 1877) — above Phase 7's ~125 s threshold; the threshold decision is the maintainer's at wrap-up. Leader closure run: `services/orders/tests packages/cqrs/tests tests/architecture` 991 passed in 84.6 s, stack down.

**What was built:** the `orders.create` NATS responder (one scope per request; shutdown drains in-flight requests and a faulted one never propagates, #8 id 50), the `fulfillment.stock.check` client (no-responders → `UNAVAILABLE`, timeout → `TIMEOUT`, established against a real NATS server; `success | RpcError` discriminated before typed decoding; a malformed reply classified, #8 id 46), the place-order handler (reference data → stock check → unit of work; a non-zero `orderDiscount` refused), the `ORD-######` allocator under `FOR UPDATE` (24-way race gap-free, a rolled-back order burns no number, seeding over a non-empty table; #8 A11 paid), #8's RPC mapping table, request validation over every schema constraint, and the first Orders host: `composition.py` (explicit `otc_cqrs` registration, validated at boot; every registered handler of all three kinds built once at boot through the new public `HandlerRegistry.registered_factories()`), the lifespan in `otc_orders/main.py`, a readiness surface that falls when a transport task dies, the outbox relay owned and awaited, one relay per process enforced at boot, every environment read reaching its adapter guarded (#8 id 56). Installed `nats-py 2.16.0`.

**Deviation accepted:** the lifespan lives in `otc_orders/main.py`, not `presentation/app.py`, because the `fact-producer-confinement` import-linter contract forbids presentation reaching aiokafka through the composition root (review Q1; #8's `OrdersHost.cs` also sat outside `Presentation`). **CLAUDE.md line 75 ("presentation (…, the lifespan)") is now inaccurate — wording change owed to the maintainer at wrap-up.** Feature 16's spec amended for it (A2', `specs/order_saga_orchestrator/design.md` §1).

**The rejections:**
- Round 1 (40 mutations, 36 killed): D-1 boot leak with Kafka down (production); D-2 `STOCK_CHECK_TIMEOUT_MS` reach to the adapter unproven; D-3 reply `currency` hard-coded `"EUR"` survives (all fixtures EUR); D-4 the no-responders clause deletable; D-5 #8's `RpcSubjectsTests` unported; D-6 a registered handler not built at boot unnoticed.
- Round 2: all six fixed, and four properties of the fixes survived their own reversion — R2-D1 `except BaseException` → `except Exception` (a cancelled boot leaks D-1's exact tasks), R2-D2 the `gather` in `_stop_tasks`, R2-D3 D-6 guarded for commands only, R2-D5 the stock-check budget bounded below only (`timeout=5` green) — plus R2-D4, `stack.pop_all()` passed as an argument (a raising runtime constructor would leak everything). #8's own round-2 sentence, "three of the four repairs were themselves unguarded", recurred almost verbatim.
- Light round 3: R2-D1 … R2-D5 closed; `_ProbedRegistry` (a test-side subclass reaching private tables, against the SLF001 rule) replaced by the public accessor. **Leader re-armed P1, P3, P4, P5 and P8 on an out-of-tree copy** (`PYTHONPATH` ahead of the editable install; control 5 passed first): P3 `a cancelled boot leaked tasks: ['nats-responder', 'orders.create stop waiter']`; P4 `the producer must be stopped`; P1 the in-flight request goes unanswered (`an orders.create request could not be answered`); P5 both `[query]` and `[event]` fail `the host must not come up with an unbuildable … handler`; P8 `the 1.5 s budget is what was applied, not a longer one: 5.08s`. Repo sources sha256-identical to the implementer's pre-arm prefixes.

**Dispositions:** Q4 — item 8 met; the gunicorn-fork / multi-replica residual ACCEPTED, NOT FIXED with a re-open trigger (review §3), its deployable half carried as an acceptance item on feature 36 `full_docker_compose`. Not built, by scope: R62 replay (feature 27's line), trace/correlation propagation (R57/R58), DB and Kafka health in readiness.

**Inherited findings:** #8 D1, D2, D3, D4, D5, D6, A3, A5, A11, ids 46, 47, 50 — **avoided** (A10 not applicable). **id 56 — recurred in part (D-2, then R2-D5 in class), fixed.** #7 N2 — avoided; **#7 N3 (a guard covering half its claim) — recurred in class (D-2, D-3, R2-D5), fixed.** #8's "Notes for #9" (revert question, arm the call site) — the call sites were armed in round 1 (R04 mapper call site: 49 failed); the revert question was not asked of the round-1 fixes until round 3's brief demanded it.

**Process incident:** the session end interrupted review round 2 mid-mutation and left `NATS_URL` → `NATS_URI` in `settings.py`; the reviewer's `/tmp` backups were gone. Detected by the leader (the only source file newer than the brief), restored by the resumed reviewer by reversing the one edit, verified 7/7 against pre-run sha256. Rule taken into later briefs: arming backups in a persistent directory with a recorded sha256, never bare `/tmp`.

**Note for feature 16:** the boot path now stops and awaits every created task on any failure, cancellation included; any task 16 adds to `start_runtime` must join that rule and the readiness rule, and its handlers pass the all-kinds boot probe.

## order_saga_orchestrator (id 16, phase 8) — 2026-10-07

**Classification:** full group (saga, wire contract, persistence). `sdd: true`: spec_author, human gate (G1 one task per command with max 256 in flight and overflow dropped to the durable row; G2 #8's summary/batch/park values; G3 no SA-6 — all approved as recommended, `design.md` §17.1), leader amendment A2' (lifespan in `main.py`), implementer, Opus reviewer with arming and the defeat list. Approved by the reviewer in round 2.

**Effort:** 2 sessions (spec in session 2 on 2026-10-06; implementation and both reviews on 2026-10-07 after the resume), one laptop reboot. Wall-clock ≈7 h: spec ≈33 min (15:54 → 16:28, 2026-10-06) plus 07:16 (implementation brief) → ≈13:38 (round-2 verdict) on 2026-10-07, which includes ≈39 min of reboot outage. Agent time from file times and the run records: spec ≈33 min; implementation round 1 ≈3.5 h (07:34 → 09:12 cut by the reboot, 09:51 → ≈11:44 resumed, then the 14.2 live walkthrough ≈5 min); review round 1 ≈42 min (11:51 → 12:33, REJECTED); rework ≈32 min (12:34 → 13:06); review round 2 ≈31 min (13:07 → ≈13:38, APPROVED); two premise checks. ≈5.8 h of agent time in total. **Passes: 1 implementation (interrupted and resumed) + 1 rework + 2 review rounds (1 rejection).**

**Baselines:** #7 ≈1 h 45 min implementation + ≈35 min review, approved first pass ("the cheapest `sdd: true` feature of phase 8 by a wide margin, on the most complex surface"). #8 ≈8.7 h wall-clock, 4 implementation passes + 4 review rounds, every defect in test code. **#9 ≈7 h wall-clock (≈5.8 h agent), 2 implementation passes + 2 review rounds**: faster than #8 by about 1.7 h and half its rounds, about three times #7. As in #8, no reviewer finding in either round was a wrong line of shipped behaviour. Every finding was a property that was correct and that no test noticed being reverted.

**Tests:** 1883 → **2355** (+467 in round 1: 366 unit saga, 72 integration saga, 5 row-lock, 10 architecture, 14 cases in feature 15's modules; +5 in round 2: 2 lifespan reach cases, 3 ledger cases). `specs/shared/test-matrix.md` row 3 moves `11 | 0 | 0 | 11` → `11 | 8 | 0 | 3`. R24's API half, R28's e2e half and R29's dead-letter case stay `TODO`, and their cells now name the ratification at the feature 16 spec gate.

**Gates:** `./quality.sh` exit 0, **2355 passed, 441 s with the developer stack down**, coverage 98.70 %. The reviewer's full run: 2355 passed in 392.76 s. **The duration cause was measured, not attributed.** The jump from 193 s happened in round 1 (7 min 08 s already); round 2 added 3.3 s. Feature 16's 75 integration saga cases take 224.6 s of the 387.8 s junit total. About 3.0 s of each is the Kafka broker's default 3 s `group.initial.rebalance.delay.ms` on every `orders.saga` join: setting it to 0 in the root `conftest.py` took 22 saga cases from 98.68 s to 32.28 s (probe T1, restored). Machine load was not the cause (32 % CPU, load average 1.8 on 16 cores). The threshold decision is the maintainer's at wrap-up. If the delay is set to 0, the SO9 offset arms must be re-run under it in the same change.

**What was built:** the saga orchestrator over the Orders aggregate: a Kafka fact subscriber (`orders.saga` group, `earliest`, one record at a time, the offset committed only after the handler, `seek` back on failure with paced redelivery); the fourteen-row step table and both compensation paths (R19–R29); a `saga_commands` ledger with idempotent enqueue inside the fact transaction, leased claims (`try_claim` for the fast path, `claim_due` with `FOR UPDATE SKIP LOCKED` for the sweeper), conditional `mark_sent` and `park`, and capped exponential back-off; a NATS commands adapter for six subjects that tells timeout from no-responders and decodes `RpcError` before the typed reply; a per-command fast path with no head-of-line blocking; a sweeper task; the saga-side `FOR UPDATE OF orders` lock; and eleven `SAGA_*` settings, all proven to reach their objects. No package installed.

**The rejection (round 1), every item a missing test:** D1, none of the eleven `SAGA_*` settings proven to reach its object (four hard-codings at once passed 1407 tests); D2, a parked row's back-off not enforced on the claim, nothing noticed; D3, a `sent` row re-claimable, nothing noticed; D4, the line order misattributed (`Order.rehydrate` sorts lines by id; it was not the database's order). Round 2 closed all four with tests only (`src/` byte-identical to round 1, verified by ctime plus content `cmp` against both rounds' backups). The reviewer re-armed 26 mutations across all three families (delete, corrupt, sibling), including wire-header corruption against the new request count; all 26 failed naming the claim. One equivalent mutant (the `status` term of `claim_due`'s parked branch, unreachable because `mark_sent` nulls `next_attempt_at`) was made killable by a planted state. The reviewer accepted it as a guard of the status invariant against features 42 and 27's coming write paths.

**Non-blocking, disposition fix (light, test-only, this phase; route to `test_maintainer`, leader arms each):** N1, `test_saga_command_ledger.py:312` unpacks before asserting, so the "due exactly at `next_attempt_at`" boundary fails as a `ValueError` instead of naming its claim. N2, the reach test's `SAGA_SENTINELS` literal is not tied to the `SAGA_*` keys of `test_orders_settings_env.py`'s variable literal, so a twelfth variable could miss the reach test (the #8 id 56 recurrence path). The fix and the arm for each are in `progress/review_order_saga_orchestrator.md`, Round 2.

**Inherited findings:** **avoided:** #8 ids 80, 88, 89, 110, 48, 51 (by construction), 94 (here; its re-run is carried to feature 27), 90; #8 feature-16 D1–D5; #7 D1, D2, D3, D5; #7's third-pass ruling; `review_shared_kernel` Q2. **Split as designed:** #8 id 62 (saga-side lock here, the race in feature 41). **Assigned:** #8 id 71 (features 41/24/27), id 91 (feature 41, attached). **Recurred:** **#8 id 56**, in round 1 (D1), for the third time this phase after feature 15's D-2 and R2-D5, and closed in round 2. **#7 N3, a guard covering half its claim**, in round 1 (D2 and D3, ledger predicates guarded on one side only), closed in round 2.

**Session incidents:**
- **The reboot restore of arm 3.9a.** The ≈09:12 reboot wiped `/tmp` (scratchpad and arming backups) while arm 3.9a's mutation (an early `consumer.commit(offset+1)` in `kafka_fact_subscriber.py`) was in place. The implementer reversed it by the exact inverse edit, verified against its transcript (no sha256 survived), then checked ruff, mypy and the 14 subscriber tests. From then on, arming backups went to the repo-local, git-ignored `.arm/` (`.gitignore:87`). Round 1's reviewer confirmed `consumer.commit(` occurs once and SO9 fails under eight mutations.
- **The orphaned arm processes.** The mutated runs of arms 3.9a and 3.9b hung for ≈1 h 50 min. There were two causes. In the test, a held handler blocked the harness exit after the first assertion failed; this was fixed in round 1 with `finally: hold.set()`. In the arm tool, `.arm/arm.py`'s `subprocess.run(timeout=420)` killed only the `uv` parent, so the pytest children were reparented and kept running; this was fixed in round 2 with `Popen(start_new_session=True)` plus `os.killpg`. The leader killed the two orphans at 11:46. The reviewer's own tool proved its kill path in round 2 (a `sleep(3600)` test under a 25 s timeout: exit 124, `group survivors=[]`). The implementer's kill path is still unexercised.

**For the leader to file (routing, not narration):** attach to feature 42's acceptance: "`park`'s `status <> 'sent'` predicate (`command_ledger.py:157`) excludes the new terminal status as well as `sent`". Round 1 raised it, and feature 42's acceptance still lists only its three original items. No `specs/shared/` root cause was found in either round, so no `SA-n` is proposed.

**Note for features 27 and 42:** both add write paths to `saga_commands` (the retry/DLQ wrapper, a `rejected` status). Each new status or mark must keep the two claim predicates and `park` closed over an explicit status set; the planted-state block in `test_so11_…` is there to fail if a terminal row keeps a due `next_attempt_at`. Any new `SAGA_*` variable joins both the unit literal and the reach test, which N2's fix makes mechanical.

**Addendum (leader, 2026-10-07) — feature 16 review N1 / N2 closed (light, test-only, `test_maintainer` haiku in three passes: its first edit imported a non-existent `otc_orders.tests` package and broke ruff twice; the leader supplied the exact replacement).** N1 `test_saga_command_ledger.py:312-315`: the boundary half now asserts on the list with its claim in the message. N2 `test_orders_host_lifespan.py::test_saga_sentinels_cover_all_saga_environment_variables`: `SAGA_SENTINELS` equals the `SAGA_*` keys of the unit test's `ENV` literal (read by `ast`, non-empty asserted). Leader verification: ruff, format, mypy clean; ledger module + new test 14 passed. Arms, both out of tree (`.arm/leader/`): N1 b3 (`claim_due` parked branch `<=` → `<`, via `PYTHONPATH` ahead of the editable install) → `AssertionError: claim_due: the parked row is due exactly at next_attempt_at`, control 13 passed; N2 (a twelfth `SAGA_TWELFTH_KNOB_MS` in a copied unit `ENV` only) → `SAGA_SENTINELS missing: {'SAGA_TWELFTH_KNOB_MS'}`, control PASSED. Repo files untouched by the arms. Classification: light.

## orders_saga_terminal_rejection_classification (id 42, phase 8) — 2026-10-07

**Classification:** full group (saga). `sdd: false`: implementer, Opus reviewer with arming and the defeat list; round 1 REJECTED for documentation only, closed by the leader after a light documentation-only round 2 (the reviewer's own recommendation, CLAUDE.md cost discipline).

**Effort:** agent time from the run records: brief + premise check ≈1 min (17 verified, 0 false), implementation ≈63 min, review round 1 ≈15 min, documentation round ≈1.3 min, leader closure ≈5 min. Elapsed ≈1 h 45 min. **Passes: 1 implementation + 1 review (rejected, docs only) + 1 leader-closed light pass.**

**Baselines:** #7 ≈30–35 min, approved first pass, 1 non-blocking finding. #8 ≈1.1 h, approved first pass, 0 blocking, 5 advisories, ~2× #7. **#9 ≈1.75 h, the slowest of the three, ~1.6× #8**, with no defect in executable code. The excess is the arming census (one test and one arm per predicate, each with a control row) and one documentation round.

**Gates:** implementer `./quality.sh` exit 0, **442 s, 2387 passed** (2356 + 31), 98.70 %, stack down. Leader closure: the three touched code files are AST-identical to the pre-round backups with docstrings stripped (`.arm/leader/f42/astcmp.py`: SAME ×3; the diff is comment/docstring only); `ruff check`, `ruff format --check` and `mypy services/orders/src` clean; `unit/saga` + both ledger integration modules 408 passed. No `quality.sh` re-run (no executable line changed). The 442 s is feature 16's saga integration time (≈3 s per case from Kafka's 3 s default group initial rebalance delay, measured in feature 16's review) — the threshold question is the maintainer's at wrap-up.

**What was built:** `TERMINAL_RPC_ERROR_CODES`, #7's and #8's nine codes member for member (the enum's only description, `TIMEOUT`, is caller-produced); a terminal `RpcError` becomes a business rejection that the dispatcher resolves on the **first** attempt through `reject` → `status = 'rejected'`, `next_attempt_at` cleared, never `park`. A transient code and an unknown code stay on the transport path and are retried (the runtime behaviour #7 and #8 shipped). Every ledger status predicate names its set (`CLAIMABLE = ('pending', 'parked')`), including `park`, whose `status <> 'sent'` would have re-parked a rejected row (acceptance item 4, carried from feature 16's review). No migration (`rejected` fits `varchar(10)`), no package.

**The rejection (documentation only):** D1 `design.md` §9.6 still showed `park … status <> 'sent'`, "All four statements" and no `reject` SQL — #8's note 5 ("a doc superseded by the feature it predicted") recurred while the record called it avoided; D2 stale wording in `design.md:522` and three docstrings; D3 record corrections. All fixed; §9.6 now lists five statements, each change marked as feature 42's amendment; the remaining `<> 'sent'` mentions (lines 524, 578, 588) are the amendment markers naming the old predicate.

**Reviewer probes (15 mutations, all killed):** one code dropped from the set fails exactly its tests (#8 probe 1); reject → park and reject+park each fail on their own claim (probe 2, note 1); each claim predicate widened to admit `rejected` with a control row fails exactly one test, the assertion an equality and never a `not in` (probe 3, note 2). The parked-branch status term rests on planted rows, accepted on feature 16's `sent` ruling; the pending branch and `try_claim` are guarded through reachable state (reviewer arm R3 fails the end-to-end test).

**Inherited findings:** #8 probes 1–3 and notes 1, 2, 4 — **avoided**; note 3 (MSBuild stale binaries) — not applicable; **note 5 — recurred, fixed in round 2.** Trilogy evidence (not work for #7/#8): #7's `markRejected` guard and #8's `park` (`!= "sent"`), `RejectAsync` and `MarkSentAsync` (`EfCoreSagaCommandStore.cs:177`) carry status-predicate gaps that #9's acceptance item 4 closes (file and line in the review).

**Carried:** the rejected path's surfacing (no `order.saga_failed.v1`, no dead letter; #7 and #8 deferred it) filed by the leader as an acceptance item on feature 27, with the instruction to take it to the gate if `specs/shared/` does not decide it.

**Addendum (leader, 2026-10-07, Phase 8 wrap-up) — the Kafka group initial rebalance delay (light, test infrastructure).** Feature 16's review round 2 measured the cause of `quality.sh`'s jump to ≈440 s: the root `conftest.py` Kafka container left `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS` at the broker default of 3 s, paid by every `orders.saga` group join (75 saga integration cases, 224.6 s). The maintainer did not answer the recommendation twice; per their standing instruction the leader proceeded with it. One implementer added `.with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")` (test-only; `docker-compose.infra.yml` untouched; the fixture-versus-deployed parity test reads PostgreSQL settings only) and re-ran the SO9 / SO1 arms under the new broker setting: R3.9a–d, R3.10, R3.10c and R3.12 all failed with their named assertions, none hung, every restore `cmp`-identical (`progress/impl_kafka_rebalance_delay.md`). **Leader's wrap-up gate (stack stopped, timed): `./quality.sh` exit 0 in 278.3 s — 2387 passed, pytest 256.5 s, coverage 98.70 %, `mypy --strict` clean on 387 source files, import-linter 11 kept.** Still above the Phase 7 threshold of ~125 s; the remaining time is the container-backed saga and outbox suites, and the threshold is the maintainer's to revisit.

**Phase 8 plan item — the wire-format check, live (leader, 2026-10-07 wrap-up).** The `order.placed.v1` that feature 16's live walkthrough produced for ORD-000007 was read back from the deployed broker (`otc.orders.facts.v1`, partition 2, offset 0, `kafka-console-consumer.sh` with key and headers) and compared with `tests/fixtures/golden_envelopes/order_placed_v1.json` (`.arm/leader/wirecheck.py`): envelope keys identical **in order** (`eventId, eventType, aggregateId, correlationId, causationId, occurredAt, payload`); compact JSON (the value equals its own `separators=(",", ":")` re-serialisation); `occurredAt` `2026-10-07T09:48:55.110Z` matches `YYYY-MM-DDTHH:MM:SS.mmmZ`; payload key set and recursive value types equal to the golden; record key = `correlationId` = `aggregateId`; headers `x-event-type:order.placed.v1, content-type:application/json`. Payload values differ, as they must (a different order); key order is not a parity claim (CLAUDE.md). The test-container version of the same check is `test_outbox_wire_parity.py` (feature 14).

## fulfillment_stock (id 17, phase 9) — 2026-10-08

**Classification:** full group (money-adjacent domain, persistence and locking, wire contract). `sdd: true`: spec_author, human gate (G1 accept the concurrent-disjoint reserve residual and cover the sequential case; G2 exact, case-sensitive code matching; G3 #8's five candidates closed with no `SA-6`, all as recommended), implementer, Opus reviewer with arming and the defeat list. Round 1 REJECTED, round 2 APPROVED (`progress/review_fulfillment_stock.md`).

**Effort:** 1 leader session (opened 2026-10-07): spec on 2026-10-07 (brief 16:29 local), human gate overnight, build and both reviews on 2026-10-08, 05:27 (implementation brief) → ≈09:30 local (round-2 verdict), ≈4 h 03 min of wall-clock. Agent time, as measured by the leader from the run records plus this review: spec_author ≈27 min, implementer ≈1 h 57 min, review round 1 ≈91 min (5 463 s), fix round ≈10 min (574 s), premise checks ≈3.5 min in all, review round 2 ≈20 min. **≈4 h 29 min of agent time in total. Passes: 1 implementation + 1 fix round + 2 review rounds (1 rejection).**

**Baselines:** #7 ≈3 h 44 min (spec ≈8 min, impl ≈1 h 35 min, 2 review passes + 1 fix), 1 rejection (an unplanned sub-clause mutation of FS5 survived). #8 ≈4 h 13 min (spec + gate ≈27 min, impl ≈1 h 51 min, 3 review passes + 2 fixes), 2 rejections (D1 the rejected path's outbox row never observed; D2 the released fact's `reason` never opened). **#9 ≈4 h 29 min of agent time, 2 review passes + 1 fix, 1 rejection.** That is ≈6 % slower than #8 with one rejection fewer, and ≈1.2× #7 with the same number of rejections. As in #7 and #8, no finding in either round was a wrong line of shipped behaviour. Every defect was a correct property that no test noticed being reverted, and `src/` was byte-identical across the fix round.

**Tests:** 2387 (A2) → **2690** (+299 in round 1, +4 in round 2: the SA-4 read-order test, the `ConcurrentReservationChangeError` test, two FS24 seam tests). `specs/shared/test-matrix.md` R30 – R35 and R61's domain half name their tests. Round 2 added no R row.

**Gates:** reviewer round 2, `./quality.sh` exit 0, **324 s (pytest `2690 passed in 282.64s`)**, developer stack down, coverage 98 % overall / 99 % domain, `mypy` clean on 458 files, import-linter 11 kept. Round 1: 300 s. Implementer: 308 s. A2 before the feature: 268 s. The maintainer's Phase 7 reference was ~125 s, and the threshold is the maintainer's call.

**What was built:** the Fulfillment stock domain (`StockItem`, `Reservation` with `reserved → released | consumed`, `reserve_order` / `release_order` with every id from a supplied `new_id`); the five `fulfillment.stock.*` NATS responders over generated wire models with a closed `RpcError` mapping, `CONFLICT` produced by no input; `StockTransactions.run` at pinned `READ COMMITTED` with an in-process 40P01 re-run; per-row `SELECT … FOR UPDATE` in code-point key order, then the order's reservations; SA-4's one lock as `stock_keys_of_order` + `lock_order_items`; the outbox writer, relay and publisher as parity-guarded copies of Orders'; the composition root, with explicit registration and boot validation. No package installed, no migration.

**The rejection (round 1), every item a missing guard:** D1, swapping `lock_order_items`' two reads (the SA-4 lock order, FS25's *"before reading the order's reservations"*) survived all 809 Fulfillment and architecture tests. This is #7's rejection shape exactly. D2, `UniqueId.new` substituted for the id port at the application → domain seam survived (FS24, #8 id 49's follow-on). D3, the `ConcurrentReservationChangeError` branch was untested. D5 – D7 were stale spec citations, an arm failure that did not name its claim, and record fixes. Round 2 closed each with a test whose arm the reviewer re-ran (R1, M1a, M1b, M9, I5 all RED, naming their claims), plus five reviewer mutations of the release lock: four RED, and one equivalent under the lock protocol (the reservations' row lock, defence in depth).

**Open at approval (non-blocking, disposition FIX now, light docs-only, before the spec commit):** N-1. `design.md:110` (ledger L15) and `requirements.md:160-161` (§3 FS24 / FS25) still name only the round-1 guards. Add the round-2 tests (`progress/review_fulfillment_stock.md` § Round 2, R2.6).

**Carried (leader, done before round 2):** feature 18's acceptance holds the despatch half of SA-4: the same two lock methods, the release-versus-despatch race in both outcomes, the despatch half of FS25's lock test (#8 id 79), and the pinned READ COMMITTED (#8 id 54). Feature 43's carried registration item is discharged by the reviewer's `Q6` arm (F-g + F-j as one fixture, RED by the WIRE clause). The implementer's own G8 arm fired by F-g alone. No `specs/shared/` root cause was found, so no `SA-n`.

**Inherited findings:** **avoided:** #8 id 49 and its follow-on (six of six sites guarded, after round 2), id 50, id 51, id 54, id 95, id 56; #8 feature-17 D1 and D2; #8 A6; #8 G6; #7 feature-17's FS5 "any status" rejection (E4 and H5). **Split as designed:** #8 id 79 (release half built and guarded here, read order included after round 2; despatch half on feature 18). **Assigned:** #8 id 101 (feature 29, already attached). **Recurred:** #7's feature-17 rejection in its general form, *an unplanned sub-clause mutation survives the full suite* (round-1 D1, FS25's clause on the SA-4 lock), closed in round 2. #8 id 49's follow-on shape, *the property guarded at some sites but not all*, also recurred at the application seam (round-1 D2) and was closed in round 2.

## fulfillment_despatch (id 18, phase 9) — 2026-10-08 — closes Phase 9

**Classification:** full group (persistence and locking, wire contract, the saga's despatch step). `sdd: false`: the specification of record is the three acceptance items of `feature_list.json` id 18 read against `specs/shared/` R36 / F6–F8 and `specs/fulfillment_stock/design.md` §15, §6.3, §6.5, §8, §10, as #8 did. Implementer, then Opus reviewer with arming and the defeat list. **APPROVED first pass, round 1** (`progress/review_fulfillment_despatch.md`).

**Effort:** 1 leader session, 1 implementation pass + 1 review pass. Wall-clock ≈1 h 40 min: implementation brief 09:33 local → verdict ≈11:12. Agent time: implementer ≈74 min (4 434 s, leader-measured), premise check of the review brief ≈1.5 min (the implementation brief's premise check is not measured here), review ≈23 min (10:49 → ≈11:12, including a full `./quality.sh` of 341 s and 21 arms). **≈1 h 39 min of agent time.**

**Baselines (quoted from the files):** #7 (`../order-to-cash-nestjs/progress/history.md:863`) ≈41 min implementation + ≈22 min review = **≈1 h 03 min, approved first pass**, 5/5 hostile mutations killed, atomicity by fault injection. #8 (`../order-to-cash-dotnet/progress/history.md:1126`) **≈1 h 46 min, 2 review rounds**, rejected once on a test whose assertion contradicted its name (`Assert.NotEqual` under "minted by"). **#9 ≈1 h 39 min, approved first pass: ≈1.6× #7, ≈7 min under #8 with one review round fewer.** What was not faster: the implementation alone (≈74 min) is ≈1.8× #7's 41 min and ≈2× #8's 36 min. The cost is the arming census (87 implementer arm runs, 76 final red, each with backup, sha256, one named test and a re-run) and a constructed concurrency suite (both SA-4 outcomes, the F8 concurrent pair, the FS25 read order) where #7 had one race and #8 repeated one ten times. That census is why the review found nothing blocking, so the extra implementation time bought the missing rejection round; it is harness cost, not Python cost.

**Tests:** 2690 → **2784** (+94: unit 71, integration 23; counted by `pytest --collect-only` over the nine new files). `specs/shared/test-matrix.md` R36 → DONE with twelve named tests; row 4 `8 | 7 | 0 | 1`, total `63 | 31 | 1 | 31`. **Gates (reviewer's run): `./quality.sh` exit 0, 341 s, `2784 passed in 302.11s`, domain coverage 99 %**, import-linter 11 kept, `init.sh` exit 0 (shared spec byte-identical to #7 and #8). Developer stack down throughout the review.

**What was built:** `despatch.create` end to end as the sixth subject of the one Fulfillment responder. The `DespatchAdvice` aggregate (F6 refusal, one `order.despatched.v1` appended before `create` returns, lines held in the canonical order `(product_code, line id)` because the line table has no position column); the pure `despatch_order` (one line per consumed reservation, F7; advice id, every line id and the event id from the supplied `new_id`); `despatch_creation.create` with F8's three layers (fast path with no transaction, the in-lock re-read under the pinned `READ COMMITTED`, the `despatches.order_reference` unique key) over feature 17's SA-4 lock (`stock_keys_of_order` + `lock_order_items`, the very methods `stock.release` calls); the `DES-` allocator in Orders' shape over 17's `sequences.py`; the despatch repository writing the advice, its lines and its fact in the attempt's session; two error-table rows (`PRECONDITION_FAILED` for no reserved stock, `UNAVAILABLE` for consumed-without-advice). No package, no migration, nothing under `services/orders` or `packages`.

**Deviations (argued in the impl report, accepted in review):** both correlation headers required on `despatch.create` (as #7, #8 and 17's reserve/release); line ids minted in the domain rather than the repository (both predecessors minted them unseamed in infrastructure; #9 guards a third mint-site kind); `ConcurrentDespatchChangeError` → `UNAVAILABLE` (#8's; #7 `INTERNAL_ERROR`, both transient); `23505` → `INTERNAL_ERROR` (transient, the retry takes the fast path).

**Rejections:** none.

**Open at approval (non-blocking, disposition FIX now, light, test-only, one `test_maintainer` batch, leader arms):** N1 `test_despatch_create.py:121` unpacks the fact list before asserting, so deleting the emission fails as a `ValueError` (arm R21 must then name "exactly one order.despatched.v1"); N2 `test_despatch_store.py:392` fails on a bare `TimeoutError` when the fast path is gone (arm R16 must then name F8's fast path). **Accepted, not fixed:** N3 `OrderDespatched(StockEventBase)` misnomer, re-open trigger the next event class or code change in `otc_fulfillment.domain.events` (rename to `FulfillmentEventBase` then). No `specs/shared/` root cause, no `SA-n`, no backlog entry.

**Dev data (for the next phase's brief):** the impl live check despatched `ORD-000007` (`DES-000006`, reservations `consumed`, `IBERFOODS` `PRD-0001` 498 / 4, `PRD-0002` 492 / 0) while Orders holds it at `stock_reserved`; Orders consumed the fact and skipped it. Orders advances only on the fact (`step_table.py:162-167`), and a later `despatch.create` for that order is answered `created: false` with no fact, so **`ORD-000007` will stall at `confirmed`** in any future live walkthrough. Avoid it or recreate `otc_fulfillment` from the seed.

**Inherited findings:** **avoided:** #8 id 54 (the pin, probed both ways: green at `READ COMMITTED`, `40001` → `UNAVAILABLE` at `REPEATABLE READ`); #8 id 79, despatch half (lock removed, only the first key locked, reads swapped: all red, none hung); #8 id 49's lesson, with the count (3 mint sites + 1 hand-over, 0 in the repository, each armed separately); #8's round-1 test-name defect (every provenance assertion is equality with a supplied value; read back by the reviewer over 42 tests); #8 ids 45 / 47 (allocator seed and lock, re-armed). **Followed:** #7's fault-injection proof with its discriminating control (re-run, plus an early-commit arm). **Recurred:** none of #7's or #8's; N1/N2 repeat #9's own feature-16 N1 shape (an arm whose failure does not name its claim), minor.

## Phase 9 — closing assessment

| | #7 (NestJS) | #8 (.NET) | #9 (Python) |
|---|---|---|---|
| `fulfillment_stock` (17) | ≈3 h 44 min, 1 rejection | ≈4 h 13 min, 2 rejections | ≈4 h 29 min agent time, 1 rejection |
| `fulfillment_despatch` (18) | ≈1 h 03 min, first pass | ≈1 h 46 min, 1 rejection | ≈1 h 39 min, first pass |
| #8's unmatched rows (46 discriminator, 49 event-id seam) | none | ≈1 h 41 min, 1 rejection | none: id 46 avoided in feature 15, id 49 in feature 17 (acceptance criteria, no feature of their own) |
| **Phase total** | **≈4 h 47 min, 1 rejection** | **≈7 h 39 min, 4 rejections** (comparable subset ≈5 h 59 min) | **≈6 h 08 min, 1 rejection** |

**Against #8, #9 wins Phase 9 on the phase total (≈0.8×) and matches on the comparable subset (≈1.03×), with a quarter of the rejections.** The saving is entirely inherited findings: #8 spent ≈1 h 41 min on two features (46, 49) that existed only to repair #8's own translation defects, and #9 carried both as acceptance criteria (id 46 on feature 15, id 49 on feature 17) and never had them. Against #7, #9 is ≈1.3× slower, and the gap is the same shape it was in Phase 8: no finding in either feature was a wrong line of shipped behaviour, and every round was spent proving properties #7 asserted once. Feature 18 breaks #8's "the predecessor's easiest feature is where the widest gap opens" law in one direction only: it did not cost a rejection here, but its implementation still ran ≈1.8× #7's, because the arming census is paid up front instead of in a review round. The ported-idiom ledger held on its first extension: L4 (#8 id 54, the row most likely to be assumed) was probed both ways and held. Owed from the phase: feature 17's N-1 (docs) and feature 18's N1/N2 (test messages), all light; the `ORD-000007` dev-data stall for the next live brief.

**Leader addendum (2026-10-08, Phase 9 close).** The three items the closing assessment lists as owed are closed in this phase. Feature 17's **N-1**: `specs/fulfillment_stock/design.md` ledger row L15 and `requirements.md`'s FS24/FS25 traceability rows now also name the round-2 guards (docs-only). Feature 18's **N1/N2** (light, test-only): edited by `test_maintainer` (`progress/impl_fulfillment_despatch_n1_n2.md`), one `ruff format` reflow by the leader, then armed by the leader with backups and `sha256` in `.arm/leader18/`. **R21** (outbox write removed from `despatch_repository.py`) → `AssertionError: exactly one order.despatched.v1 in the outbox`. **R16** (fast path removed from `despatch_creation.create`) → `Failed: the repeat waited on the held stock row: F8's fast path did not answer before the transaction`. Each restore was confirmed with `cmp`, and both affected files re-ran green (14 passed). The `ORD-000007` dev-data stall is carried in the Phase 10 brief.

**Phase 9 session record (leader, 2026-10-07 → 2026-10-08).** One session, as CLAUDE.md requires. Every brief was premise-checked before dispatch: seven checks, which caught four false or conflicting claims of the leader's own before they reached a subagent (Fulfillment's empty packages described as absent; a fixture path; the arms forbidden by a `src` bound; the registration guard's pinned literal). The leader also fixed one gate blocker after the maintainer's `quality.sh` run: ruff formats Python blocks inside Markdown, and the leader's N1/N2 record quoted the pre-format snippet. **Maintainer rulings at the Phase 9 gate (2026-10-08):** (1) the `quality.sh` wall-clock reference is re-baselined from ~125 s (Phase 7) to **~360 s**, with 320.2 s measured at the wrap-up (stack stopped; `2784 passed in 286.35s`). (2) When a later feature of a phase extends files an earlier feature created and neither is committed yet, the commits split **by file**, and the earlier commit's body says that the shared files carry their final content (Phase 8's 15/16 split was the unstated precedent). Also: `/temp/` (the maintainer's local run logs) is git-ignored.

## billing_credit (id 19, phase 10) — 2026-10-09 — opens Phase 10

**Classification:** full group (money domain, persistence and locking, wire contract, the saga's compensation step). `sdd: true`. The sequence was spec_author, a human gate (G1, the zero-amount hold, approved as recommended), an implementer, then an Opus reviewer with arming and the defeat list. **Round 1 REJECTED** (3 blocking defects, all guards); **round 2 APPROVED** (`progress/review_billing_credit.md` §§0–9 and § Round 2).

**Effort:** 1 leader session spanning 2026-10-08 → 2026-10-09. Agent time, as the leader measured it plus the reviewers' own records, comes to **≈5 h 06 min** in total:

| Step | Time |
|---|---|
| spec_author | ≈26 min (1 563 s) |
| implementer, in two runs | ≈25 min + ≈86 min (the first run stopped when the session ended and was resumed with its context) |
| premise checks before round 1 (three) | ≈3 min |
| review round 1 | ≈42 min |
| fix round | ≈77 min (4 633 s) |
| premise checks before round 2 (two) | <2 min |
| review round 2 | ≈45 min |

The human gate is not counted. **Passes:** 1 implementation + 1 fix round + 2 review rounds (1 rejection).

**Baselines (quoted from the files):**

| Build | Total | Outcome |
|---|---|---|
| #7 (`../order-to-cash-nestjs/progress/history.md:882`) | **≈3 h 15 min** | 1 rejection: the port-refusal branch emitted no fact |
| #8 (`../order-to-cash-dotnet/progress/history.md:1215`) | **≈5 h 39 min** (comparable subset ≈4 h 20 min) | 1 rejection, 4 blocking defects, all guards |
| **#9** | **≈5 h 06 min** | **1 rejection, 3 blocking defects, all guards** |

That makes #9 **≈0.90× #8** on the total and **≈1.57× #7**. As in #7 and #8, no finding in either round was a wrong line of shipped behaviour, and `src/` was byte-identical across the fix round (`find -newer` empty). What was not faster: the implementation alone (≈1 h 51 min) ran ≈1.3× #7's ≈1 h 25 min, and the fix round (≈77 min) was 2.3× #8's ≈33 min. It was spent mostly on the two instruments: a parity guard that now compares the whole file outside the docstring, and a census that reads declarations and cross-checks them against imported `MetaData`. That is harness cost, not Python cost.

**Tests:** 2 784 (A2, before the feature) → 3 111 (round 1) → **3 154** (round 2: +42 parity sentinel cases, +1 `summarise` case). `specs/shared/test-matrix.md` has R37 – R41 → DONE. R42 – R44 belong to feature 20.

**Gates** (round-2 reviewer's run, developer stack down):

- `./quality.sh` exit 0 in **353 s** (`3154 passed in 327.79s`)
- coverage 97.42 % overall / 99 % domain
- `mypy --strict` clean on 551 files
- import-linter: 11 kept, 0 broken

Other runs: round 1 349 s; the implementer 366 s; A2 331 s. The maintainer's reference is ~360 s.

**What was built:**

- The `BuyerCredit` aggregate with an append-only ledger (`hold` / `consume` / `release`). `consume` is numerically neutral, so R40 is an identity rather than a branch.
- `summarise`, with an int64 check on every per-order and per-line sum.
- Three NATS subjects (`billing.credit.hold`, `.release`, `.list`) behind a bounded responder (`pool_size = bound + 1`), with one `AsyncSession` per request.
- The line lock: `SELECT … FOR UPDATE` at pinned `READ COMMITTED`, with the committed-exposure scalar read after the lock and `CAST(… AS bigint)`. `22003` maps to `CreditLedgerOverflowError` → `DOMAIN_ERROR`.
- Billing's outbox: nine parity-guarded copies of Orders' family, emitting `credit.approved.v1` / `credit.rejected.v1` / `credit.released.v1`.
- The credit-decision port (feature 20's seam), whose adapter reason type cannot name `over_limit`.
- `BC34`'s Kafka client-id pattern in all three producer services.
- Explicit `otc_cqrs` registration, which discharges feature 43's carried item.

No migration was added, and no package was installed beyond task A3.

**The rejection (round 1), every item a missing guard:**

- **D1:** the release path's `availableCreditAfter` (the fact, and both reply branches) could be replaced by the credit limit with the whole Billing suite green (U8, U9, U10). Every fixture released the line's only exposure, so the fixture satisfied the relation by accident.
- **D2:** the parity instrument compared neither the lines before a copy's docstring nor the rest of its closing line. An import-time statement hidden there passed parity, ruff and mypy.
- **D3:** the census recognised one textual form of `__tablename__ = "outbox"`.

Round 2 closed each one, and the reviewer re-armed it:

- U8, U9 and U10 went RED in the named tests. Two further mutations of the reviewer's own (the pre-release value, and limit − released) were also RED.
- The Q1 mutation went RED, naming both regions.
- Every round-1 form went RED, including a BinOp table name inside `persistence/`, caught by the import cross-check.
- The new `MIRRORS_NOT_OWNERS = {"seed"}` exclusion was ruled correct. The seed writes already-published rows and owns no migration, and #7 and #8 write the same rows through the services' own schemas. The exclusion was also shown to fail when it goes stale or absorbs a sibling.
- N1 and N2 were closed. N3 is **ACCEPTED, NOT FIXED** (cosmetic message; re-open on any edit to `credit_repository.py:63-66` or to `UnknownCreditEntryTypeError`'s constructor).

**Open at approval (non-blocking; disposition FIX NOW, light, test-only, before feature 19's commit; the leader runs the arms):** all three are in `tests/architecture/test_outbox_copy_parity.py` and are described in review § R2.6.

- **R2-1:** the parity instrument does not check the *canonical's* preamble or closing-line tail. Round 1's Q1 mutation applied to Orders' `relay.py` passes parity, ruff, format and mypy: arm D2i must go RED, and D2h too.
- **R2-2:** P6's claim that the import cross-check covers forms the scan cannot read holds only for `persistence/*.py`. Arm D3g (`Table("out" + "box", …)` in `infrastructure/messaging/`) must go RED, or the claim must be narrowed.
- **R2-3:** no sentinel arms a comment-only tail. Arm IM1 must go RED.

**Carried / routed:** round 1's `specs/shared/` gap (`saga.md` §2 has no `credit.release` row) is filed as backlog **213**, attached to feature 41. Feature 43's registration item was discharged (round 1, G6).

**Inherited findings (`design.md` §17):**

- **Avoided:**
  - #8 ids 49 (the id port at every fact and entry site), 50, 51, 53, 54 (pinned READ COMMITTED, probed both ways), 55 / A6, 56, 63, 67, 68, 76, 85, 87, 102, 111.
  - #8 feature-19 D1 (the prescribed mutation was run: six `[ARM]` tasks were sampled at random in round 1, all matching), #8 D4 and #8 A1.
  - #7 feature-19 D1 (the port-refusal fact) and #7 N1.
- **Assigned:** #8 id 57 → feature 22; ids 41 / 62 / 66 / 71 → feature 41; 74 → 27; 84 → 25; 100 → 24.
- **Recurred:** **#7 W3 / N5 and #8 D3**, *a fact field whose corruption survives the suite*, recurred as round-1 **D1** (`credit.released.v1`'s `availableCreditAfter` and both reply branches) and was fixed in round 2. **#9's own feature-17 rejection class** (unplanned call-site mutations surviving the suite) recurred as U8 – U10. Task J1 had enumerated the `release(` / `save(` call sites, but not the result fields built after them. Also fixed in round 2.
- **#9's own instrument lesson** (*changing an instrument swaps its premises*) recurred twice:
  - round-1 D2 / D3, closed;
  - round 2's R2-1, the canonical operand, the premise nobody wrote down, open as fix-now.

**Review round 2 findings R2-1 – R2-3, closed 2026-10-09 as a LIGHT change** (CLAUDE.md, Cost discipline: test-only): one implementer (≈3 min, 192 s), no separate reviewer. `tests/architecture/test_outbox_copy_parity.py` only: the canonical operand's preamble and closing-line tail are now checked (R2-1); the import cross-check walks the scan's whole population, `infrastructure/**/*.py` minus `__init__.py` (R2-2, option a); a comment-only closing-line tail has its own sentinel (R2-3). Arms D2h, D2i, D3g and IM1 were each seen RED by the implementer and restored with `cmp` (`progress/impl_billing_credit.md` § Review round 2 findings). The leader read the fix sites, confirmed with `git status` that Orders' `relay.py` is back to HEAD and that the D3g file is gone, and re-ran the file: **94 passed** (88 before), `ruff check`, `ruff format --check` and `mypy` clean. R2-1 is closed in the same phase that found it.

## billing_credit_simulator (id 20, phase 10) — 2026-10-09 — approved first pass

**Classification:** full group, because R44 is a wire / saga-compensation claim (the leader's reason). `sdd: false`, so there was no spec phase and no human gate; the design is feature 19's seam (`specs/billing_credit/design.md` §15.1). The sequence was implementer, then an Opus reviewer with arming and the defeat list. **Round 1 APPROVED**: 0 blocking defects, 2 non-blocking items FIX NOW (light), 1 nit (`progress/review_billing_credit_simulator.md`).

**Effort:** 1 leader session, one implementation pass and one review pass. Wall-clock runs from the first artefact (`progress/brief_impl_billing_credit_simulator.md` and its premise check, ≈10:07) to the verdict (≈10:58): **≈51 min**.

| Step | Time |
|---|---|
| premise check (implementer brief) | ≈35 s (the leader's measurement) |
| implementer | ≈31 min (1 878 s, the leader's measurement) |
| premise check (review brief) | <1 min |
| review | ≈18 min (≈10:40 → ≈10:58; 6.4 min of it `quality.sh`, ≈2 min the R16 clamp arm on its 130 s NATS timeout) |

**Baselines (quoted from the files):**

| Build | Total, first artefact → verdict | Outcome |
|---|---|---|
| #7 (`../order-to-cash-nestjs/progress/history.md:903`) | **≈39 min** | approved first pass, 6 non-blocking findings |
| #8 (`../order-to-cash-dotnet/progress/history.md:1261`) | **≈1 h 04 min** | approved first pass, 3 non-blocking findings (N1, A1, N2) |
| **#9** | **≈51 min** | **approved first pass, 0 blocking, 2 FIX NOW + 1 nit** |

That makes #9 **≈0.80× #8** and **≈1.3× #7**. **Not faster than #7:** the implementation (≈31 min against #7's ≈20) carried what #7 only probed. That is the committed 200 000-draw measured theory (#8's), a 20-value refusal table for Python's own `float()` coercions, three lifespan tests through `create_app()`, and 20 arms. The review was the same length as #7's (≈18 min). It spent its time on 17 arms of its own, a real `quality.sh` run and a parse probe, against #7's coverage run and its 200 000-draw throwaway probe.

**Tests:** 3 160 → **3 234** (+74). The reviewer's `quality.sh` (developer stack down): exit 0, **382 s**, `3234 passed in 356.11s`. Coverage 97.42 % overall and 99 % domain; import-linter 11 kept, 0 broken. `specs/shared/test-matrix.md` R42–R44 → DONE (39 green, 1, 23 pending of 63).

**What was built:**

- `infrastructure/credit/simulator.py`: the `.99` rule is evaluated first and consumes no draw; then a strict `random() < rate` on an injected plain callable; the constructor refuses a non-finite or out-of-range rate.
- `CreditSimulatorSettings.failure_rate` (`CREDIT_FAILURE_RATE`, default 0, empty = 0): an ASCII numeral regex, then `float`, then finite and range checks, via a `BeforeValidator`. The decorator census forbids `@field_validator`.
- The composition root binds the simulator by default, as in #7 `app.module.ts:142` and #8 `BillingProgramConfiguration.cs:36`.
- The `.env.example` entry, the reach-test literal and the conftest variable.

No `domain/`, `application/` or `presentation/` file changed (BC15; `find -newer` lists 12 files). No package was installed.

**Approval evidence:** 17 reviewer arms, all RED in a named test, each restored by `cp` with `cmp=True`.

- The ordering: the swap (R1) and the `.99` branch consuming a draw (R2), both at rate 1 with a source returning 0.
- `rate * 0.5` (R8), caught only by the measured theory; `<=` (R9), caught only by the boundary test.
- The composition read deleted (R3), and `/ 100` at the constructor (R10).
- Always-approve bound by default (R4); the literal entry removed (R5); a sibling alias (R14).
- The cents reason corrupted at the wire (R6); `requestedAmount` ↔ `availableCredit` transposed in the shared payload builder (R7).
- `re.ASCII` dropped (R11); the rate branch returning the cents reason (R12); clamping (R13 unit; R16 lifespan, see N1).
- The predicate reading `available_credit` (R15); the fixture guard made a no-op (R17).

**Open at approval (FIX NOW, light, one batch before feature 20's commit; the leader runs the arm):**

- **N1:** `integration/test_credit_simulator.py:136-152`. Under a clamp, the lifespan refusal test fails only on a 130 s NATS connection timeout, which does not name R43. Monkeypatch the root's NATS connect to `pytest.fail("R43: the boot reached NATS …")`. R16 / A13 must then fail within seconds, naming R43. The clamp is already killed by name at unit level (R13).
- **N2:** the impl report's ported-idiom ledger lacks the #7 and #8 line citations (`simulator-credit-decision.ts:54/58/66/76/82/91`, `SimulatorCreditDecision.cs:49/60/70/119/125/126/130`). It also lacks two rows: the accepted-spelling set, where #7 refuses `1e-1`, `+0.5`, `1.` and `-0` but #8 and #9 accept them; and Python's `%` sign semantics, unreachable because BC33 refuses negative amounts at `credit_wire.py:59`.
- **N3 (nit):** `conftest.py:377` still says "approving adapter".

**Record corrections:** #7 N6 was already closed at HEAD (inherited from #8's back-port), not "not touched". O1 (`1.0000000000000001` → 1.0) is ACCEPTED WITH EVIDENCE as trilogy-identical; re-open if any build adopts a decimal-exact parse. Nothing is rooted in `specs/shared/`, so no SA and no backlog entry.

**Inherited findings:**

- **Avoided:**
  - #8 A1, #8 N1, #8 N2 / #7 N2;
  - #7 N1 (the R44 key sets are compared to each other), #7 N3, #7 N5;
  - #7 N6 (by inheritance).
- **Not applicable:** #7 N4.
- **Recurred:** #9's own arming-message class (feature 16 N1, feature 18 N1/N2) as N1. Nothing from #8's backlog recurred.

**Review findings N1 – N3 and record corrections RC1 – RC2, closed 2026-10-09 as a LIGHT change** (CLAUDE.md, Cost discipline: test-only plus record): one implementer (≈2 min, 125 s), no separate reviewer. N1: `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting` now replaces the root's NATS connect with a `pytest.fail` naming R43 and the value, so the clamp mutation fails in 8.5 s with `R43: the boot reached NATS with CREDIT_FAILURE_RATE='1.5': not refused` (it failed in 131 s on `NoServersError` before). N2: the ported-idiom ledger carries file-and-line citations and the two missing rows (accepted spellings, where #7 and #8 disagree; Python's `%` sign, unreachable behind `BC33`). N3: the `billing_host` docstring names the simulator default. The leader confirmed that `settings.py` is byte-identical to the pre-arm backup and to the reviewer's, and re-ran `test_credit_simulator.py` + `test_credit_simulator_settings.py` (**46 passed**), with `ruff check`, `ruff format --check` and `mypy` clean.

## billing_invoicing (id 21, phase 10) — 2026-10-10 — approved first pass

**Classification:** full group (money domain, saga command responder, wire contract, persistence, a two-aggregate transaction). `sdd: true`: spec_author, the human gate (G1 adopted as recommended, `progress/spec_billing_invoicing.md` § Gate ruling), implementer with the live walkthrough, then an Opus reviewer with arming and the defeat list. **Round 1 APPROVED**: 0 blocking defects; 5 non-blocking items FIX NOW (light: N1, N2 design-text corrections; N3 one assertion in the retryability guard; N4, N5 comments) and 1 routing item for the leader (R1: feature 22's acceptance list must carry BI8's lock-order binding) — `progress/review_billing_invoicing.md`.

**Effort:** 1 spec pass + 1 human gate + 1 implementation pass (live walkthrough included) + 1 review pass, plus three premise checks.

| Step | Time |
|---|---|
| spec_author | ≈28 min (1 685 s, the leader's measurement) |
| human gate | the maintainer's wait, not counted |
| premise checks (spec brief, implementer brief, review brief) | 3 × <1 min |
| implementer, live walkthrough included | ≈4 h 08 min (14 887 s, the leader's measurement) |
| review | ≈30 min active (21:07 → ≈21:20 and 05:27 → ≈05:44; the machine was in S3 suspend from ≈21:20 to 05:27:13, `journalctl`, excluded); 6 min 14 s of it `quality.sh` |
| **Total of measured agent time** | **≈5 h 09 min** |

**Baselines (quoted from the files):**

| Build | Total, first spec artefact → verdict | Outcome |
|---|---|---|
| #7 (`../order-to-cash-nestjs/progress/history.md:922`) | **≈1 h 51 min** | approved on round 2; 2 blocking (N1 0/60 boxes ticked, N2 discount check inside the transaction) |
| #8 (`../order-to-cash-dotnet/progress/history.md:1305`) | **≈3 h 16 min** | approved on round 2; 3 blocking (D1, D2, D3 — line 1366 "3/3 blocking defects closed"; its "two survived" paragraph counts the mutation survivors D1 and D2 only) |
| **#9** | **≈5 h 09 min** | **approved first pass, 0 blocking** |

That makes #9 **≈1.58× #8** and **≈2.8× #7**: **not faster.** The implementation alone (≈4 h 08 min) exceeds #8's whole feature. It bought 54 of 54 `[ARM]` tasks armed through 158 arm rows, a J1 sweep that mutated every call site of every hand-built seam (two missing tests found and added), and the live walkthrough. #8 spent its time differently: a fix pass and a second review (≈44 min) after its suite let a zeroed discount and a corrupted payment fact through. #9's spec pre-empted both, and the reviewer's 54 arms found no code defect, so the second round was never needed. The spec pass (≈28 min) was ≈1.5× #8's (≈19 min).

**Tests:** 3 234 → **3 415** (+181). The reviewer's `quality.sh` (developer stack down): exit 0, 374 s, `3415 passed in 354.54s`, coverage 97.46 % overall and 98 % domain, import-linter 11 kept / 0 broken. `specs/shared/test-matrix.md` R45, R46 → DONE (41 green, 1 scoped, 21 pending of 63, re-derived from the rows).

**What was built:** the `Invoice` aggregate (`InvoiceState = Issued | Paid(paid_at)` as one attribute; totals derived from the lines; `mark_paid` delivered uncalled and returning its fact for feature 22), the `billing.invoice.issue` / `.list` route entries on the one `CreditResponder`, the issue unit (fast path; then line lock → plain re-read → currency → `consume` → `INV-` counter → `Invoice.issue` → both saves in one `run()`), the `INV-` allocator over backlog 211's seed, the invoice reads, mapper and repository, and G1's offset clamp on all three list readers (`billing.invoice.list`, `billing.credit.list`, `fulfillment.stock.list`). No migration, no package, no `services/orders/` change. `R40`'s `consume` has its first live caller; the live walkthrough issued `INV-000006` for `ORD-000008` and `INV-000007` for a fresh discounted order `ORD-000010` (59 243 / 777 / 58 466), both reaching `invoiced` unattended with available credit unchanged by the consume.

**Approval evidence:** 54 reviewer arms, 52 red on a named assertion, each restored by `cp` with `cmp` identical. The discount zeroed at six sites (decoder, aggregate, column, fact, list mapper, list wire); the most plausible wrong value at each total; the lock order, `consume` placement and BC38's zero hold; the `INV-` seed and continuation; the clamp at each of three sites; a sibling `RpcError` code at all eight mapping sites; six randomly drawn `[ARM]` tasks (seed 20261009: B8, C1, C5, E2, F4, G6) re-run exactly; nine unplanned call-site mutations, including both fact families (deletion and wire corruption) and the ledger row most likely to be assumed (asyncpg's `UUID` subclass). Two survivors, both explained: the hold → exposure split (killed by feature 19's `summarise` guards when widened) and the integration BI5 residue (killed by the unit entry guard, as the spec's placement lesson predicts).

**Open at approval (FIX NOW, light, one batch before feature 21's commit):** N1 `design.md` §6.2 / §13.3 and `tasks.md` F6 describe race and F6 loser outcomes the code does not produce (observed `PRECONDITION_FAILED`, `INTERNAL_ERROR` 23505, `UNAVAILABLE` 40001). N2 `design.md` §5.2, L41, §16.2 and `requirements.md` BI23 still say `@final` (the code uses an `__init_subclass__` refusal; reviewer's recommendation to the maintainer: accept, do not widen the decorator census). N3 the retryability guard reads terminal-ness from Orders' set for `PRECONDITION_FAILED` only; assert it for every domain-refusal input (BI25), armed by mapping `DomainError` to `INTERNAL_ERROR`. N4 two test comments overclaim (a residue assertion's message; the race header). N5 `credit_repository.py`'s docstring omits the relay's `update(Outbox)`. **R1 (leader):** add BI8's lock-order binding to feature 22's acceptance list.

**Inherited findings:**

- **Avoided:** #8 ids 45, 47, 49, 53/55, 54, 57 (seam), 65, 72, 85, 102; #8 D1, D2, D3, R2-N1, R2-N3, N6; #7 N1, N2/N10, N3, N4/N5, N7, N8 — each with the arm or guard in `progress/review_billing_invoicing.md` §7.
- **Recurred (this run's own):** a design prescribing a decorator the census forbids (caught by `quality.sh`); a spec predicting failure outcomes it had not measured (N1, defeat-list row 9's stale-premise class); a residue assertion worded as an entry claim, in a message only (N4a, #7 N10's class); a #8 guard classified **Ported** with its terminal-set assertion dropped (N3, the "port the guards too" class). Nothing from #8's backlog recurred.

**Would #7's or #8's standard have caught the open items?** N1 and N2: no — neither predecessor's review compared the design's predicted failure outcomes with the observed ones. N3: #8's yes — #8's own BI25 test read the terminal set (`BillingErrorMapperTests.cs:173-184`), and #9's port dropped that assertion while classifying the file **Ported**. N4a: #7's yes (it is #7's N10 class).

**Review findings N1 – N5 and routing item R1, closed 2026-10-10 as a LIGHT change** (CLAUDE.md, Cost discipline: spec text, comments, one test assertion): one implementer (≈1 min, 69 s), no separate reviewer. N1 / N2: `specs/billing_invoicing/{design,requirements,tasks}.md` now state the race outcomes the code produces and the runtime finality refusal (no `@final` remains; the census is not extended, review §4.7). N3: `tests/architecture/test_billing_rpc_error_retryability.py` asserts every `DOMAIN_ERRORS` input maps into Orders' `TERMINAL_RPC_ERROR_CODES`; arm Q6f (`credit_rpc_errors.py:82` → `Code.internal_error`) failed with `CreditLimitExceededError is answered INTERNAL_ERROR, which Orders' saga adapter would retry; BI25/BI26 require a terminal code`. N4 / N5: comments and one docstring. R1: the leader added the BI8 lock-order binding to feature 22's acceptance. The leader confirmed that `credit_rpc_errors.py` is byte-identical to its backup and that `credit_repository.py` differs from the reviewer's backup only in its module docstring (AST compare), and re-ran the retryability file (**3 passed**) and Billing's unit tests (**470 passed**).

## billing_remittance_intake (id 22, phase 10) — 2026-10-10 — approved first pass; closes the order-to-cash cycle end to end for the first time in #9

**Classification:** full group (money domain, saga facts, persistence, wire contract). `sdd: false`: the design is the seam features 19 and 21 cut (`specs/billing_credit/design.md` §15.3, `specs/billing_invoicing/design.md` §15.1). There is no spec phase and no human gate. The implementer ran the live walkthrough, then an Opus reviewer armed the guards and walked the defeat list. **Round 1 APPROVED**: 0 blocking defects; 2 non-blocking items FIX NOW (light: N1, a `type: ignore[attr-defined]` on `result.rowcount` in `invoice_repository.py:132`; N2, a ledger and docstring claim that the writer's per-row flush carries R47's ordering, which reviewer arm RV16 showed is not load-bearing on this path); 1 routing item for the leader (R1: feature 25 must map `billing.payment.register`'s `RpcError`s to `openapi.yaml:673-675`, not port #8's classifier verbatim). Full record: `progress/review_billing_remittance_intake.md`.

**Effort:** 1 implementation pass (live walkthrough included) + 1 review pass, plus two premise checks.

| Step | Time |
|---|---|
| premise checks (implementer brief, review brief) | 2 × <1 min (≈43 s for the review brief, the leader's measurement) |
| implementer, live walkthrough included | ≈57 min (3 423 s, the leader's measurement; mtimes 05:41:34 → 06:38:36) |
| review | ≈23 min (brief 06:41:02 → verdict ≈07:04 CEST); 6 min 56 s of it `quality.sh`, ≈11 min the 22 reviewer arms and 5 re-run implementer arms |
| **Total of measured agent time** | **≈1 h 21 min** |

**Baselines (quoted from the files):**

| Build | Total, first artefact → verdict | Outcome |
|---|---|---|
| #7 (`../order-to-cash-nestjs/progress/history.md:943`) | **≈1 h 01 min** (48 + 13) | approved first pass, 0 blocking |
| #8 (`../order-to-cash-dotnet/progress/history.md:1376`) | **≈1 h 28 min** (56 + 32) | approved first pass, 0 blocking |
| **#9** | **≈1 h 21 min** (57 + 23, premise checks under a minute each) | **approved first pass, 0 blocking** |

That makes #9 **≈0.92× #8** and **≈1.33× #7**: **slightly faster than #8, not faster than #7.** The implementation took #8's time (57 vs 56 min) and delivered more. It ran 83 arms against #8's seven. It closed #8's N3 as a refusal where #8 discarded the `None`, and closed #8's N1 (id 57) and N2 by construction where #8 shipped them as findings. It extended #7's N11 to amount and currency per `openapi.yaml:673`. It added a UNIQUE-backstop race across credit lines and the BI8 held-lock probe. The live walkthrough moved `ORD-000008` and `ORD-000010` to `completed`. The review was shorter than #8's (23 vs 32 min). It ran 22 mutations of its own, re-ran 5 of the implementer's 83 at random, and ran one `quality.sh`; it did not re-run the Billing suite separately.

**Tests:** 3 415 → **3 492** (+77). The reviewer's `quality.sh` (developer stack down): exit 0, 416 s, `3492 passed in 392.45s`, coverage 97.47 % overall and 98 % domain, import-linter 11 kept / 0 broken, mypy strict clean over 593 files. `specs/shared/test-matrix.md`: R47 → DONE; R48 and R49 keep their API halves TODO for feature 31 (the route is feature 25's), with the integration halves DONE. Totals: 42 green, 1 scoped, 20 pending of 63.

**What was built:** `billing.payment.register`, a route entry on the one `CreditResponder` with no rename. The unit:
1. the R48 fast path, outside any transaction;
2. resolve the invoice, unlocked;
3. one clock read;
4. inside `run()`, lock the credits row (BI8's first lock);
5. re-read the invoice, plain;
6. the under-lock R48 dedup;
7. `Invoice.mark_paid`, which raises R49's three refusals and returns `PaymentReceived`;
8. `BuyerCredit.release(INVOICE_PAID)` caused by that fact's `event_id` (#8 id 57), with `None` refused as `credit.not_outstanding`;
9. the guarded `UPDATE … WHERE status = 'issued'`, the `payments` INSERT (`23505` on `uq_payments_payment_reference` → `PaymentReferenceReusedError`) and outbox row 1;
10. the release entry and outbox row 2.

No migration, no package, no change under `services/orders/`.

**The three departures from #7 / #8, ruled KEEP (review §2):**
1. Refusing a payment whose release has nothing outstanding follows R47's text, which #7 / #8's discard violated, and #9's gated designs. The state is unreachable through the saga (`domain-model.md:200`, `saga.md:233-257`).
2. A reference reused with another amount or currency is decided by `openapi.yaml:672-673` and `asyncapi.yaml:3696`.
3. `INVOICE_NOT_PAYABLE` / `PAYMENT_MISMATCH` are decided by the `RpcError` contract ("`code` is stable and machine-readable"; the two enum values have no other possible producer) and R49's "machine-readable reason". Both codes are terminal in Orders' set. Feature 31's HTTP script stays #7's and #8's provided feature 25 maps the codes (routing item R1).

**Approval evidence:**
- 22 reviewer arms, 20 killed by a named assertion.
- The two survivors, both explained: RV03, because the broker test does not assert `reason` while the outbox test does (RV03b killed); and RV16, the per-row flush (N2).
- Both mutation families on the facts: the swap killed at the broker (RV01); valid-value payload corruption killed at the outbox and the broker (RV17 / RV17b `valueDate`, RV18 `amount`, RV03b `reason`, RV04 `availableCreditAfter` = the limit).
- BI8 inverted at an infrastructure site (RV06) and defeated behind a matching call log (RV07), both killed by the held-lock race.
- The gross substituted for the net at the domain site (RV05) killed.
- 5 / 5 randomly chosen implementer arms reproduced their recorded messages.
- Acceptance 2 re-searched independently with planted sentinels (the guard went 3 failed, then 5 passed after removal).

**Inherited findings:**
- **Avoided:** #8 id 57; #8 feature-22 review N1, N2, N3, A1, A2, A3; #8 id 54; #7 N11 (extended); #8 ids 48, 49, 53 / 55, 63, 74, 102 (impl §11, each with its guard).
- **Did not recur:** #8 N12, N13.
- **Recurred (this run's own):** a ported-idiom ledger row whose mechanism claim had not been armed (N2). The property held and was guarded, but the attributed link was not load-bearing. This is the class the Phase 8 gate made binding, caught here by probing the claim rather than the behaviour.

**Would #7's or #8's standard have caught the open items?** N1: no; neither reviewed typing escapes. N2: no; neither probed a claimed ordering link apart from the ordering itself (#7's and #8's reviews armed the swap only). R1: #8's yes in effect, because its Gateway was built later against its own Billing codes. #9's dotted `details.code` make a verbatim port fail silently, which only a cross-feature read shows.

**Review findings N1 – N2 and routing item R1, closed 2026-10-10 as a LIGHT change** (CLAUDE.md, Cost discipline; the leader classified N1 light although it touches a persistence statement, because it changes only the statement's static type — the SQL is unchanged — and is guarded by an existing test plus one arm): one implementer (≈2 min, 104 s), no separate reviewer. N1: `invoice_repository.py`'s `rowcount` read goes through `cast("CursorResult[Any]", …)` instead of `# type: ignore[attr-defined]`, so Billing's `src` holds no `type: ignore`; arm: dropping the `status == "issued"` guard failed `test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing` with `DID NOT RAISE StoreUnavailableError`, restored with `cmp`. N2: `payment_register.py`'s docstring and the impl record's "Emission order" row now attribute R47's ordering to call order plus the `Identity` `seq` (review RV16). R1: the leader filed the Gateway's payment-error mapping on feature 25's acceptance. The leader diffed `invoice_repository.py` against the reviewer's backup (the statement unchanged, only the cast and import added), confirmed `grep -rn "type: ignore" services/billing/src` is empty, and re-ran the two payment integration files and `test_write_path_population.py` (**90 passed**).
