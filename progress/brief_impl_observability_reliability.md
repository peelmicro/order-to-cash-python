# Brief — implementer, feature 27 `observability_reliability` (phase 14), stage by stage

**Classification: full group** (saga, persistence, wire contract). The maintainer approved the spec on 2026-10-12 ("approved"; G1 – G4 as recommended).

**Each pass implements the stages its dispatch message names, and no others.** Stop at the last named stage's gate box (S1.8, S2.7, S3.11, S4.23, S5.9, S6.8, S7.6 — each "Stage gate"), even if time remains. The leader reads your record and runs the stage gate before the next pass.

## Inputs (exact paths)

- **The spec you work from:** `specs/observability_reliability/{requirements,design,tasks}.md`. `tasks.md` is the checklist (tick `[x]` as you go; "How to read this file" defines `[ARM]`, `[MEASURE]`, `[LEADER]`, the mutation families, the standing rules and the **Bounds** — they bind you). `design.md` §11 is the ported-idiom ledger, §12 the ported-guard table, §14 the defect classes from #8's three rejected rounds.
- **The gate record:** `progress/spec_observability_reliability.md` — the Status paragraph carries the ruling. Item 12 is built per G1 (`tasks.md` S4.15 – S4.16): no synthetic `orders.cancel.requested` envelope and no dead letter for an operator-cancel park.
- **Process lessons:** `progress/current.md` "Process lessons from Phase 13" (fixtures differ from every plausible wrong order; no ledger row says "cannot be armed" without the failed probe; a test's name is a claim; ask the ledger question of every framework workaround). CLAUDE.md's Arming protocol and Runs rules (read them on disk).

## Your record

Write `progress/impl_observability_reliability.md`, **one section per stage**, appended pass by pass (never rewrite an earlier stage's section; add a dated "revision" note if a later stage changes an earlier claim). Per stage: what was built (files), every `[MEASURE]` output verbatim, every `[ARM]` with backup path + `sha256`, the mutation, the failure text verbatim, the restore `cmp`, the green re-run; the stage gate's commands with exit codes and pass counts; any deviation from `design.md`, with the reason, also written on the `tasks.md` box; and every finding with a proposed disposition. Ledger rows that change go into `design.md` §11 with the reason.

## Rules that are easy to break

- **`[LEADER]` tasks:** do not do them. Name the keys / files in the record and in your return, and continue with what does not depend on them.
- Do not touch `feature_list.json` (S8.7 is the reviewer's / leader's, not yours), `specs/shared/` (except the Status cells `tasks.md` names, and only when a stage proves the row), `infra/`, compose, `.env*`, `n8n/`, `apps/web/`.
- No git command that writes the index or the working tree (`stash`, `reset`, `restore`, `clean`, `checkout`); read committed content with `git show HEAD:<path>`; undo by re-editing.
- Arming backups go into the repo-local `.arm/r27/` (git-ignored), never `/tmp`. Every test run under a process-group timeout: `setsid --wait timeout -k 10 <s> …`. **Without `--wait`, `setsid` forks and returns at once when the shell made it a group leader** (leader, 2026-10-12: its `exit=0` was recorded while pytest was still starting, and the log was overwritten from offset 0), so a status read after it is `setsid`'s, not pytest's. Take the result from an artifact (`--junitxml`, or pytest's summary line), never from the status alone. Never two runs against the same containers at once; wait on the PID you started.
- The `otcpy` developer stack is stopped (only `otcpy-n8n` runs); integration suites must pass with it down (testcontainers). Do not start the developer stack; the live walkthrough (S8) is dispatched separately.
- Dependencies only through `uv add --package otc-<svc> …`; record the resolved versions.

## Return

At most 10 lines: stages completed, the stage gate's result (counts from the command), `[ARM]` boxes armed / not armed (each unarmed one named), `[LEADER]` items waiting, and findings. Everything else is in the record.
