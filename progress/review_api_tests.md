# Review: feature 31 `api_tests` (phase 18, full group)

**Verdict: REJECTED.** One bounded round of test-only fixes (D1 to D6 below). Everything else listed here was verified and does not need re-review.

Reviewer: Opus, 2026-10-18, start 18:37, end 19:16 CEST (39 min, one session). Brief: `progress/brief_review_api_tests.md`. Implementer record: `progress/impl_api_tests.md`.

## What I ran, and what I did not

- `tests/api` once, with the developer infrastructure down (`docker ps`: only `otcpy-n8n` and `kb-poc-*`, and `kb-poc-postgres` holds 5432 and `kb-poc-proxy` holds 8080). Result: `54 passed in 91.52s` (`.arm/r31/api_full.log`). Load average was about 9.6 throughout.
- I did **not** re-run `./quality.sh`. I relied on `.arm/n218/quality.log` (18:32:34, `5288 passed in 1452.18s`, web `687 passed`, `quality.sh: all gates passed`, lines 822, 1389, 1432). `find tests services packages specs conftest.py -newer .arm/n218/quality.log -type f -not -path '*__pycache__*'` printed nothing. My arm restores used `shutil.copy2`, which keeps mtimes, and each restore was checked with `cmp`. `git status --short services packages apps` shows only entry 217's `test_gateway_degraded.py`. `grep -rn "REVIEWER ARM" services tests packages` printed nothing.
- `tests/architecture/test_no_reload_servers.py`: `19 passed`. `./init.sh`: exit 0.
- 13 arms of my own (below), each one named test, run under `setsid --wait timeout -k 15 <T>`. Backups are in `.arm/r31/backups/` with their `sha256`. Each restore was a `cp` checked by `cmp`, then `__pycache__` was cleared and the test re-run green. Runner: `.arm/r31/arm.py`, specs `.arm/r31/*.json`, log `.arm/r31/arms.log` (filtered copy: `arms_clean.log`).

## Counts re-derived

| Claim | Command | Result |
|---|---|---|
| tests added: 54 | `pytest tests/api --collect-only -q` per file | 43 + 7 + 3 + 1 = 54. **Fleet tests: 10, not 11** (7 black-box + 2 money + 1 R61; `test_r1_the_money_bearing_responses...` is fleet-free). See D5 |
| 18 operations, 79 cells | `yaml.safe_load(openapi.yaml)`, get/post only (no put/patch/delete in the contract; the 3 non-method keys are `parameters`) | 18, 79 |
| 6 + 26 + 47 = 79 | `ast` over the three literals | 6, 26, 47, no duplicates |
| Billing's tables = 9 | `grep -A1 "op.create_table(" services/billing/` | 8 created tables + `alembic_version` = 9 = `BILLING_TABLES`; no `schema=` anywhere in Billing's `src` |
| matrix: 62 green / 0 scoped / 1 not yet | script over the 63 `**R<n>**` rows of the working tree and of `git show HEAD:` | 60 `DONE`, plus R24 ("integration half DONE; API half DONE"), plus R29 (all three cases DONE) = 62; R28 (e2e TODO) = 1; 0 SCOPED. HEAD had 56 DONE + R24/R28/R29 + 3 NOT YET + 1 SCOPED = 57/1/5. Only R1, R24, R48, R49 and R61 changed, and their columns 1 to 4 are byte-equal to HEAD. The per-feature summary rows reconcile (feature 3: 10/0/1, R28) |
| #8 backlog regex hits | the implementer's regex over `../order-to-cash-dotnet/feature_list.json`, **without** the id filter | ids 5, 8, 12, 14, 16, 17, 22, 23, 24, 27, 29, 31, 38, 52, 54, 57, 60, 71, 72, 73, 105, 111. The record classified only 31, 72, 105 and 111. See D2 |

## Defects

**D1. Blocking. `tests/api/test_api_instruments.py:255-275` (`test_poll_waits_between_probes_and_gives_up_naming_what`) has no bounded, message-bearing failure for the two properties it guards.**
- The probe `never()` (`:261-263`) never awaits anything. With the pacing sleep deleted (`api_support.py:257`), the loop never yields, so `asyncio.timeout` cannot fire and the test hangs. I re-ran I9 myself: `ARMED exit 124`, the 40 s process-group kill, with no output. With the bound widened (I10), the test waits out the widened bound.
- `pyproject.toml` has no pytest timeout (`grep -n timeout pyproject.toml`: nothing in `[tool.pytest.ini_options]`). In `quality.sh` a pacing or bound regression therefore hangs the gate indefinitely instead of failing.
- `CLAUDE.md`'s arming protocol requires the failure's "message must name the claim", and pacing must be proven by a change of kind. A hang is neither. The implementer disclosed this (record section 10), and the brief's question 3 asked for exactly this.
- **Fix:** make the probe yield (`await asyncio.sleep(0)` inside `never`), so a deleted sleep becomes thousands of calls and the existing `4 <= len(calls) <= 7` assertion fires with its message. Wrap the `poll` call in an outer `asyncio.timeout` (a few seconds), so a widened or deleted bound fails as a named `TimeoutError`, not the `"never happened within 0.55 s"` match. Then re-run I9 and I10 and record verbatim messages, not exit 124.

**D2. Blocking (record; C7 "every inherited #8 finding is accounted for"). `progress/impl_api_tests.md` section 7 filtered the #8 backlog population by id ("ids >= 100 plus ids 31 and 72").**
- #8's backlog entries start at id 39 (`final_checkpoint` is 38, `orders_catalog_responder` is 40), so ids 39 to 99 were never classified. Without the filter, the same regex also hits **38, 52, 54, 57, 60, 71, 73**, plus the #8 feature rows 5 to 29.
- Two of these bear directly on this feature:
  - **#8 id 57** `completion_pair_has_no_causal_edge`: `credit.released.v1`'s `causationId` must be `payment.received.v1`'s `eventId`. This is the happy path's third edge. #9 does guard it: my arm R24-ID57 below fails on the floor naming the missing pair. But the record does not name it avoided.
  - **#8 id 60** `envelope_fixture_collisions_defeat_provenance_assertions`: distinct envelope values in fixtures. This applies to the fleet-free causal-order fixtures. `A`, `B` and `C` are distinct, but the record does not say so.
- `CLAUDE.md`: "Never filter the population by the property under test; make the expected set a literal and derive the rest by subtraction."
- **Fix:** re-run the command without the id filter, print the full hit list, and classify every hit (applies to 31: avoided or recurred / owned by another #9 feature, named / n/a). The #8 feature rows (5 to 29) may be classified as one group with a reason.

**D3. Blocking. `tests/api/test_black_box_api.py:215-223` (R48's outbox clause) is satisfied by the sibling invoice.**
- My arm R48-SUBST substitutes `control_invoice["invoiceReference"]` for `invoice["invoiceReference"]` in the outbox filter. The test **passes** (`ARMED exit 0`): the control order was also paid exactly once, so "exactly one `payment.received.v1` in Billing's outbox" holds for the wrong invoice too.
- The topic clause (`:228-229`) does name the `paymentReference`, so a production misattribution is still caught there. But the outbox clause, one of R48's three counted pieces of evidence, is not armed against `CLAUDE.md`'s mutation family 3 ("a substitution's failure must name the intended break"). It is also a fixture that satisfies the relation by accident (count = 1 for both).
- The implementer's defeat list (section 11) says row 3 "does not apply". It does: invoices and orders are a sibling-identifier family.
- **Fix:** assert the outbox row's payload `paymentReference == payment_reference` (and `orderReference`), or give the control a count other than one. Then re-run R48-SUBST and see it fail with a message naming the outbox.

**D4. Required in this round (mitigated, so not a coverage hole for R1). `tests/api/test_money_representation.py:325-331` (`minimum_for`) lets the system under test switch off its own vacuity check.**
- The exemption keys on the response's own `headerComplete: false`. My arm R1-HC-T1 has `wire_response` report `headerComplete: false` and drop `currency` on every order detail. `test_r1_every_monetary_field_of_every_gateway_response...` then **passes** (`ARMED exit 0`).
- The R1 row still holds, because the injection test's control fails on the same mutation (R1-HC-T2: `real GET /orders/{id}: the sweep found 0 monetary field(s), fewer than the 6`), and that test is named in R1's row.
- The main sweep's population claim ("every money-bearing cell driven", `:374-378`) still checks only that the key is present in `money_seen`, not that a count above zero was seen. That is the brief's question 4a answered in the affirmative for that test.
- **Fix:** keep the R50 exemption for poll-time documents, but require the completed order's detail (which the test already locates, `:305-309`) to meet `DETAIL_MINIMUM` unconditionally, or assert `money_seen[cell] >= minimum` per cell. Then re-run R1-HC-T1 red.

**D5. Required (record). The record says "11 fleet tests: 1 + 1 + 1 + 3 + 1 + 2 + 1".** That sum is 10, and collection agrees (above). `CLAUDE.md`: "a number that does not reconcile with the last run is a finding."

**D6. Required (closing prerequisite). `progress/impl_api_tests.md` carries no effort record** (sessions, wall-clock start and end, including the cut first run at I9). The feature cannot be closed into `progress/history.md` without it. Add it in the fix round so the closing reviewer can copy it.

## Verified (no change needed)

1. **R61 fixture deviation (question 1).**
   - The open reservation is real and goes through the saga's code path. The test uses `fulfillment.stock.reserve`, the Orders saga's subject (`services/orders/src/otc_orders/infrastructure/messaging/saga_subjects.py:10`). `services/fulfillment/src/otc_fulfillment/presentation/stock_responder.py:126` routes it to `_reserve` and then to `ReserveStockCommand`, the handler an order's reservation uses. The body matches `StockReserveRequestPayload`.
   - "Advances no order" is not vacuous. A real order (`invoiced`, its reservation `consumed`) is in the fixture, and the claim is the full equality of every table of the Orders database, the topic counts and the API's own view. A15-ORD (forged) and A13' (production fact) both turned it red.
   - The reservation claim is no longer guarded only by forgery. My production arm **R61-TOUCH** (`lock_for_replenish` also `UPDATE reservations SET updated_at = now()` for the locked stock rows) fails with `R61: fulfillment.reservations changed`. This is a corrupt-a-non-semantic-column family, and it also shows the comparison reads every column.
2. **R48 forged evidence (question 2).**
   - A3e-PAY/OUT/TOP show that each count reads its table, outbox and topic.
   - The control order makes the payments table hold two new rows (`:232`), so the payment row is invoice-scoped (substitution would fail at `:214`, since the reference differs).
   - The outbox clause is D3.
3. **R24 / #8 id 105 (question 5).**
   - The required edges are the `(cause, effect)` type pairs among the envelopes read off the three topics (`fact_type_pairs`, `:90-94`). The timeline's pairs must equal them, with a floor of 3.
   - Reversing the projector's causal tiebreak (`timeline_order.py:92`, depth `1` to `-1`; arm R24-A1) fails scenario 1 naming `order.confirmed.v1 (index 2) precedes its cause credit.approved.v1`, and scenario 2 naming `R28: stock.released.v1 must precede order.cancelled.v1`. Both directions were probed.
   - Corrupting the source of the third edge (#8 id 57's defect: `payment_register.py:142` `causation_id=fact.event_id` changed to the request id; arm R24-ID57) fails on the floor, naming the two remaining pairs. So the floor is load-bearing.
4. **R49 (question 6).**
   - "Nothing changed" covers all 9 tables (derived above), compared row by row, plus the topic counts.
   - The three refusals are three distinct checks: `invoice.py:358-360` (Paid), `:365-366` (currency), `:367-370` (amount).
   - The matrix sentence about the third path is proved by A6'.
   - My arm **R49-UNDER** (`!=` changed to `>`, so underpayment is accepted) fails on the `total - 1` iteration with `R49: Billing's database changed`. Both iterations are therefore load-bearing.
5. **R1 (question 4).**
   - The population is derived from the contract, the expected set is a literal, and coverage is by subtraction in both directions.
   - Problem bodies (400, 404, 409, 422), list pages and the timeline (inside the detail) are swept.
   - My production arms of new families all fail naming the claim:
     - **R1-SIB**: the currency moved onto a sibling (`totals`) of `items`. Fails with `fewer than the 6`.
     - **R1-BOOL**: invoice `amount: true`. Fails with `GET /invoices 200: $.items[0].amount: R1 requires an integer count of minor units, got True`.
     - **R1-STR**: credit `availableCredit` as a string. Fails with `GET /credits 200: ... 75 ..., fewer than the 100`.
   - The exemption is D4.
6. **Black box (question 7).** `httpx` over the uvicorn socket is the only driver used by any test in `tests/api` (`grep "fleet.http"` hits only a docstring). The fleet's `AsyncExitStack` owns every lifespan, including the Gateway's (`tests/saga_e2e/conftest.py:307-308`). The `Fleet.gateway` addition is additive (2 lines) and changes no existing driver. The uvicorn task is awaited on teardown.
7. **Architecture guard (question 9).** `+"tests/api/conftest.py": 2` matches `uvicorn.Config` and `uvicorn.Server` at `tests/api/conftest.py:58-59`, with no `reload` or `watch` argument. The total 13 to 15 is correct, and the guard is green.
8. **Matrix (question 8).** Column 5 was recounted by script (above). I read every new sentence in the five rows against the tests, and they hold. The scoped paragraph (line 83) is consistent with R1 = DONE.
9. **Ledger (question 10).** Spot-checked citations:
   - #8 `progress/history.md:3081` (real Kestrel, `HttpClient`);
   - #7 `progress/history.md:1176-1178` (spawned `node dist/main.js`);
   - #8 `GatewayTestHost.cs:62-66` (`--urls http://127.0.0.1:0`);
   - #8 `SagaFactHandler.cs:292` (cancel at `fact.OccurredAt`);
   - #8 `PaymentRegisterService.cs:56` / `:98` (the two reads);
   - #8 `impl_api_tests.md` section 7 (the shared-fleet design change, at about line 306).

   All of these hold. L6's "four layers" claim is consistent with A3a-d. Inherited findings 105, 72, F1, the shared-fleet regression, both of #7's rejections, 104 and 63 are named. 57 and 60 are missing (D2).

## Arms (verbatim, `.arm/r31/arms_clean.log`)

Defeat-list rows exercised:
- 2, corrupt a field: R1-BOOL, R1-STR, R61-TOUCH, R24-ID57, R49-UNDER.
- 3, sibling substitution: R1-SIB (sibling object), R48-SUBST (sibling invoice).
- 7, drop an optional element: R1-HC.
- 12, a path the population never drives: R61-TOUCH, through the replenish lock path that A12 could not reach.
- 1, deletion: POLL-I9.

```
## R1-SIB      (wire_response: OrderDetail's currency moved into its sibling `totals`)
ARMED exit 1
   E       AssertionError: GET /orders/{id} 200: the sweep found 3 monetary field(s), fewer than the 6 that a response of this kind always carries - the sweep would be vacuous
restored services/gateway/src/otc_gateway/presentation/wire.py sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 62.00s (0:01:02)']
## R1-BOOL     (wire_response: every invoice item's `amount` = true)
ARMED exit 1
   E       AssertionError: GET /invoices 200: $.items[0].amount: R1 requires an integer count of minor units, got True
restored ... wire.py sha256 af99c368... cmp exit 0
GREEN exit 0 ['1 passed in 57.59s']
## R1-STR      (wire_response: every credit's `availableCredit` = str(...))
ARMED exit 1
   E       AssertionError: GET /credits 200: the sweep found 75 monetary field(s), fewer than the 100 that a response of this kind always carries - the sweep would be vacuous
restored ... wire.py sha256 af99c368... cmp exit 0
GREEN exit 0 ['1 passed in 57.91s']
## R61-TOUCH   (stock_repository.lock_for_replenish: UPDATE reservations SET updated_at=now() WHERE stock_id IN locked rows)
ARMED exit 1
   E               AssertionError: R61: fulfillment.reservations changed
   E                 At index 2 diff: {... 'order_reference': 'ORD-000007', 'units': 3, 'status': 'consumed', ... 'updated_at': ...16, 53, 26, 841000 ...} != {...
restored services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py sha256 1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9 cmp exit 0
GREEN exit 0 ['1 passed in 48.14s']
## R24-A1      (timeline_order.py:92 depth 1 -> -1; scenario 1, -x)
ARMED exit 1
   E           AssertionError: causal order violated: order.confirmed.v1 (index 2) precedes its cause credit.approved.v1 (index 3): ['order.placed.v1', 'stock.reserved.v1', 'order.confirmed.v1', 'credit.approved.v1', 'order.despatched.v1', 'invoice.issued.v1', 'order.completed.v1', 'credit.released.v1', 'payment.received.v1']
restored services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py sha256 ff45b14be9c3f5e00f572b6852322394c6a4f31e3eeaf52e16634c68346275a4 cmp exit 0
GREEN exit 0 ['2 passed in 50.33s']
## R24-A1-S2   (same mutation; scenario 2)
ARMED exit 1
   E       AssertionError: R28: stock.released.v1 must precede order.cancelled.v1: ['order.placed.v1', 'stock.reserved.v1', 'credit.rejected.v1', 'order.cancelled.v1', 'stock.released.v1']
restored ... timeline_order.py sha256 ff45b14b... cmp exit 0
GREEN exit 0 ['1 passed in 32.29s']
## R24-ID57    (payment_register.py:142 credit.released causation = the request id, #8 id 57's defect)
ARMED exit 1
   E       AssertionError: the brokers' facts carry only 2 causal edge(s): [('credit.approved.v1', 'order.confirmed.v1'), ('credit.released.v1', 'order.completed.v1')]
   E       assert 2 >= 3
restored services/billing/src/otc_billing/application/payment_register.py sha256 e4233978d124a9d3001ca649b527ec0494e4f25c1f584cd373fc65b91241a456 cmp exit 0
GREEN exit 0 ['1 passed in 42.87s']
## R49-UNDER   (invoice.py:367 `!=` -> `>`: an underpayment is accepted)
ARMED exit 1
   E       AssertionError: R49: Billing's database changed
   E         Left contains 4 more items, first extra item: 'credit_items: 17 row(s) before, 18 after'
restored services/billing/src/otc_billing/domain/invoice.py sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 33.26s']
## R48-SUBST   (test: the outbox filter reads control_invoice's reference)          -> D3
ARMED exit 0
   1 passed in 34.06s
restored tests/api/test_black_box_api.py sha256 7cd123f586aedbb4fcd18bb6fb4a4f6abf2b962636143e937a3fae2c6b56d1a9 cmp exit 0
GREEN exit 0 ['1 passed in 33.87s']
## POLL-I9     (api_support.poll: pacing sleep deleted; 40 s process-group kill)    -> D1
ARMED exit 124
restored tests/api/api_support.py sha256 2e51c64957e0f8d6408f1bbb4985abc5ccf5999cab7e741bfd3d2d45091d3ee9 cmp exit 0
GREEN exit 0 ['1 passed in 0.62s']
## R1-HC-T1    (wire_response: OrderDetail reports headerComplete:false and drops currency; main sweep)  -> D4
ARMED exit 0
   1 passed in 36.88s
restored ... wire.py sha256 af99c368... cmp exit 0
GREEN exit 0 ['1 passed in 31.74s']
## R1-HC-T2    (same mutation; injection test)
ARMED exit 1
   E       AssertionError: real GET /orders/{id}: the sweep found 0 monetary field(s), fewer than the 6 that a response of this kind always carries - the sweep would be vacuous
restored ... wire.py sha256 af99c368... cmp exit 0
GREEN exit 0 ['1 passed in 30.86s']
```

Staleness note: `tests/api/api_support.py`'s current sha256 is `2e51c649...`, while the implementer's I1 to I10 backups are `c95d0829...`. `diff .arm/n31/backups/tests__api__api_support.py tests/api/api_support.py` shows only the wording of the minimum's message (lines 138-139). I8's `match` still holds, so those arms are not stale in substance.

## R<n> to test mapping (verified)

| R | Test(s) | Exercises it? |
|---|---|---|
| R1 (API) | `test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code`, `::test_r1_the_money_bearing_responses_of_the_contract_are_exactly_the_literal_set_and_every_other_cell_is_accounted_for`, `::test_r1_a_wrong_shape_currency_or_a_non_integer_amount_injected_into_a_real_response_fails_naming_the_field_path`, `test_api_instruments.py::test_r1_*` (27 cases) | yes (D4 weakens the first test alone) |
| R24 (API) | `test_black_box_api.py::test_scenario_1_...`, `::test_scenario_2_...`, `test_api_instruments.py::test_r24_*` (7) | yes |
| R48 (API) | `test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact` | yes (D3: the outbox clause) |
| R49 (API) | `test_black_box_api.py::test_r49_a_mismatched_amount_...`, `::test_r49_a_mismatched_currency_...`, `::test_r49_a_different_reference_against_a_paid_invoice_...` | yes |
| R61 (API) | `test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact` | yes |

Acceptance items: 1 (happy + compensation) yes; 2 (duplicate `paymentReference`) yes, apart from D3; 3 (inventory) yes, record section 2 with every row mapped; 4 (id 105) yes; 5 (R49) yes; 6 (R1) yes, apart from D4; 7 (R61) yes.

## CHECKPOINTS.md

- C1: [x] harness files exist; [x] `./init.sh` exits 0. Agent model declarations not re-walked: no change in this feature.
- C2: [x] at most one feature `in_progress` or `in_review` (31 only); [x] every status valid; [x] `progress/current.md` describes this session.
- C3: [x] no production file changed (`git status`); [x] `lint-imports` green in `.arm/n218/quality.log` (not re-run: no source change since); [x] no cross-service access: the tests read each service's database as evidence only, through its own DSN; [x] the Kafka/NATS classification holds (the R61 fixture's NATS reserve is an RPC on the saga's own subject).
- C4: [x] `quality.sh` passes (log above, not re-run); [x] integration tests use testcontainers and pass with the developer infrastructure down (my run); [x] no Jest. [ ] **"Verification is real" not met for D1 (a hang, not a message), D3 or D4.**
- C5: [ ] effort record missing (D6); [x] Claude did not commit.
- C6: n/a (`sdd: false`); [x] every R (R1, R24, R48, R49, R61) is named in `test-matrix.md`.
- C7: [x] `test-matrix.md` columns 1 to 4 unchanged (five rows checked against HEAD); [x] the black-box script proves #7's and #8's steps (inventory, section 2); [ ] **every inherited #8 finding accounted for: D2**.

## Routing

No gap here is rooted in `specs/shared/`, so no `SA-n` or backlog entry is owed. All of D1 to D6 are fixed in this phase, on this feature.

## What must change before re-review

1. D1: `test_poll_waits_between_probes_and_gives_up_naming_what` fails with a message, within a bound, for both the deleted sleep and the widened bound. Re-run I9 and I10 and record verbatim.
2. D2: the full, unfiltered #8 backlog hit list, each hit classified, with 57 and 60 named as avoided or recurred.
3. D3: R48's outbox clause names the payment. Re-run R48-SUBST red.
4. D4: the main R1 sweep cannot be switched off by `headerComplete: false`. Re-run R1-HC-T1 red.
5. D5: the fleet-test count corrected.
6. D6: the implementer's effort record (sessions, wall-clock) added to `progress/impl_api_tests.md`.

All six are test or record changes. The re-review can be scoped to these six items and their arms (light; no production path changes). Feature 31 is set back to `in_progress`.
