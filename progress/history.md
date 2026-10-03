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
**Tests:** `init.sh` exits 0 on the fresh tree and **exits 1 on all 15 break cases** (#8 tested 8), each restore confirmed with `cmp`: two features `in_progress`; an invalid status; a duplicate id; an `sdd` feature past `pending` without its triple-doc; invalid JSON; a missing harness file; six agents; an agent that neither pins nor documents its model; `current.md` naming the wrong feature; a superseded rule reintroduced; a feature id disappearing and a `done` reverting (tripwire); `.python-version` pinning an unavailable interpreter; a shared-spec file edited; a sibling's spec file missing here. The installed `commit-msg` hook rejects "closes all four Billing features" without a `counted:` line and accepts it with one.
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
