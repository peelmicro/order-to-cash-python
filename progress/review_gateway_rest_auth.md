# Review — feature 25 `gateway_rest_auth` (phase 13, full group, round 1)

**Verdict: REJECTED** — one production defect in the deliberate body-validation departure (B1) and one vacuous E1 guard at the read-model adapter (B2). Everything else the brief asked me to push on held under my own mutations. Feature 25 set back to `in_progress`.

Reviewer: Opus (session model). Inputs read in full: `progress/brief_review_gateway_rest_auth.md`, `progress/impl_gateway_rest_auth.md` (295 lines), `progress/brief_impl_gateway_rest_auth.md`, `progress/premise_impl_gateway_rest_auth.md`, `feature_list.json` id 25 (8 acceptance items). Arms on copies in `.arm/r25/` (tool `.arm/r25/arm.py`: backup + sha256, mutate, one target in its own process group with `killpg` on timeout, restore by `cp`, `cmp`, clear `__pycache__` / `.mypy_cache`, rerun green); verbatim logs in `.arm/r25/logs/<arm>.log`.

**What I re-ran and what I did not.** I did not re-run the implementer's 60+ arms. I ran my own 24 mutations and one probe (table in §4), the named tests they target, `lint-imports` under four mutations, and `./quality.sh` once at the end with the developer stack down (`docker ps`: `otcpy-n8n` only): **exit 0, 527 s for the script, `4423 passed in 494.87s` = 0.1119 s per test** (the implementer's final run was `1 failed, 4422 passed in 497.20s`; the one failure was the Billing guard, now updated and green). ruff format `979 files already formatted`, ruff check `All checks passed!`, mypy `Success: no issues found in 798 source files`, import-linter `Contracts: 13 kept, 0 broken`, coverage 97.35 % overall (gate 60), domain 98 % (gate 80), web `1 passed`, `quality.sh: all gates passed`. Log: `.arm/r25/quality.log`.

## 1. Blocking findings

### B1 — a JSON body sent under a non-JSON or absent `Content-Type` is a 500 `INTERNAL_ERROR` with an ERROR traceback, on all five body routes, including the anonymous `POST /auth/login`

- **Where:** `services/gateway/src/otc_gateway/presentation/wire.py:24-28`, `_json_mode_validator`: `return model.model_validate_json(json.dumps(value), ...)`.
- **Why it happens:** FastAPI 0.142.2 (`fastapi/routing.py:446-463`) passes the body as **bytes** when the `Content-Type` is not `application/json` / `+json`, or is absent (strict content type). `json.dumps(bytes)` raises `TypeError`, which pydantic does not turn into a validation error, so it reaches `ProblemMiddleware` as an unforeseen failure: 500 `INTERNAL_ERROR`, logged at ERROR with a traceback. Without the WrapValidator, FastAPI's own validation would refuse bytes as "not a valid dictionary" -> the 400 handler. So this is introduced by the record's deliberate departure (§12 (b)), which is exactly brief item 9's question ("does a body FastAPI would accept bypass it on any route?" — here the body bypasses validation into a crash).
- **Evidence (probe P1, a temporary test file run against the unit harness, then deleted; `ls services/gateway/tests/unit/test_zz*` -> no such file):** 5 routes × 4 media types:

  | Route | `text/plain` | `application/x-www-form-urlencoded` (curl `-d`'s default) | none | `application/merge-patch+json` |
  |---|---|---|---|---|
  | `POST /orders` | 500 | 500 | 500 | 400 |
  | `POST /stock/replenish` | 500 | 500 | 500 | 400 |
  | `POST /auth/login` (anonymous) | 500 | 500 | 500 | 400 |
  | `POST /invoices/{id}/payments` | 500 | 500 | 500 | 400 |
  | `POST /orders/{id}/cancel` | 500 | 500 | 500 | (harness artifact: body accepted, the fake RPC had no reply) |

  Verbatim: `ERROR otc_gateway.presentation.asgi:asgi.py:130 POST /orders failed unexpectedly ... TypeError: Object of type bytes is not JSON serializable`.
- **Why it matters:** every one of these operations declares `400 BadRequest` in `openapi.yaml` for a malformed request and none declares 500; a client error is reported as a server fault; and on the public login route any anonymous caller can write ERROR-level tracebacks at will (the very log noise the record's V1/V2 fix set out to remove). #7 (Nest body parser -> `{}` -> 400) and #8 (ASP.NET -> 415) never answered 500 here.
- **Remedy:** in the validator, a value that is not the parsed JSON document (bytes or str from a non-JSON media type) is refused as a validation failure (raise `ValueError` / `PydanticCustomError`) so it becomes the 400 `VALIDATION_FAILED` Problem — or refuse non-JSON media types before the body is read. Guard: one test whose population is **derived from the app** (every operation with a `requestBody`, read from the routes, not a hand list — today n = 5), each driven with `text/plain`, `application/x-www-form-urlencoded` and no `Content-Type`, each required to answer 400 `application/problem+json` and to log no ERROR line; armed by reverting the fix (it must fail naming the route and the media type).

### B2 — E1's guard at the read-model adapter is satisfied by accident: the whole `test_order_read_model.py` (21 tests) stays green with `initialAmount` and `totalAmount` transposed in the adapter

- **Where:** `services/gateway/src/otc_gateway/infrastructure/mongo_order_read_model.py:143-146` (the `_summary` parse that both the list and the detail use) and `services/gateway/tests/integration/test_order_read_model.py:174` `test_the_three_totals_of_the_seed_are_three_different_numbers_so_a_swap_is_seen`.
- **Why:** every one of the six seeded sagas has `initialDiscount = 0`, so in each document `initialAmount == totalAmount` (`ORD-000001 16130 0 16130` ... `ORD-000006 24999 0 24999`, printed from `otc_seed.domain.data.sagas.SAGAS`). The test named "three different numbers so a swap is seen" asserts only `len({s.initial_amount for s in SAGAS}) > 1` — across sagas, not within one — so its name claims a property it never checks (CLAUDE.md: "Fixtures must not satisfy the assertion's relation by accident"; #8 E1 and #8 backlog 65).
- **Evidence:** arm I-r2 (the six-case field-by-field test: `6 passed` under the mutation) and arm I-r2c (the whole file: **`21 passed in 7.06s` under the mutation**). The transposition is caught elsewhere, by one test only: arm I-r2b, `test_gateway_over_real_responders.py::test_a_placed_order_is_pending_until_the_projector_has_written_it` (its order has line discounts, 8525 / 165 / 8360): `{'totalAmount': 8525} != {'totalAmount': 8360}`. So production is guarded today, but the record's §4 claim "E1 avoided (F1-F3)" rests on F1-F3, which mutate `application/order_views.py` over a fake read model and never execute the adapter's parse.
- **Remedy:** give `test_order_read_model.py` at least one document whose three totals are pairwise distinct (e.g. project the facts of an order with line discounts, as the real-responder test does) and make the totals assertion run on it; fix or rename test :174 so it asserts what its name says; arm with the adapter transposition (both `initialAmount<->totalAmount` and `initialDiscount<->totalAmount`), which must fail in `test_order_read_model.py` itself.

## 2. Non-blocking findings, with dispositions

- **N1 — statuses the Gateway answers that `openapi.yaml` does not declare (rooted in `specs/shared/`; ROUTE, do not narrate).** `POST /orders` answers **404 `NOT_FOUND`** for an unknown product / retailer / company / currency (Orders' `ReferenceDataNotFoundError` -> `NOT_FOUND`, `services/orders/src/otc_orders/presentation/orders_create.py:178-184`; asserted by `test_an_unknown_product_is_a_404_by_orders_own_not_found`), but `placeOrder` declares 201/400/401/409/422/503 only (`openapi.yaml:226-245`). Likewise `GET /orders` and `GET /orders/{id}` answer 503 on a read-model outage (declared: 200/400/401 and 200/202/401/404), `GET /orders/{id}` 400 on a malformed id, `cancelOrder` 400 and 502. #7 (`apps/gateway/src/domain/problem/rpc-error-mapping.ts:48`, Orders `rpc-error-mapper.ts:62`) and #8 (`RpcErrorClassification.cs` generic `NOT_FOUND` -> 404; Orders `OrdersCreateErrorMapper.cs:107-108`) answer the same, so this is inherited parity, not a #9 defect — but the contract is incomplete. **Disposition: the leader files a backlog entry (next free id 215, e.g. `openapi_declares_fewer_statuses_than_the_gateways_answer`) attached to feature 31 `api_tests` (the black-box script is where an undeclared status is observed), whose acceptance is an `SA-n` proposal declaring the read-model 503 and the reference-data 404 (or a ruling mapping them to declared statuses), applied to #7/#8/#9 together.** The record's own §1 table also omits the 404 from `POST /orders`' bracketed undeclared list — correct it in the round-2 record.
- **N2 — `C3` and `C8` survive, as equivalent mutants: ACCEPTED, NOT FIXED.** Re-proved independently against PyJWT 2.15.1: dropping `iss` from `require` with `issuer=` kept -> `MissingRequiredClaimError Token is missing the "iss" claim`; allowing `none` with a key supplied -> `InvalidKeyError When alg = "none", key value must be None.` My own JWT arm R7 (`"verify_iss": False`) fails the refusal table (`DID NOT RAISE InvalidTokenError`). Re-open trigger: a PyJWT upgrade past 2.15.x, or any change to how `issuer=` or the key is passed to `jwt.decode`.
- **N3 — `Q3a` survives by design: ACCEPTED.** Acceptance item 8 itself says "otherwise record that the residual still does not apply". Re-grepped: `grep -n lambda services/gateway/src/otc_gateway/composition.py` -> `7:` and `123:` (docstring text) and `305: HealthCheck("readModel", lambda: database.command("ping")),` (a readiness probe outside `register_handlers`, not a handler); `grep -rn lambda services/gateway/src --include=*.py | grep -v composition.py` -> no output (exit 1). The 14 registrations (`composition.py:124-137`) are all `registry.register_*(Message, HandlerClass)`. `Q3b` (`test_the_root_registers_no_lambda_handler`) is the trip-wire; item 8's re-open trigger stands.
- **N4 — `R63` marked DONE at the API level from in-process ASGI tests plus one real-process test.** Consistent with the row's own text ("nothing below the gateway needs to be reachable"); the counts reconcile (my count of column 5 over the 63 rows: 48 `DONE`, 1 `SCOPED`, 14 other, = the table's 48 / 1 / 14). No action.
- **Settled items confirmed, no finding:** `orderDiscount` -> Orders `VALIDATION_FAILED` (`orders_create.py:185-188`) -> Gateway 400, declared on `placeOrder`. `Idempotency-Key` travels as payload `requestId` (`order_commands.py:18-21`). `registerPayment` declares `503 UpstreamUnavailable` (`openapi.yaml:739-740`), and #7 (`problem-json.filter.ts:121-122`) and #8 (`ProblemJsonMiddleware.cs:118-119`) also answered "order not projected" with 503 `UPSTREAM_UNAVAILABLE`; #9 adds `Retry-After: 2`. The Billing guard fails on a third file (R10). `.env.example`: every Gateway name the leader added is a `validation_alias` in `infrastructure/settings.py` (12 of 12; `OTC_REQUEST_TIMEOUT_MS` / `OTC_GATEWAY_URL` are n8n's, moved, not new), and `load_settings()` run in a scratch directory whose `.env` is a copy of `.env.example` boots: `jwt bytes 41`, `port 3001`, `throttle 10 60000`. The staged `git mv` is the disclosed process breach, not a code finding.

## 3. Brief items 1-10

1. **Seam — holds.** Subjects: R1 (sibling `billing.invoice.issue`) fails by name (`Extra items in the left set: 'billing.invoice.issue' ... right set: 'billing.payment.register'`). Payload: R2 (sibling key `invoiceReference` for `invoiceId`) fails — the generated asyncapi model refuses the construction, so the payment call never happens and the subject set differs; R3 (sibling value: the order id as `invoiceId`) fails on the wire (`{'invoiceId': '0a0a...'} != {'invoiceId': 'f1f1...'}`). Real hosts: I-r1 (payment correlation = invoice id) against real Billing fails on what Billing **wrote** (`assert [] == ['payment.received.v1', 'credit.released.v1']`); I-r3 (`orders.create` -> sibling `orders.cancel`) against real Orders fails `503 == 201`. Real-responder tests drive Orders, Fulfillment and Billing hosts through their own lifespans (`tests/integration/conftest.py`), no stub.
2. **Anonymous sweep — holds.** The population is `fastapi.routing.iter_route_contexts(app.routes)`, i.e. the served routes; the middleware is deny-by-default on `(method, path)` before routing, so a non-`APIRoute` route is protected regardless and can only become public through `PUBLIC_OPERATIONS`, which is asserted equal to the test literal and to `security: []`. R4 (protected `GET /stock` made public) fails; R5 (a NEW route added and made public) fails with `GET /r25-debug [no header] -> 200` × 8 kinds; R6 (a new protected route) fails the population literal with `Extra items in the left set: ('GET', '/r25-debug')`.
3. **JWT — holds.** 15 refusal rows; my R7 arm bites; C3/C8 equivalence re-proved (N2). The flipped-signature fix is a guard, not a retry: it deterministically replaces the signature's first base64url character (`A`<->`B`), whose six bits are all significant, so the decoded bytes always differ.
4. **C3, C8, Q3a:** acceptable dispositions (N2, N3).
5. **Acceptance 6 and 7 — hold.** Fixture ids pairwise distinct (`ORDER_ID 0a0a...`, `INVOICE_ID f1f1...`, `OTHER_INVOICE_ID e2e2...`, request id fresh and asserted not equal to either). One parametrized case per row (5 rows) plus sibling-code twins; my R8 (the `payment.reference_reused` row keyed under sibling `CONFLICT`) fails `'PRECONDITION_FAILED' == 'PAYMENT_REFERENCE_REUSED'`; my R9 (order looked up by the invoice reference) fails `503 == 201`.
6. **Acceptance 5 and 8 — hold.** Gateway in `SERVICES`, `TABLES["gateway"]` 5 commands + 9 queries. Q-r1 (one registration delegated to a helper in `auth_handlers.py`) fails naming `auth_handlers.py:13, not from composition.py`; Q-r2 (one registration deleted) fails the probe with `No query handler is registered for ListCompaniesQuery`. Lambda grep: N3.
7. **Acceptance 4 — holds.** L-r1 (a lazy import of `NatsRpcClient` inside a function in `order_queries.py`) breaks `gateway-order-queries-read-model-only` (`... -> nats (l.25, l.26)`); L-r2 (an import through `otc_gateway.composition`) breaks it and the layers contract; L-r3 (an `if TYPE_CHECKING:` import of `scope`) breaks it; L-r4 (the adapter importing `otc_orders`) breaks `service-independence`. Runtime half: `test_r54_the_list_and_the_detail_are_answered_with_nats_stopped_and_no_write_model_at_all`.
8. **E1 — FAILS at the adapter site (B2).**
9. **Departures:** the `WrapValidator` -> B1. "Order not projected" -> 503: declared, and #7/#8 did the same (§2).
10. **Ledger — verified halves:** row 2: #7 `jwt-token.adapter.ts:23-35` (`jwt.verify(token, secret, { issuer })`) and #8 `Infrastructure/Auth/JwtTokenService.cs:113-115` (issuer compared only if the token carries one) are as stated; row 1: #7 `presentation/guards/jwt-auth.guard.ts` and #8 `Presentation/Auth/BearerAuthenticationMiddleware.cs` exist; row 5: #8 `Application/Commands/RegisterPaymentCommand.cs:70-95` resolves the order from the read model and throws `OrderNotYetProjectedError`, as stated; #7 `register-payment.command.ts:36-37` are the scan bounds (200 / 5). Guard cells: rows 1, 2, 4, 5 seen to fail by my R4-R9; row 7 (inclusion projection) not re-armed by me (K1/K6 in the record). Row 6's "#7 `issued-order-window.ts`" and the remaining citations I did not open.

## 4. Arming table (my mutations)

All restored by `cp` from `.arm/r25/bak/<id>/`, `cmp` identical, sha256 after = before, caches cleared, restored run green. Full logs `.arm/r25/logs/<id>.log`.

| Arm | Mutation | Target | Result (verbatim) | sha256 before = after |
|---|---|---|---|---|
| R1 | `PAYMENT_REGISTER = "billing.invoice.issue"` | `test_rpc_subjects.py::test_the_gateways_subjects_are_exactly_the_channels_the_contract_says_it_calls` | FAILED `Extra items in the left set: 'billing.invoice.issue'` | rpc_subjects.py `553814c5118940494c9daaff44c69fdee4ad1884f47c3093f6b3f7929497b227` |
| R2 | payment payload `invoice_reference=str(command.invoice_id)` for `invoice_id=` | `test_rpc_subjects.py::test_every_request_the_gateway_sends_carries_exactly_the_contracts_keys` | FAILED `assert {'billing.cre....cancel', ...} == {...}` (+ `ValidationError ... PaymentRegisterRequestPayload`) | payment_handlers.py `7c996c3db771a9ccd1960b30892dbb205acb5b0c6cb037769f61e077dde75972` |
| R3 | `invoice_id=order_id` | `test_gateway_payments_http.py::test_the_payment_body_carries_the_invoice_id_and_the_remittance_as_the_contract_says` | FAILED `{'invoiceId': '0a0a0a0a-...'} != {'invoiceId': 'f1f1f1f1-...'}` | payment_handlers.py `7c996c3d...` |
| R4 | `("GET", "/stock")` added to `PUBLIC_OPERATIONS` | `test_gateway_auth_sweep.py::test_every_protected_route_of_the_running_app_refuses_every_kind_of_anonymous_request` | FAILED `assert ['GET /stock ... -> 500', ...] == []` | public_routes.py `0872da5946141146edca2f31ff5884519a8e016da5bc901c8940e0dcd3bd50bc` |
| R5 | new `GET /r25-debug` route + made public | same | FAILED `'GET /r25-debug [no header] -> 200'` (8 items) | public_routes.py `0872da59...`, routes_ops.py `97f7e49c82ce274e80eb41bba5091a0bdbd00f370c96246d8cb25f5f04798742` |
| R6 | new protected `GET /r25-debug` route | `test_the_sweep_covers_the_expected_population_by_subtraction` | FAILED `Extra items in the left set: ('GET', '/r25-debug')` | routes_ops.py `97f7e49c...` |
| R7 | `options={"require": ..., "verify_iss": False}` | `test_jwt_token_service.py` | FAILED `DID NOT RAISE InvalidTokenError` (1 failed, 4 passed, `-x`) | jwt_token_service.py `39d3b436be6efb26990f45bcae041b65a52e10ddb59e475dedc78fe8ecfdfee7` |
| R8 | `("CONFLICT", "payment.reference_reused")` row key | `test_item_7_each_billing_refusal_row_is_the_status_and_code_the_contract_declares` | FAILED `'PRECONDITION_FAILED' == 'PAYMENT_REFERENCE_REUSED'` | rpc_error_classification.py `2353e4ec9de3f0afadd64c95dabdefab1afab2a82f22ad3cc7c775d4569df391` |
| R9 | scan returns `invoice.invoice_reference` | `test_the_payment_x_correlation_id_is_the_invoices_order_id_read_from_the_read_model` | FAILED `assert 503 == 201` | payment_handlers.py `7c996c3d...` |
| R10 | new file `application/zz_r25_probe.py` naming `billing.payment.register` | `services/billing/tests/unit/test_no_internal_payment_timer.py::test_no_service_or_package_but_billing_mentions_the_payment_subject` | FAILED `Left contains 1 more item: {'.../zz_r25_probe.py': 1}` | created file removed, `exists=False` |
| L-r1 | lazy `from ...nats_rpc_client import NatsRpcClient` in a function of `order_queries.py` | `uv run lint-imports` | `Contracts: 11 kept, 2 broken.` `... -> nats (l.25, l.26)` | order_queries.py `21cc2a46a4aa3cd06c2ccb03a785c84bdf36df248d13819a5d22d0fc288a1466` |
| L-r2 | `import otc_gateway.composition` inside a function of `order_queries.py` | `lint-imports` | `Contracts: 11 kept, 2 broken.` `order_queries -> otc_gateway.composition (l.19)` `composition -> nats` | order_queries.py `21cc2a46...` |
| L-r3 | `if TYPE_CHECKING: from ...scope import GatewayScope` | `lint-imports` | `Contracts: 12 kept, 1 broken.` `order_queries -> otc_gateway.application.scope` | order_queries.py `21cc2a46...` |
| L-r4 | `import otc_orders` in the Mongo adapter | `lint-imports` | `The seven services do not import each other BROKEN` | mongo_order_read_model.py `0473292a7026632a77c2a06b4f2113e9e1e0d38987c521d89e1ffed7ce223575` |
| I-r1 | payment `correlation_id=command.invoice_id` | real Billing: `test_the_payment_is_sent_under_the_orders_id_and_billing_wrote_the_facts_under_it` | FAILED `assert [] == ['payment.rec....released.v1']` | payment_handlers.py `7c996c3d...` |
| I-r2 | adapter `initialAmount`<->`totalAmount` | `test_order_read_model.py::test_the_detail_of_each_seeded_saga_equals_the_stored_document_field_by_field` | **SURVIVED** `6 passed` | mongo_order_read_model.py `0473292a...` |
| I-r2b | same | `services/gateway/tests/integration` (`-x`) | FAILED in `test_a_placed_order_is_pending_until_the_projector_has_written_it`: `{'totalAmount': 8525} != {'totalAmount': 8360}` | mongo_order_read_model.py `0473292a...` (no rerun; I-r2c's rerun covers the file) |
| I-r2c | same | `test_order_read_model.py` (whole file) | **SURVIVED** `21 passed in 7.06s` | mongo_order_read_model.py `0473292a...` |
| I-r3 | `ORDERS_CREATE = "orders.cancel"` | real Orders: `test_post_orders_is_a_201_whose_every_figure_equals_the_row_orders_stored` | FAILED `assert 503 == 201` (`UPSTREAM_UNAVAILABLE`) | rpc_subjects.py `553814c5...` |
| Q-r1 | `LoginCommand` registered by a helper in `auth_handlers.py` called from the root | `test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[gateway]` | FAILED `register_command(...LoginCommand) was called from .../auth_handlers.py:13, not from composition.py` | auth_handlers.py `735bdf3a03b0143d02baa15b38b440ea36b55c49b8c00da2057730196694193b`, composition.py `9ebbdb8f18418e382874c76ab4f4a24cfdd01afde80f7db7532b7d5a7690d293` |
| Q-r2 | `ListCompaniesQuery` registration deleted | same | FAILED `No query handler is registered for ListCompaniesQuery. Exactly one is required.` | composition.py `9ebbdb8f...` |
| P1 | probe (not a mutation): 5 body routes × 4 media types | temporary `tests/unit/test_zz_review_probe_body.py` (copy of `.arm/r25/probe_body.py`), deleted after | 15 × 500 (B1) | file removed; `git status` unchanged |

Equivalence checks for C3 / C8: an inline PyJWT 2.15.1 script (N2), outputs quoted verbatim there.

## 5. Inherited #8 findings — avoided / recurred

| #8 finding | Verdict | Evidence |
|---|---|---|
| D1 (subjects and payload keys asserted against themselves) | **avoided** | subjects read from `asyncapi.yaml` + literal; keys compared with the schema both ways; payloads built from generated models; R1-R3, I-r1, I-r3 |
| D2 (sweep selected by the property under test) | **avoided** | literal public set, protected set by subtraction from served routes, deny-by-default middleware; R4-R6 |
| D3 (JWT settings that existed nowhere) | **avoided** | `JwtSettings`, no secret default, 32-byte minimum; `.env.example` names = aliases, dev value boots (41 bytes) |
| E1 (detail money fields unasserted; #8 backlog 65) | **recurred at the adapter site, caught at system level by one test** | B2: I-r2 / I-r2c survive in the read-model file; I-r2b fails in the real-responder file; F1-F3 cover `order_views.py` only |

## 6. Traceability (rows this feature claims)

| R / item | Test(s) I checked exercise it |
|---|---|
| R48 (route half) | `test_an_accepted_payment_is_a_201_and_a_duplicate_is_a_200_with_the_replay_header`; real Billing `test_a_replay_is_a_200_duplicate_and_emits_no_second_fact` |
| R49 (route half), acceptance 7 | `test_item_7_*` (5 rows + sibling twins; R8); real Billing `test_every_refusal_billing_answers_arrives_as_the_status_the_contract_declares` |
| acceptance 6 | `test_the_payment_x_correlation_id_is_the_invoices_order_id_read_from_the_read_model` (R9), `test_an_invoice_whose_order_is_not_projected_yet_is_a_retryable_503_and_nothing_is_paid`; real Billing I-r1 |
| R54 gateway half, acceptance 4 | `test_r54_the_list_and_the_detail_are_answered_with_nats_stopped_and_no_write_model_at_all`; two import-linter contracts (L-r1..L-r3) |
| R55 gateway half | `test_a_placed_order_is_pending_until_the_projector_has_written_it` (real Orders), G1-G3 in the record |
| R60 Gateway leg | `test_gateway_health.py`, `test_gateway_degraded.py` (not re-armed by me) |
| R61 route | `test_replenish_adds_the_delta_to_the_stock_row` (real Fulfillment) |
| R63 | `test_gateway_auth_login.py` R63 tests (not re-armed by me; H1-H6 in the record) |
| acceptance 1 | `test_openapi_conformance.py` (both directions; not re-armed by me; A1-A3 + 9 in-test arms) |
| acceptance 3 | `test_gateway_listens_on_gateway_port.py` (O1/O2 in the record; not re-run by me beyond `quality.sh`) |
| acceptance 5, 8 | `test_registration_behaviour.py[gateway]` (Q-r1, Q-r2), `test_gateway_registration.py::test_the_root_registers_no_lambda_handler` |

## 7. CHECKPOINTS.md

- C1: [x] harness files exist; [x] `progress/current.md`, `history.md` exist; [x] seven agents; [x] each declares a model or deliberate inheritance (leader, reviewer, spec_author by description); [x] `./init.sh` exit 0 (run by me after setting 25 to `in_progress`; log `.arm/r25/init.log`).
- C2: [x] at most one `in_progress` (0 before my edit, 1 after); [x] every status valid; [x] `done` features have tests (`quality.sh` 4423 passed); [x] `current.md` is the leader's; [x] no `blocked`.
- C3: [x] `lint-imports` 13 kept, 0 broken; [x] no cross-service DB access (the Gateway reads only the read model; L-r4); [x] no new shared runtime package; [x] no `domain` imports `otc_cqrs`; [x] kernel/cqrs `dependencies = []` (unchanged); [x] no float / `/` in domain money (money guard green; the one `/ 1000` is a NATS timeout in `infrastructure`); [x] every interaction NATS-RPC per `asyncapi.yaml` (Gateway publishes no fact); [x] no stray debug logging found in `services/gateway/src`.
- C4: [x] `quality.sh` exit 0; [x] Gateway domain tests import no framework (layers contract kept); [x] integration tests on testcontainers with the developer stack down; [x] coverage 97.35 % / 98 %; [x] no Jest/Karma/Jasmine. **But B1/B2 mean the green suite does not yet prove the body-error and adapter-totals claims.**
- C5: [x] no stray files from me (`.arm/` is git-ignored; probe removed); [ ] history entry with effort record — not applicable on a rejection; [x] `feature_list.json` reflects the state (25 -> `in_progress`); C5's commit boxes are the leader's.
- C6: not applicable (`sdd: false`); test-matrix rows updated, counts reconcile (N4).
- C7: [x] `specs/shared/` changed only in `test-matrix.md`'s Status column and counts; [x] inherited findings accounted (§5); the rest of C7 is wrap-up scope.

## 8. What must change before round 2

1. **B1:** a non-JSON or absent `Content-Type` on any body route answers 400 `VALIDATION_FAILED` (`application/problem+json`), logs no ERROR line; guard over the population of body operations read from the app (n = 5 today), three media cases each, armed by reverting the fix.
2. **B2:** `test_order_read_model.py` asserts the totals on a document whose three totals are pairwise distinct; test :174 asserts what its name claims (or is renamed); armed with the adapter transposition (I-r2c must fail inside that file).
3. Record: §1's `POST /orders` row lists the undeclared 404; §4's E1 line names the adapter site and B2's fix.
4. Leader (not the implementer): file backlog **215** for N1 (attached to feature 31, acceptance = an `SA-n` proposal or a ruling), so the gap is routed, not narrated.

Round 2 is a re-review of B1 and B2 only, plus a re-run of I-r2c and P1.

---

# Round 2 — re-review of B1, B2, P1, I-r2c and §8 items 1-3 (2026-10-12)

**Verdict: APPROVED** — B1 and B2 are closed, and my own arms and probes confirm it. The round produced one new finding, **R2-N1**. It is non-blocking, but it is a false verification claim that must be corrected before the commit (light, text only; see below). Feature 25 is set to `done` (one line in `feature_list.json`).

Reviewer: Opus. Scope: what round 1 §8 set, nothing else. Inputs: round 1 §1 and §8, the implementer's "Round 2" section in `progress/impl_gateway_rest_auth.md`, and `progress/brief_impl_gateway_rest_auth_round2.md`. Arms used copies in `.arm/r25r2/`, with the tool `.arm/r25r2/arm.py` (round 1's tool, re-pointed): backup and sha256 into `.arm/r25r2/bak/<id>/`, the mutation, one command in its own session with `killpg` on timeout, restore by `copy2`, `cmp`, `__pycache__` and `.mypy_cache` cleared, and a rerun to green. Arm definitions are in `.arm/r25r2/run_arms.py` and logs in `.arm/r25r2/logs/`. The probe runs from `.arm/r25r2/tests/unit/` against a byte copy of the unit `conftest.py`, so no test file was added under `services/`.

**What I ran and what I did not.** I did **not** re-run `./quality.sh`. Instead I read the implementer's log `.arm/n25r2/quality.log`: `4427 passed in 496.00s`, mypy `Success: no issues found in 799 source files`, `quality.sh: all gates passed`. The log ended at 08:18:02, after the last edits to the round-2 files (08:06-08:09). These are the commands I ran myself:
- the two targeted files, `25 passed`;
- `ruff check services/gateway`, `All checks passed!`;
- `ruff format --check services/gateway`, `80 files already formatted`;
- `mypy` on the three changed files, `Success: no issues found in 3 source files`;
- `lint-imports`, `Contracts: 13 kept, 0 broken`;
- 9 arms and the P1 probe.

## R2.1 B1 — CLOSED

**The fix** is at `presentation/wire.py:24-35`. `_json_mode_validator` refuses `bytes | bytearray` with `ValueError`, which yields 400 `VALIDATION_FAILED`.

**Can a str reach it under a non-JSON type?** No. FastAPI 0.142.2 (`fastapi/routing.py:446-463`) calls `request.json()` only when the media type is absent or non-strict, or is `application/json` / `*+json`. In every other case it hands over `body_bytes`. A str therefore reaches the validator only as a JSON string literal under a JSON type, and `json.dumps(str)` cannot raise. I probed that case (`"abc"` → 400). A str **sent by the client** under a non-JSON type arrives as bytes, which is the probe's `str` column below.

**Does the population come from the served routes?** Yes. All of the following come from probe `test_population_three_ways` / `test_lazy_included_router_late_route_is_seen_and_served` (log `.arm/r25r2/logs/P1.log`):
- `app.routes` holds only `_IncludedRouter` objects (`top-level app.routes types: ['_IncludedRouter']`).
- `iter_route_contexts` expands them through `effective_route_contexts()` (`fastapi/routing.py:1871-1897`, which rebuilds when the router's version changes).
- The derived set equals the 5 `requestBody` operations of `specs/shared/openapi.yaml`, and the 5 of `app.openapi()`.
- Every non-GET route the app serves is one of those 5 `APIRoute`s.
- A body route added to `routes_billing.router` **after** the app was built is derived (`{('POST', '/zz-late-body')}`) and served (`200 {"x":3}`).

**Probe P1 re-run, and widened.** It covers the 5 served body operations, 9 media types and 3 body forms.
- **Media types:** `text/plain`, `text/plain; charset=utf-8`, `application/x-www-form-urlencoded`, none, `application/xml`, `application/octet-stream`, `multipart/form-data; boundary=xyz`, `application/jsonx`, and the JSON control `application/merge-patch+json`.
- **Body forms:** bytes, a str (httpx `content=str`) and non-UTF-8 bytes.
- **Login** was driven with a fresh harness per cell, because the harness throttle (limit 3) answers 429 before validation.

| Route | 8 non-JSON / absent types × 3 body forms (24 cells) | ERROR records |
|---|---|---|
| `POST /auth/login` (anonymous) | 24 / 24 → 400 `application/problem+json` `VALIDATION_FAILED` | none |
| `POST /orders` | 24 / 24 → 400 `VALIDATION_FAILED` | none |
| `POST /orders/{id}/cancel` | 24 / 24 → 400 `VALIDATION_FAILED` | none |
| `POST /invoices/{id}/payments` | 24 / 24 → 400 `VALIDATION_FAILED` | none |
| `POST /stock/replenish` | 24 / 24 → 400 `VALIDATION_FAILED` | none |

- **Round 1 → round 2 change:** the round-1 table's 500 cells (`text/plain`, `x-www-form-urlencoded`, none, on all five routes) are now 400, with no ERROR line.
- **The JSON control column is unchanged from round 1**, as expected, because the fix does not touch the JSON path. It gives 400 on orders, replenish and payments. Login gives 401, because my probe body is a well-formed login. Cancel gives 500 from the harness, because the body is accepted and the fake RPC has no reply. That is the same harness artifact round 1 recorded.
- **JSON edge bodies under `application/json`** (a string literal, a number, `null`, `NaN`, invalid UTF-8, 5000-deep nesting): every one answers 400 on login and on orders, with no ERROR record.

**The B1 guard's arms:**

| Arm | Mutation | Result (verbatim) | sha256 before = after, `cmp` |
|---|---|---|---|
| A1 (revert the fix) | `wire.py`: `if isinstance(value, bytes \| bytearray):` → `if False:` | `test_every_body_operation_answers_400_...` FAILED: `Left contains 15 more items, first extra item: 'POST /auth/login [text/plain] -> 500 application/problem+json INTERNAL_ERROR'`, plus 15 `ERROR ... failed unexpectedly` records naming each route; `1 failed, 2 passed` | `23e6de1f...0108f1` (same as the implementer's), identical; restored `3 passed` |
| A2 (a served route escapes the derivation) | `app.py`: `routes_auth.router` included through a sub-`FastAPI` mounted at `""` instead of `include_router`, so login is still served but through a `Mount` | both census tests FAILED: `Extra items in the right set: ('POST', '/auth/login')` | `e63a28ea...239f8c`, identical; restored `15 passed` |
| A3 (the derivation narrowed) | test copy: `... and str(context.path) != "/orders"` | `2 failed, 1 passed`: `Extra items in the right set: ('POST', '/orders')` | `6aa1dd77...7f5a425`, identical; restored `3 passed` |

The census sentinel therefore fails when an existing body route escapes the derivation. One limit is left (R2-N2): a **new** route that escapes it is outside the literal too.

## R2.2 B2 — CLOSED

**The new test.** `test_the_three_totals_reach_the_list_summary_and_the_detail_each_from_its_own_element` (`tests/integration/test_order_read_model.py:195-227`):
- It inserts a copy of a projector-written seed document with totals **8525 / 165 / 8360**. The values are pairwise distinct, none is a substring of another, and the test asserts `len(set(...)) == 3` itself.
- It asserts all three totals on the **list summary** (`list_orders` → `order_summary`), on the **detail** (`find_by_id` → `order_detail`), as wire JSON, and on `ReadModelTotals`.

**The renamed test.** Test :174 is now `test_the_totals_of_each_seeded_saga_are_the_seeds_own_three_numbers`. Its comment says that it is **not** a swap guard, and why.

**Arms**, all at the adapter's parse (`mongo_order_read_model.py:144-146`):

| Arm | Mutation | Run | Result | sha256 / `cmp` |
|---|---|---|---|---|
| A4 = **I-r2c** | `initialAmount` ↔ `totalAmount` | whole `test_order_read_model.py` | **`1 failed, 21 passed`** (round 1: `21 passed`). Failing: the new test, `{'totalAmount': 8525} != {'totalAmount': 8360}` / `{'initialAmount': 8360} != {'initialAmount': 8525}` | `0473292a...ce223575` (= implementer's), identical; restored `22 passed` |
| A5 | `initialDiscount` ↔ `totalAmount` | the new test alone | FAILED `{'initialDiscount': 8360} != {'initialDiscount': 165}` | same, identical |
| A6 | `initialAmount` ↔ `initialDiscount` (the pair the implementer did not arm) | the new test alone | FAILED `{'initialAmount': 165} != {'initialAmount': 8525}` | same, identical |

The new document alone catches all three transpositions.

**The implementer's "other money site" table.** Population: `grep -rniE "amount|discount|price" services/gateway/src --include=*.py`, which finds 10 files. The money lines are listed by file (`order_commands.py:28,29,33,53-55`, `order_views.py:41-49,58,59`, `payment_handlers.py:50`, `mongo_order_read_model.py:144-146,174,175`, `catalog_handlers.py:53`, plus `billing_handlers.py`, `ports/`, `rpc_error_classification.py`, `routes_billing.py` and the `wire.py` comment). That matches the implementer's sites. `order_commands.py:33` `order_discount` has no same-element neighbour; Orders refuses it. I re-ran two of the implementer's rows and added one:

| Arm | Mutation | Run | Result |
|---|---|---|---|
| A7 = m3 | `order_commands.py:28-29` `unit_price` ↔ `line_discount` | `services/gateway/tests/unit` | `1 failed, 279 passed`, `test_place_order_sends_the_contracts_payload_with_the_idempotency_key_as_request_id`: `'unitPrice': 250, 'lineDiscount': 24999` != `24999 / 250`. sha256 `10b96795...620c8a1d9`, `cmp` identical, restored `280 passed` |
| A8 = m5 | `billing_handlers.py` `amount` ↔ `total_amount` | same | `1 failed, 279 passed`, `test_list_invoices_sends_every_filter_and_writes_each_amount_from_its_own_field`. sha256 `b85530d5...a3c`, identical, restored `280 passed` |
| A9 (mine) | `billing_handlers.py` `amount` ↔ `discount` (the third pair; the implementer armed `amount`/`discount` against `total_amount` only) | same | `1 failed, 279 passed`, same test (`'amount': 5750, 'discount': 130000`). Identical, restored `280 passed` |

The table's claims held wherever I tested them.

## R2.3 §8 record items 1-3 — DONE

1. §1 now has the B1 400 behaviour, as shown above.
2. B2: done, as shown above.
3. §1's `POST /orders` row lists the undeclared 404 and cites backlog 215. §4's E1 line names the adapter site `infrastructure/mongo_order_read_model.py:143-146`, the round-1 recurrence and the round-2 test.

## R2.4 New findings

**R2-N1 — a false "declared on all five" claim, with a verification that cannot see it.** Non-blocking. Disposition: **fix, light, text only, before the wrap-up commit**, with the leader reading the diff.

- **What is claimed, and where:**
  - `wire.py:28-29` (comment): "400 `VALIDATION_FAILED`, which `openapi.yaml` declares on every body operation".
  - `test_gateway_body_media_types.py:6` (docstring): "`openapi.yaml` declares 400 on each of these operations".
  - The impl record's Round 2 B1 paragraph says 400 is declared on `login`, `placeOrder`, `cancelOrder`, `registerPayment` and `replenishStock`, "checked by the conformance test that compares declared responses with the served ones".
- **Why it is false:** `cancelOrder` declares **202, 401, 404, 409, 503** and **no 400**. I parsed it from `specs/shared/openapi.yaml`: `('POST', '/orders/{id}/cancel', True, ['202', '401', '404', '409', '503'])`. The record's own §1 row lists cancel's 400 as undeclared (`[400, 502]`).
- **Why the cited check cannot catch it:** the conformance test compares the statuses the **generated document** declares (`test_openapi_conformance.py:123-126`) with `openapi.yaml`. It never observes a served status, so it cannot see a runtime 400.
- **Behaviour:** correct. A malformed body is a 400, and 400 is the only sensible answer.
- **Contract side:** already routed. Backlog **215**'s title lists "POST /orders/{id}/cancel 400". Its acceptance item 2 ("no #9 test asserts an undeclared status as contract without citing this entry") now applies to the three cancel cases of `test_every_body_operation_answers_400_...`.
- **Required:** reword the comment, the docstring and the record sentence. They should say that 400 is declared on four of the five operations and that `cancelOrder`'s 400 is undeclared (backlog 215). The test should cite 215. This is a light change: an implementer, or `test_maintainer` for the docstring. No arm is needed, because no behaviour changes.

**R2-N2 — the census literal cannot see a *new* body route that escapes the derivation.** For example, a new sub-app mounted with its own body route is in neither the derived set nor the literal. **ACCEPTED, NOT FIXED.**
- **Why it is accepted:** for a contract operation, the conformance test's "declared operation that is not mapped is reported" (`test_openapi_conformance.py:221`) fails instead, because a mounted sub-app's routes are absent from the generated document. A body route that is not in the contract is already a conformance failure in the other direction (`:228`).
- **Re-open trigger:** any `app.mount(...)`, or any non-`APIRoute` route, added to `presentation/app.py`.

**Observation, not a finding.** The login throttle counts a malformed-body request before validation. The harness limit is 3, so the 4th cell answers 429. This is intended: the throttle guards the anonymous route whatever the body. The guard sends exactly 3 login requests, inside the limit.

## R2.5 Traceability

Round 1 §6 stands. Round 2 adds no `R<n>` and changes no `test-matrix.md` row: `git diff --stat HEAD -- specs/shared` still shows `test-matrix.md` alone (9/9 lines), the same as round 1. B1 and B2 map as follows:
- **B1** → `test_gateway_body_media_types.py::test_every_body_operation_answers_400_validation_failed_for_a_non_json_media_type`, with the census guard `test_the_body_operations_of_the_running_app_are_the_expected_five`. Armed by A1, A2 and A3.
- **E1 at the adapter (#8 E1 / backlog 65)** → `test_order_read_model.py::test_the_three_totals_reach_the_list_summary_and_the_detail_each_from_its_own_element`. Armed by A4, A5 and A6.

## R2.6 CHECKPOINTS.md (round-2 scope)

- C1: [x] harness unchanged since round 1; [x] `./init.sh` run after my status edit (below).
- C2: [x] no `in_progress` after setting 25 to `done`; [x] every status valid.
- C3: [x] `lint-imports` 13 kept, 0 broken; [x] no new shared code, and no cross-service import in the round-2 diff (it touches only the `presentation/wire.py` validator and Gateway tests).
- C4: [x] targeted tests green; [x] the implementer's `quality.sh` log shows all gates passed (4427), and I read it rather than re-running it; [x] the integration test runs on testcontainers Mongo with the developer stack down (`docker ps`: `otcpy-n8n` only); [x] B1 and B2's claims are now proven by tests that I saw fail.
- C5: [x] no stray files from me (the probes and the conftest copy are in git-ignored `.arm/r25r2/`; `git status` shows none under `services/` or `tests/` from me); [x] `feature_list.json` id 25 → `done` (one line); **[ ] `progress/history.md` effort entry — owed by the leader.** Earlier entries use harness-reported agent durations (`history.md:1300`), which only the leader holds. Artefact times I can attest to:
  - impl brief 05:48;
  - review-1 brief 07:43;
  - review 1 written 08:04;
  - round-2 brief 08:05;
  - round-2 record 08:18.

  Per the reviewer contract, the feature is not closeable until that entry lands. It must name each inherited #8 finding as avoided or recurred; E1 **recurred at the adapter in round 1 and was closed in round 2**.
- C6: not applicable (`sdd: false`).
- C7: [x] `specs/shared/` is unchanged by round 2; [x] the N1 contract gap is routed as backlog 215, filed by the leader (attached to 26), and R2-N1's cancel 400 sits inside 215's population.

**`./init.sh` after my edit: exit 1, with one failure** (log `.arm/r25r2/init.log:35`): `progress/current.md claims a feature while none is active: "**Feature:** gateway_rest_auth (id 25, phase 13) ..."`. This is the expected consequence of the transition to `done`. `progress/current.md` is the leader's file, and the leader must advance it, together with the history effort entry and the R2-N1 text fix, before the session moves on. My `feature_list.json` change is the one line `472` (`"status": "done"`): `git diff HEAD -- feature_list.json` shows it next to the leader's backlog-215 entry and nothing else.
