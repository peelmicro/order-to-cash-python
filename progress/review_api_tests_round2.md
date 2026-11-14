# Review round 2: feature 31 `api_tests` (scoped to D1 to D6)

**Verdict: APPROVED.** All six defects are closed with evidence from my own runs. No new finding. Reviewer: Sonnet, 2026-10-18, start 19:54, end 20:05 CEST (one session, about 11 min). Brief: `progress/brief_review_api_tests_round2.md`.

## Method

I did not re-run `./quality.sh` (the brief's claim: `.arm/n31r2/quality.log`, all gates passed, 5 288 passed; `git status` shows no change under `services/`, `packages/` or `specs/` beyond entry 217's `test_gateway_degraded.py` and the matrix, and my arm restores were `cp` + `cmp`). I ran `tests/api` once with the developer infrastructure down (`docker ps`: only `kb-poc-*` and `otcpy-n8n`): `54 passed in 99.46s`, exit 0 (`.arm/r31r2/api_full.log`). Arms: `.arm/r31r2/arm.py` (backup with `sha256`, one mutation, one named test under `setsid --wait timeout -k 15`, restore by `cp`, `cmp`, `__pycache__` cleared). Logs: `.arm/r31r2/*.log`.

## Defects

- **D1 closed.** `test_poll_waits_between_probes_and_gives_up_naming_what` now yields in `never()` and wraps `poll` in an outer `asyncio.timeout(5)` that fails by name.
  - I9 (pacing sleep replaced by `pass`): `AssertionError: 63230 probes in 0.55 s: the loop is not paced at 0.1 s` / `assert 63230 <= 7`; `1 failed in 0.79s`.
  - I10 (`asyncio.timeout(seconds)` to `asyncio.timeout(1000)`): `Failed: poll(seconds=0.55) did not end at its own bound within 5 s (50 probes): the bound is not the asyncio.timeout the claim names`; `1 failed in 5.35s`.
  - Restored (`cmp` 0, `sha256` 2e51c649...), green `1 passed in 0.61s`.
- **D2 closed.** I ran `python3 -I .arm/n31r2/backlog_enum.py` (read first: no id filter, whole-entry regex) over the 110 entries of #8's `feature_list.json`. My hit list: 5, 8, 12, 14, 16, 17, 22, 23, 24, 27, 29, 31, 38, 52, 54, 57, 60, 71, 72, 73, 105, 111 = 22 entries, identical to the record's section 7 table (the group row 5 to 29 covers 11 ids, then 31, 38, 52, 54, 57, 60, 71, 72, 73, 105, 111). Every hit has a classification with a reason. #8 id 57 (credit.released causation must be payment.received's eventId; my first-round arm R24-ID57 fails on the floor) and id 60 (distinct fixture values) are checked against `../order-to-cash-dotnet/feature_list.json` and are what the record says; both are named AVOIDED in sections 7 and 8.
- **D3 closed.** R48's outbox clause asserts `paymentReference == payment_reference` and the invoice reference equals the invoice's and differs from the control's.
  - R48-SUBST (filter reads `control_invoice["invoiceReference"]`): `AssertionError: Billing's outbox row is not this payment's: {... 'invoiceReference': 'INV-000006', 'paymentReference': 'PAY-CONTROL-f502c440d31e' ...}` / `assert 'PAY-CONTROL-f502c440d31e' == 'PAY-IDEMP-6c50b57063be'`. It names the outbox row.
  - My own substitution R48-SUBST2 (expected payment reference replaced by the control's): fails with the same outbox message.
  - R48-SUBST3 (payments filtered by the control's invoice id): fails `exactly one payment row` / `assert ['PAY-CONTROL-6345f81eb05b'] == ['PAY-IDEMP-a9c9b48a4842']`.
  - Restored (`cmp` 0), green `1 passed in 36.84s`.
- **D4 closed.** The main sweep now requires the completed order's detail to have `headerComplete` not false and to meet `DETAIL_MINIMUM` unconditionally.
  - R1-HC-T1 (`wire_response` post-processes order details: `headerComplete=false`, currency and totals dropped; my own implementation of the mutation): `AssertionError: the completed order has no header` / `assert False is not False`.
  - The minimum alone (R1-DETAIL-ALONE, header left true, currency and totals dropped): `AssertionError: GET /orders/{id} 200 (the completed order): the sweep found 0 monetary field(s), fewer than the 6 that a response of this kind always carries - the sweep would be vacuous`. The `DETAIL_MINIMUM` check fails on its own, which the implementer had not shown.
  - Restored `wire.py` (`cmp` 0, `sha256` af99c368...), green `1 passed in 34.72s`.
  - A first attempt of mine had an indentation error in the mutation (the test never ran); I discarded it and redid it. The numbers above are from the valid runs.
- **D5 closed.** `pytest tests/api --collect-only -q --no-cov`: `54 tests collected`. Of the 11 tests in the three fleet-capable files, 10 take the `api` fixture (the literal-set test does not). Record section 0 says 10.
- **D6 closed.** `progress/impl_api_tests.md` "Round 2" carries the effort table: sessions, brief and baseline times, the run cut at I9 (about 08:59), resume, final log, the review, round 2 (about 19:10 to 19:55, 45 min).

## Other checks

- Not re-opened: first-review verdicts. No round-2 change touches them (test and record files only).
- CHECKPOINTS: C4 [x] now (D1, D3, D4 messages verified); C5 [x] effort record present, Claude did not commit; C7 [x] inherited #8 findings accounted for (D2). C1 to C3, C6 as in the first review.
- Routing: no gap rooted in `specs/shared/`; no `SA-n` or backlog entry owed.

## Residual observations (no action)

- The implementer's disclosure about the final `quality.sh` (entry 217's Mongo test flake) is superseded: round 2's `quality.sh` log reports all gates passed.

Effort (this review): start 19:54, end 20:05 CEST, one session.
