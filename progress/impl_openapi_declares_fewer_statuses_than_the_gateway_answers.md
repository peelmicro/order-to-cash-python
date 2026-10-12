# Impl record: backlog 215 `openapi_declares_fewer_statuses_than_the_gateway_answers`, #9's code half of SA-9

Classification: light (as briefed); it stayed within the Gateway's error mapping, its generated document and its tests.

## Built
1. **Unreadable reply is a 503 `UPSTREAM_UNAVAILABLE`** (parity with #7 and #8). `PROTOCOL_ERROR` in `domain/rpc_error_classification.py` is now `GENERIC["UNAVAILABLE"]`. Decision: code `UPSTREAM_UNAVAILABLE` (the amended `UpstreamUnavailable` covers "a reply the Gateway could not read"; a new code would be a 5xx outside the by-name set). The `detail` is still the error's own text, so it says the reply was unreadable.
2. **`default` on every operation of the generated document.** `FastAPI(responses=contract.UNLISTED_PROBLEM)` in `presentation/app.py` (declared once, a route cannot forget it); `contract.declared` accepts `int | str`; `openapi_shape.py` writes `default` as `application/problem+json` too; `GET /docs` (`routes_ops.py`) writes its own `default` explicitly, because the app-level model would otherwise be served as `text/html`.
3. **`test_gateway_status_population.py`** restated: every contract operation carries `default`; `DECLARED_BY_NAME = 61` (counted over the contract, `default` excluded); the by-name-undeclared pairs equal literals (`GATEWAY_ORIGINATED` 34 -> 24, the ten 502 pairs removed; `PASS_THROUGH` 25 unchanged); sentinel: no 502 is answered, `POST /orders/{id}/cancel 503` is declared by name. Docstring and citations updated to the closed state.

## Files
`services/gateway/src/otc_gateway/{domain/rpc_error_classification.py, presentation/{app,contract,openapi_shape,problems,routes_ops}.py}`; tests `tests/unit/{test_gateway_orders_http,test_gateway_rpc_routes,test_openapi_conformance,test_gateway_status_population}.py`; `feature_list.json` line 890 (`in_review`).

## Proof (R mapping; no new R, backlog 215 acceptance)
- Unreadable reply 503 on every RPC route: `test_every_rpc_route_maps_an_unreadable_reply_to_503_upstream_unavailable_not_to_a_502` (renamed, parametrised) and `test_cancel_order_refuses_a_reply_naming_a_reason_the_contract_does_not_allow`.
- `default` present and compared: `test_the_generated_document_matches_the_committed_openapi_yaml_in_both_directions` (statuses compared, `default` included), `test_every_generated_operation_declares_default_as_a_problem_document`, `test_arm_a_route_that_stopped_declaring_default_is_reported`.
- Population: `test_the_status_population_against_openapi`.

## Arms (backups in `.arm/n215/`, restored with `cmp`)
- Mapping reverted to 502: `test_cancel_order_refuses_a_reply_naming_a_reason_the_contract_does_not_allow` failed, `assert (502, 'UPSTREAM_PROTOCOL_ERROR') == (503, 'UPSTREAM_UNAVAILABLE')`. (Run with `-x`; the parametrised rpc-routes test was not reached, not armed separately.)
- `responses=` removed from `create_app` (default dropped everywhere): conformance failed with `GET /auth/me: statuses ['200', '401'] != ['200', '401', 'default']` plus 17 more, and the two default tests failed. Not armed per single route, only app-wide; the single-route case is the mutated-document arm `test_arm_a_route_that_stopped_declaring_default_is_reported`.
- New by-name-undeclared pair: simulated by adding `("GET", "/stock", 507)` to the literal; the population test failed naming `('GET', '/stock', 507)`. This is the literal's inverse, not a new real status source; a real source was not armed.

## Run
`./quality.sh`: exit 0, "all gates passed"; pytest 4762 passed in 557.22 s (about 0.117 s per test), coverage 97.59%; `./init.sh` exit 0.

## Surprises / limits
- My first guess of `DECLARED_BY_NAME` (69) was wrong; measured 61 and the test said so.
- The `/docs` media-type trap above (route `response_class=HTMLResponse`).
- Not done: the other-service tests, `specs/`, and the cancel test's name was not changed.
