# Premise check — brief_impl_gateway_rest_auth.md

VERIFIED   .env.example 218-228 hold GATEWAY_PORT=3001 (224), OPERATOR_USERNAME (225), PASSWORD (226); Mongo block 50-54 incl. MONGO_DB_READMODEL=otc_read_model; NATS_URL at 107 — sed -n on each range.
VERIFIED   "No JWT setting anywhere in #9" — case-insensitive grep over py/toml/yml/yaml/sh/env: only openapi.yaml:918 `bearerFormat: JWT` (a scheme, not a setting); .env.example and docker-compose have none (compose has GATEWAY_OPERATOR_* only).
VERIFIED   gateway skeleton: app.py, test_gateway_health.py, empty application/domain(+value_objects)/infrastructure, no composition.py/main.py — find services/gateway -type f.
VERIFIED   gateway pyproject deps = fastapi, uvicorn, otc-shared-kernel, otc-contracts, otc-cqrs — sed of pyproject.
VERIFIED   all named templates/inputs exist (billing & projector composition/main, orders nats_stock_availability/nats_saga_commands/rpc_reply, generated openapi.py/asyncapi.py, wire.py, envelope.py, the five named guards, test_read_model_sole_writer.py, test_credit_subjects.py, test_rpc_subjects.py, design.md) — [ -e ] loop, no MISSING.
VERIFIED   Orders RPC clients set x-correlation-id/x-request-id (nats_saga_commands.py:145-146), bound the wait (timeout=timeout_ms/1000), decode RpcError.
FALSE      "the Projector also holds the only MongoDB client" — services/seed/src/otc_seed/composition.py:46 and infrastructure/mongo.py:16 also build/use AsyncMongoClient (only readmodel.* publisher claim holds: projector/infrastructure/signal/nats_update_signal_publisher.py is the sole hit).
VERIFIED   test_registration_behaviour.py:45 `SERVICES = [`; :407 `def test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher`.
VERIFIED   test_write_path_population.py:60 quote `"gateway": "no database: it forwards over NATS and holds no connection",` exactly.
VERIFIED   test_outbox_copy_parity.py:574 names services/gateway/src/otc_gateway/infrastructure/persistence/models.py.
VERIFIED   test_money_guard.py:56 SERVICES lists "gateway".
VERIFIED   root pyproject.toml: 270 `id = "layers-gateway"`; 177 "otc_gateway"; 192 "otc_gateway.domain"; 252 ".application"; 253 ".presentation"; 351 "otc_gateway".
VERIFIED   test-matrix.md 180-181 = R54/R55 (gateway halves named), 191 = R60, 202 = R63.
VERIFIED   openapi.yaml is 1964 lines (wc -l); :896 is `/docs:`; 110-158 span /auth/login and /auth/me.
FALSE      "serve the committed bytes at /docs as openapi.yaml:896 declares" — :896-912 declares GET /docs as a `text/html` "Interactive API documentation ... Human-facing rendering of this document", not the committed YAML bytes.
VERIFIED   docs/lessons.md:123 is the #7 first-gateway-rejection "both sides of the seam" passage.
VERIFIED   test_billing_rpc_error_retryability.py 131-140 is the table with a "Gateway maps it to" column.
VERIFIED   #8 commits: 27643ba "feat(gateway): the sixth service — REST, JWT, rate limiting and SSE" (25+26; stat touches Gateway and Stream files), 04d4329 "fix(gateway): listen on GATEWAY_PORT...", d5c8a3a "fix(gateway): unify the duplicated RPC payload records...".
VERIFIED   #7 commits 4f52c8e "feat(gateway): the first HTTP surface, and the wire mismatch it exposed", 423643e "rate-limit POST /auth/login", d19342c "black-box API tests through a real spawned Gateway".
VERIFIED   #9 1a9ac06 "fix(orders,fulfillment,billing): bound the boot-time NATS connect" — git log --oneline -1.
VERIFIED   #8 history.md 1734 = "## gateway_rest_auth (id 25...)", 1765 = next feature header; section holds D1/D2/D3, E1, "approved after one rejection" (REJECTED round 1, APPROVED round 2).
VERIFIED   #7 history.md:1013 = "## gateway_rest_auth (id 25...)"; Effort line "REJECTED twice, then approved".
VERIFIED   the four #8 progress/*.md files, LoginThrottleOptions.cs, LoginRateLimiterExtensions.cs, IssuedOrderWindow.cs, RegisterPaymentCommand.cs exist; #7 apps/gateway exists.
FALSE      "`find ../order-to-cash-dotnet/tests -path '*Gateway*' -name '*.cs'` lists 73 files" — that command prints 79 (6 under obj/bin); 73 only with obj/bin excluded.
VERIFIED   "491.63 s / 4 089 passed = 0.120 s per test" — progress/current.md:36 verbatim.
VERIFIED   feature 25 has 8 acceptance items; 5-8 carried from 43, 22, 22, 24 (feature_list.json); item 5 is the longest; status in_progress, sdd false, phase 13.
VERIFIED   features 40 (orders_catalog_responder), 41 (orders_cancel_responder), 26 (gateway_sse_push) pending phase 13; /orders/stream at openapi.yaml:383; asyncapi has catalog.reference.list and orders.cancel channels (545, 272) plus the other RPC subjects named.
FALSE      "statusRank, processedEventKeys, timelineOrderVersion excluded per design §7 / PR33" — design.md §7 (lines 365-383) contains none of the three names; the exclusion is PR33 in specs/projector_read_model/requirements.md:129 ("feature 25 exclude...") and design.md lines 100-109 only list the fields. (PR33 itself holds.)
VERIFIED   R54/R55 gateway halves belong to 25 (R55 also 31, 26, 29) — test-matrix rows 180-181.
UNVERIFIABLE "#8 left six of eight subjects exercised only against stubs" — needs a read of #8's whole test suite; not settled by one command.
VERIFIED   Does the brief forbid anything the acceptance items mandate? NO — bounds allow services/gateway/**, gateway pyproject deps (PyJWT, item 2), root importlinter (item 4), tests/architecture (items 5, 8), test-matrix; the forbidden set (other services, packages/**, .env.example, compose) is mandated by none of items 1-8.

Verdict: DO NOT ACT as-is — 4 FALSE (Mongo-client exclusivity, /docs "committed bytes", 73 files, design §7 for the exclusion), 1 UNVERIFIABLE. All four are minor corrections.

NOTED: feature 25 acceptance 7 cites RpcErrorClassification.cs:75 for the INVOICE_NOT_PAYABLE generic row (actual :77) and :63-67 for detail overrides (dictionary at :60-66); acceptance 6 cites RegisterPaymentCommand.cs:23-44 for the order-id resolution (that range is the error class and records; the handler resolution is at :65-97).
