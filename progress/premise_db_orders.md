# Premise check: brief_db_orders.md (feature 9)

VERIFIED  Plan lines 335-383 hold the type-delta table, infrastructure tables, saga tables, sequence tables and per-database list with FK counts "8 / 2 / 3" (line 376) -- `sed -n 335p;376p;383p` on the plan.
VERIFIED  Plan line 455 = `orders/  # + alembic/ (own migration history) + tests/{unit,integration}`.
VERIFIED  Plan line 690 lists SQLAlchemy 2.1.3, asyncpg 0.31.0, Alembic 1.20.0, pydantic-settings 2.15.0 (and pins for all dev tools).
VERIFIED  Plan line 878 = "Phase 6/8 -- `otc_app` is the owner of each `otc_*` database".
VERIFIED  Plan lines 962-974 = Phase 6 checklist; line 967 = the `otc_orders` bullet with the json guard "armed by switching the column to `jsonb`".
VERIFIED  Plan: #8 "shipped 7 of 8 FKs undeclared with a green suite" -- plan line 376; #8 review_db_orders.md:138 "D1 BLOCKING. Seven of the eight foreign keys ... absent", :148 live sys.foreign_keys returned exactly one row, :132 "Seven of them are already deleted, and the suite is green". (Round 1 only: the regenerated #8 migration now has 8.)
VERIFIED  #8 review round 1 REJECTED with a "Defects" section -- review_db_orders.md:136 `## Defects`.
VERIFIED  FK count 8 for otc_orders -- Databases.EN.md lines 68,82 (3x currency_id), 95-97 (orders: company, retailer, currency), 113-114 (order_items: order, product) = 8; #8 InitialCreate.cs has exactly 8 `table.ForeignKey` (lines 141,167,193,223,229,235,260,266); #7 drizzle 0000_bizarre_champions.sql:114-121 per #8 review :148 (not re-opened by me).
VERIFIED  #8 migration filenames: 20260901100855_InitialCreate.cs, 20260910052102_AddOrdersRequestId.cs exist under ../order-to-cash-dotnet/src/Orders/Infrastructure/Persistence/Migrations/ (also 20260910091952_AddSagaCommandsDeadLetterColumns.cs).
VERIFIED  #8 progress/impl_db_orders.md and review_db_orders.md exist.
VERIFIED  #8 id 44 = money_column_width (int -> bigint, "all 13 money columns", amended initial migrations); id 45 = order_number_allocator_seed_race (IF NOT EXISTS ... INSERT race, 16 concurrent first-ever allocations) -- #8 feature_list.json.
VERIFIED  #8 id 85 = container fixtures self-assign host ports (brief's "Docker-held ports"); id 104 = dead-letter producer defaults to localhost:9092 (brief's "developer Kafka on 9092").
VERIFIED  Quantity is `integer` in #8: InitialCreate.cs:252 `quantity = table.Column<int>(type: "int", nullable: false)`; in #7: drizzle/0000_bizarre_champions.sql:83 `quantity int NOT NULL` and order-items.schema.ts:31 `int('quantity')`.
VERIFIED  Dead-letter column names `dead_lettered_at`, `triggering_event_envelope`, `triggering_event_topic` -- #8 20260910091952_AddSagaCommandsDeadLetterColumns.cs:15,21,27; and absent from the plan's saga_commands definition (plan line ~370).
VERIFIED  #8 request_id: filtered unique index `uq_orders_request_id ... [request_id] IS NOT NULL` (AddOrdersRequestId.cs:21-25); plan says #9 uses a plain unique index (default NULLS DISTINCT).
VERIFIED  Root pyproject.toml pytest: `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`, `asyncio_default_test_loop_scope = "function"`; filterwarnings has one testcontainers ignore (the wait_container_is_ready line). Note: it also has two more entries (error::StarletteDeprecationWarning, error::PytestUnraisableExceptionWarning), so "the one testcontainers exemption" is accurate only for exemptions.
VERIFIED  quality.sh section 6 = `uv run pytest --cov --cov-report=term-missing:skip-covered` (quality.sh:36-37).
VERIFIED  testcontainers.community.postgres present -- .venv/lib/python3.14/site-packages/testcontainers/community/postgres/__init__.py defines `class PostgresContainer`.
VERIFIED  asyncpg-stubs in dev group -- pyproject.toml `"asyncpg-stubs==0.31.3"` under [dependency-groups] dev; installed (asyncpg_stubs-0.31.3.dist-info).
VERIFIED  otc_contracts.wire.to_wire_json exists -- packages/contracts/src/otc_contracts/wire.py:116 `def to_wire_json(model: WireModel) -> str`, re-exported in __init__.py:4.
VERIFIED  feature_list.json id 9: in_progress, sdd false, 5 acceptance items, note inherits #8 ids 44 and 45; the 5th item is the quantity item citing D8.
VERIFIED  review_shared_kernel.md D8 (line 61) is the quantity item; Q3 (line 83) with "what stays owed" at line 88; impl_shared_kernel.md, review_contracts_package.md exist.
VERIFIED  services/orders/pyproject.toml deps = fastapi, uvicorn, otc-shared-kernel, otc-contracts, otc-cqrs; infrastructure/ holds only __init__.py.
VERIFIED  Compose: `postgres:` service image postgres:18.6 (docker-compose.infra.yml:74-75); infra/postgres/init/01-create-databases.sh exists; COMPOSE_PROJECT_NAME=otcpy (.env:19).
VERIFIED  specs/shared/ has domain-model.md, requirements.md, saga.md; R62 is in requirements.md:507.
VERIFIED  Version-pin idiom question: members list bare names (fastapi, uvicorn); exact pins live in the root dev group. No SQLAlchemy/pydantic-settings in any member today (grep on services/*, packages/*).
VERIFIED  #8's allocator doc cites the racy `IF NOT EXISTS ... INSERT` (EfCoreOrderNumberAllocator.cs:35,40).

NOTE (not false, for the implementer's attention): services/orders/tests/ is flat (only test_orders_health.py); there are no unit/ or integration/ subdirectories yet, whereas plan line 455 shows tests/{unit,integration}. The brief already says "confirm against how the scaffold laid out", so this is accurate as a question.
VERIFIED  #7 emits eight FKs at drizzle/0000_bizarre_champions.sql:114-121 -- `sed -n 114,121p` shows 8 ADD CONSTRAINT ... FOREIGN KEY lines (3 currency_id, orders x3, order_items x2).
UNVERIFIABLE  "pydantic-settings if absent" is a conditional; confirmed absent in members, present as a plan pin only.

Verdict: SAFE TO ACT -- 0 FALSE, 1 UNVERIFIABLE (trivial conditional), rest VERIFIED.
