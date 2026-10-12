# Implementation record — feature 40 `orders_catalog_responder` (phase 13, `sdd: false`, full group)

Status set to `in_review` (that line only). Result of `./quality.sh`: **exit 1, by one test outside my bounds** (section 9): 4 501 passed, 1 failed, and the failing test is the Gateway's own `test_the_catalog_routes_answer_the_mapped_no_responder_error_until_feature_40`, which asserts the very state this feature ends. I may not edit `services/gateway/**`; the leader must flip it (section 10).

## 1. What was built

`catalog.reference.list` is answered by the Orders service, over the same NATS responder and the same queue group as `orders.create`.

| Layer | File | What |
|---|---|---|
| port | `services/orders/src/otc_orders/application/ports/reference_catalog.py` | `ReferenceCatalog` widened with `list_products(*, include_disabled)`, `list_retailers`, `list_companies`, `list_currencies()`; read views `ProductListing` (price is `Money`), `PartyListing`, `CurrencyListing` |
| query | `application/queries/list_reference_data.py` (new) | `ListReferenceDataQuery(Query[ReferenceListing])` (`kinds: frozenset[ReferenceKind]`, `include_disabled`) and `ListReferenceDataQueryHandler(scope)`, which asks `scope.catalog`; a kind not asked for stays `None` |
| adapter | `infrastructure/persistence/reference_catalog.py` | the four `list_*` on the ONE `SqlAlchemyReferenceCatalog`: plain SELECT, `ORDER BY code`, `WHERE disabled_at IS NULL` unless `include_disabled`, own short session closed by `async with` |
| wire | `presentation/catalog_reference_list.py` (new) | `decode_request` (generated `CatalogReferenceListRequestPayload`, strict; absent body = all defaults), `to_query`, `to_reply` (generated `Product`/`Party`/`CurrencyView`), `encode` (`to_wire_json`) |
| responder | `presentation/orders_create_responder.py` | a `ROUTES` table (`orders.create`, `catalog.reference.list`); both subscribed in queue group `otc-orders`; `start()` now AWAITS `flush()` after the last subscribe; the class keeps its name (precedent below) |
| errors | `presentation/orders_create.py` | `map_error` maps `InvalidCatalogReferenceListRequestError` to `VALIDATION_FAILED` beside the orders.create refusal |
| subjects | `infrastructure/messaging/subjects.py` | `CATALOG_REFERENCE_LIST_SUBJECT = "catalog.reference.list"` |
| root | `composition.py` | one statement: `registry.register_query(ListReferenceDataQuery, ListReferenceDataQueryHandler)` |

Currencies: `includeDisabled` has no effect on them (the `currencies` table has no `disabled_at`); the Gateway never asks for them (its three routes send one of products, retailers, companies), but the contract lists the kind and the responder answers it.

## 2. Decisions (with citations)

**One task, a route table (not a second task, not a second class).** CLAUDE.md "One asyncio task class per transport". #7 serves both subjects from one microservice (`apps/orders/src/presentation/catalog-reference-list.controller.ts` beside `orders-create.controller.ts`, one `createOrdersNatsMicroserviceOptions`, `main.ts:36-46`). #8 added the second subject to the existing `OrdersCreateResponder` and says "never a second `BackgroundService`" (`../order-to-cash-dotnet/progress/history.md:1684-1706`; `OrdersCreateResponder.cs` at `14d9a66`, `Task.WhenAll` over one loop per subject). #9 already has the pattern twice: `services/billing/src/otc_billing/presentation/credit_responder.py:1-12` (`ROUTES`, "added WITHOUT renaming the class") and Fulfillment's `StockResponder`. I followed it, keeping `OrdersCreateResponder`'s name.

**Queue group: yes.** #7 sets none (`main.ts:40-46`, no `queue` option; `grep -rn queue apps/orders/src/main.ts` has no hit). #8 subscribed the catalog subject without one (`OrdersCreateResponder.cs:74` `SubscribeAsync(RpcSubjects.CatalogReferenceList, ...)`, no queue argument) and its review left that as an item for the Gateway's brief (`history.md:1706`, "subscribed without a NATS queue group"). #9's `orders.create` already uses `queue=ORDERS_QUEUE_GROUP` (`subjects.py:8`, the old `start()`), and Billing/Fulfillment do the same for every subject, so the catalog joins `otc-orders`. Armed: A7.

**`flush()` after the subscribes.** The old `start()` returned after `subscribe`; Billing's does `await self._connection.flush()` after the last one ("the host is reachable when startup returns", `credit_responder.py:8-10`, #8 id 63/95). A request right after boot could otherwise find no responder, the race #8's fix round closed. Armed: A14.

**Empty body.** An absent body is the all-defaults request, because every field of the request schema is optional and #7's controller does the same (`catalog-reference-list.controller.spec.ts:33`, "defaults an omitted request body to kinds: [] ... includeDisabled: false"). `orders.create` refuses an empty payload because its schema has required fields. Armed: A17.

**Widen the port (as #8) rather than alias two ports (as #7).** #7: two ports on one adapter (`catalog-reference-list.port.ts:1-21`, `app.module.ts:134-137` `useExisting: ORDER_REFERENCE_DATA`), chosen so the existing fake did not grow. #8: widened `IOrderReferenceCatalog`; its fake grew four methods (`history.md:1684-1706`). #9: widened, because acceptance item 2 says the lookup order acceptance already calls "exposed as a query", and the scope has one `catalog` slot; the price is that `FakeCatalog` in `test_place_order_handler.py` grew four methods that raise `AssertionError` (placing an order must not list), which turns the cost into a guard.

**Ordering by `code`, in SQL.** #8 orders in each list (`EfCoreOrderReferenceCatalog.cs` at `14d9a66`, lines 58, 81, 98, 107: `OrderBy(Code)` x4). #7 does not order (`order-reference-data.repository.ts`, no `orderBy`/`asc`; it filters in application code at lines 131 and 163). The spec does not require an order; a stable one makes the Gateway's pages deterministic, so #9 follows #8 and guards all four lists (A5 of #8).

## 3. Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied it with | in #9 it is supplied by | Guard (armed) | What turns red if the row were false |
|---|---|---|---|---|---|
| The listing reads through the SAME adapter place-order uses | `useExisting` alias of two tokens to one class (`app.module.ts:134-137`); two separate ports (`catalog-reference-list.port.ts:1-21`) | one widened port, one `EfCoreOrderReferenceCatalog` (`CatalogReferenceListPortReuseTests.cs:41`, `:68` at `14d9a66`) | `catalog = SqlAlchemyReferenceCatalog(sessions)` once (`composition.py`), bound in `scope_factory`; both handlers read `self._scope.catalog` | `test_the_reference_catalog_adapter_is_constructed_once_and_only_by_the_composition_root` (AST count of the constructor over `src`, sentinel for the attribute form and the comment form); A21 (a second construction) | `{'composition.py': 2} == {'composition.py': 1}` |
| Which collections to read | controller defaults `kinds` to `[]` meaning all (`controller.spec.ts:33`) | validator + `HandleAsync` per kind | `ListReferenceDataQueryHandler` tests each kind; `to_query` defaults to `list(Kind)` | `test_only_the_requested_collection_is_read_and_the_others_stay_none[x4]`; A5, A5b-d, A19, A22 | the handler reads a collection nobody asked for |
| `includeDisabled` filter | applied in application code after one SELECT (`order-reference-data.repository.ts:131,163`); controller default false (`controller.spec.ts:33`) | `Where(DisabledAt == null)` in each list (`EfCoreOrderReferenceCatalog.cs:55,78,95`) | `WHERE disabled_at IS NULL` in the SELECT, unless `include_disabled` | D1 below: wire (`test_include_disabled_true_reaches_the_query`), handler (`test_include_disabled_reaches_every_listing...`), SQL (`..._listed_field_for_field_in_code_order[True/False]`), NATS (`test_include_disabled_true_adds_the_disabled_row...`), Gateway (`test_include_disabled_through_the_gateway...`); A1, A2, A2b, A3, A3b, A20, A20b | the disabled row appears (or vanishes) when it should not |
| Sorted lists | none (heap order, accidental) | `OrderBy(Code)` x4 | `ORDER BY code` x4 | one integration test per list with a fixture whose insertion order differs from code order and from its reverse; A4, A4b, A4c | first element is the insertion-first row, not the code-first row |
| Subject equals the contract's channel address | literal in the controller decorator | `RpcSubjectsTests` | `CATALOG_REFERENCE_LIST_SUBJECT` read from the YAML by channel id | `test_the_catalog_subject_is_the_address_of_the_catalog_reference_list_channel`; A13 | `'catalog.reference.list' == 'catalog.references.list'` |
| Queue group | none (no option, `main.ts:40-46`) | none (the open item) | `queue=ORDERS_QUEUE_GROUP` in `start()` | `test_the_responder_subscribes_both_subjects_in_the_queue_group_and_flushes_after`; A7 | `('orders.create', 'otc-sibling') != ('orders.create', 'otc-orders')` |
| Money as integer minor units | `price: number` | `long` | `Money.amount` (int) into the generated strict `int` field | `test_the_reply_carries_each_field_...integer_money`, `test_prices_are_integer_minor_units_...`; A16 (`/ 1`) | pydantic `Input should be a valid integer ... input_value=1999.0` |
| JSON bytes | Nest serializer | `System.Text.Json` options | `to_wire_json` (compact, camelCase, non-ASCII raw, `None` omitted) | `test_the_reply_is_compact_json_with_non_ascii_written_raw`, `test_prices_are_integer_minor_units_and_the_reply_is_compact_utf8` | extra spaces / `€` / `null` collections |
| Session ownership (event-loop affinity) | per-request Drizzle pool | `DbContext` per request | each `list_*` opens `async with self._sessions()` from the lifespan's `async_sessionmaker`; no module-level session | `test_the_listings_issue_reads_only_and_hold_no_lock` (`engine.pool.checkedout() == 0`, statement log: 4 SELECTs, no write verb, no `FOR UPDATE`/`FOR SHARE`); A10 (a lock added) | `['SELECT ... FOR UPDATE'] == []` |
| Typing gap (`Any` from `Row`) | n/a | n/a | `row.code`, `row.price` are `Any` from SQLAlchemy `Row`; every listing field is passed into a typed dataclass that `Money`/pydantic then validate; `mypy --strict` clean | the generated models are strict (A9, A16 fail at construction) | validation error naming the field |

## 4. Guard-port table (enumerating #8's tests for this mechanism by content)

| #8 test (commit `14d9a66`) | Assertion | Disposition |
|---|---|---|
| `CatalogReferenceListAcceptanceTests` x5: kinds omitted returns all four; one kind omits the other three from the wire; `includeDisabled` true vs omitted; unknown kind refused as VALIDATION_FAILED; orders.create still answers concurrently | ported | `test_kinds_omitted_returns_the_four_collections...`, `test_only_the_requested_kind_is_present_in_the_reply[x4]`, `test_include_disabled_true_adds_the_disabled_row...[x3]`, `test_a_malformed_request_is_answered_validation_failed...[x7]`, `test_orders_create_still_answers_on_the_same_responder` (sequential, not concurrent: the concurrency of the task is `test_requests_are_served_concurrently_a_slow_one_does_not_hold_the_next`, unchanged) |
| `EfCoreOrderReferenceCatalogListTests` x8: each list with and without the disabled row, every field; currencies field for field; products ordered by code | ported and widened | `test_{products,retailers,companies}_are_listed_field_for_field_in_code_order[False/True]`, `test_currencies_...`, ordering for ALL four (the A5 finding) |
| `CatalogReferenceListPayloadTests` x9: camelCase keys of each payload, optionals omitted not null, only requested collections present, BC23 retyped key lists vs asyncapi, G5 renamed-property scratch copy | partly not applicable: #9 has no hand-written payload record; the generated models ARE the contract (`otc_contracts.generated.asyncapi`). Ported as the reply-document tests | `test_the_reply_carries_each_field_...`, `test_a_collection_that_was_not_asked_for_is_absent...`. The key-list comparison is deliberately not ported (no retyped list exists) |
| `CatalogReferenceListPortReuseTests` x2: exactly one implementation registered; both handlers depend on the catalog | ported as an AST count (A21) and, for the "handlers depend on the port" half, by `layers-orders` (pyproject.toml:282-289: application cannot import infrastructure), #9's counterpart of #8's constructor-shape test. The unit test that claimed it by asserting `handler._scope.catalog is catalog` was deleted in Round 2 (N1: true by construction) | `test_the_reference_catalog_adapter_is_constructed_once_...` |
| `CatalogReferenceListRequestValidatorTests` x4: omitted ok, every declared value ok, empty array refused, unknown value refused | ported | `test_a_request_the_schema_refuses_is_a_validation_failure...[x8]`, `test_the_kinds_field_reaches_the_query` |
| `ListCatalogReferenceQueryHandlerTests` x6: only products; all four; fields unchanged; `includeDisabled` passed through false and true to every requested list; disabled product excluded | ported | the handler tests in `test_catalog_reference_list.py` |
| `RpcSubjectsTests` (catalog subject) | ported | `test_rpc_subjects.py` |
| #7 `catalog-reference-list.controller.spec.ts` x4: reply as-is; omitted body defaults; unknown kind returns VALIDATION_FAILED; bus rejection returns INTERNAL_ERROR, never throws | ported | `test_an_absent_body_is_...`, `test_a_malformed_catalog_request_is_answered_with_validation_failed`, `test_a_failing_read_is_answered_with_internal_error...` (also asserts the exception text, with a password, is NOT in the reply: A18) |

## 5. Tests added (no `R<n>`; `sdd: false`) — 75 tests, 4 427 to 4 502

| File | Tests | Proves |
|---|---|---|
| `services/orders/tests/unit/test_catalog_reference_list.py` | 33 | request decoding, query, handler fan-out, reply bytes, responder subscriptions and refusal path, single construction |
| `services/orders/tests/unit/test_rpc_subjects.py` | +1 | subject equals channel address |
| `services/orders/tests/integration/test_reference_catalog_listing.py` | 9 | the adapter against PostgreSQL: every field, filter, ordering of the four lists, reads only, no lock, session closed |
| `services/orders/tests/integration/test_catalog_reference_list_responder.py` | 24 | the real host over real NATS |
| `services/orders/tests/integration/test_catalog_through_gateway.py` | 8 | acceptance 1 through the REAL Gateway (`otc_gateway.main.create_app()`, its NATS client) against the real Orders host and PostgreSQL, no stub; 401 without a token |

Fixture `catalog_data` (`tests/integration/conftest.py`): rows for four kinds, one disabled row per kind that has the notion; insertion orders B,D(disabled),C,A / N,X(disabled),K,M / R,S(disabled),P,Q / USD,EUR,JPY against code orders A,B,C,D / K,M,N,X / P,Q,R,S / EUR,JPY,USD, so each differs from its code order and from its reverse, with and without the disabled row. Every value in a row is distinct from every other in the same row (price, ean, gln, vat, name, description all differ; no value contains another).

Existing tests edited (all inside `services/orders/tests/**` or `tests/architecture/**`, each because a literal had to include the new registration or port method):

| File | Edit | Why |
|---|---|---|
| `services/orders/tests/unit/test_orders_create_responder.py` | `FakeConnection` keeps one subscription per subject and has `flush` | the responder now subscribes two subjects and flushes |
| `services/orders/tests/unit/test_place_order_handler.py` | `FakeCatalog` has the four `list_*` methods, each raising | the port widened |
| `services/orders/tests/integration/test_orders_host_lifespan.py` | boot-refusal test: 11 → 12 problems (+ the query by name); the "one handler missing" wrapper forwards `register_query` | one more registration |
| `tests/architecture/test_registration_behaviour.py` | `TABLES["orders"]["queries"]` names `ListReferenceDataQuery` | the registration census |
| `tests/architecture/test_write_path_population.py` | `reference_catalog.py` `execute` count 3 → 6, with the reason | three more SELECTs |

## 6. Arming table

Runner: `.arm/n40/arm.py` (backup of the file in `.arm/n40/<arm>.bak`, the ONE named test, process group killed on timeout, restore by `cp`, `cmp`, `__pycache__` of that directory removed). Every arm restored `identical`. `sha256` is of the file before the mutation (the `.bak`). Messages are the first `E` lines of the run (verbatim, truncated by pytest where it truncates).

| Arm | Mutation | Test that failed | Message | sha256 (file) | cmp |
|---|---|---|---|---|---|
| A1 | `to_query`: `include_disabled=bool(request.include_disabled)` → `False` | `test_include_disabled_true_reaches_the_query` | `AssertionError: assert False is True` | `39290fe8…` (catalog_reference_list.py) | identical |
| A2 | handler passes `False` to `list_products` | `test_include_disabled_reaches_every_listing_that_has_the_notion` | `assert (False, True, True) == (True, True, True)` | `6702d745…` (list_reference_data.py) | identical |
| A2b | handler passes `True` to `list_companies` | same | `assert (False, False, True) == (False, False, False)` | `6702d745…` | identical |
| A3 | products: drop the `disabled_at IS NULL` filter | `test_products_are_listed_field_for_field_in_code_order` | `Left contains one more item: {'code': 'PRD-D', ... 'Delta drum' ...}` | `9707cb12…` (reference_catalog.py) | identical |
| A3b | parties: drop the filter | `test_retailers_...`/`test_companies_...` | `Left contains one more item: {'code': 'RET-X', 'name': 'Xenon Stores' ...}` | `9707cb12…` | identical |
| A4 | products: drop `ORDER BY` | `test_products_are_listed_field_for_field_in_code_order` | `At index 0 diff: {'code': 'PRD-B' ...}` | `9707cb12…` | identical |
| A4b | parties: drop `ORDER BY` | `test_retailers_...` | `At index 0 diff: {'code': 'RET-N' ...}` | `9707cb12…` | identical |
| A4c | currencies: drop `ORDER BY` | `test_currencies_...` | `At index 0 diff: {'code': 'USD' ...} != {'code': 'EUR' ...}` | `9707cb12…` | identical |
| A5 | handler: retailers read regardless of `kinds` (first run: SURVIVED) | first `test_only_the_requested_collections_are_read...` (retailers only) passed | **survivor**: the test asked for retailers alone, the mutation is invisible there. Fixed: the test is parametrised over all four kinds; re-run: `AssertionError: products alone was requested / assert ['products', 'retailers'] == ['products']` | `6702d745…` | identical |
| A5b / A5c / A5d | same for products / companies / currencies | `test_only_the_requested_collection_is_read_and_the_others_stay_none` | `retailers alone was requested`, `products alone was requested` x2 | `6702d745…` | identical |
| A6 | `ROUTES` loses the catalog entry | `test_the_responder_subscribes_both_subjects_...` | `Right contains one more item: ('catalog.reference.list', 'otc-orders')` | `b26f5be1…` (orders_create_responder.py) | identical |
| A7 | queue group `otc-sibling` | same | `('orders.create', 'otc-sibling') != ('orders.create', 'otc-orders')` | `b26f5be1…` | identical |
| A8 | `map_error` loses the catalog refusal case | `test_a_malformed_catalog_request_is_answered_with_validation_failed` | `assert 'INTERNAL_ERROR' == 'VALIDATION_FAILED'` | `dbb19135…` (orders_create.py) | identical |
| A9 | party `gln=listing.vat` | `test_the_reply_carries_each_field_...` | `ValidationError ... gln String should match pattern '^[0-9]{13}$' input_value='ESV1'` | `39290fe8…` | identical |
| A9b | product `currency='USD'` constant | same | `assert {'products': ...} == {'products': ...}` | `39290fe8…` | identical |
| A10 | `.with_for_update()` on the product SELECT | `test_the_listings_issue_reads_only_and_hold_no_lock` | `assert ['SELECT prod...e FOR UPDATE'] == []` | `9707cb12…` | identical |
| A11 | retailers read from the Company table (sibling table) | `test_retailers_are_listed_field_for_field_in_code_order` | `At index 0 diff: {'code': 'CMP-P', ...}` | `9707cb12…` | identical |
| A12 | `enabled=row.disabled_at is not None` (products) | `test_products_are_listed_field_for_field_in_code_order` | `At index 0 diff: {'code': 'PRD-A' ...}` | `9707cb12…` | identical |
| A13 | subject `catalog.references.list` (sibling subject) | `test_the_catalog_subject_is_the_address_of_the_catalog_reference_list_channel` | `channel catalogReferenceList: the subject Orders answers is not the spec's address` | `893daf84…` (subjects.py) | identical |
| A14 | `flush()` removed | `test_the_responder_subscribes_both_subjects_...` | `assert [] == [2]` | `b26f5be1…` | identical |
| A15 | `register_query` line deleted | `test_the_wire_flag_reaches_the_catalog_through_the_built_dispatcher` | `DispatcherValidationError: No query handler is registered for ListReferenceDataQuery. Exactly one is required.` | `2c68f205…` (composition.py) | identical |
| A16 | `price=listing.price.amount / 1` | `test_the_reply_carries_each_field_...` | `Input should be a valid integer [type=int_type, input_value=1999.0, input_type=float]` | `39290fe8…` | identical |
| A17 | empty body refused | `test_an_absent_body_is_the_all_kinds_enabled_only_request` | `InvalidCatalogReferenceListRequestError: catalog.reference.list request is invalid: (body).` | `39290fe8…` | identical |
| A18 | `INTERNAL_ERROR` message = `str(error)` | `test_a_failing_read_is_answered_with_internal_error_that_carries_no_internal_text` | `assert 'hunter2' not in '{"code": "I...` | `dbb19135…` | identical |
| A19 | `kinds` empty/None → products only | `test_an_absent_body_is_the_all_kinds_enabled_only_request` | `Extra items in the right set: <ReferenceKind.RETAILERS: 'retailers'>` | `39290fe8…` | identical |
| A20 | `to_query` `include_disabled=True` constant | `test_include_disabled_true_adds_the_disabled_row_marked_not_enabled` (NATS) | `assert [True, True, True, False] == [True, True, True]` | `39290fe8…` | identical |
| A20b | `to_query` `include_disabled=False` constant, seen THROUGH the Gateway | `test_include_disabled_through_the_gateway_adds_the_disabled_row` | `Right contains one more item: {'code': 'PRD-D', ... 'Delta drum' ...}` | `39290fe8…` | identical |
| A21 | a second `SqlAlchemyReferenceCatalog(sessions)` in the root | `test_the_reference_catalog_adapter_is_constructed_once_and_only_by_the_composition_root` | `assert {'composition.py': 2} == {'composition.py': 1}` | `2c68f205…` | identical |
| A22 | `kinds` ignored on the wire (always all four) | `test_only_the_requested_kind_is_present_in_the_reply` | `Left contains 3 more items, first extra item: 'retailers'` | `39290fe8…` | identical |

Raw output: `.arm/n40/arms.jsonl`, `arms2.jsonl`, `arms3.jsonl` (A1 was run first, alone, and its line is in this table only).

**Defeat list (CLAUDE.md, twelve rows), the ones that apply.** 1 delete the behaviour: A3, A4*, A6, A14, A15, A17. 2 corrupt a supplied field: A9, A9b, A16. 3 substitute a sibling identifier: A7 (queue group), A11 (sibling table), A13 (sibling subject). 4 shadow in a comment or string: the construction counter walks the AST (`test_the_construction_counter_sees_a_second_construction_and_an_attribute_form` feeds it a comment containing the constructor and requires 0). 5 and 6 dead region / raw string: the counter counts a call under `if False:` (stricter, by design) and ignores a string. 7 drop an optional element: A17 (the body), A19 (`kinds`). 8 literal vs literal: the expected rows are the fixture's own tuples, the production code never sees them. 9 closer half satisfied, premise stale: A5 (the first test satisfied "retailers" and left three kinds unguarded; fixed by parametrising). 10 build output / caches: `__pycache__` removed after each arm. 11 a form the instrument does not recognise: the counter handles `Name` and `Attribute` calls (sentinel). 12 failure through a path the population never drives: A20b (the flag lost between request and the Gateway's reply is seen through the Gateway).

## 7. Inherited findings

| Finding | Verdict | Evidence |
|---|---|---|
| D1 (`includeDisabled` unguarded end to end, fixture without a disabled row) | **avoided** | A1, A2, A2b, A3, A3b, A20, A20b; the fixture seeds one disabled row for each of products, retailers, companies |
| D2 (a ledger half invented) | **avoided** | every "#7 relied on" and "#8 supplied" cell cites a file and line read this session; where #7 had nothing (queue group, ordering) the cell says so, with the grep |
| A4 (a guard named in the ledger is owed an arm) | **avoided** | every guard in the ledger has an arm: A21 (single construction), A7 (queue group), A13 (subject), A16 (money), A10 (reads only) |
| A5 (ordering guarded for products only) | **avoided** | A4, A4b, A4c plus the four per-kind ordering tests; the fixture's insertion order differs from code order and from its reverse |
| A6 (the `message.Data is null` branch untested) | **avoided** | `test_an_absent_body_is_the_same_as_an_empty_object` (NATS) and `test_an_absent_body_is_the_all_kinds_enabled_only_request`, A17 |

New in #9, recorded: my first armed run SURVIVED once (A5). The per-kind handler test asked for retailers alone, so deleting the condition for the other three was invisible; the fix (a parametrised test, `kind` in the failure message) is in section 6.

## 8. Live record

`docker ps` before: `otcpy-n8n` only (`.arm/n40/live/docker_before.txt`). `docker compose -p otcpy -f docker-compose.infra.yml start`; `uvicorn otc_orders.main:app --port 8101`; `JWT_SECRET=<32+ bytes> python -m otc_gateway` (port 3001). Both `/health/ready` 200. Registers of `progress/current.md` "Live dev data" read first; this walkthrough places no order and writes nothing.

| Route (token from `/auth/login`) | HTTP | count | first row | last code |
|---|---|---|---|---|
| `GET /catalog/products` | 200 | 12 | `PRD-0001`, ean `5901000000012`, "Ration Pack Bundle", price `24999` (int), `EUR`, enabled | `PRD-0012` |
| `GET /catalog/retailers` | 200 | 7 | `AldiDe`, "Aldi Deutschland", `DE`, vat `DE812631079`, gln `5400000000065`, `EUR`, enabled | `LeroyMerlinFr` |
| `GET /catalog/companies` | 200 | 22 | `ALBIONFOODS`, "Albion Foods Ltd", `GB`, gln `5400000000331`, `GBP`, enabled | `UKDISTRIB` |
| the same with `?includeDisabled=true` | 200 | 12 / 7 / 22 | the seed has no disabled row, so the count is unchanged (the effect of the flag is proved by the fixture tests, not by this walk) | |
| `GET /catalog/products`, no token | 401 | | | |

Shutdown: SIGTERM to both; 0 `Traceback` in `orders.log` and `gateway.log`; `docker compose ... stop`; `docker ps` after: `otcpy-n8n` only; ports 3001 and 8101 free. Logs: `.arm/n40/live/`.

## 9. `quality.sh`, twice

| | Exit | pytest | Time | Per test | Coverage |
|---|---|---|---|---|---|
| Baseline (stack down, before any edit) | 0 | 4 427 passed | 495.06 s (523 s whole script) | 0.1118 s | 97.35% |
| Final | **1** | 4 501 passed, **1 failed** | 500.66 s (507 s whole script) | 0.1112 s (500.66 / 4 502) | 97.38% |

Delta: +75 tests (33 + 1 unit, 9 + 24 + 8 integration; the 4 427 + 75 = 4 502 reconciles with 4 501 + 1), +5.6 s, time per test -0.5%. The first final run had 3 failures; two were Orders tests I had to update (`test_orders_host_lifespan.py`, section 5), fixed and re-run; the one left is `services/gateway/tests/integration/test_gateway_over_real_responders.py::test_the_catalog_routes_answer_the_mapped_no_responder_error_until_feature_40`, which asserts `503 UPSTREAM_UNAVAILABLE` for the three catalog routes "until feature 40". It fails with `KeyError: 'code'` because the routes now answer 200. Because pytest failed, the web gate behind it did not run in the final script; the web part passed in the baseline and no web file was touched. The Gateway test sits in `services/gateway/**` and the brief forbids my editing it; the leader must replace it (suggested: delete it, since `test_catalog_through_gateway.py` is the positive replacement).

## 10. What I could not do, and surprises

* **Cannot finish green alone**: the stale Gateway test above (bounded out of my edits). One test, named; nothing else is red.
* No `specs/shared/test-matrix.md` edit: the file's rows are `R1`-`R63` and feature 40 owns none (`grep -n -i "catalog" specs/shared/test-matrix.md` finds only the R11 row's words); I changed no derived count.
* `place_order` still does not filter disabled rows (`find_retailer`, `find_company`, `find_products` return a disabled row). That is today's behaviour and not in the two acceptance items; listing with `includeDisabled=false` now shows a place-order form rows that `orders.create` would also accept, and the reverse is not true. Recorded for the leader, not changed.
* `catalog_data` is in the shared Orders `conftest.py` because a conftest module is not importable by name under `--import-mode=importlib`; three test files use it.
* `OrdersCreateResponder` keeps its name although it serves two subjects (Billing's `CreditResponder` precedent). Renaming would touch the composition root, the lifespan tests and every record that cites it.

## 11. Files touched

Source: `services/orders/src/otc_orders/application/ports/reference_catalog.py`, `application/queries/__init__.py` (new), `application/queries/list_reference_data.py` (new), `infrastructure/persistence/reference_catalog.py`, `infrastructure/messaging/subjects.py`, `presentation/catalog_reference_list.py` (new), `presentation/orders_create.py`, `presentation/orders_create_responder.py`, `composition.py`. Tests: see sections 5. `tests/architecture/test_registration_behaviour.py`, `tests/architecture/test_write_path_population.py` (one literal each). `feature_list.json`: id 40 `status` only. Not touched: `domain/**`, `alembic/**`, `models.py`, `services/gateway/**`, `packages/**`.

Packages installed: none.


## Round 2 (B1 and N1 of `review_orders_catalog_responder.md`; test-only)

**B1.** `catalog_data` (`services/orders/tests/integration/conftest.py`) re-seeded; `CatalogData` gained `insertion` (codes in insert order). Sentinel, computed first by `.arm/n40r2/orders.py` (each line is the order by that column; code order is the sorted codes):

| list | insertion | code order (+disabled / enabled) | by sibling column (+disabled) | by sibling column (enabled only) |
|---|---|---|---|---|
| products | B D C A | A B C D / A B C | ean B D A C; name C A D B; description D A C B | ean B A C; name C A B; description A C B |
| retailers | N X K M | K M N X / K M N | name M K X N; country N M X K; vat N K M X; gln X M N K | name M K N; country N M K; vat N K M; gln M N K |
| companies | R S P Q | P Q R S / P Q R | name Q S P R; country Q R S P; vat R P S Q; gln S R Q P | name Q P R; country Q R P; vat R P Q; gln R Q P |
| currencies | USD EUR JPY | EUR JPY USD | iso_number JPY USD EUR; symbol USD JPY EUR | (no disabled row) |

Every sibling order differs from code order, in both populations. Values changed: product ean/name/description, party name/country/vat/gln, currency symbols (`AD$`, `CE€`, `BJ¥`; the `EU€` assertion in `test_prices_are_integer_minor_units_and_the_reply_is_compact_utf8` became `CE€`). Not covered, by construction: `decimal_points` (values 2, 2, 0: two equal) and `price`/currency columns of products (not a sort a refactor would plausibly substitute; stated, not claimed). Other readers of `catalog_data` compare against its own wire rows or its codes, so they assert what their names say with the new values; the full suite is green.

Self-guard: new `test_catalog_data_fixture.py` (19 tests): `test_no_sibling_column_orders_a_list_the_way_its_code_does` (4 lists x 2), `test_code_order_differs_from_insertion_order_and_its_reverse` (4 x 2), `test_every_sibling_column_value_is_distinct_...` (3). Armed: reverting the four product names to the old Alpha..Delta set fails 2 tests with `products (include_disabled=False): ordering by name gives ['PRD-A', 'PRD-B', 'PRD-C'], identical to code order` (and the `True` variant); restored, `cmp` identical.

Arms (`.arm/n40r2/arm.py`, verbatim outputs `.arm/n40r2/<arm>.out`; file sha256 `9707cb12…` before each; all restored `cmp` identical, `__pycache__` removed). Each runs the adapter test, the NATS ordering test and the Gateway route test of the list:

| Arm | Mutation | Failed (of tests run) |
|---|---|---|
| R1 | products `order_by(Product.code)` -> `.name` | 4 failed, 5 passed: adapter `[False]` `[True]`, NATS `[products]`, Gateway `/catalog/products` (`AssertionError: assert [{'code': 'PR...rapped', ...}] == [{'code': 'PR...r tray', ...}]`) |
| R3b | products -> `.ean` | 4 failed, 5 passed (same four) |
| R1c | products -> `.description` | 4 failed, 5 passed (same four) |
| R2 | parties `order_by(table.code)` -> `.name` | 8 failed, 3 passed: adapter retailers `[False]` `[True]`, companies `[False]` `[True]`, NATS retailers and companies, Gateway retailers and companies |
| R2b/c/d | parties -> `.vat` / `.gln` / `.country` | 8 failed, 3 passed each (same set) |
| R3 | currencies -> `.symbol` | 2 failed, 6 passed: adapter, NATS `[currencies]` |
| R3c | currencies -> `.iso_number` | 2 failed, 6 passed |
| A4 / A4b / A4c | drop `ORDER BY` (products / parties / currencies) | 2 failed / 3 failed, 1 passed / 1 failed (adapter tests; message `AssertionError: assert [{'code': 'PR...` etc.) |

Note: The Gateway currencies route has no test in that file, so R3/R3c are not seen through the Gateway (as in round 1, "adapter + NATS").

**Defeat-list row 3 (sibling identifier)** now holds for ordering: all 4 lists x every sibling column, through the adapter and NATS (and the Gateway for products and parties). A5 is recorded as **recurred in sibling-substitution form, then fixed in this round** (round 1 B1).

**N1.** `test_the_listing_handler_reads_the_same_catalog_object_place_order_resolves` deleted. Guard-port table row for `CatalogReferenceListPortReuseTests` now names A21 (single construction) and `layers-orders` (pyproject.toml:282-289) as the counterparts. N4: `FakeConnection.flushed_after` deleted from `test_orders_create_responder.py` (`flush` returns `None`). N3 (`test_system_clock.py`) untouched.

**`./quality.sh`** (developer stack down): first run exit 1 (`EU€` literal, fixed above; 1 failed, 4518 passed, 513 s); second run exit code 0, "all gates passed", 4519 passed in 505.08 s (0.11 s/test), coverage 97.38% on the first run. Files touched this round: `services/orders/tests/integration/conftest.py`, `.../test_catalog_data_fixture.py` (new), `.../test_catalog_reference_list_responder.py` (line 115), `services/orders/tests/unit/test_catalog_reference_list.py`, `.../test_orders_create_responder.py`, `feature_list.json` (status `in_review`).
