# premise_db_billing — fact-check of the feature 11 brief

FALSE       #7 outbox parity test is at `apps/seed/outbox-parity.spec.ts` — `find ../order-to-cash-nestjs -name 'outbox-parity*' -not -path '*/node_modules/*'` returns `apps/seed/src/outbox-parity.spec.ts` (the `src/` is missing in the brief; #8's review A4 line 258 has the same short path). The file exists; only the path is wrong.
VERIFIED    Every other path in the brief exists — Databases.EN.md, Plan.md, both #8 InitialCreate.cs, #8 impl_db_billing.md / review_db_billing.md / feature_list.json, fulfillment alembic.ini, alembic/{env.py,script.py.mako,versions/0001_initial_fulfillment_schema.py}, settings.py, persistence/{models,range_guards,sequences,types}.py, tests/{unit,integration}, root conftest.py, impl/review_db_fulfillment/orders.md; ls output.
VERIFIED    Plan line 971: "Closed-set FK assertions from `pg_constraint` (8 / 2 / 3)" — sed -n 971p.
VERIFIED    Plan lines 335-383 are the type-delta section — line 335 "Database per service", table "MySQL -> MS-SQL -> PostgreSQL (the whole delta)" inside, 383 is "---".
VERIFIED    FK count 3 for otc_billing: doc §6 (credit_items->credits, invoice_items->invoices cascade, payments->invoices); #8 InitialCreate.cs ForeignKey at lines 122, 145, 169; #7 apps/billing/drizzle/0000_brown_hammerhead.sql:94-96.
VERIFIED    §7 says notifications holds only processed_events — "Its only table is **`processed_events`**".
VERIFIED    payments has no updated_at — §6 "Append-only (no `updated_at`)"; column table lists created_at only.
VERIFIED    #8 review_db_billing A1 index closure (presence-only IndexTests), A2 parity omits IsIdentity, A3 round-trip does not assert timestamps, A4 parity test lives inside Billing.IntegrationTests (#7 put it in apps/seed) — lines 237-253; A1-A6 all exist.
VERIFIED    #8 id 44 says "all 13 money columns" — feature_list.json:1246.
VERIFIED    Billing money columns = 7 (credits.credit_limit; credit_items.amount; invoices.amount, discount, total_amount; invoice_items.price; payments.amount), counted from §6; orders = 6 per MONEY_COLUMNS in services/orders/tests/integration/test_orders_schema_types.py:163-170 (`assert len(set(MONEY_COLUMNS)) == 6`); fulfillment = 0. 6+7 = 13, so id 44 reconciles.
VERIFIED    Fulfillment settings class has no populate_by_name (model_config = env_file, extra) and password default None plus a validator that raises; orders' has populate_by_name=True and password default "otc_app_dev_password".
VERIFIED    tests/architecture/test_range_guard_parity.py:22 `MEMBERS = ("orders", "fulfillment")`.
VERIFIED    Backlog 204 (d) password no default, (e) drop populate_by_name, attached to orders_acceptance id 15 (pending); 207 range-guard expression types, attached to fulfillment_stock id 17, pending; 208 (a) index tuple gains indoption + indnkeyatts, back-ported to orders/fulfillment, (b) settings fixture clears every alias var, attached to db_billing id 11 — feature_list.json.
VERIFIED    Feature 11 is in_progress, sdd false, 3 acceptance items.
VERIFIED    quality.sh 46 -> 61 -> 69.5 s — review_db_fulfillment.md:285 (45.8, 61.0, 69.5); impl_db_orders.md:3 (45.8 s); impl_db_fulfillment.md:108 (61.0 s). The ~90 s trigger and template-database mitigation are at review_db_fulfillment.md:286-288.
VERIFIED    review_db_fulfillment N5 re-open trigger "feature 11 places billing's copy anywhere but infrastructure/persistence/"; census hole P4 (copy at infrastructure/range_guards.py) at lines 87, 302-307.
VERIFIED    Same four packages added in both fulfillment and orders pyproject.toml (git diff): sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings; billing/notifications pyproject currently have none of them.
VERIFIED    Root conftest.py: one session-scoped postgres:18.6, per-test CREATE DATABASE; `integration` marker in pyproject.toml:101-102.

Verdict: DO NOT ACT as written until the one path is corrected (1 FALSE, 17 VERIFIED, 0 UNVERIFIABLE). The FALSE is a path typo (apps/seed/src/outbox-parity.spec.ts); no design premise is wrong.
