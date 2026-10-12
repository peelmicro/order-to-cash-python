# Brief — spec_author, spec amendments `SA-7`, `SA-8`, `SA-9` (phase 13, ruled at the gate 2026-10-12)

**Task:** apply the three amendments **exactly as proposed** to all three repositories, in the order `SA-7` → `SA-8` → `SA-9`, record each everywhere the SA convention requires, and write `progress/sa7_sa8_sa9_application.md` (in #9) with every command and its result. Do **not** commit in any repository. Return a summary of at most 10 lines.

**The ruling (maintainer, 2026-10-12, verbatim): "SA-7, SA-8, SA-9 approved".** The texts are the proposals — read them, do not re-decide them:

- `progress/proposal_sa7.md` — one row in `saga.md` §2's command table, after `credit.hold`.
- `progress/proposal_sa8.md` — `saga.md`: a new §4.3 paragraph *"A stock reservation that arrives after the cancellation"* after the *"A credit approval that arrives after the cancellation"* paragraph; §5's `stock.reserved.v1` row's Orchestrator cell; §6's `stock.reserved.v1` redelivery row's *What happens* cell. Wrap the new §4.3 paragraph at the same width as its neighbours (that file hard-wraps its prose; match the file, not CLAUDE.md's markdown rule for our own docs).
- `progress/proposal_sa9.md` — `openapi.yaml`: (A) a new shared response `UnlistedProblem` under `components/responses` (place it after `UpstreamUnavailable`) and a `default` response referencing it on **every** operation (count the operations with a command first — the leader counts 18 — and report the count after); (B) `UpstreamUnavailable`'s description replaced; (C) one sentence appended to `/stock/replenish`'s description. Indentation exactly as the file's neighbours.

The proposals' code-half and recommendation sections are **not** for you (the leader dispatches #9's code; #7's and #8's code is not changed).

## Repositories

- #9: `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python`
- #8: `../order-to-cash-dotnet`
- #7: `../order-to-cash-nestjs`

Before any edit (leader-verified, re-check): `sha256sum specs/shared/saga.md specs/shared/openapi.yaml` is `c2829f87c2bc3221…` / `e73efb8abe4fc5d1…` in all three. If not equal, stop and report.

## Steps, per amendment, in order (SA-7, then SA-8, then SA-9)

1. Edit #9's file, `cp` the identical bytes to #8 and #7, confirm `cmp` and record the three `sha256` after this amendment. **After `SA-7`, save a copy of the post-`SA-7` `saga.md` to `progress/sa_snapshots/saga.after_sa7.md`** (the wrap-up commits each amendment on its own and needs the intermediate state; `SA-8` also edits `saga.md`).
2. Generated files: only `SA-9` touches `openapi.yaml`. Find by search what each repository generates from it and regenerate with that repository's own generator, then run its drift check — follow exactly what `SA-6` did (#9 `progress/history.md`, the entry "Shared amendment SA-6"; #9 `progress/sa6_application.md`): #7 `pnpm --filter @otc/contracts run generate` / `check` / `test`; #8 `apps/web` `pnpm run types:generate` / `types:check` and `dotnet test tests/Gateway.UnitTests` (its `OpenApiContractTests`); #9 `uv run python scripts/generate_contracts.py`, `--check`, `uv run pytest packages/contracts -q`. Never hand-edit a generated file. If a toolchain is missing, stop and report. **Report, do not fix,** any test outside the contracts packages that the new `default` responses break in #8 or #7 (e.g. a conformance test comparing declared statuses) — the leader decides.
3. Records, following the `SA-6` entries' shape exactly (`grep -n "SA-6"` in each repository's `README.md` and `progress/history.md`):
   - `README.md` registry: one row per amendment in #9 and #8 (#7's README has no registry — as for `SA-6`, none is created). Raised: #9, Phase 13. Touches / why, one line each: `SA-7` `saga.md` §2 — the `credit.release` row the command table lacked (backlog 213); `SA-8` `saga.md` §4.3, §5, §6 — a stock reservation landing after an operator cancel at `placed` was never released (backlog 216, reproduced in #9, shared by #7 and #8); `SA-9` `openapi.yaml` — a `default` Problem response on every operation (59 of 100 Gateway statuses were undeclared, in all three builds) and `UpstreamUnavailable` no longer promises "not applied" after a timeout (backlog 215). Update the sentence after #9's table ("Any further amendment raised here will be `SA-7` onwards…") and #8's back-port status paragraph if present; enumerate with a command any sentence in the three READMEs that names `SA-6` as the last amendment or counts the amendments, and classify each hit.
   - `progress/history.md` in each repository: **one entry per amendment, appended in the order `SA-7`, `SA-8`, `SA-9`** (the wrap-up builds per-amendment commits by cutting this file at section headers, so the order matters): the ruling, the files changed, the sha256 after, the regeneration / drift results. In #9 append after the last existing entry (`gateway_sse_push`), nothing between.
   - #9 `CLAUDE.md` line 9: "next is `SA-7`" → "next is `SA-10`". #7's and #8's `CLAUDE.md` carry no pointer (as for `SA-6`; verify).
   - `specs/shared/test-matrix.md` is exempt from byte identity (per-assessment Status column) and needs no change.
4. Run `./init.sh` in #9 and report section 5d (shared-spec parity with #8 and #7: six files each).

## Bounds

Write only: `specs/shared/saga.md` and `specs/shared/openapi.yaml` (three copies each), the generated files regenerated by their generators, `README.md`, `progress/history.md` and (#9) `CLAUDE.md`'s pointer in each repository, and in #9 `progress/sa_snapshots/saga.after_sa7.md` and `progress/sa7_sa8_sa9_application.md`. No other change. No `feature_list.json` in any repository. No git command that writes the index or working tree, and no commit or push. Prose in our own Markdown (README, history): no hard line-wraps.
