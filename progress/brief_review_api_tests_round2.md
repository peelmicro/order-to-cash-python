# Brief — reviewer, feature 31 `api_tests`, re-review (scoped to D1–D6)

**Task:** approve or reject feature 31 (`in_review`) on the six defects of `progress/review_api_tests.md` § Defects, and that file's § "What must change before re-review" (six items). The first review's other verdicts stand; do not re-open them unless a round-2 change breaks one. The implementer's changes are recorded in `progress/impl_api_tests.md` § "Round 2" (line 569 on). Read `CLAUDE.md` on disk for the arming protocol.

**Model choice:** the leader launched this re-review with Sonnet, not Opus. Every round-2 change is test or record only (`tests/api/**` and `progress/impl_api_tests.md`), as the first reviewer recommended.

## Verified by the leader this session

- Files modified after the first review (`find -newer progress/review_api_tests.md`, caches excluded): `tests/api/{api_support,test_black_box_api,test_api_instruments,test_money_representation}.py`, `progress/impl_api_tests.md`, plus the leader's `feature_list.json`, `progress/current.md` and this brief. No file under `services/`, `packages/`, `specs/` or `tests/observability/` changed.
- The implementer's `./quality.sh` log: `.arm/n31r2/quality.log`, "all gates passed", 5 288 passed in 1 625.85 s. No source file is newer than it, so do not re-run the whole gate.

## Check

1. **D1:** re-run arm I9 (the pacing sleep deleted at `api_support.py`'s `poll`) and arm I10 (the bound widened) yourself. Each must fail within seconds with a message naming the claim. Also check the test is still green and still bounded.
2. **D2:**
   - Re-run the unfiltered #8 backlog enumeration yourself. The implementer's script is at `.arm/n31r2/backlog_enum.py`; read it before running it.
   - Compare your hit list with the record's, and confirm every hit is classified.
   - Spot-check #8 ids 57 and 60 against `../order-to-cash-dotnet/feature_list.json`.
3. **D3:** re-run R48-SUBST (the outbox filter reads `control_invoice["invoiceReference"]`). It must fail, with a message naming the outbox. Then a second substitution of your own choosing: for example the payment reference of the control payment.
4. **D4:**
   - Re-run R1-HC-T1: `wire_response` reports `headerComplete: false` and drops `currency` on every order detail. The main sweep must fail.
   - The implementer says this arm tripped its new "the completed order has no header" assertion first, so the `DETAIL_MINIMUM` check was never seen to fail on its own. Arm it alone: for example, a mutation that keeps the header and drops the detail's money fields, or the minimum check deleted. Report whether it fails.
5. **D5:** the fleet-test count, via `pytest --collect-only`.
6. **D6:** the effort record is present, with sessions and wall-clock, including the run that was cut at I9.
7. Run `tests/api/` once with the developer infrastructure down. Only `otcpy-n8n` and another project's `kb-poc-*` containers are up, and the machine is loaded by an `ollama` `llama-server`: leave it running.

## Output and bounds

Read-only, apart from `.arm/r31r2/` (temporary arms, restored by `cp` + `cmp`, with a `sha256` recorded) and your outputs.

- Every run goes under `setsid --wait` with a timeout that kills the process group.
- Write `progress/review_api_tests_round2.md`:
  - the verdict, and each Dn as closed or open, with evidence;
  - your arms, verbatim;
  - any new finding, each with a disposition;
  - the effort (start and end).
- Set feature 31 to `done` (approved) or `in_progress` (rejected), on that line only.
- No git command that writes the index or the working tree.

Return only "result in `progress/review_api_tests_round2.md`" plus a one-line verdict.
