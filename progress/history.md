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
