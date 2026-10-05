# Premise check: brief_backlog_sweep.md

VERIFIED   Paths exist: the five review files, test_kernel_surface.py, test_money_guard.py, test_range_guard_parity.py, wire.py, seed settings.py and range_check.py  (ls, all listed)
VERIFIED   review_shared_kernel.md round 2 (line 242) holds R2-1, R2-2, R2-3 (lines 301, 307, 313)  (grep)
VERIFIED   review_contracts_package.md round 2 (line 212) holds R2-1..R2-4 (lines 273-284)  (grep)
VERIFIED   review_db_orders.md holds F1 (208), F2 (222), F5 (245)  (grep)
VERIFIED   review_db_fulfillment.md holds Q2 (7c row 225) and A1 (281)  (grep)
VERIFIED   review_db_billing.md N1 (line 166)  (grep)
VERIFIED   orders settings.py line 14 is `populate_by_name=True`, line 20 is `default="otc_app_dev_password"`  (grep -n)
VERIFIED   services/orders/tests/unit has no settings test  (ls: only test_orders_range_guards.py)
VERIFIED   fulfillment, billing and notifications settings tests exist at the cited names  (ls)
VERIFIED   range_guards.py copies are exactly orders, fulfillment, billing  (find; seed has range_check.py, not range_guards.py)
VERIFIED   Seed range_check.py is a separate file with no ClauseElement logic  (grep ClauseElement|isinstance: only Integer-family table lookups)
VERIFIED   Feature 10 closed (b) and (c) in the copies: each has the docstring "ORM-enabled DML", "Core only" in quotes, the real test name, and the `not isinstance(value, ClauseElement)` pass-through (lines 11-22, 118); unit tests `test_a_sql_expression_..._passes_through` exist in orders, fulfillment and billing. (The note says "both copies"; three exist and all carry it.)
VERIFIED   CLAUDE.md line 51 has the rule "Findings are fixed in the phase that detects them"  (grep)
VERIFIED   .env.example exists, and so does .env; POSTGRES_APP_PASSWORD=otc_app_dev_password is in both, POSTGRES_HOST is in neither  (grep)
VERIFIED   Generic Envelope: none in packages/contracts. `generated/asyncapi.py:114` has a non-generic `class Envelope(WireModel)` with `payload: dict[str, Any]`; grep for Generic|TypeVar in the package returns nothing.
VERIFIED   Item 203(2)'s feature 14 attachment and feature_list.json entries 202/203/204/207/210 match the brief's descriptions (python json load)
VERIFIED   #8 review_db_orders D6 exists: ../order-to-cash-dotnet/progress/review_db_orders.md:182 "credential default duplicated in source"
VERIFIED   Reliance on the orders password default: only alembic/env.py:26 `OrdersDatabaseSettings().url` (no test, no compose use of the Python default); the compose file has its own `:-otc_app_dev_password` at docker-compose.infra.yml:87
FALSE      "this phase's sequences.py change is in the population" of the 204(a) grep (`insert(\|update(\|text(\|bulk_`) — the grep has 5 hits in services/orders/src: models.py:199, 200 (server_default=text(...)) and range_guards.py:13, 14, 15 (docstring). sequences.py has ZERO hits: ADVANCE_ORDER_SEQUENCE is a plain upper-case SQL string ("UPDATE order_number_sequences ..."), executed in tests (test_orders_counter_seed.py:59, 121) via conn.execute. The population needs a wider pattern to include it.
UNVERIFIABLE  That feature 10 closed (b)/(c) "in Phase 6" — the code is verified; the commit d437b27 is the last range_guards.py commit for fulfillment (feature_list phase 6 for id 10 agrees), but the orders copy's commit was not individually attributed.

Verdict: DO NOT ACT (1 FALSE, 1 UNVERIFIABLE)
NOTED: seed test_seed_settings.py has an autouse fixture clearing an `_ALL` list, but no test named like billing's test_the_fixture_clears_every_alias_the_settings_class_declares (grep returns only billing and notifications).
