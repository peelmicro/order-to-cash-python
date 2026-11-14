# impl: api_tests (feature 31, phase 18)

Status: implemented; feature 31 set to `in_review`. Full group (wire contract, Billing's database). No production file is changed (every `services/**` edit was a temporary arming edit, restored by `cp` and checked with `cmp`; the `sha256` of each backup is in the arming table).

## 0. What was built

| File | Role |
|---|---|
| `tests/api/conftest.py` (new) | Loads `tests/saga_e2e/conftest.py`'s `fleet` fixture BY PATH and re-exports it (one definition of the fleet, not a copy); the `api` fixture serves the fleet's Gateway app on a real uvicorn socket (port 0, socket held by the fixture, `lifespan="off"` because the fleet's lifespan already ran, no reload) and logs in with `httpx` over TCP. |
| `tests/api/api_support.py` (new) | The instruments: `parse_json` (floats stay `DecimalToken`), `sweep_for_money_fields`, `money_problems`, `check_money_findings`, `find_decimal_numbers`, `timeline_edges`, `assert_causal_order`, `fact_edges`, `dump_database`/`diff_tables`, `poll`, and `BlackBox` (every response is recorded and R1-checked AT RECEIPT). |
| `tests/api/test_black_box_api.py` (new) | Scenarios 1-4, R48, R49 x3 (acceptance 1, 2, 3, 4, 5). |
| `tests/api/test_money_representation.py` (new) | R1 population, sweep and real-response arms (acceptance 6). |
| `tests/api/test_stock_replenishment.py` (new) | R61 (acceptance 7). |
| `tests/api/test_api_instruments.py` (new) | Fleet-free arms of the instruments (43 cases). |
| `tests/saga_e2e/conftest.py` | +2 lines: `Fleet.gateway` (the Gateway ASGI app) so `api` can serve it. No existing test drives anything differently. |
| `tests/architecture/test_no_reload_servers.py` | `EXPECTED_POPULATION` +`"tests/api/conftest.py": 2` and the total 13 -> 15, on purpose (the guard found my two uvicorn call sites in the first `quality.sh` run). |
| `specs/shared/test-matrix.md` | Column 5 of R1, R24, R48, R49, R61, the summary rows, the scoped-rows paragraph. |
| `feature_list.json` | id 31 status line only. |

Tests added: 54 in `tests/api` (10 fleet tests, re-derived in round 2 (D5): 7 black-box + 2 money + 1 R61; 44 fleet-free, of which 43 instrument tests; see section 2). Each fleet test boots its own fleet (about 15 s).

## 1. Answers to the brief's questions

**Fleet fixture: reuse or another?** Reuse, without copying: `tests/saga_e2e/conftest.py:222` (`fleet`, function-scoped) is imported by path in `tests/api/conftest.py` (the same `spec_from_file_location` idiom `conftest.py:55-63` uses for `dead_letter_support`), because importlib mode makes test directories non-packages. The only change to the original is `Fleet.gateway`. Scope: `fleet` is `loop_scope="function"`; every test boots and fully tears down its own fleet before the next starts, so #8's regression (`../order-to-cash-dotnet/progress/impl_api_tests.md:306`, two fleets alive at once, 5 timeouts) cannot happen by construction. Cost: ~15 s per fleet test, 54 tests in about 50 s.

**In-process ASGI or a real socket?** Real socket. `fleet.http` (`conftest.py:312`, `ASGITransport`) never serialises a request or a response: no h11 framing, no header casing, no `Content-Length`, no real `Content-Type` negotiation, and the ASGI call skips the server. #7 spawned real processes (`../order-to-cash-nestjs/progress/history.md:1177`) and #8 ran real Kestrel with `HttpClient` the only client (`../order-to-cash-dotnet/progress/history.md:3081`); both proved the wire. The pattern exists in `services/gateway/tests/conftest.py:236-245` (`_serve`). What a socket adds: the bytes (`DecimalToken` exists because the money claim is about the BYTES `3000.0` vs `3000`), the `idempotent-replay` and `application/problem+json` headers as a client receives them, the app's middleware under a real server. What it does not add (stated, not claimed): the lifespan is the fleet's (`lifespan="off"`), and the processes share one event loop and one interpreter (#7's real processes did not), so a bug that only appears with separate processes (shared global state) would not show.

**R49's read path.** `dump_database` opens its own asyncpg connection to Billing's database and reads, never writes. "Nothing changed" = every row of every table of the `public` schema: the nine in `BILLING_TABLES` (`invoices`, `invoice_items`, `payments`, `credits`, `credit_items` = the credit ledger, `outbox`, `processed_events`, `invoice_number_sequences`, `alembic_version`), asserted EQUAL to the discovered set so a new table fails the guard, compared after `quiesce()` (every outbox row published and two consecutive dumps of the three write models identical) plus the fact count of the three topics. The seed's own rows are in the dump (5 seeded payments), so counts are never compared with zero without a control.

## 2. Inventory of #7's assertions (from `../order-to-cash-dotnet/progress/impl_api_tests.md` section 2, re-checked against `../order-to-cash-nestjs/apps/gateway/src/black-box-api.integration.spec.ts:485-647`)

| #7 assertion | #9 test and what it does |
|---|---|
| S1 `placed.totalAmount === 49_998` | `test_scenario_1_...`: `placed["totalAmount"] == 3000` (own fixture: `unitPrice` override, 2 x 1500) |
| S1 `projectionPending === true`, `status === 'placed'` | same test, same two asserts |
| S1 `invoiced.references.invoiceReference` truthy | same test (and equal to the listed invoice's reference) |
| S1 `invoice.totalAmount === 49_998` | `invoice["totalAmount"] == 3000` |
| S1 payment 201, `outcome === 'accepted'` | same |
| S1 `completed.status === 'completed'` | same, via `GET /orders/{id}` |
| S1 completion triple in `events[]` | same, three `in` asserts, plus the nine-fact set equal to the nine published facts |
| S1 `assertCausalOrder(completed.events)` | `assert_timeline_is_causally_ordered` (section 5) |
| S2 `totalAmount % 100 === 99` | PORTED (#8 did not): `test_scenario_2_...` |
| S2 `cancellationReason === 'credit_rejected'` | ported |
| S2 three indices present; rejected < released, rejected < cancelled | ported (the set of five types is asserted equal, then the indices) |
| S2 released < cancelled (R28's own clause) | ported, message names R28 |
| S2 equal `occurredAt` of released and cancelled | ported, commented as documentation, not the ordering proof (#7 review section 5) |
| S2 `assertCausalOrder(cancelled.events)` | ported (floor 1) |
| S2 reservation rows: length 1, `released` | ported (`[reservation] = rows`, status `released`, Fulfillment's own database) |
| S3 first 201 `accepted`; second 200 `duplicate`; `Idempotent-Replay: true` | `test_scenario_3_r48_...` (also: absent on the first reply; same `paymentReference`, `invoiceReference`, `orderReference` in the replay) |
| S3 `COUNT(*) payments WHERE payment_reference = 1` | strengthened: one row BY INVOICE, one `payment.received.v1` in the outbox, one on the topic; the control order's payment makes the table hold two new rows |
| S4 no token -> 401 | `test_scenario_4_...` (an anonymous client of the same server; also `code == UNAUTHORIZED`) |
| S4 malformed id -> 400, unknown id -> 404 | same test (and `VALIDATION_FAILED`, `NOT_FOUND`) |
| R49 (never a #7 scenario; #8 added three) | `test_r49_*` x 3 |

Not ported: none. (#8 deliberately left S2's `% 100` and S4 to other files; #9 has no other file doing the S4 trio through a real socket, so they are here.)

## 3. R1: population, Python's JSON numbers, arms

**Population.** `money_bearing_cells(openapi.yaml)` walks every response of every operation through `$ref` and finds the ones that reach `MinorUnits` or `Money`: 6 of the contract's 79 (method, path, status) cells (`POST /orders 201`, `GET /orders 200`, `GET /orders/{id} 200`, `GET /invoices 200`, `GET /credits 200`, `GET /catalog/products 200`). The expected set is a literal in `test_money_representation.py`; the test fails on a difference in either direction, and `every cell == MONEY | DRIVEN_WITHOUT_MONEY | NOT_DRIVEN` (6 + 26 + 47 = 79) with the three pairwise disjoint. The served route table (`fleet.gateway.openapi()`, generated from the routes, not from the yaml) must list the same 18 operations. In: every JSON response, including Problem bodies and the lists (each item swept). Out, with the reason beside each literal group: SSE frames (`text/event-stream`, `OrderStreamUpdate` has no `MinorUnits` in the schema; feature 26), `/docs` (HTML), the 401/503/429/`default` cells not driven (same middleware answer or needs a dependency down; their schemas reach no `MinorUnits`). #8 swept 5 endpoints over a fake `IRpcClient` (`MoneyRepresentationHttpTests.cs`); #7 swept stub responders; #9 sweeps the real fleet and EVERY response any test of the suite receives (`BlackBox.call` checks at receipt), so the invoice and order bodies of 54 tests are checked, not only one test's.

**Python's JSON numbers.** `parse_json` = `json.loads(parse_float=DecimalToken)`. `true`: not a number (`_is_json_number` excludes `bool`; without the exclusion `projectionPending: true` beside `currency` in the real `POST /orders` answer would be a money field; arm I2); `{"amount": true, "currency": "EUR"}` IS flagged through the canonical-amount rule and fails the integer check ("got True"). `100.0`, `1e2`, `1E+2`, `-0.0`, `100.00` -> `DecimalToken`, refused and named (arm I5 shows that without the hook they would parse as `float`). An integer beyond `bigint` (`2**63`, `-2**63-1`, `10**30`; Python ints are unbounded) is refused (arm I6); `2**63-1`, `-2**63`, `0` pass. Currency: exactly three capitals, matched with `fullmatch` (`"EUR\n"` passes the textbook `^[A-Z]{3}$` with `re.match`; arm I4); `eur`, `Eur`, `EURO`, `EU`, `""`, `" EUR"`, `"EUR "`, `"€UR"`, `978`, `null`, `true`, `[]`, and a MISSING currency (no finding is produced, so the per-kind minimum is what fails) are refused. `XXX`/`ZZZ`-shaped unknown codes pass the shape (`shared_kernel`'s table lists only the NON-default exponents, so there is no membership table to test against); the fleet test therefore also requires every observed currency to be in the Orders database's own `currencies` table (EUR, GBP and USD are observed). R1 forbids all of the refused forms ("integer count of minor units together with an ISO 4217 alpha-3 code"); it cannot forbid an unknown but well-formed code without the table.

**Disclosed limit (also #7's and #8's).** A string or `true` under a key other than `amount` is not a JSON number, so the shape sweep cannot name it. The per-kind minimum (tight: 3 for `POST /orders`, 3 per list item for orders and invoices, 4 per credit, 1 per product, 3 + 3 per line for an order detail) catches it without a path: injection "unitPrice string" and "unitPrice true" fail with "fewer than".

**Arms required by acceptance 6.** In the suite, on bytes the Gateway sent (`test_r1_a_wrong_shape_currency_or_a_non_integer_amount_injected_into_a_real_response_fails_naming_the_field_path`): currencies `eur`, `EURO`, `EU`, `""`, `"EUR\n"`, `" EUR"`, `null`, `978` and amounts `3000.0`, `3000.50`, `3e3`, `3E+3`, `-0.0`, a value beyond `bigint`, `unitPrice` as a string and as `true`, and the currency dropped, each injected into the real `GET /orders/{id}` text, each failing and naming `$.totals.totalAmount` / `$.items[0].unitPrice` / `fewer than`. In production (arms A7', A8', A9' below): the Gateway's `wire_response` lower-casing the currency, writing `totalAmount` as `3000.0`, dropping the currency. Sentinel: the dropped-currency case (zero findings) fails on the minimum.

## 4. Ported-idiom ledger

| # | #7 relied on | #8 supplied it with | #9 supplies it with | Guard (armed) |
|---|---|---|---|---|
| L1 | Real spawned processes (`../order-to-cash-nestjs/apps/gateway/src/black-box-api.integration.spec.ts:1-13`, history `:1177`) | Real Kestrel, `GatewayTestHost` (`../order-to-cash-dotnet/tests/Gateway.IntegrationTests/GatewayTestHost.cs:62-88`) | uvicorn on a socket the fixture holds, `httpx` over TCP (`tests/api/conftest.py:60-83`) | every request of the suite goes through `BlackBox.call` on that socket; a mutation in the Gateway's `wire_response` (A7'-A9') is seen by the client |
| L2 | A worker-process DB client because the Gateway could not resolve `mysql2` (`no-write-database-client.spec.ts`) | EF Core in the test project (`BlackBoxApiTests.cs`) | asyncpg in the test (`api_support.dump_database`); no layer rule reaches `tests/` | n/a (nothing to hand-build); read-only by construction (`SELECT` only) |
| L3 | `PRD-0001` seeded at 24999 so one unit totals `.99` | per-line `unitPrice` override (`BlackBoxApiTests.cs`) | the same override (`PlaceOrderLine.unitPrice`, `openapi.yaml:1355`) | `test_scenario_2` asserts `totalAmount % 100 == 99` (the fixture claim, which #8 skipped) |
| L4 | Timeline order by `occurredAt` then `statusRank` (D4: inverted the completion triple) | `TimelineOrder.cs` causal-depth tiebreak (`$reduce` fixpoint) | `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py:92` `sortBy {occurredAt, __depth, eventId}` | A1: reversing the depth key fails scenarios 1 and 2 naming the inverted pair |
| L5 | The `occurredAt` tie of released/cancelled kept as documentation | `SagaFactHandler.cs:292` reuses the fact's instant | the same tie is asserted as documentation in `test_scenario_2` | the array-order asserts above it are the proof; A1 |
| L6 | One `paymentReference` -> one payment | two layers (`PaymentRegisterService.cs:56`, `:98`) | FOUR layers found while arming: the fast read (`payment_register.py:171`), the authority read under the lock (`:124`), `Invoice.mark_paid`'s Paid guard (`invoice.py:360`), the credit-not-outstanding refusal (`:145`), and the `payments.payment_reference` UNIQUE constraint | A3a (one layer: green, defence in depth), A3b (both reads), A3c/A3d (layers removed one at a time; the count assertions cannot be reached by a production mutation without surgery on the constraint, so they are armed by forging the evidence they read: A3e x 3) |
| L7 | Python-only: `int / int`, `bool` is an `int`, `json` floats | n/a | `DecimalToken`, the bool exclusion, `fullmatch`, int64 bound | I2, I4, I5, I6 |

Two-party claim (L4, "a tiebreak that orders correctly in one direction"): probed both ways by A1 (depth ascending -> descending flips the triple AND the compensation pair).

## 5. R24 and #8 id 105

The edges the timeline must resolve are derived from the BROKERS: `fact_type_pairs(facts)` = the (cause type, effect type) pairs among the envelopes the three services published for the order (`causationId` naming another published `eventId`), read from the three topics. The timeline's own pairs must EQUAL them, then `assert_causal_order(required_edges=len(expected))` runs the general invariant and its own count check. Happy path: 3 edges (credit.approved -> order.confirmed, payment.received -> credit.released, credit.released -> order.completed), floor 3 asserted so the derivation cannot go vacuous; #8 measured the same 3. The compensation path has 1 edge-floor. Fleet-free meta-guards: no `causationId` at all (id 105's case), two entries swapped (D4's shape), fewer edges than required, a `causationId` naming nothing in the timeline (not an edge), a requirement of zero refused, and `fact_edges` ignoring a command id and a self-cause.

## 6. Guard-port table (#8's and #7's tests for these mechanisms, by content)

| Source test | Disposition |
|---|---|
| #8 `MoneyFieldSweep.cs` walk (effective currency carried down, canonical `amount` key, leaf rule) | ported (`sweep_for_money_fields`) |
| #8 `MoneyFieldSweepCanonicalAmountTests.ACanonicalMoneyAmountThatHasRegressedToADecimalStringIsStillDiscovered` | ported (`test_r1_a_canonical_money_amount_that_regressed_to_a_decimal_string_is_still_discovered`) |
| #8 `MoneyRepresentationHttpTests` (5 endpoints over a fake RPC client; `findings.Count > 0` vacuity assert) | ported and widened (real fleet, every response, per-kind tight minimum) |
| #7 `money-field-sweep.ts` name-based exception for `Money.amount` | ported (canonical rule) |
| #8 `AssertCausalOrder`, `..._FailsNamingTheViolation`, `..._FailsNamingNoEdgesChecked` (id 105) | ported (5 fleet-free cases) |
| #8 `minimumEdgesChecked: 3` measured by setting 1000 | replaced: the minimum is derived from the topics (section 5) |
| #8 R49 x 3, `ReadBillingCountsAsync` (counts of 3 tables) | ported and widened to every row of 9 tables + topic counts |
| #8 `FulfillmentStockEndToEndTests` (units 10 -> 35 only) | widened: R61 section; #8 did not assert reservations, facts or orders |
| #8 `WaitUntilReachableAsync` pacing + `GatewayReadinessPacingRaceTests` (ids 63, 69) | ported for `poll` (`test_poll_waits_between_probes_and_gives_up_naming_what`; arms I9, I10) |
| #7 `statusRank` fix and the "never weaken an assertion" rejection | the R28 assertion is kept whole (released < cancelled) and armed by A1 |

## 7. #8 backlog classification (redone in round 2, D2: NO id filter)

Command (`python3 -I .arm/n31r2/backlog_enum.py`, 110 features of `../order-to-cash-dotnet/feature_list.json`, regex `black.?box|MoneyFieldSweep|money.?field|AssertCausalOrder|causal.?order|causationId|paymentReference|idempoten|PAYMENT_MISMATCH|INVOICE_ALREADY_PAID|api_tests|R49|R48|R24|R61` over each entry's whole JSON). Full hit list, 22 entries, one classification each:

| #8 id | name | matched | classification for 31 |
|---|---|---|---|
| 5, 8, 12, 14, 16, 17, 22, 23, 24, 27, 29 | feature rows (messaging_topology ... web_app) | `idempoten`, `causationId`, `paymentReference`, `money field`, `R48` in their acceptance prose | one group: #8's feature rows, each owned by a #9 feature that is already done or by its own spec; they describe the production mechanism, not an API test. n/a to 31 |
| 31 | api_tests | itself | the feature |
| 38 | final_checkpoint | `R48` (names the traced requirement) | n/a: owned by #9's final checkpoint (feature 36 or later), not 31 |
| 52 | retroactive_ported_idiom_ledger_decode_boundaries | `idempoten` | n/a: decode boundaries of the services, a #9 service-phase ledger |
| 54 | fulfillment_ledger_row_for_unhinted_in_transaction_reread | `idempoten` | n/a: Fulfillment's ledger; 31 only reads Fulfillment's tables as evidence |
| 57 | completion_pair_has_no_causal_edge | `R49`, `causationId` | AVOIDED (applies): `credit.released.v1.causationId` must be `payment.received.v1.eventId`. `test_scenario_1_...` derives the `(cause, effect)` pairs from the three topics and requires >= 3 edges; the reviewer's arm R24-ID57 (`payment_register.py:142` causation = the request id) fails on the floor naming the two remaining pairs (`.arm/r31/arms_clean.log`) |
| 60 | envelope_fixture_collisions_defeat_provenance_assertions | `causationId` | AVOIDED (applies): the fleet-free causal-order fixtures (`test_api_instruments.py::test_r24_*`) use distinct `eventId`/`causationId` values `A`, `B`, `C`, so a transposition fails; arm I1/I7 |
| 71 | operator_note_survives_the_compensation_branches | `causationId` | n/a: the operator note on the timeline, owned by #9's saga/projector features |
| 72 | test_matrix_rows_that_outlived_their_named_closer | R24/R48/R49/R61 | AVOIDED (applies): item 7 (R61) is in; matrix R1/R24/R48/R49/R61 all moved |
| 73 | notification_send_degrades_on_permanent_failure | `idempoten` | n/a: Notifications |
| 105 | causal_order_check_is_vacuous_without_causation_id | AssertCausalOrder | AVOIDED (applies): edge count derived from the topics, floor 3, arms A1/A2/I1/I7 |
| 111 | outbox_relay_poison_payload_retry_loop_unverified | `idempoten` | n/a: the relay, owned by the outbox feature |

Also read by name: 63/69 (unpaced readiness loop; applies, avoided by `poll`, arms I9/I10 re-run in round 2), 104 (developer stack hides a green suite; applies, avoided: run with `otcpy-*` down).

## 8. Inherited findings: avoided or recurred

| Finding | Verdict |
|---|---|
| #8 id 57 (completion pair has no causal edge) | avoided: floor of 3 derived edges; reviewer's arm R24-ID57 red |
| #8 id 60 (envelope fixture collisions) | avoided: distinct `A`, `B`, `C` values in the fleet-free causal fixtures |
| #8 id 105 (vacuous causal check) | avoided: edge count derived from the topics, meta-guards, arms A1/A2/I1/I7 |
| #8 id 72 (row outlived its closer) | avoided: item 7 (R61) is in; matrix R1/R24/R48/R49/R61 all moved |
| #8 F1 (a Status sentence claimed the third refusal "the identical code path") | avoided: the R49 Status says the opposite and it is proved (A6': removing the Paid guard changes the code to 409 `PRECONDITION_FAILED`); every other sentence written into the matrix is tied to a named test |
| #8 shared-fleet regression (5 timeouts) | avoided: a fleet per test, torn down first (section 1) |
| #7 rejection 1 (closed R28 with its assertion deleted) | avoided: R28 untouched in the matrix (still e2e TODO, feature 32); the released < cancelled assert is kept and armed |
| #7 rejection 2 (status ordering posing as causal) | avoided: A1 reverses the projector's causal-depth tiebreak and both paths fail naming the pair |
| #8 id 104 (developer infra hides) | avoided: both `quality.sh` runs with only `otcpy-n8n` and the `kb-poc-*` containers (which hold 5432 and 8080) up |
| #8 id 63 (unpaced loop) | avoided: `poll` paces and bounds; arms I9, I10 (re-armed in round 2 with messages, see Round 2) |
| New, recurred (small): a test of mine flaked once in 5 runs (section 10) | recurred, fixed |

## 9. Decisions and deviations the brief did not settle

1. **R61's open reservation is made over NATS, not by an order.** Through the Gateway an order's reservation is consumed by its despatch within about 100 ms (the order is `invoiced` with `reserved_units` back at 0), so `reservedUnits` unchanged would be `0 == 0`. The fixture asks Fulfillment's real responder for `fulfillment.stock.reserve` for an order reference Orders has never seen (Orders records it as `unknown_order` and moves nothing), then the replenish goes through the Gateway only. The real order (`invoiced`, reservation `consumed`) is in the same fixture. A reviewer who wants the reservation to belong to an order will find no way to hold one open through the Gateway.
2. **`Fleet.gateway`** added to `tests/saga_e2e/conftest.py` (additive).
3. **`EXPECTED_POPULATION`** in `tests/architecture/test_no_reload_servers.py` edited on purpose (the guard worked).
4. The R1 sweep runs at receipt on every response of every test, a wider net than the brief asked for.

## 10. Surprises

* A test of mine failed once on a green tree (one in about five runs): the sweep's minimum failed on `GET /orders/{id} 200` with 0 money fields. Mechanism: the poll (`wait_order`) can receive a 200 for a projection that holds facts but no header yet (`headerComplete: false`, R50: facts may arrive before `order.placed.v1`), which has no currency and no totals. Fix: the minimum is 0 for such a document (`minimum_for`). 8 consecutive green runs after the fix. The same failure appeared once as the post-restore re-run of the first A8 arm.
* In the first full `quality.sh` run two failed: (a) `test_no_reload_servers` (my uvicorn call sites; fixed on purpose); (b) `services/gateway/tests/integration/test_gateway_health_probes.py::...[rpcTransport]`, a `pymongo.errors.ServerSelectionTimeoutError: ... connection closed` against that test's OWN Mongo container, which passes alone 3/3. Unexplained mechanism beyond the container connection closing; not a test of this feature (run 2 below).
* Billing has four layers behind "a second payment is refused" (L6), so no production mutation can corrupt the R48 counts and keep a 200 reply; the count assertions are armed by forging the evidence they read.
* `lock_for_replenish` loads no reservation rows (`stock_repository.py:115`, `_load(rows, [])`), so a replenish cannot touch a reservation: "arm" A12 passes and is recorded as NOT an arm. The reservation claim is armed by forging (A15-RES).
* `app.openapi()` of the served Gateway inlines `MinorUnits` as `integer`, so money is derived from the contract yaml; the served table proves the cells are served routes.
* Process: the first run of this task was cut at arm I9 by the Claude Code process exiting with `api_support.py` armed (`pass` for the pacing sleep); the leader found it, I restored it from the backup (`cmp` equal, `sha256` c95d0829...) and re-ran I9 first. Without the sleep the probe never yields and `asyncio.timeout` cannot fire, so I9 and I10 were detected by the 40 s process-group kill (exit 124), not by an assertion: a hang is a detection but not a message. SUPERSEDED in round 2 (D1): the probe yields and the call is bounded from outside; both arms now fail with a message.

## 11. Defeat list (rows that apply)

1 delete the behaviour (A1-A14, I1-I10); 2 corrupt a supplied field (A7', A8', injections, forgeries A3e/A6e/A15); 3 substitute a sibling identifier (APPLIES, corrected in round 2 (D3): invoices and orders are a sibling-identifier family; R48's outbox clause was satisfied by the control invoice and now asserts the row's `paymentReference`; arm R48-SUBST red); 4-6 shadow in a comment/dead region/raw string (do not apply: behavioural tests, no source scanner; the `EXPECTED_POPULATION` guard is the existing AST one); 7 drop an optional element (the dropped currency, A9' and the injection; round 2 (D4): `headerComplete: false` plus a dropped currency, arm R1-HC-T1); 8 compare a literal to a literal (the causal floor 3 is checked against a value derived from the topics, not a literal on both sides; the R49 control rows come from the database); 9 closer half satisfied, premise stale (every ledger row cites file and line on both halves); 10 build output joins the population (the contract cells come from the yaml, not a glob); 11 a form the instrument does not recognise (`true`, `"15.00"` under a non-`amount` key: DISCLOSED limit, caught by the minimum); 12 failure served through a path the population never drives (R61: the replenish handler cannot reach reservations, shown; R48: four layers).

## 12. Arming table

Backups: `.arm/n31/backups/` (path with `/` replaced by `__`); runner `.arm/n31/arm.py` / `arm2.py` (backup + `sha256`, mutate exactly one occurrence, one named test under `setsid --wait timeout -k 15 600`, restore by `cp`, `cmp`, clear `__pycache__`, re-run green). Verbatim output follows; every `GREEN exit 0` is the restored tree re-run. The first A7/A8/A9 and A4-A6 entries are superseded by the primed ones (A7/A8/A9: the driver failed before the sweep, and A8's mutation text was invalid; A4-A6: status asserted before state; both fixed and re-armed). The first A8 `GREEN exit 1` is the flake of section 10.

```
## A1 projector timeline_order.py:92 sortBy depth 1 -> -1 ; tests scenario_1 + scenario_2
ARMED exit 1
   E           AssertionError: causal order violated: order.confirmed.v1 (index 2) precedes its cause credit.approved.v1 (index 3): ['order.placed.v1', 'stock.reserved.v1', 'order.confirmed.v1', 'credit.approved.v1', 'order.despatched.v1', 'invoice.issued.v1', 'order.completed.v1', 'credit.released.v1', 'payment.received.v1']
   E       AssertionError: R28: stock.released.v1 must precede order.cancelled.v1: ['order.placed.v1', 'stock.reserved.v1', 'credit.rejected.v1', 'order.cancelled.v1', 'stock.released.v1']
   2 failed
sha256 ff45b14be9c3f5e00f572b6852322394c6a4f31e3eeaf52e16634c68346275a4 cmp exit 0 ; GREEN 2 passed
## A2 projector delta_to_pipeline.py:46 causationId no longer stored; scenario_1
ARMED exit 1
   E       AssertionError: the timeline resolves [], the published facts carry [('credit.approved.v1', 'order.confirmed.v1'), ('credit.released.v1', 'order.completed.v1'), ('payment.received.v1', 'credit.released.v1')]
   E       assert [] == [('credit.app...released.v1')]
   E         
   E         Right contains 3 more items, first extra item: ('credit.approved.v1', 'order.confirmed.v1')
   E         Use -v to get more diff
   FAILED tests/api/test_black_box_api.py::test_scenario_1_a_placed_order_completes_after_a_payment_and_its_timeline_is_in_causal_order
   1 failed in 14.68s
sha256 851603f7b00e850755eabf2ca700832c0870c97862fc49fec76e2c41de0a049b cmp exit 0
GREEN exit 0 ['1 passed in 14.28s']
## A3a billing payment_register.py: fast-path duplicate read neutralised only; scenario_3
ARMED exit 0
   1 passed in 14.98s
sha256 e4233978d124a9d3001ca649b527ec0494e4f25c1f584cd373fc65b91241a456 cmp exit 0
GREEN exit 0 ['1 passed in 15.03s']
## A3b billing payment_register.py: BOTH idempotency reads neutralised (fast path + authority read under the lock); scenario_3
ARMED exit 1
   E       AssertionError: {"type":"about:blank","title":"Invoice already paid","status":409,"detail":"Invoice INV-000007 is already paid.","code":"INVOICE_ALREADY_PAID","correlationId":"8f2ce9f3-4067-4cc5-888f-466e96d4040c","occurredAt":"2026-10-18T06:37:33.687Z"}
   E       assert 409 == 200
   E        +  where 409 = <Response [409 Conflict]>.status_code
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 14.29s
sha256 e4233978d124a9d3001ca649b527ec0494e4f25c1f584cd373fc65b91241a456 cmp exit 0
GREEN exit 0 ['1 passed in 14.94s']
## A3c billing: both idempotency reads neutralised + the Paid guard removed + (test-side, temporary) the payments.payment_reference UNIQUE constraint dropped in the test database, so the third layer cannot hide the first two; scenario_3 (state asserted first)
ARMED exit 1
   E       AssertionError: {"type":"about:blank","title":"The invoice has no outstanding credit exposure to release","status":409,"detail":"Order ORD-000008 has no outstanding credit exposure to release; the payment was not recorded.","code":"PRECONDITION_FAILED","correlationId":"9993dd45-aab0-455f-8722-16c1b3272681","occurredAt":"2026-10-18T06:38:57.399Z"}
   E       assert 409 == 200
   E        +  where 409 = <Response [409 Conflict]>.status_code
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 14.85s
sha256 e4233978d124a9d3001ca649b527ec0494e4f25c1f584cd373fc65b91241a456 payment_register.py cmp exit 0
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf invoice.py cmp exit 0
sha256 8b3e365656f4508b15afe75af95ace05d59fa8377fec53cc41bda502a6dd0398 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 14.93s']
## A3d as A3c plus the credit-not-outstanding refusal removed (a fourth layer found while arming A3c)
ARMED exit 1
   E       AssertionError: {"type":"about:blank","title":"The owning context is unreachable","status":503,"detail":"The owning context is unreachable","code":"UPSTREAM_UNAVAILABLE","correlationId":"d61ca596-b882-45fd-84da-938cc7e88afe","occurredAt":"2026-10-18T06:39:38.333Z"}
   E       assert 503 == 200
   E        +  where 503 = <Response [503 Service Unavailable]>.status_code
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 15.06s
sha256 e4233978d124a9d3001ca649b527ec0494e4f25c1f584cd373fc65b91241a456 payment_register.py cmp exit 0
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf invoice.py cmp exit 0
sha256 8b3e365656f4508b15afe75af95ace05d59fa8377fec53cc41bda502a6dd0398 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 15.02s']
## A3e-PAY test-side evidence forgery: a second payments row for the invoice (evidence forged in Billing's database); scenario_3
ARMED exit 1
   E       AssertionError: exactly one payment row
   E       assert ['PAY-IDEMP-0...0c672d7abb93'] == ['PAY-IDEMP-0c672d7abb93']
   E         
   E         At index 0 diff: 'PAY-IDEMP-0c672d7abb93X' != 'PAY-IDEMP-0c672d7abb93'
   E         Left contains one more item: 'PAY-IDEMP-0c672d7abb93'
   E         Use -v to get more diff
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 14.96s
sha256 8b3e365656f4508b15afe75af95ace05d59fa8377fec53cc41bda502a6dd0398 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 15.57s']
## A3e-OUT test-side evidence forgery: a second payment.received.v1 row in Billing's outbox; scenario_3
ARMED exit 1
   E       AssertionError: exactly one payment.received.v1 in Billing's outbox for the invoice
   E       assert 2 == 1
   E        +  where 2 = len([{'id': UUID('d725c40c-b098-43eb-9de1-2fc00806a2e9'), 'event_id': UUID('fa7712d0-2903-4a08-a48c-a99dbbb93321'), 'event...ced4921ee15'), 'event_type': 'payment.received.v1', 'aggregate_id': UUID('31d019e6-69b3-4bfc-bb7c-7ff3644ec63c'), ...}])
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 14.84s
sha256 8b3e365656f4508b15afe75af95ace05d59fa8377fec53cc41bda502a6dd0398 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 15.13s']
## A3e-TOP test-side evidence forgery: a second payment.received.v1 record on the topic; scenario_3
ARMED exit 1
   E       AssertionError: exactly one payment.received.v1 on the topic: [{'eventId': 'd251bab1-9c5a-46f6-8d94-434b577b5cb7', 'eventType': 'payment.received.v1', 'aggregateId': '231d0598-27ed-4888-9e33-211a39175056', 'correlationId': '567487a0-f61f-498e-ba49-d1358f895e66', 'causationId': '2f8ed24d-a4f6-4282-93a3-102a63d18d18', 'occurredAt': '2026-10-18T06:41:33.334Z', 'payload': {'orderReference': 'ORD-000008', 'invoiceReference': 'INV-000007', 'paymentReference': 'PAY-IDEMP-e12e413b8fdb', 'currency': 'EUR', 'amount': 7497, 'valueDate': '2026-10-13T08:30:00.000Z', 'source': 'test'}}, {'eventId': 'd251bab1-9c5a-46f6-8d94-434b577b5cb7', 'eventType': 'payment.received.v1', 'aggregateId': '231d0598
   E       assert 2 == 1
   E        +  where 2 = len([{'eventId': 'd251bab1-9c5a-46f6-8d94-434b577b5cb7', 'eventType': 'payment.received.v1', 'aggregateId': '231d0598-27ed..., 'aggregateId': '231d0598-27ed-4888-9e33-211a39175056', 'correlationId': '567487a0-f61f-498e-ba49-d1358f895e66', ...}])
   FAILED tests/api/test_black_box_api.py::test_scenario_3_r48_the_same_payment_reference_twice_records_one_payment_and_one_fact
   1 failed in 15.18s
sha256 8b3e365656f4508b15afe75af95ace05d59fa8377fec53cc41bda502a6dd0398 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 14.98s']
## A4 billing domain/invoice.py: amount check removed; r49 amount
ARMED exit 1
   E       AssertionError: {"outcome":"accepted","paymentReference":"PAY-BADAMT-f8d1b59cc170","invoiceReference":"INV-000006","orderReference":"ORD-000007","invoiceStatus":"paid","paidAt":"2026-10-18T06:42:14.098Z"}
   E       assert 201 == 422
   E        +  where 201 = <Response [201 Created]>.status_code
   FAILED tests/api/test_black_box_api.py::test_r49_a_mismatched_amount_is_refused_422_payment_mismatch_and_billings_database_is_unchanged
   1 failed in 14.99s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 16.25s']
## A5 billing domain/invoice.py: currency check removed; r49 currency
ARMED exit 1
   E       AssertionError: {"outcome":"accepted","paymentReference":"PAY-BADCCY-f6cc277cabd1","invoiceReference":"INV-000006","orderReference":"ORD-000007","invoiceStatus":"paid","paidAt":"2026-10-18T06:42:48.726Z"}
   E       assert 201 == 422
   E        +  where 201 = <Response [201 Created]>.status_code
   FAILED tests/api/test_black_box_api.py::test_r49_a_mismatched_currency_is_refused_422_payment_mismatch_and_billings_database_is_unchanged
   1 failed in 14.78s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 15.06s']
## A6 billing domain/invoice.py: Paid guard removed; r49 second reference
ARMED exit 1
   E       AssertionError: {'type': 'about:blank', 'title': 'The invoice has no outstanding credit exposure to release', 'status': 409, 'detail': 'Order ORD-000007 has no outstanding credit exposure to release; the payment was not recorded.', ...}
   E       assert 'PRECONDITION_FAILED' == 'INVOICE_ALREADY_PAID'
   E         
   E         - INVOICE_ALREADY_PAID
   E         + PRECONDITION_FAILED
   FAILED tests/api/test_black_box_api.py::test_r49_a_different_reference_against_a_paid_invoice_is_refused_409_invoice_already_paid_and_billings_database_is_unchanged
   1 failed in 14.99s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 15.73s']
## A4' (re-armed after the state-first reorder) amount check removed; r49 amount
ARMED exit 1
   E       AssertionError: R49: Billing's database changed
   E       assert ['credit_item...ore, 6 after'] == []
   E         
   E         Left contains 4 more items, first extra item: 'credit_items: 17 row(s) before, 18 after'
   E         Use -v to get more diff
   FAILED tests/api/test_black_box_api.py::test_r49_a_mismatched_amount_is_refused_422_payment_mismatch_and_billings_database_is_unchanged
   1 failed in 16.87s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 15.51s']
## A5' currency check removed; r49 currency
ARMED exit 1
   E       AssertionError: R49: Billing's database changed
   E       assert ['credit_item...ore, 6 after'] == []
   E         
   E         Left contains 4 more items, first extra item: 'credit_items: 17 row(s) before, 18 after'
   E         Use -v to get more diff
   FAILED tests/api/test_black_box_api.py::test_r49_a_mismatched_currency_is_refused_422_payment_mismatch_and_billings_database_is_unchanged
   1 failed in 15.44s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 15.31s']
## A6' Paid guard removed; r49 second reference
ARMED exit 1
   E       AssertionError: {'type': 'about:blank', 'title': 'The invoice has no outstanding credit exposure to release', 'status': 409, 'detail': 'Order ORD-000007 has no outstanding credit exposure to release; the payment was not recorded.', ...}
   E       assert 'PRECONDITION_FAILED' == 'INVOICE_ALREADY_PAID'
   E         
   E         - INVOICE_ALREADY_PAID
   E         + PRECONDITION_FAILED
   FAILED tests/api/test_black_box_api.py::test_r49_a_different_reference_against_a_paid_invoice_is_refused_409_invoice_already_paid_and_billings_database_is_unchanged
   1 failed in 17.12s
sha256 c3ca9162a6171c313b47728b8d3de43c4b2d6b80955ffba5e294f31173886fdf cmp exit 0
GREEN exit 0 ['1 passed in 15.48s']
## A6e test-side evidence forgery: a second payments row appears during the refused attempt; r49 second reference
ARMED exit 1
   E       AssertionError: R49: Billing's database changed
   E       assert ['payments: 6...ore, 7 after'] == []
   E         
   E         Left contains one more item: 'payments: 6 row(s) before, 7 after'
   E         Use -v to get more diff
   FAILED tests/api/test_black_box_api.py::test_r49_a_different_reference_against_a_paid_invoice_is_refused_409_invoice_already_paid_and_billings_database_is_unchanged
   1 failed in 15.11s
sha256 7cd123f586aedbb4fcd18bb6fb4a4f6abf2b962636143e937a3fae2c6b56d1a9 test_black_box_api.py cmp exit 0
GREEN exit 0 ['1 passed in 15.46s']
## A7 gateway wire.py wire_response: currency lower-cased on the wire; r1 sweep
ARMED exit 1
   E       assert 400 == 201
   E        +  where 400 = <Response [400 Bad Request]>.status_code
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 14.60s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 16.65s']
## A8 gateway wire.py wire_response: totalAmount written with a fraction; r1 sweep
ARMED exit 1
   E           json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 157 (char 156)
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 14.14s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 1 ['1 failed in 17.35s']
## A9 gateway wire.py wire_response: currency dropped from every body; r1 sweep
ARMED exit 1
   E       KeyError: 'currency'
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 14.38s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 16.61s']
## A7' (re-armed: R1 checked at receipt) gateway wire.py wire_response: currency lower-cased on the wire; r1 sweep
ARMED exit 1
   E       AssertionError: POST /orders 201: $.initialAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency); $.initialDiscount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency); $.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 13.34s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 16.37s']
## A8' gateway wire.py wire_response: totalAmount written with a fraction; r1 sweep
ARMED exit 1
   E       AssertionError: POST /orders 201: $.totalAmount: R1 requires an integer count of minor units, got DecimalToken(3000.0)
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 13.07s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 16.79s']
## A9' gateway wire.py wire_response: currency dropped from every body; r1 sweep
ARMED exit 1
   E       AssertionError: POST /orders 201: the sweep found 0 monetary field(s), fewer than the 3 response kind always carries - the sweep would be vacuous
   FAILED tests/api/test_money_representation.py::test_r1_every_monetary_field_of_every_gateway_response_is_an_integer_accompanied_by_a_currency_code
   1 failed in 16.43s
sha256 af99c368f5c7a3b1cc4802efeb31b0a56fca8eb3dc012ba5cc48bfcf2bc25373 cmp exit 0
GREEN exit 0 ['1 passed in 17.62s']
## A11 fulfillment stock_item.replenish also zeroes reserved_units; r61
ARMED exit 1
   E           AssertionError: PRD-0002: reservedUnits untouched
   E           assert 0 == 4
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 14.95s
sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc cmp exit 0
GREEN exit 0 ['1 passed in 15.36s']
## A12 fulfillment stock_item.replenish also releases every reservation of the item; r61
ARMED exit 0
   1 passed in 15.30s
sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc cmp exit 0
GREEN exit 0 ['1 passed in 15.32s']
## A13 fulfillment stock_item.replenish also raises a stock.released.v1 fact; r61
ARMED exit 1
   E       AssertionError: {"type":"about:blank","title":"An unexpected error occurred","status":500,"detail":"An unexpected error occurred","code":"INTERNAL_ERROR","correlationId":"e09999e9-b016-48eb-bc2a-9016fc31bb48","occurredAt":"2026-10-18T06:54:25.826Z"}
   E       assert 500 == 200
   E        +  where 500 = <Response [500 Internal Server Error]>.status_code
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 14.92s
sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc cmp exit 0
GREEN exit 0 ['1 passed in 15.84s']
## A14 fulfillment stock_item.replenish adds the delta twice; r61
ARMED exit 1
   E           AssertionError: PRD-0002: units up by exactly the delta
   E           assert 547 == (497 + 25)
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 15.40s
sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc cmp exit 0
GREEN exit 0 ['1 passed in 15.10s']
## A13' fulfillment stock_item.replenish also raises a well-formed stock.released.v1 fact; r61
ARMED exit 1
   E               AssertionError: R61: orders.processed_events changed
   E               assert [{'id': UUID(...c), ...}, ...] == [{'id': UUID(...ne.utc), ...}]
   E                 
   E                 At index 0 diff: {'id': UUID('38908555-46e7-4c74-996c-1530fc346e6c'), 'event_id': UUID('1e7ead4c-327c-4db3-b797-b46b422c4667'), 'consumer': 'orders.saga', 'processed_at': datetime.datetime(2026, 10, 18, 6, 56, 18, 594000, tzinfo=datetime.timezone.utc), 'created_at': datetime.datetime(2026, 10, 18, 6, 56, 18, 594000, tzinfo=datetime.timezone.utc)} != {'id': UUID('39951fc4-a4dd-4dc9-ac61-0647d6626a61'), 'event_id': UUID('cfc28a24-1a39-4ab3-b07f-6e2d801deb9d'), 'consumer': 'orders.saga', 'processed_at': datetime.datetime(2026, 10, 18, 6, 56, 17, 566000, tzinfo=datetime.tim...
   E                 
   E                 ...Full output truncated (3 lines hidden), use '-vv' to show
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 15.33s
sha256 d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc cmp exit 0
GREEN exit 0 ['1 passed in 15.19s']
## A12 (not an arm) replenish also releases every reservation of the item: test passes because lock_for_replenish loads no reservation rows (stock_repository.py:115 _load(rows, []))
## A15-RES test-side evidence forgery: the open reservation row changes (forged); r61
ARMED exit 1
   E               AssertionError: R61: fulfillment.reservations changed
   E               assert [{'id': UUID(...b', ...}, ...] == [{'id': UUID(...b', ...}, ...]
   E                 
   E                 At index 3 diff: {'id': UUID('399344e2-4dde-4d5f-936c-569486d9e110'), 'stock_id': UUID('58120fca-22a4-46cb-a27a-99e65425f87e'), 'company_code': 'SPANATURAL', 'retailer_code': 'AldiEs', 'product_code': 'PRD-0002', 'order_reference': 'ORD-900001', 'units': 5, 'status': 'reserved', 'created_at': datetime.datetime(2026, 10, 18, 6, 56, 51, 840000, tzinfo=datetime.timezone.utc), 'updated_at': datetime.datetime(2026, 10, 18, 6, 56, 51, 840000, tzinfo=datetime.timezone.utc)} != {'id': UUID('399344e2-4dde-4d5f-936c-569486d9e110'), 'stock_id': UUID('58120fca-22a4-46cb-a27a-99e654...
   E                 
   E                 ...Full output truncated (2 lines hidden), use '-vv' to show
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 15.31s
sha256 6fe065f062e7f207e810363719b9761f3a0848a3e7033d9264bf4976187d0f28 test_stock_replenishment.py cmp exit 0
GREEN exit 0 ['1 passed in 16.85s']
## A15-ORD test-side evidence forgery: an order moves (forged); r61
ARMED exit 1
   E               AssertionError: R61: orders.orders changed
   E               assert [{'id': UUID(...c), ...}, ...] == [{'id': UUID(...c), ...}, ...]
   E                 
   E                 At index 1 diff: {'id': UUID('28485bd8-1765-4e95-a654-11bbea1803a1'), 'order_reference': 'ORD-000007', 'request_id': None, 'order_date': datetime.datetime(2026, 10, 18, 6, 57, 28, 931000, tzinfo=datetime.timezone.utc), 'company_id': UUID('90a8e0cc-f58d-4c8a-a31a-7f84bccf24ae'), 'retailer_id': UUID('9436d555-ec26-4488-a8e3-728b2ebbc5c3'), 'currency_id': UUID('23ab1a2b-bce4-4b83-8304-6b5a1084990c'), 'initial_amount': 4500, 'initial_discount': 0, 'total_amount': 4500, 'status': 'paid', 'cancellation_reason': None, 'notes': None, 'created_at': datetime.datetime(2026, 10, 18...
   E                 
   E                 ...Full output truncated (2 lines hidden), use '-vv' to show
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 16.88s
sha256 6fe065f062e7f207e810363719b9761f3a0848a3e7033d9264bf4976187d0f28 test_stock_replenishment.py cmp exit 0
GREEN exit 0 ['1 passed in 15.26s']
## A15-TOP test-side evidence forgery: a record appears on a topic (forged; the tables are identical, the topic count differs); r61
ARMED exit 1
   E       AssertionError: R61: a fact was published
   E       assert {'orders': 3,... 'billing': 2} == {'orders': 2,... 'billing': 2}
   E         
   E         Omitting 2 identical items, use -vv to show
   E         Differing items:
   E         {'orders': 3} != {'orders': 2}
   E         Use -v to get more diff
   FAILED tests/api/test_stock_replenishment.py::test_r61_a_replenish_through_the_gateway_raises_units_and_changes_no_reservation_no_order_and_publishes_no_fact
   1 failed in 14.89s
sha256 6fe065f062e7f207e810363719b9761f3a0848a3e7033d9264bf4976187d0f28 test_stock_replenishment.py cmp exit 0
GREEN exit 0 ['1 passed in 16.95s']
## I1 api_support.assert_causal_order: the 'fewer edges than required' check deleted (#8 id 105)
ARMED exit 1
   E       Failed: DID NOT RAISE AssertionError
   E       Failed: DID NOT RAISE AssertionError
   FAILED tests/api/test_api_instruments.py::test_r24_id105_a_timeline_without_any_causation_id_fails_naming_that_no_edges_were_checked
   FAILED tests/api/test_api_instruments.py::test_r24_a_timeline_that_resolves_fewer_edges_than_required_fails_naming_both_counts
   2 failed, 41 passed in 1.09s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I2 api_support._is_json_number: the bool exclusion deleted
ARMED exit 1
   E       AssertionError: assert ['$.projectio....totalAmount'] == ['$.totalAmount']
   E         
   E         At index 0 diff: '$.projectionPending' != '$.totalAmount'
   E         Left contains one more item: '$.totalAmount'
   E         Use -v to get more diff
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_true_is_not_a_number_so_it_is_not_flagged_beside_a_currency_but_is_when_it_is_the_amount
   1 failed, 42 passed in 1.08s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I3 api_support: currency matched with re.match instead of fullmatch
ARMED exit 1
   E       AssertionError: []
   E       assert ([] == []
   E         
   E         Use -v to get more diff) is False
   E       AssertionError: []
   E       assert ([] == []
   E         
   E         Use -v to get more diff) is False
   E       AssertionError: []
   E       assert ([] == []
   E         
   E         Use -v to get more diff) is False
   FAILED tests/api/test_api_instruments.py::test_r1_the_currency_must_be_exactly_three_capital_letters["EURO"-False]
   FAILED tests/api/test_api_instruments.py::test_r1_the_currency_must_be_exactly_three_capital_letters["EUR\\n"-False]
   FAILED tests/api/test_api_instruments.py::test_r1_the_currency_must_be_exactly_three_capital_letters["EUR "-False]
   3 failed, 40 passed in 1.08s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I4 api_support: the textbook '^[A-Z]{3}$' with re.match (accepts 'EUR\n')
ARMED exit 1
   E       AssertionError: []
   E       assert ([] == []
   E         
   E         Use -v to get more diff) is False
   FAILED tests/api/test_api_instruments.py::test_r1_the_currency_must_be_exactly_three_capital_letters["EUR\\n"-False]
   1 failed, 42 passed in 1.08s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I5 api_support.parse_json: floats parsed as Python floats (parse_float removed)
ARMED exit 1
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E       ValueError: not enough values to unpack (expected 1, got 0)
   E           assert '$.totals.initialAmount' in "GET /orders/{id}: $.totals.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)"
   E            +  where "GET /orders/{id}: $.totals.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)" = str(AssertionError("GET /orders/{id}: $.totals.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)"))
   E            +    where AssertionError("GET /orders/{id}: $.totals.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)") = <ExceptionInfo AssertionError("GET /orders/{id}: $.totals.totalAmount: R1 requires an ISO 4217 alpha-3 currency code beside the amount, got 'eur' (at $.currency)") tblen=2>.value
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[100.0]
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[1e2]
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[1E+2]
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[1.5]
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[-0.0]
   FAILED tests/api/test_api_instruments.py::test_r1_a_json_number_written_as_a_decimal_is_refused_and_named[100.00]
   FAILED tests/api/test_api_instruments.py::test_r1_the_failure_names_the_path_of_every_violation_not_only_the_first
   7 failed, 36 passed in 1.10s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.01s']
## I6 api_support.money_problems: the int64 bound deleted
ARMED exit 1
   E       AssertionError: []
   E       assert ([] != []) is True
   E       AssertionError: []
   E       assert ([] != []) is True
   E       AssertionError: []
   E       assert ([] != []) is True
   FAILED tests/api/test_api_instruments.py::test_r1_an_integer_beyond_the_bigint_column_is_refused[9223372036854775808-True]
   FAILED tests/api/test_api_instruments.py::test_r1_an_integer_beyond_the_bigint_column_is_refused[-9223372036854775809-True]
   FAILED tests/api/test_api_instruments.py::test_r1_an_integer_beyond_the_bigint_column_is_refused[1000000000000000000000000000000-True]
   3 failed, 40 passed in 1.08s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I7 api_support.assert_causal_order: the cause-precedes-effect check deleted
ARMED exit 1
   E       Failed: DID NOT RAISE AssertionError
   FAILED tests/api/test_api_instruments.py::test_r24_a_timeline_with_two_entries_swapped_fails_naming_the_violation
   1 failed, 42 passed in 1.07s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.01s']
## I8 api_support.check_money_findings: the minimum deleted
ARMED exit 1
   E       Failed: DID NOT RAISE AssertionError
   E       Failed: DID NOT RAISE AssertionError
   FAILED tests/api/test_api_instruments.py::test_r1_a_money_field_with_no_currency_anywhere_above_it_is_not_discovered_so_the_minimum_is_the_guard
   FAILED tests/api/test_api_instruments.py::test_r1_a_response_whose_money_fields_all_vanished_fails_the_minimum_naming_the_response
   2 failed, 41 passed in 1.08s
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['43 passed in 1.02s']
## I9 api_support.poll: the pacing sleep deleted
## I9 api_support.poll: the pacing sleep deleted (40 s process-group kill: without the sleep the probe never yields, the loop starves, asyncio.timeout cannot fire)
ARMED exit 124 (SUPERSEDED by Round 2)
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['1 passed in 0.59s']
## I10 api_support.poll: the asyncio.timeout bound widened to 1000 s (so a probe that never succeeds is not ended by the bound; 40 s kill)
ARMED exit 124
sha256 c95d082910f51f104a3e7ebfde67cda9efded4dbf5d5cc4398a2853db3a98408 cmp exit 0
GREEN exit 0 ['1 passed in 0.59s']

```

## 13. Matrix counts

Recount by script before: 63 rows, summary 57 green / 1 scoped / 5 not yet green. After: 62 green / 0 scoped / 1 not yet green (R28, its e2e half, feature 32). Moved: R1 (SCOPED -> DONE), R24, R48, R49, R61. Only column 5 of those five rows, four summary rows, the Total row and the scoped paragraph changed (`git diff` shows 11 lines).

## 14. Quality runs

Baseline (developer stack down; `kb-poc-*` holding 5432 and 8080): all gates passed, pytest 5 231 passed in 837.97 s, wall 23 min 06 s.
Run 1 (after the feature, 14:01Z -> 14:16Z, log `.arm/n31/quality_final_run1.log`): ruff, mypy, import-linter, contracts and web gates green; pytest `2 failed, 5283 passed in 904.33 s`. Failure (a) `test_no_reload_servers` was MINE (fixed, section 0). Failure (b) was `test_gateway_health_probes.py::test_r60_...[rpcTransport]`.
Run 2 (after the fix, 14:17Z -> 14:33Z, log `.arm/n31/quality_final.log`): all gates green except pytest `1 failed, 5284 passed in 959.82 s (0:15:59)`, wall about 16 min plus the web gate; the one failure is (b) again.

**Finding (b), not caused by this feature, unresolved and NOT green: the final `quality.sh` is red on one test.** `test_r60_readiness_reports_the_paused_dependency_down_within_its_bound_while_liveness_answers_throughout_and_recovers[rpcTransport]` fails with `pymongo.errors.ServerSelectionTimeoutError ... connection closed / Connection reset by peer` against the test's OWN Mongo container right after its unpause. Evidence it is independent of `tests/api`: it fails when run ALONE in a fresh session (`pytest services/gateway/tests/integration/test_gateway_health_probes.py`: failed 4 of 6 runs at 16:35-16:37, passed 3 of 3 at about 14:00); it fails after `tests/architecture/test_no_reload_servers.py` only, after `tests/api/test_api_instruments.py` only (no container at all) and after `tests/saga_e2e/test_saga_paths.py`; the baseline run at 06:20Z passed it. During those minutes the machine was loaded by another project (`kb-poc` eval + `ollama` at 200-500% CPU, `kb-poc-postgres`/`ai`/`otcpy-n8n` restarting, load average 3.5). Mechanism not proved beyond "the test's Mongo container resets the first connection after unpause under load"; a recovery race in a feature-24-era test. Disposition for the leader: re-run `quality.sh` when the machine is quiet; if it still fails, the fix is that test's (retry the first connection or wait for the container's readiness after unpause), not this feature's.
Delta against the baseline: pytest 5 231 -> 5 285 collected (+54 tests, all in `tests/api`), 837.97 s -> 959.82 s (+122 s: +50 s of the new tests, the rest the loaded machine); the architecture guard population 13 -> 15.

Packages installed: none.

## Round 2 (review `progress/review_api_tests.md`, D1 to D6; test and record changes only)

Session: about 19:10 to 19:55 CEST on 2026-10-18 (one session, 45 min, including the final `quality.sh`). Backups and logs in `.arm/n31r2/` (`sums.txt` for the `sha256`; restores by `cp` + `cmp`, `__pycache__` cleared, green re-run).

* **D1.** `test_poll_waits_between_probes_and_gives_up_naming_what`: `never()` now `await asyncio.sleep(0)`, and the `poll` call sits inside an outer `asyncio.timeout(5)` that turns a timeout into `pytest.fail` naming the claim. Re-run arms, verbatim:
  * I9 (pacing sleep deleted from `api_support.poll`): `AssertionError: 75976 probes in 0.55 s: the loop is not paced at 0.1 s` / `assert 75976 <= 7`; `1 failed in 0.76s`. Restored (`cmp` equal), green `1 passed in 0.63s`.
  * I10 (`asyncio.timeout(seconds)` widened to `asyncio.timeout(1000)`): `Failed: poll(seconds=0.55) did not end at its own bound within 5 s (50 probes): the bound is not the asyncio.timeout the claim names`; `1 failed in 5.26s`. Restored, green `1 passed in 0.63s`.
* **D2.** Section 7 redone without the id filter: command, 22-entry hit list, one classification per hit (feature rows 5 to 29 as one group); #8 id 57 and id 60 named AVOIDED, with the test and the arm; section 8 gained their rows.
* **D3.** R48's outbox clause now asserts the outbox row's `paymentReference == payment_reference`, its `invoiceReference` equals the invoice's, and differs from the control's. R48-SUBST (the filter reads `control_invoice["invoiceReference"]`): `AssertionError: Billing's outbox row is not this payment's: {... 'invoiceReference': 'INV-000006', 'paymentReference': 'PAY-CONTROL-9044f908488a', ...}` / `assert 'PAY-CONTROL-9044f908488a' == 'PAY-IDEMP-3737c0f1a95a'` (it was `ARMED exit 0`). Restored, `cmp` equal. Section 11 row 3 corrected.
* **D4.** The main R1 sweep now takes the completed order's detail (`drive_every_operation`'s `detail_text`), requires `headerComplete` not false and sweeps it against `DETAIL_MINIMUM` unconditionally; the R50 exemption in `minimum_for` stays for poll-time documents. R1-HC-T1 (`wire_response` reports `headerComplete: false` and drops every `currency` on order details): `AssertionError: the completed order has no header` / `assert False is not False` (it was `ARMED exit 0`). Restored `wire.py` (`sha256` af99c368..., `cmp` equal). Disclosed: the first assertion to fire is the header one; the minimum on the same document would fail too (no currency means 0 money fields), but I did not arm that line alone.
* **D5.** `pytest tests/api --collect-only -q --no-cov`: 54 tests; fleet tests are the 7 in `test_black_box_api.py`, 2 in `test_money_representation.py` (the literal-set test is fleet-free) and 1 in `test_stock_replenishment.py` = 10. Section 0 corrected.
* **D6.** Effort record (times from the leader's brief, round 2 mine):

| Span | Time (2026-10-18 unless stated) |
|---|---|
| brief written / baseline `quality.sh` started | 07:56:22 / 07:57:32 |
| first run cut (Claude Code process exited, `api_support.py` armed at I9) | about 08:59 |
| Mongo readiness fix (entry 217), `booted` race fix (entry 218): separate light entries | between 16:40 and 18:35 |
| run resumed / final `quality.sh` log / record last written | about 15:52 / 16:33:34 / 16:36:36 |
| review (rejected) | about 18:37 to 19:09:32 (the review file says 19:16) |
| round 2 | about 19:10 to 19:55 (45 min) |

Round 2 verification: `tests/api` once, developer infrastructure down (`docker ps`: only `kb-poc-*` and `otcpy-n8n`): `54 passed in 90.73s`. Then `./quality.sh` once (`.arm/n31r2/quality.log`, 19:26 to 19:53): `5288 passed in 1625.85s (0:27:05)`, web `687 passed`, `quality.sh: all gates passed`. Files touched: `tests/api/test_api_instruments.py`, `tests/api/test_black_box_api.py`, `tests/api/test_money_representation.py`, this record, and feature 31's status line. `git status` shows no new change under `services/`, `packages/` or `specs/` from this round.
