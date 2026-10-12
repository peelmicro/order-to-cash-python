# Review: backlog 215 code half (Gateway alignment with SA-9), round 1 (light, Sonnet)

**Verdict: APPROVED**

Scope: `services/gateway/**` changes for 215 only. `quality.sh` and the full suite were NOT re-run (another run is live); I ran the targeted Gateway files `test_openapi_conformance`, `test_gateway_rpc_routes`, `test_gateway_orders_http`, `test_gateway_status_population`, `test_gateway_docs`: 102 passed after every restore. The implementer's quality.sh figures (4762 passed, exit 0) are taken from their record, not verified by me.

## Checklist (brief "What changes")
1. Unreadable reply is 503 `UPSTREAM_UNAVAILABLE`: `PROTOCOL_ERROR = GENERIC["UNAVAILABLE"]` (rpc_error_classification.py:87), used in problems.py:117. Code kept as `UPSTREAM_UNAVAILABLE` (parity with #7/#8), reasoning recorded. Done.
2. `default` on every operation: `FastAPI(responses=contract.UNLISTED_PROBLEM)` (app.py:89), problem+json media type in openapi_shape.py, explicit `default` on `/docs`. Conformance compares status sets including `default`. Done.
3. Population test restated: every contract operation carries `default`, `DECLARED_BY_NAME = 61`, originated/pass-through literals, 502 sentinel, 503 declared sentinel. Done.

## Greps
`grep -rnE "502|UPSTREAM_PROTOCOL_ERROR|PROTOCOL_ERROR" services/gateway/src services/gateway/tests` returned 5 hits, all classified: rpc_error_classification.py:87 and problems.py:41,117 (the `PROTOCOL_ERROR` constant, now 503); test_gateway_status_population.py:40 (docstring) and :524-525 (`502 ... not in pairs`, a negative sentinel). No test asserts a 502 or `UPSTREAM_PROTOCOL_ERROR` positively.

## Arms (backups + sha256 in `.arm/r215/`, restored with cmp and sha256sum -c, __pycache__ cleared)
- Arm 1, drop `default` from ONE route (`GET /stock`, in `shaped_openapi`): `test_the_generated_document_matches_the_committed_openapi_yaml_in_both_directions` FAILED naming `GET /stock: statuses ['200','401','503'] != ['200','401','503','default']`. Passes the brief.
- Arm 2, a REAL new source: `raise GatewayNotFoundError` added in `ListOrdersHandler.handle`. Without a table entry, `test_the_handler_raise_sites_are_exactly_the_ones_classified_here` FAILED naming `('order_queries.py', 'ListOrdersHandler.handle', 'GatewayNotFoundError')`. With the site classified to `GET /orders`, `test_the_status_population_against_openapi` FAILED with `Extra items: ('GET', '/orders', 404)`. Both layers work. (A first attempt on `POST /stock/replenish` passed because 404 is declared by name there; correct behaviour, not a defect.)
- Arm 3, revert mapping to `Classified(502, "UPSTREAM_PROTOCOL_ERROR", ...)`: 5 assertions failed `assert (502, 'UPSTREAM_PROTOCOL_ERROR') == (503, 'UPSTREAM_UNAVAILABLE')` (parametrised rpc-routes test and the cancel test; population test also failed).

## Defects
None blocking. Minor, accepted: the implementer's cancel test name (`..._refuses_a_reply_naming_a_reason_the_contract_does_not_allow`) was not renamed; it still asserts the 503 and is correct.

## Routing
The root cause (contract listing fewer statuses than the Gateway answers) is closed by SA-9 itself; nothing further to route. Effort record for 215 is the leader's to add to `progress/history.md` (I did not edit `feature_list.json`; the leader sets 215 to done).
