# SA-7, SA-8, SA-9 application — command record (spec_author, 2026-10-12)

Brief: `progress/brief_spec_sa7_sa8_sa9.md`. Ruling (maintainer, 2026-10-12, verbatim): "SA-7, SA-8, SA-9 approved". Texts: `progress/proposal_sa7.md`, `proposal_sa8.md`, `proposal_sa9.md` (spec halves only). Nothing committed in any repository; no git command that writes the index or working tree was run; no `feature_list.json` touched.

## 1. Pre-edit parity

`sha256sum specs/shared/saga.md specs/shared/openapi.yaml` in #9, #8, #7 → all three `c2829f87c2bc3221aa6a8574fac3920e19f3363e21c64887728d428f5fc9a880` (saga) / `e73efb8abe4fc5d1ac2d114b9d0453884d135fe9e19c6caee1e3cce1597cdfd4` (openapi). Equal; proceeded. `git status --short specs/shared README.md progress/history.md CLAUDE.md`: #8 and #7 empty; #9 `progress/history.md` and `specs/shared/test-matrix.md` already modified before this session (not by me).

## 2. SA-7 — `saga.md` §2

- Edit: one row inserted after the `credit.hold` row, the proposal's text verbatim (python replace asserting exactly one anchor). `git diff`: 1 insertion.
- `cp` to #8 and #7; `cmp` #9↔#8, #9↔#7 → silent (OK).
- Snapshot: `cp` to `progress/sa_snapshots/saga.after_sa7.md`, `cmp` OK.
- **sha256 after SA-7** (#9, #8, #7, snapshot): `c8552a315b1bcfd61940b64af71175e21774cf645803532344e43bfac2441336`.

## 3. SA-8 — `saga.md` §4.3, §5, §6

- Edits (each anchor asserted unique): (1) the §4.3 paragraph inserted after the "A credit approval that arrives after the cancellation" paragraph, preceded by a blank line, using the proposal's line breaks (max line 79 columns; the neighbour paragraph's lines reach 81 characters); (2) §5 `stock.reserved.v1` Orchestrator cell replaced by the proposal's text; (3) §6 `stock.reserved.v1` redelivery row: the proposal's sentence appended to *What happens* after ". " (the separator the `order.placed.v1` row uses). `diff` against the snapshot: 11 lines added (paragraph + blank), 2 rows changed.
- `cp` to #8 and #7; `cmp` OK both.
- **sha256 after SA-8** (all three): `feab76f2db910ea1a76a653c0e3b8bbfaafa653a144bc2f32eeaff3a5bbdd6b2 (after the wrap-up fold of §6's *Why it is safe* cell to `Layers 1 + 2 + 3`; before the fold `8fb00520a299fa1a558c7c93c45d80a3c0c3ce56e2cbaabc347b5c7b78a98b62`)`.
- Citation check: **F5** is `domain-model.md:269`, R34 `requirements.md:266`; the §6 wording mirrors the existing `credit.rejected.v1` redelivery row.
- **Observation, not acted on (outside the proposal):** the §6 row's *Why it is safe* column still reads "Layers 1 + 2", while the appended sentence relies on Layer 3 (an idempotent command), as the `credit.rejected.v1` row states with "Layers 1 + 3". The proposal changes only *What happens*; applied as approved. If the leader wants the column to read "Layers 1 + 2 + 3", that is a further amendment (`SA-10`), not a silent edit.

## 4. SA-9 — `openapi.yaml`

**Operation count (before editing):** `grep -cE "^    (get|post|put|patch|delete|head|options|trace):"` → **18**; `grep -c "^      responses:"` → **18**. Matches the leader's 18.

- (A) For each of the 18 `      responses:` blocks, `default:` + `$ref: '#/components/responses/UnlistedProblem'` inserted after the block's last non-blank line (8 / 10-space indent, as the neighbours). `UnlistedProblem` added under `components/responses` directly after `UpstreamUnavailable`, the proposal's text verbatim.
- (B) `UpstreamUnavailable`'s description replaced by the proposal's seven lines.
- (C) `/stock/replenish`: the sentence appended to the description's last paragraph ("legitimate repeats. A `503` after a timeout does not mean the top-up was / not applied: re-read `GET /stock` before retrying."), wrapped at the paragraph's width.
- **Verification after:** `yaml.safe_load` → 18 operations; operations without `default == {$ref: UnlistedProblem}` → `[]`; last key of every responses map is `default` → True; `components.responses` = `BadRequest, Unauthorized, NotFound, DomainError, TooManyRequests, UpstreamUnavailable, UnlistedProblem`; `grep -c "#/components/responses/UnlistedProblem"` → **18**. `git diff --numstat`: 57 insertions, 4 deletions.
- `cp` to #8 and #7; `cmp` OK both.
- **sha256 after SA-9** (all three): `fbd920c9ec5038ce4c6c2e72ed3d5807cf32118ab4f6b2b8bb409b25361ee5ab`.
- Stack-agnosticism: added lines of both spec files grepped for `nest|drizzle|nuxt|mysql|typescript|dotnet|efcore|mssql|csharp|python|fastapi|sqlalchemy|postgres|angular` → 0 hits (sentinel line containing `nestjs` matched).

## 5. Generated files and drift checks (SA-9 only)

No generator reads `saga.md` (`grep -l saga.md` over #9 `scripts/generate_contracts.py`, #7 `packages/contracts/scripts/*.mts` and `lib/*.mts`, #8 `apps/web/scripts/openapi-types.mjs` → none).

**#7** (`order-to-cash-nestjs`):
- `pnpm --filter @otc/contracts run check` BEFORE → exit 1, `contracts:check FAILED — committed generated files are stale`, last hunk `replenishStock` `+ default: components["responses"]["UnlistedProblem"];`.
- `run generate` → exit 0, `wrote packages/contracts/src/generated/{asyncapi,openapi}.types.ts`. `run check` AFTER → exit 0, `contracts:check OK`.
- Artifact: `openapi.types.ts` 43+/4−; `grep -c 'default: components["responses"]["UnlistedProblem"]'` → 18; old phrase "not applied; the client" → 0; `asyncapi.types.ts` not in `git status`.
- `pnpm --filter @otc/contracts test` → 5 files, 22/22 passed.
- `pnpm --filter @otc/gateway --filter @otc/contracts --filter ./apps/web run typecheck` → exit 0 (all three Done).
- Tests outside contracts that read `openapi.yaml`: `apps/gateway/src/contract-drift.integration.spec.ts` (routes via `test-support/openapi-routes.ts`, not statuses) — unaffected by `default`; `money-field-sweep.ts` cites the file in comments only. **No break found to report.**

**#8** (`order-to-cash-dotnet`):
- `apps/web` `pnpm run types:check` BEFORE → exit 1, `src/generated/openapi.ts is stale … first difference at line 288` (the replenish sentence).
- `pnpm run types:generate` → exit 0. `types:check` AFTER → exit 0, `types:check OK`.
- Artifact: `apps/web/src/generated/openapi.ts` 43+/4−; 18 `default` entries; old phrase 0.
- `pnpm exec tsc --noEmit` in `apps/web` (not `typecheck`, whose `next typegen` writes files) → exit 0.
- `dotnet test tests/Gateway.UnitTests` → `Passed! Failed: 0, Passed: 248, Total: 248` (includes `OpenApiContractTests`: `MappedEndpoints_MatchOpenApiYamlExactly…`, `OpenApiYaml_Declares17PathsAnd18Operations`, `TheDeliberatelyExcludedPaths…`; the spec is embedded, `src/Gateway/Gateway.csproj:64`).
- `grep -rIn '"responses"\|Responses' tests src/Gateway --include=*.cs` → no hits: **no #8 test compares declared statuses. No break found to report.**
- Working tree after: only `README.md`, `apps/web/src/generated/openapi.ts`, `progress/history.md`, the two spec files (plus ignored `bin/`/`obj/`).

**#9:**
- `uv run pytest packages/contracts -q` BEFORE → exit 1, **3 failed, 215 passed** (`test_generation_drift.py`: `test_the_committed_generated_files_equal_a_fresh_generation`, `test_the_drift_check_flags_an_edited_file_and_a_missing_file_by_name`, `test_the_check_command_names_the_drifted_file_and_exits_non_zero`).
- `uv run python scripts/generate_contracts.py` → exit 0, wrote `asyncapi.py`, `openapi.py`, `nullable.py`. `git diff`: exactly two lines, the `# Source: specs/shared/openapi.yaml sha256-prefix16=` header of `openapi.py` and `nullable.py`, `e73efb8abe4fc5d1` → `fbd920c9ec5038ce`; `asyncapi.py` unchanged.
- `--check` → exit 0, `contracts drift check: 3 generated files match a fresh generation`.
- `uv run pytest packages/contracts -q` AFTER → **218 passed**.
- **For the leader (expected, the proposal's code half, not fixed):** `uv run pytest services/gateway/tests/unit/test_openapi_conformance.py services/gateway/tests/unit/test_gateway_status_population.py -q -p no:cacheprovider` → **2 failed, 16 passed**: `test_the_generated_document_matches_the_committed_openapi_yaml_in_both_directions` (18 items, first `"GET /auth/me: statuses ['200', '401'] != ['200', '401', 'default']"`) and `test_the_status_population_against_openapi` (`ValueError: invalid literal for int() with base 10: 'default'`). Both are backlog 215's #9 code half. `quality.sh` will fail on them until it lands.

## 6. Records

**README registries.**
- #9 `README.md`: `:29` intro "`SA-6` was raised here:" → "`SA-6` – `SA-9` were raised here:"; rows `SA-7`, `SA-8`, `SA-9` added after `SA-6` (Raised "#9, Phase 13"; one line each, per the brief; the `SA-9` count reworded to "59 of the 100 statuses #9's Gateway can answer were undeclared; the gap is the contract's, shared by all three builds", because 59 is #9's count — #7 and #8 answer 45 of those pairs, per `proposal_sa9.md`); `:43` "Any further amendment raised here will be `SA-7` onwards" → states SA-7 – SA-9 applied 2026-10-12 and "`SA-10` onwards".
- #8 `README.md`: rows `SA-7`, `SA-8`, `SA-9` after `SA-6`, in #8's longer "What was wrong" style; back-port status paragraph extended with the three amendments, both after-hashes, and "They change no #7 or #8 code: both orchestrators predate `SA-8`'s release of a late stock reservation."
- #7 `README.md`: no registry (`grep -niE "SA-6|amendment"` → 0 hits); none created, as for `SA-6`.
- Enumeration, `grep -niE "SA-6|SA-[0-9]+ onwards|\b(five|six|seven|eight|nine) (amendments|raised)|amendment" README.md`, every hit classified: #9 `:27` heading, unchanged; `:29` updated; `:38` SA-6 row, unchanged; `:43` updated; `:175`, `:184`, `:205` projector narrative / phase row naming SA-6 as the causationId amendment (not as the last), unchanged. #8 `:33`, `:37` generic amendment prose (no count), unchanged; `:46` SA-6 row, unchanged; `:51` back-port paragraph, updated; `:161` SA-4 narrative; `:244`, `:252`, `:282`, `:286`, `:294` benchmark and phase rows — none counts amendments or names SA-6 as last; unchanged. #7: no hits.

**`progress/history.md`:** three sections appended in order SA-7, SA-8, SA-9 at the end of each file (#9 directly after `gateway_sse_push`, nothing between; #8 after its SA-6 section; #7 after its SA-6 section). Bodies identical across the three repositories; headings "(raised here in Phase 13, applied to #7 and #8 in the same session)" in #9, "(raised in #9 Phase 13, applied here in the same session)" in #8 and #7. 45 lines added in each of #8 and #7 (`git diff --numstat`); #9 1379 → 1424 lines. Each names the ruling, the files, before/after sha256, regeneration and drift results.

**`CLAUDE.md`:** #9 `:9` "next is `SA-7`" → "next is `SA-10`" (1 occurrence). #8 `CLAUDE.md:9` says "spec amendment (`SA-n`)" with no number; #7's has no pointer (`grep -n "SA-n\|SA-[0-9]\|amendment"` → none) — nothing to update.

**`specs/shared/test-matrix.md`:** exempt, unchanged by this session.

**Forward-looking wording to make true at commit:** the history entries and #8's back-port paragraph say each amendment is "committed on its own in each repository" at the wrap-up, SA-7 before SA-8 before SA-9. Committing SA-7 alone requires `progress/sa_snapshots/saga.after_sa7.md` (sha `c8552a31…`) as `saga.md`'s content for that commit, and #8's README / #9's README carry all three rows in one working-tree state (the wrap-up will need to cut them per amendment, as for history).

**Out-of-bounds staleness noted, not edited:** #9 `AGENTS.md:23` (`grep -n "SA-" AGENTS.md`) reads "identical to #7's and #8's through `SA-1`…`SA-6`; `SA-6` was raised here, Phase 12" — now identical through `SA-9`, with `SA-6` – `SA-9` raised here. Outside this brief's bounds; leader-owned. `:43` is generic (no number) and stays true.

## 7. `./init.sh` (#9)

Exit 0. Section 5d:

```
[OK]    shared spec byte-identical to ../order-to-cash-dotnet across 6 file(s); test-matrix.md exempt (per-assessment Status column)
[OK]    shared spec byte-identical to ../order-to-cash-nestjs across 6 file(s); test-matrix.md exempt (per-assessment Status column)
```

No `[FAIL]`. Warnings: 185 uncommitted changes; `quality.sh` reminders (workspace, `apps/web`).

## 8. Files written

- #9: `specs/shared/saga.md`, `specs/shared/openapi.yaml`, `packages/contracts/src/otc_contracts/generated/openapi.py`, `.../generated/nullable.py`, `README.md`, `CLAUDE.md` (one pointer), `progress/history.md`, `progress/sa_snapshots/saga.after_sa7.md`, `progress/sa7_sa8_sa9_application.md`.
- #8: `specs/shared/saga.md`, `specs/shared/openapi.yaml`, `apps/web/src/generated/openapi.ts`, `README.md`, `progress/history.md` (plus ignored `bin/`/`obj/` from `dotnet test`).
- #7: `specs/shared/saga.md`, `specs/shared/openapi.yaml`, `packages/contracts/src/generated/openapi.types.ts`, `progress/history.md`.
