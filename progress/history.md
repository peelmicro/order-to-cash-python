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
