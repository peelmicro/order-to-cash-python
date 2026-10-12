# Review: feature 40 `orders_catalog_responder` (phase 13, full group, round 1)

**Verdict: REJECTED.** One blocking defect, B1. The A5 class (#8: an ordering claim guarded on only part of its population) recurs here in its sibling-substitution form. In every list the reply carries, the fixture's sort order by a sibling column equals its code order. So replacing `ORDER BY code` with `ORDER BY name` (or by `ean`, or for currencies by `symbol`) leaves every ordering test green, through the adapter, through NATS and through the Gateway. The remedy is fixture data only (a test-only change), plus re-arming. All the production behaviour I probed is correct, and every other guard I armed failed as it should.

Inputs read: `progress/brief_review_orders_catalog_responder.md`, `progress/impl_orders_catalog_responder.md`, `progress/brief_impl_orders_catalog_responder.md`, `progress/premise_impl_orders_catalog_responder.md`, the working-tree diff of `services/orders/**`, the two architecture literals, the Gateway's catalog route and handler, and #7's and #8's cited sources.

## Blocking

### B1: the "ordered by code" claim survives a sibling-column substitution in all four lists (A5 recurred)

- **Claim.** `infrastructure/persistence/reference_catalog.py:80, 118, 143` orders by `code`. The port docstring, the adapter docstring, the ledger row "Sorted lists … `ORDER BY code` x4" and four test names (`…_in_code_order`, `test_every_list_is_ordered_by_code_not_by_insertion_or_its_reverse`) all state it.
- **Fixture.** `services/orders/tests/integration/conftest.py:669-705` (`catalog_data`). Insertion order differs from code order and from its reverse, as the brief asked. But each list's sibling columns sort in exactly code order:
  - products: name Alpha/Bravo/Charlie/Delta and ean …089/…102/…126/…140, both A,B,C,D;
  - retailers: name Kappa/Mistral/Norte/Xenon, which is K,M,N,X;
  - companies: name Pampa/Quebec/Rio/Sierra, which is P,Q,R,S;
  - currencies: symbol `EU€`/`JP¥`/`US$`, which is EUR,JPY,USD.
- **Surviving mutations** (my arms, below):

| Arm | Mutation | Tests run | Result |
|---|---|---|---|
| R1 | products `.order_by(Product.code)` → `.order_by(Product.name)` | adapter `test_products_…_in_code_order[x2]`, NATS `test_every_list_is_ordered_by_code…[x4]`, Gateway `test_the_gateway_route_returns_the_seeded…[x3]` | **SURVIVED**, `9 passed` |
| R2 | parties `.order_by(table.code)` → `.order_by(table.name)` | adapter retailers + companies `[x2 each]`, NATS `[x4]`, Gateway `[x3]` | **SURVIVED**, `11 passed` |
| R3 | currencies `.order_by(Currency.code)` → `.order_by(Currency.symbol)` | adapter `test_currencies_…`, NATS `[x4]` | **SURVIVED**, `5 passed` |
| R3b | products `.order_by(Product.ean)` | adapter `test_products_…_in_code_order[x2]` | **SURVIVED**, `2 passed` |

- **Why it matters.** This is the inherited finding the brief told me to push hardest on (#8's A5, `../order-to-cash-dotnet/progress/history.md:1702`). CLAUDE.md's mutation families include "substitute a valid sibling identifier" (line 126) and "Fixtures must not satisfy the assertion's relation by accident" (line 127). The implementer's brief required "a fixture's order must differ from every plausible wrong order". Sorting a place-order form by display name is the most plausible wrong order, and these fixtures cannot tell it from code order. Phase 12 rejected the same class (`progress/history.md:1302`, round-1 B4: "R50's fixture could not tell `occurredAt` order from `eventId` order"). The implementer's defeat-list row 3 names A7/A11/A13 as its sibling substitutions, but none of them touches ordering.
- **Remedy (test-only).** In `catalog_data`, choose values so that, in each list, sorting by every sibling column (product `name`, `ean`, `description`; party `name`, `vat`, `gln`, `country`; currency `iso_number`, `symbol`) differs from code order. Ideally it should also differ from insertion order and from its reverse, with and without the disabled row. Keep the existing pairwise-distinctness. Then re-arm R1, R2, R3 and R3b, plus the deletions A4/A4b/A4c, and record them verbatim. Use a sentinel first, by computing the per-column orders. A small assertion inside the fixture or a unit test that checks this property of the fixture would make it self-guarding (optional).

## Non-blocking (each with a disposition)

- **N1: one test overstates what it proves.** `services/orders/tests/unit/test_catalog_reference_list.py:197` `test_the_listing_handler_reads_the_same_catalog_object_place_order_resolves` only asserts `ListReferenceDataQueryHandler(scope)._scope.catalog is catalog`. That is true by construction. It never touches `PlaceOrderCommandHandler` or what `handle` reads. The real guards for the two-party "same adapter" claim are the AST construction count (A21; my R13 probed the other direction, a handler that builds its own adapter, and it fails) and `layers-orders` (application cannot import infrastructure). **Disposition: fix in the B1 round.** Delete the test, or rename it to what it asserts. It costs nothing, and a ledger row should not be credited to it.
- **N2: after feature 41, a real-NATS HTTP-level no-responder 503 is no longer proven.** The deleted Gateway test left no hole today:
  - `services/gateway/tests/unit/test_gateway_rpc_routes.py:291` `test_every_rpc_route_maps_a_missing_responder_to_503_upstream_unavailable` covers all three catalog routes (`RPC_ROUTES:273-275`, through a fake RPC);
  - `test_nats_rpc_client.py:112` proves the real client raises `RpcUnavailableError` on no responder;
  - `test_gateway_over_real_responders.py:345` `test_cancel_answers_the_mapped_no_responder_error_until_feature_41` still proves the composed path over real NATS.

  When feature 41 retires that last test, only the two halves remain. **Disposition:** the leader attaches an acceptance item to feature 41: either keep one real-NATS HTTP 503 test against a subject nobody serves, or record that the two-half proof is accepted. This is not feature 40's to fix.
- **N3: a pre-existing flaky test, outside feature 40's change.** `./quality.sh` failed on `services/orders/tests/unit/test_system_clock.py:15` (`assert len({instant.microsecond …}) > 1, "a real clock moves"`): 1 000 `SystemClock.now()` calls fell within one millisecond. In isolation, five runs gave passed, failed, passed, failed, failed. The file was last changed in `ccbe631` (feature 14), and feature 40 touches neither it nor `infrastructure/clock.py`. Population: `grep -rn "a real clock moves" --include=*.py services packages tests` → 1 hit (this file). **Disposition: fix in this phase** (CLAUDE.md "findings are fixed in the phase that detects them"). This is a light, test-only fix for `test_maintainer`: sample until the clock moves, with a wall-time bound, so a fast machine cannot fail it. It must not count against feature 40.
- **N4 (cosmetic).** `services/orders/tests/unit/test_orders_create_responder.py:60,79`: `FakeConnection.flushed_after` is recorded and never asserted. The flush is guarded by `test_the_responder_subscribes_both_subjects_in_the_queue_group_and_flushes_after` (A14). **Disposition: accept, no re-open trigger** (dead fake state, no claim rests on it). Delete it if the B1 round touches the file.

## Arming table (reviewer's own; runner `.arm/r40/arm.py` + `arm2.py`, raw lines in `.arm/r40/arms.jsonl`)

Method for every arm:
- back up into `.arm/r40/<arm>.bak` and record its `sha256`;
- mutate the first occurrence;
- run the named tests with `timeout -k 10 420` in a new session (process group);
- restore with `cp`, check with `cmp` (identical in all 18 arms), and remove `__pycache__` in that directory.

Re-hashed at the end: `reference_catalog.py` 9707cb12…, `catalog_reference_list.py` 432c468d…, `composition.py` 2c68f205…, `list_reference_data.py` 6702d745…, Gateway `catalog_handlers.py` 5103c5a0…, `routes_catalog.py` 294ba2f3…, all equal to the backups. Dev stack down throughout (`docker ps`: `otcpy-n8n` only, before and after).

| Arm | Defeat row | Mutation | Test(s) | Result (verbatim head) |
|---|---|---|---|---|
| R1 | 3 sibling | products order by `name` | adapter + NATS + Gateway ordering | **SURVIVED** `9 passed` (B1) |
| R2 | 3 | parties order by `name` | adapter + NATS + Gateway | **SURVIVED** `11 passed` (B1) |
| R3 | 3 | currencies order by `symbol` | adapter + NATS | **SURVIVED** `5 passed` (B1) |
| R3b | 3 | products order by `ean` | adapter | **SURVIVED** `2 passed` (B1) |
| R4 | 2 corrupt | **seam, responder side:** reply builder `_party` `vat=listing.code` | Gateway `test_the_gateway_route_returns_the_seeded_enabled_rows_field_for_field_in_code_order` | failed [retailers, companies]: `'vat': 'RET-K' … != … 'vat': 'FRK1122334'` |
| R5 | 2 | **seam, Gateway side:** `_party` `vat=party.name` | same | failed: `'vat': 'Kappa Retail' … != … 'vat': 'FRK1122334'` |
| R5b | 2 | Gateway product `description=product.name` | same | failed [products]: `'description': 'Alpha pallet' … != … 'one euro pallet, wrapped'` |
| R15 | 2/11 | **seam, wire key:** responder bytes `"vat"` → `"vatNumber"` (key renamed after serialisation) | same | failed [retailers, companies]: the `vat` key missing from the Gateway's items |
| R16 | 7 drop optional | responder omits `description` (optional in the contract) | same | failed [products]: items carry no `description` |
| R14 | 2 | companies list reversed in `to_reply` | same | failed [companies]: `{'code': 'CMP-R' …} != {'code': 'CMP-P' …}` |
| R6 | 1, D1 hop 1 | Gateway route `ListRetailersQuery(include_disabled=False)` | `test_include_disabled_through_the_gateway_adds_the_disabled_row` | failed [retailers]: `Right contains one more item: {'code': 'RET-X' …}` |
| R7 | 1, D1 hop 2 | Gateway request `include_disabled=False` | same | failed [x3]: `Right contains one more item` PRD-D / RET-X / CMP-S |
| R8 | 1, D1 SQL hop | `_list_parties` always filters (`if True:`) | adapter `test_companies_…_in_code_order` | failed `[True]`: `Right contains one more item: {'code': 'CMP-S' …}` |
| R9 | 2, payload on the wire | `price=listing.price.amount + 1` | NATS `test_kinds_omitted_returns_the_four_collections_enabled_rows_only` | failed: `AssertionError: products … 'price': 2000 … != … 'price': 1999` |
| R10 | 1 (instrument) | a 7th `session.execute(...)` in `reference_catalog.py` | `test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[orders]` | failed: `Counter({('call', 'execute'): 7}) != Counter({('call', 'execute'): 6})` |
| R11 | 11 (instrument) | currencies `select(...)` swapped for `update(Currency)…returning(...)`, the `execute` count kept at 6 | same | failed: `Counter({('call', 'execute'): 6, ('call', 'update'): 1}) != …` |
| R12 | 1 | `register_query(ListReferenceDataQuery, …)` deleted | `test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[orders]` | failed: `DispatcherValidationError: No query handler is registered for ListReferenceDataQuery. Exactly one is required.` |
| R13 | 3, two-party other direction | the listing handler builds its own `SqlAlchemyReferenceCatalog` | `test_the_reference_catalog_adapter_is_constructed_once_and_only_by_the_composition_root` | failed: `Left contains 1 more item: {'application/queries/list_reference_data.py': 1}` |

Brief item 4 (the seam): R4, R5, R5b, R15, R16 and R14 all fail in `test_catalog_through_gateway.py`, against the real Gateway app (`otc_gateway.main.create_app()`) and the real Orders host over real NATS and PostgreSQL. Brief item 7: the `3 → 6` count still fails on an added `execute` (R10) and on a read swapped for a write that keeps the count (R11), and the new Orders registration row fails on deletion (R12).

## Must-hold checklist (implementer brief) and `feature_list.json` id 40 acceptance

| Item | Verified by | Status |
|---|---|---|
| Acceptance 1: `GET /catalog/products|retailers|companies` return real data through the Gateway | `test_catalog_through_gateway.py` (8 tests, real Gateway + real responder + PostgreSQL); R4–R7, R14–R16 fail there | met |
| Acceptance 2: reuses the lookup place-order calls, exposed as a query | one widened `ReferenceCatalog` port; `composition.py:359` builds one `SqlAlchemyReferenceCatalog`, bound at `:384`; `ListReferenceDataQuery(Query[ReferenceListing])` registered explicitly (`composition.py` `register_handlers`); R12, R13, A21 | met |
| Reply validated against the generated `CatalogReferenceListReplyPayload`, one serializer, integer money with currency | `to_reply` builds the generated `Product`/`Party`/`CurrencyView`; `encode` = `to_wire_json`; unit full-document equality (key sets both ways); R9, A16 | met |
| Malformed request → `VALIDATION_FAILED` `RpcError`, never unanswered | `map_error` arm (A8); NATS `test_a_malformed_request_is_answered_validation_failed_never_left_unanswered[x7]`; `_serve` answers every exception | met |
| Reads only, no lock, own session | `test_the_listings_issue_reads_only_and_hold_no_lock` (A10); each `list_*` opens and closes `async with self._sessions()`; R11 | met |
| Gateway fields asserted with pairwise-distinct fixture values | R4/R5/R5b/R15/R16 fail by name | met; **ordering fixture: B1** |
| Responder lifecycle | unchanged single task, started by `responder.start()` (now awaits `flush()`, A14) and awaited by the lifespan (`composition.py`, the `nats-responder` stop stage) | met |

## Ported-idiom ledger (impl record §3): claims checked, not just existence

- **"Same adapter place-order uses."** Probed both ways:
  - root builds a second adapter: A21 fails;
  - handler builds its own: R13 fails.

  History halves read on disk:
  - #7 `apps/orders/src/app.module.ts:127-137` (`useExisting: ORDER_REFERENCE_DATA`, with its comment) and `application/ports/catalog-reference-list.port.ts:1-21` (two ports, one adapter);
  - #8 `14d9a66:…/CatalogReferenceListPortReuseTests.cs:41-51` (exactly one registration) and `:53-75` (constructor-shape test).

  The latter's #9 counterpart is `layers-orders` (pyproject.toml:282-289). The impl record's guard-port table should say so (fold it into the B1 round; not blocking).
- **Queue group.** Confirmed:
  - #7: `apps/orders/src/main.ts:36-46` has no `queue` option;
  - #8: `14d9a66:src/Orders/Presentation/OrdersCreateResponder.cs:74` is `SubscribeAsync(RpcSubjects.CatalogReferenceList, …)` with no queue;
  - #9: `orders_create_responder.py` `start()` subscribes with `queue=ORDERS_QUEUE_GROUP`, armed by A7.
- **`includeDisabled` filter.** Confirmed:
  - #7 filters in application code (`order-reference-data.repository.ts:131,163`);
  - #8 uses `Where(DisabledAt == null)` (`EfCoreOrderReferenceCatalog.cs:55,78,95`);
  - #9 filters in SQL.

  Every hop is armed: wire A1/A20/A20b, handler A2/A2b, SQL A3/A3b/R8, Gateway route R6, Gateway request R7.
- **Sorted lists.** History halves are correct: #8 `EfCoreOrderReferenceCatalog.cs:58,81,98,107` `OrderBy(Code)`; #7 has no `orderBy`. **The guard does not cover the claim: B1.**
- **Money, JSON bytes, subject, typing gap.** Confirmed by A16, R9, the compact-UTF-8 tests, A13, and `mypy --strict` clean (`Success: no issues found in 806 source files`).

## #8 inherited findings

| #8 id | Verdict | Evidence |
|---|---|---|
| D1 (`includeDisabled` unguarded end to end, no disabled row in the fixture) | **avoided** | one disabled row per kind that has the notion; every hop armed (above), including through the real Gateway (R6, R7, A20b) |
| D2 (an invented history half) | **avoided** | every #7/#8 cell I opened matched its file and line (above) |
| A4 (a named guard owed an arm) | **avoided** | every ledger guard has an arm (A7, A10, A13, A16, A21) |
| A5 (ordering guarded for part of the population) | **recurred**, in sibling-substitution form | deletion is guarded in all four lists (A4/A4b/A4c), substitution in none: B1 |
| A6 (the null-body branch untested) | **avoided** | `test_an_absent_body_is_the_same_as_an_empty_object` (NATS), A17 |

## Settled items the brief asked me to confirm

- **No `test-matrix.md` row.** `grep -n -i "catalog\|feature 40\|orders_catalog" specs/shared/test-matrix.md` gives one hit, line 106: the R11 row, whose "catalogue" refers to the event catalogue. The working-tree `test-matrix.md` diff (9 lines) is entirely feature 25's: R48, R49, R54, R60, R61, R63 and the derived counts. Feature 40 has no row and made no edit. Confirmed.
- **Gateway test deletion.** No hole at the HTTP level today (N2 above for what happens after feature 41).
- **`place_order` accepts disabled rows.** Settled by the leader; not re-opened.

## `./quality.sh` (once, end of review, dev stack down)

| Exit | pytest | Time | Coverage | Other gates |
|---|---|---|---|---|
| **1** | **4 500 passed, 1 failed** | 504.16 s | 97.38% (gate 60%) | ruff `All checks passed!`; mypy `Success: no issues found in 806 source files`; import-linter `Contracts: 13 kept, 0 broken.`; contracts drift `3 generated files match` |

- **Reconciliation.** The implementer had 4 501 passed + 1 failed = 4 502. The leader then deleted one Gateway test, giving 4 501. My run: 4 500 + 1 = 4 501.
- **The one failure is N3**, the pre-existing clock flake, not feature 40's.
- **The web gate (section 7) did not run**, because `set -e` stops after pytest. No web file is in feature 40's change.

`./init.sh` exits 0.

## CHECKPOINTS.md (walked for this feature; C6 not applicable, `sdd: false`)

**C1: harness**
- [x] AGENTS/CLAUDE/CHECKPOINTS/feature_list/init.sh exist
- [x] progress/current.md and history.md exist
- [x] the agents exist
- [x] each agent declares its model (unchanged since the last gate; not re-walked line by line)
- [x] `./init.sh` exits 0

**C2: state**
- [x] at most one feature `in_progress` (after this verdict: feature 40)
- [x] valid statuses (init.sh)
- [x] every `done` feature has passing tests (not affected by this feature)
- [x] current.md describes the active session (the leader owns it)
- [x] no `blocked` feature without a reason (init.sh)

**C3: architecture**
- [x] domain purity: lint-imports, 13 kept, 0 broken; no file under `domain/**` changed
- [x] no cross-service DB access or service import (independence contract kept)
- [x] shared runtime code limited to `shared_kernel`, `contracts` and `cqrs`
- [x] no `domain` imports `otc_cqrs`
- [x] `dependencies = []` unchanged
- [x] no float, `Decimal` or `/` in money (A16 proves a float fails construction; `Money.amount` passed as an int)
- [x] `catalog.reference.list` is a NATS-RPC row (asyncapi `catalogReferenceList`, caller Gateway, responder Orders)
- [x] no stray debug logging

**C4: verification**
- [ ] `./quality.sh` passes: **exit 1**, on N3 (pre-existing, not this feature's code). Must be green before close.
- [x] no domain test added
- [x] integration tests use testcontainers (NATS, PostgreSQL, MongoDB for the Gateway) and passed with the dev stack down
- [x] coverage 97.38%
- [x] no Jest, Karma or Jasmine

**C5: clean close**
- [x] no suspicious untracked files (`.arm/` is git-ignored)
- [ ] history entry with an effort record: not yet, because the feature is rejected
- [x] feature_list reflects state (`in_progress`)
- [ ] human told: not yet, because the feature is rejected
- [x] Claude did not commit

**C7: reuse fidelity**
- [x] `specs/shared/` is unchanged by feature 40 (no edit)
- [x] no deviation needing an `SA-n`: no gap rooted in `specs/shared/` was found, so there is nothing to route
- [ ] every inherited #8 finding is accounted for: D1, D2, A4 and A6 are avoided; **A5 recurred (B1)** and must appear as a recurrence in the effort entry even after the fix
- n/a: R-id claims, n8n workflows, API script and README benchmark do not apply to this feature

## What must change before re-review

1. **B1.** Re-seed `catalog_data` (`services/orders/tests/integration/conftest.py:669-705`) so that each list's order by every sibling column differs from its code order (and still differs from insertion order and its reverse, with and without the disabled row). Re-arm R1, R2, R3, R3b and A4/A4b/A4c, and record the verbatim failures in `progress/impl_orders_catalog_responder.md` (arming table and defeat-list row 3).
2. **N1.** Delete or rename `test_the_listing_handler_reads_the_same_catalog_object_place_order_resolves`. Name `layers-orders` as #9's counterpart of #8's constructor-shape test in the guard-port table.
3. **N3** (leader, routed to `test_maintainer`, outside feature 40): de-flake `services/orders/tests/unit/test_system_clock.py`, so that `./quality.sh` exits 0, including section 7 (web).
4. **N2** (leader): attach the no-responder 503 item to feature 41's acceptance.

Re-review scope: B1's fixture plus the re-run arms, N1, and one `./quality.sh` run. Everything else above is verified and need not be re-walked.

---

## Round 2 (2026-10-12): re-review of B1 and N1 (and N4); one `./quality.sh`

**Verdict: APPROVED.** B1 is fixed. In every list, ordering by every sibling column a refactor could plausibly substitute now fails the ordering tests through the adapter and NATS, and through the Gateway for products and parties. I checked this with the reviewer's own sentinel and 15 code arms, of which 9 are substitutions round 1 did not name. The new fixture self-guard fails when the data regresses to an ordering coincidence (F1, F2). N1 and N4 are closed. `./quality.sh` exits 0. Two non-blocking findings carry dispositions: N5 (one new test name overstates what it asserts) and N6 (one population member is guarded for deletion only by its siblings).

Scope, as fixed by round 1's "What must change": B1's fixture and the re-run arms, N1 (and N4), and one `./quality.sh`. Nothing else was re-walked. N2 (feature 41 acceptance item, confirmed present in `feature_list.json` id 41) and N3 (`test_system_clock.py`) belong to the leader. Inputs: round 1 above; `progress/impl_orders_catalog_responder.md` "Round 2" and its guard-port table (line 58); `progress/brief_impl_orders_catalog_responder_round2.md`; `services/orders/tests/integration/conftest.py` (`catalog_data`); `test_catalog_data_fixture.py`; `infrastructure/persistence/models.py`; `infrastructure/persistence/reference_catalog.py`. Dev stack down throughout (`docker ps`: `otcpy-n8n` only, before and after).

### B1: the reviewer's own sentinel (computed before any arm)

Method: `.arm/r40r2/orders.py` reads the `currencies`, `products` and `parties` literals out of `catalog_data` with `ast.literal_eval`, so it does not trust the implementer's table. It derives code order and insertion order. For every non-key column in `models.py` it computes the order and whether any tie resolution could equal code order. The columns are: product `ean`, `name`, `description`, `price`, currency code and `disabled_at`; party `name`, `country`, `vat`, `gln`, currency code and `disabled_at`; currency `iso_number`, `symbol` and `decimal_points`.

| list | population | code | insertion / reverse | sibling orders | coincides |
|---|---|---|---|---|---|
| products | +disabled | A B C D | B D C A / A C D B | ean B D A C; name C A D B; description D A C B; price A B D C; currency (A,D) B C; disabled_at B C A D | none |
| products | enabled | A B C | B C A / A C B | ean B A C; name C A B; description A C B; disabled_at B C A | **price A B C, currency A B C** |
| retailers | +disabled | K M N X | N X K M / M K X N | name M K X N; country N M X K; vat N K M X; gln X M N K; currency, disabled_at differ | none |
| retailers | enabled | K M N | N K M / M K N | name M K N; country N M K; vat N K M; gln M N K | none |
| companies | +disabled | P Q R S | R S P Q / Q P S R | name Q S P R; country Q R S P; vat R P S Q; gln S R Q P | none |
| companies | enabled | P Q R | R P Q / Q P R | name Q P R; country Q R P; vat R P Q; gln R Q P | none |
| currencies | (no disabled) | EUR JPY USD | USD EUR JPY / JPY EUR USD | iso_number JPY USD EUR; symbol USD JPY EUR; decimal_points JPY (USD,EUR) | none |

Every cell the implementer's Round 2 table states matches mine. The two coincidences are `price` and the joined currency code over the enabled products only. The implementer disclosed both ("not covered, by construction"). With the disabled row present they differ, so the `[True]` tests must kill them, and X2 and X3 below show that they do. `currency_id` and `id` are random `uuid4` values, so an `ORDER BY id` substitution survives a single run with probability 1/6 (3 rows) or 1/24 (4 rows) per test. Across the five tests per list that is negligible. It is not a deterministic guard, and I record it here rather than claim it.

### Arms (reviewer's own; runner `.arm/r40r2/arm.py`, raw output `.arm/r40r2/<arm>.out`, records `.arm/r40r2/arms.jsonl`)

Method for every arm:
- copy the file to `.arm/r40r2/<arm>.bak` and record its `sha256`: `reference_catalog.py` `9707cb1287863391…`, `conftest.py` `2414c314f80354c9…`;
- apply the mutation and run the named tests with `timeout -k 10 420` in a new session (`start_new_session=True`; on timeout, `killpg`);
- restore with `cp`, then check with `cmp` plus a sha256 re-check: **identical in all 18 arms**;
- remove `__pycache__`.

At the end, `sha256sum` of both files equals `.arm/r40r2/sha_before.txt`. The green baseline before arming was the six feature 40 test files: `98 passed in 25.48s`.

The ordering arms run five tests per product mutation and seven per party mutation: the adapter `[False]` and `[True]`, NATS `test_every_list_is_ordered_by_code…` (which uses `include_disabled=True`), Gateway `test_the_gateway_route_returns_the_seeded_enabled_rows…`, and Gateway `test_include_disabled_through_the_gateway_adds_the_disabled_row`.

| Arm | Named in round 1? | Mutation (`reference_catalog.py`) | Result |
|---|---|---|---|
| R1 | yes | products `.order_by(Product.name)` | **5 failed**, 7 passed: adapter `[False]` `[True]`, NATS `[products]`, Gateway enabled + include-disabled `/catalog/products`. `At index 0 diff: {'code': 'PRD-C', … 'name': 'Anvil carton' …} != {'code': 'PRD-A', …` |
| R3b | yes | products `.order_by(Product.ean)` | **5 failed** (same five): `At index 0 diff: {'code': 'PRD-B', 'ean': '5400000000018' …} != {'code': 'PRD-A' …` |
| X1 | **no** | products `.order_by(Product.description)` | **5 failed** (same five): `At index 0 diff: {'code': 'PRD-D', … 'description': 'dried fruit, ten-kilo sack' …} != {'code': 'PRD-A' …` |
| X2 | **no** | products `.order_by(Product.price)` (the enabled-only coincidence) | **3 failed**, 9 passed: adapter `[True]`, NATS `[products]`, Gateway include-disabled. `assert ['PRD-A', 'PR...D-D', 'PRD-C'] == ['PRD-A', 'PR...D-C', 'PRD-D']`. The enabled-only tests pass, as the sentinel predicted. |
| X3 | **no** | products `.order_by(Currency.code)` (the joined label) | **3 failed** (same three): `At index 1 diff: 'PRD-D' != 'PRD-B'` |
| R2 | yes | parties `.order_by(table.name)` | **10 failed**, 4 passed: adapter retailers and companies `[False]` `[True]`, NATS `[retailers]` `[companies]`, Gateway enabled and include-disabled for both. `At index 0 diff: {'code': 'RET-M', 'name': 'Albacete Foods' …} != {'code': 'RET-K' …` |
| X4 | **no** | parties `.order_by(table.vat)` | **10 failed** (same ten): `{'code': 'RET-N', … 'vat': 'AA1234567' …} != {'code': 'RET-K' …` |
| X5 | **no** | parties `.order_by(table.gln)` | **10 failed** (same ten): `{'code': 'RET-X', … 'gln': '4012345000016' …} != {'code': 'RET-K' …` |
| X6 | **no** | parties `.order_by(table.country)` | **10 failed** (same ten): `{'code': 'RET-N', … 'country': 'AT' …} != {'code': 'RET-K' …` |
| R3 | yes | currencies `.order_by(Currency.symbol)` | **2 failed**, 3 passed: adapter `test_currencies_…`, NATS `[currencies]` |
| X7 | **no** | currencies `.order_by(Currency.iso_number)` | **2 failed** (same two) |
| X8 | **no** | currencies `.order_by(Currency.decimal_points)` | **2 failed** (same two) |
| A4 | yes | products `ORDER BY` deleted | **5 failed** (the five product tests) |
| A4b | yes | parties `ORDER BY` deleted | **7 failed**, 7 passed. Adapter retailers `[False]` `[True]`, companies `[False]`; NATS `[retailers]`; Gateway enabled retailers and companies; Gateway include-disabled retailers. **Companies `[True]`, NATS `[companies]` and Gateway include-disabled companies pass: N6.** |
| A4c | yes | currencies `ORDER BY` deleted | **2 failed** (adapter, NATS `[currencies]`) |

The Gateway does not exercise the currency list (no Gateway currencies route test), the same as in round 1. The currency claim is held at the adapter and NATS levels.

**Fixture self-guard armed** (mutations to `conftest.py`, test `test_catalog_data_fixture.py`):

| Arm | Mutation | Result |
|---|---|---|
| F1 | companies `gln` reassigned so that gln order = code order (P 013, Q 020, R 037, S 044) | **2 failed**, 17 passed: `test_no_sibling_column_orders_a_list_the_way_its_code_does[companies-False]` and `[companies-True]` |
| F2 | currency symbols reverted to round 1's `US$` / `EU€` / `JP¥` (the original B1 coincidence) | **2 failed**, 17 passed: `[currencies-False]` and `[currencies-True]` |
| F3 | product B's name `Dune crate` → `Anvil carton plus` (distinct, but contains product C's `Anvil carton`) | **survived**, `3 passed` on `test_every_sibling_column_value_is_distinct_and_contained_in_no_other`: N5 |

The self-guard is armed for its central claim (F1, F2). Its premise is that Python's codepoint sort predicts PostgreSQL's collation. For this data every arm's observed first-differing row matched the sentinel's prediction, so the premise held empirically. Every column here is decided at a first character that is an uppercase ASCII letter or a digit. Re-open trigger: values that differ only in case or punctuation.

### Non-blocking (each with a disposition)

- **N5: a new test name overstates its assertion.** `services/orders/tests/integration/test_catalog_data_fixture.py:57` `test_every_sibling_column_value_is_distinct_and_contained_in_no_other` asserts only `len(set(values)) == len(values)`. F3 shows it passes when one value contains another. This is the same class as round 1's N1, introduced by the fix. The property itself holds today: `.arm/r40r2/contain.py`, over the AST-extracted literals, finds `containment hits: 0` within each column and within each row. No assertion in feature 40 relies on containment, because the comparisons are dict and list equality. **Disposition:** fix in this phase as a light, test-only change routed by the leader to `test_maintainer`. Either rename the test to `…_is_distinct`, or add the substring check and arm it with F3. It does not gate feature 40.
- **N6: deleting the party `ORDER BY` is not seen by the companies include-disabled population.** In A4b, the unordered join returns companies in `P Q R S` order. That is code order, even though insertion is `R S P Q`. Because the projected query joins `currencies`, the planner, not insertion order, sets the unordered order. The fixture's insertion-order premise ("unordered output = insertion order") is therefore weaker than the docstring reads. The deletion is still killed for companies, by the adapter's `[False]` and the Gateway's enabled `/catalog/companies`, and for every list overall. The substitution arms are unaffected. **Disposition:** accept with evidence (A4b, `.arm/r40r2/A4b-parties-no-order.out`). Re-open trigger: `_list_parties` is split per table, or the `ORDER BY` becomes conditional on `include_disabled`. Either change would leave companies `[True]` as the only test of a code path.

### N1 and N4 verified

- `grep -rn "reads_the_same_catalog_object\|flushed_after\|_scope.catalog is" services tests packages --include=*.py` gives **no output, exit 1**. The overstated test and the dead `flushed_after` state are gone. The remaining `flush` references are the asserted `connection.flushes == [2]` (`test_catalog_reference_list.py:346`, A14) and `FakeConnection.flush` (`test_orders_create_responder.py:77`, which returns `None`).
- The guard-port table, `progress/impl_orders_catalog_responder.md:58`, now names A21 and `layers-orders`. `pyproject.toml:280-289` is that contract (presentation > infrastructure > application > domain), as round 1 asked.

### `./quality.sh` (once, dev stack down; log `.arm/r40r2/quality.log`)

| Exit | pytest | Time | Per test | Coverage | Other gates |
|---|---|---|---|---|---|
| **0** (`quality.sh: all gates passed`) | **4 519 passed**, 0 failed | 513.89 s (534.42 s wall for the script) | 0.1137 s | 97.38% (gate 60%) | ruff `All checks passed!`; mypy `Success: no issues found in 807 source files`; import-linter `Contracts: 13 kept, 0 broken.`; contracts drift `3 generated files match`; web (section 7) ran: Vitest `Tests 1 passed (1)`, Analog build OK |

Reconciliation: round 1 had 4 500 + 1 = 4 501. Round 2 adds 19 (`test_catalog_data_fixture.py`) and removes 1 (N1), giving 4 519. That matches this run and the implementer's second run. `./init.sh` exits 0.

### R / acceptance mapping touched by this round

Feature 40 owns no `R<n>` (round 1, "No `test-matrix.md` row", confirmed). The claim this round re-proves is the port's "listed in code order". It is now held per list and per population:
- products and parties by the adapter `test_{products,retailers,companies}_are_listed_field_for_field_in_code_order[False|True]`, NATS `test_every_list_is_ordered_by_code_not_by_insertion_or_its_reverse[<kind>]`, and the two Gateway route tests;
- currencies by the adapter and NATS.

Each one is armed by deletion and by substitution of every sibling column (table above).

### CHECKPOINTS.md (only the boxes this round changes; the rest stand as walked in round 1)

- C4 [x] `./quality.sh` passes: exit 0, including section 7 (web). Round 1's open box is now closed.
- C4 [x] integration tests use testcontainers and pass with the dev stack down.
- C5 [x] no suspicious untracked files (`.arm/` is git-ignored, `.gitignore:87`).
- C5 [ ] **history entry with an effort record: owed by the leader.** Per the brief, this reviewer writes only this section and feature 40's status line. Feature 40 is not closeable until `progress/history.md` carries its entry: sessions, wall-clock, full classification, and the rejection round. In it, #8 A5 is **recurred** (round 1 B1, sibling-substitution form) and **closed in round 2**; D1, D2, A4 and A6 are **avoided**.
- C5 [x] feature_list reflects state: id 40 → `done` (this line only).
- C5 [x] Claude did not commit; no index-writing git command was run.
- C7 [x] every inherited #8 finding is accounted for (above). No gap rooted in `specs/shared/` was found, so there is nothing to route as an `SA-n`.
