# premise_seed_job — fact-check of the feature 12 brief

VERIFIED    feature_list.json id 12 is `seed_job`, `in_progress`, `sdd: false`, 5 acceptance items — grep -n '"id": 12,' -A25 feature_list.json (lines 211-224).
VERIFIED    Backlog 201 `attached_to` names seed_job and carries the quoted item — feature_list.json:658 ("also affects web_app (id 29) and seed_job (id 12)") and :662 (exact wording).
VERIFIED    services/seed is a stub — `find services/seed`: __main__.py (calls `run_seed`), tests/test_seed_cli.py (`assert main() == 0`), empty application/domain(+value_objects)/infrastructure/presentation packages; pyproject deps are only otc-shared-kernel and otc-contracts.
VERIFIED    pymongo not installed in the workspace venv — `.venv/bin/python -c 'import pymongo'` -> "ModuleNotFoundError: No module named 'pymongo'" (root pyproject.toml:200,224 only lists it as a forbidden import name).
VERIFIED    `otc_seed` is in `service-independence` (id at pyproject.toml:318, modules list ends with "otc_seed" at line 325), `layers-seed` (:304-311) and `otc_seed.domain` in `domain-purity` (:192).
VERIFIED    #8 Seed.csproj ProjectReferences Orders, Fulfillment, Billing — src/Seed/Seed.csproj:15-17 (plus SharedKernel, Contracts at 10-11).
VERIFIED    tests/architecture/test_money_guard.py:23 walks `services/*/src/otc_*/domain` — line 23 `for domain in sorted(root.glob("services/*/src/otc_*/domain"))`; SERVICES list at :17 includes "seed".
VERIFIED    Compose pins postgres:18.6 / mongo:8.3.8 at docker-compose.infra.yml:75 and :135; testcontainers==4.15.0 at pyproject.toml:44 and uv.lock:1308.
VERIFIED    Root conftest provides `postgres_server` (session, sync, :67-68), `fresh_database` (:79-80), `migrated_database_from_template` (:131-132, one template per service via `_TEMPLATES` cache in `_template_for`).
VERIFIED    #8 seed layout (Domain/Data, Domain/Deterministic, Domain/Sagas, Infrastructure/Persistence, Infrastructure/Mongo) and tests (tests/Seed.UnitTests, tests/Seed.IntegrationTests) exist — find/ls.
VERIFIED    Oracle tests/Seed.IntegrationTests/OracleFixtures/order_timeline_from_number7.json is 720 lines — wc -l.
VERIFIED    #8 progress/impl_seed_job.md and review_seed_job.md exist; D1 at review_seed_job.md:151-165 (D2 begins :166), D1 fix section at :317 (D3-D6 begin ~:355), lesson ("transferable lesson for #9") at :280. All three line refs are in review_seed_job.md, not impl_seed_job.md (impl:151-165 is an arming table, impl:317-355 and :280 do not exist, file is 267 lines) — the brief's sentence is ambiguous but true of the review file.
VERIFIED    #8 was rejected once on D1 (order_timeline values unguarded) — review_seed_job.md:151, impl_seed_job.md:194 ("rejected on the first review. D1 was the only blocking finding").
VERIFIED    #7 seed files — ls apps/seed/src: deterministic.ts, deterministic.spec.ts, data/*.data.ts, writers/{orders-db,fulfillment-db,billing-db,mongo}.writer.ts, verify.ts, outbox-parity.spec.ts, clock.ts, mongo-config.ts all present.
VERIFIED    #7 deterministic.ts: `timeHiAndVersion = \`4${hex.slice(13, 16)}\`` (line 22); timeMid is slice(8,12), so hex index 12 is never used (variant uses hex[16], seq 17-20, node 20-32).
VERIFIED    Databases.EN.md exists at the stated path; §8 `order_timeline` at line 310; tables §4-§7 at lines 41/194/241/306.
VERIFIED    Three counter-seed sentinels exist at services/{orders,fulfillment,billing}/tests/integration/test_*_counter_seed.py, 87 lines each, `test_sentinel_check_then_insert_seed_loses_the_race` at :75, `rounds = 10` (:76), CALLERS = 16 with asyncio.Barrier (:23,:35).
VERIFIED    review_db_billing A1 measured the three at 16.4 s — progress/review_db_billing.md:179-181 ("The three sentinels are 16.4 s").
VERIFIED    progress/current.md records 99.8 s whole-script for the Phase 6 wrap-up, threshold ~90 s — current.md:24.
VERIFIED    The otcpy dev stack has 12 containers up — `docker ps --format '{{.Names}}' | wc -l` -> 12.
VERIFIED    Volumes otcnet_mssql_data and otcnet_mongodb_data exist — `docker volume ls`.
VERIFIED    Plan counts 3 currencies, 12 products, 7 retailers, 22 companies, 215 stock rows, 154 credit lines — Python Plan.md:1018; #8 impl_seed_job.md:11-12 (215, 154) and review_seed_job.md:76-77.
VERIFIED    #8 review states 6 orders, 11 items, 50 outbox rows, 6 timeline documents — review_seed_job.md:5 and :194.
VERIFIED    Existing nats warning filter in pyproject.toml (:114-119) and tests/architecture/test_warning_policy.py exist; testcontainers/community/mongodb exists in the venv.
VERIFIED    Backlog 204(a) classification of `insert(/update(/text(/bulk_` hits, 204(d) no password default (feature_list.json:705,708), 205 instants (:714); billing settings at services/billing/src/otc_billing/infrastructure/settings.py exists.
VERIFIED    "ids from 211" — highest id in feature_list.json is 210.
VERIFIED    #8 SagaFixtures.cs says "one link shorter than a live saga's causal chain" (src/Seed/Domain/Sagas/SagaFixtures.cs:38); #7 SAGAS at apps/seed/src/data/sagas.data.ts:823; toTimelineDocument at writers/mongo.writer.ts:125; node v24.19.0.
VERIFIED    No instruction contradicts CLAUDE.md on disk — implementer edits only allowed paths (services/, conftest.py, scripts/, pyproject tool sections, uv add via implementer); no commit/index-writing git; feature_list.json single-line edit rule matches; in_review not done; light/full classification and ids from 201+ rule (211 is next free) consistent.

Verdict: SAFE TO ACT (0 FALSE, 0 UNVERIFIABLE, 28 VERIFIED).
NOTED: the brief's "#8's reports: impl/review ... read D1 (151-165), round-2 fix (317-355), line 280" applies to review_seed_job.md only; an implementer opening impl_seed_job.md at those lines will find something else.
