# Premise check: brief for feature 10 `db_fulfillment`

VERIFIED  Files from feature 9 exist (conftest.py, alembic.ini, alembic/{env.py,script.py.mako,versions/0001_initial_orders_schema.py}, infrastructure/{settings.py,persistence/{models,range_guards,sequences,types}.py}, tests/integration/* (8 files), tests/unit/test_orders_range_guards.py) — `ls` of each directory lists them all.
VERIFIED  progress/impl_db_orders.md and review_db_orders.md exist, findings F1-F9 — review_db_orders.md has F1..F9; verdict "APPROVED (round 1)".
VERIFIED  Root conftest.py holds one session postgres:18.6 and a fresh DB per test, loop scopes documented — conftest.py:57 `postgres_server` session scope, :69 `fresh_database` loop_scope="function", docstring lines 16-19.
VERIFIED  `integration` marker in root pyproject.toml — pyproject.toml:101-103.
VERIFIED  CLAUDE.md line 82 — `sed -n 82p`: "The only shared runtime code is packages/shared_kernel (dependencies = [] ...), packages/contracts and packages/cqrs".
VERIFIED  feature_list id 204 (b)(c)(d) content — id 204 acceptance item 2 = docstring/residual pin naming ORM DML paths; item 3 = ClauseElement unit test armed by reverting; item 4 = no password default; (a) is the population grep.
VERIFIED  id 206 content — acceptance: FK tuple gains confupdtype/condeferrable/condeferred, index tuple gains pg_am.amname, `# type: ignore[type-arg]` at :122 removed; attached_to db_fulfillment (id 10).
VERIFIED  Feature 10 is in_progress, sdd false, 3 acceptance items — feature_list.json id 10.
VERIFIED  `# type: ignore[type-arg]` in test_orders_foreign_keys_and_indexes.py — line 122 `def _diagnostic(expected: set, live: set) -> str:  # type: ignore[type-arg]`.
VERIFIED  review F1 (guard docstring says "Core", stale test name; five ORM DML paths) / F5 (password default "otc_app_dev_password", settings.py:20, confirmed on disk) / F7 (the ignore at :122) — review_db_orders.md:208,245,256; range_guards.py:11-13 still says "Core" and cites nonexistent `test_every_integer_column_is_guarded`; real test at test_orders_quantity_range.py:46; residual pin name at :135.
VERIFIED  FK count 2 for otc_fulfillment — Databases.EN.md §5 (reservations.stock_id -> stock; despatch_items.despatch_id -> despatches cascade); #8 InitialCreate.cs has exactly `table.ForeignKey(` at :114 and :140; #7 apps/fulfillment/drizzle/0000_nappy_mad_thinker.sql `grep -c "FOREIGN KEY"` = 2 (lines 75,76), 0001/0002 = 0. Plan:969 says 8 / 2 / 3.
VERIFIED  Databases.EN.md sections: §3 conventions (l.30), §4.3 reliability tables (l.123), §5 fulfillment (l.194); §5 says `int`/`datetime`; `outbox`,`processed_events` "identical to §4.3".
VERIFIED  Plan lines 335-383 hold the type-delta table (l.344 timestamptz(3), l.358 outbox with identity seq; l.335 starts the section); lines 962-974 are the Phase 6 checklist (l.962 heading, l.969 FK counts 8/2/3, l.974 commits).
VERIFIED  #8 migration path `../order-to-cash-dotnet/src/Fulfillment/Infrastructure/Persistence/Migrations/20260901103111_InitialCreate.cs` — `ls` lists it. Also impl_db_fulfillment.md and review_db_fulfillment.md exist (A1-A3 at review lines 221, 233, 239).
VERIFIED  Feature 9 added the same four packages to services/orders/pyproject.toml — git diff shows + sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings. services/fulfillment/pyproject.toml currently has none of them.
VERIFIED  quality.sh runs tests/architecture — quality.sh:37 `uv run pytest --cov ...`; pyproject.toml:98 testpaths = ["tests","packages","services"]; tests/architecture/ holds 5 test files. (The directory is reached via pytest testpaths, not named in quality.sh.)
VERIFIED  Feature 9 measured quality.sh at ~46 s — impl_db_orders.md:3 and :31: 46.8 s stack up, 45.8 s stopped.
VERIFIED  #8 advisories A1-A3 avoided in feature 9's instruments (as far as read) — test_orders_json_and_timestamps.py covers timestamp read-back; foreign-keys test uses `assert live == EXPECTED_FKS, diagnostic` (:138) and a closed index set (:150). Not armed by me.
VERIFIED  Composed otcpy postgres has otc_fulfillment — `docker exec otcpy-postgres psql -lqt` lists otc_fulfillment; .env.example:39 POSTGRES_DB_FULFILLMENT.
UNVERIFIABLE  "Feature 9 approved first pass today" (date) — review says round 1 APPROVED and backlog filed 2026-10-05 (= today per session date); no command confirms the wall-clock "today".
UNVERIFIABLE  Acceptance 1's "leave composed DB at head" and the quality.sh green gates — need a suite/migration run.

Verdict: SAFE TO ACT (0 FALSE, 2 UNVERIFIABLE).
NOTED: orders' settings.py:20 still has the password default (expected, 204(d) is feature 15's); the brief's wording "Core" fix is needed in range_guards.py:11-13 as the brief says.
