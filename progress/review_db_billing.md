# review_db_billing — feature 11 (id 11, phase 6), assessment #9 — closes Phase 6

**Verdict: APPROVED** (round 1). Process: **full** (persistence). Reviewer session 12:34–12:50.

0 blocking, 1 minor, 3 nits, 1 advisory. Every finding has a disposition below; two backlog entries are proposed (209, 210) for the leader to file. **Backlog 208 is met as written** and can be set `done` (see Q5, Q6).

## What I ran, and what I did not re-run

- `./quality.sh` once, sequentially, with the `otcpy` stack **stopped** (12 containers `docker stop`ped, `docker ps` = 0, nothing listening on 5432/9092/4222/27017): **rc=0, 84.6 s wall clock, 734 passed in 63.6 s**, total coverage 99.15 %, domain 100 %, import-linter **10 kept, 0 broken**, mypy clean on 167 files. Output: scratchpad `review_quality.out`.
- Stack restarted (`docker start`): **12 of 12 healthy**. `./init.sh` **exit 0**. Composed `otc_billing` and `otc_notifications` both at `0001`.
- **15 arms of my own**, none a repeat of the implementer's (A–L below), each through a helper that does `cp` backup → one exact replacement → ONE named test → restore → `cmp` → clear every `__pycache__` and `.mypy_cache` → re-run green. Outputs: scratchpad `arms_review_{parity,closedset,billing,template,208b}.out`.
- A timing experiment of the template mitigation (integration subset, with and without the template).
- I did **not** re-run the implementer's 74 arms. I re-ran the suite once (the gate claim is about the full suite) and otherwise only the tests my arms target.

## CHECKPOINTS.md

**C1 — harness complete**
- [x] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh` exist (`init.sh` checks them; exit 0).
- [x] `progress/current.md`, `progress/history.md` exist.
- [x] `.claude/agents/` holds the 7 agents.
- [x] Every agent declares its model: 4 by `model:`, leader/reviewer/spec_author by a description stating they inherit (read from the frontmatter).
- [x] `./init.sh` exits 0 (after the stack restart).

**C2 — state coherent**
- [x] No feature `in_progress` (11 was `in_review`; now `done`).
- [x] Every status valid (`init.sh`).
- [x] Every `done` feature has passing tests (734 passed).
- [x] `current.md` describes this session (feature 11, `in_review`, reviewer launched).
- [x] No `blocked` feature.

**C3 — architecture**
- [x] `lint-imports`: 10 kept, 0 broken (run inside `quality.sh`). `grep -rnE "^(from|import) (sqlalchemy|asyncpg|alembic|pydantic)"` over billing's and notifications' `domain` and `shared_kernel`: 0 hits.
- [x] No cross-service DB access or import. `grep -rnE "otc_(orders|fulfillment|gateway|projector|seed|notifications)" services/billing --include=*.py`: 2 hits, both prose (migration docstring line 9, `models.py:12`). Same for notifications against the other six: 2 hits, both prose (`models.py:4`, migration line 4). No FK leaves its database (3 FKs, all inside `otc_billing`; `otc_notifications` 0).
- [x] No new shared runtime package: `range_guards.py`/`types.py` are copied (feature 10's ruling) and policed by the parity guard.
- [x] No domain imports `otc_cqrs`; no domain code changed.
- [x] `shared_kernel` and `cqrs` untouched (`git diff --stat`: neither listed).
- [x] No `float`/`Decimal` in billing or notifications source (`grep -rnE "float|Decimal" services/billing/src services/notifications/src`: 0 hits). Money is `int`/`bigint`.
- [x] No interaction added (schema only).
- [x] No debug logging, no context-free TODO in the new files.

**C4 — verification real**
- [x] `./quality.sh` passes (my run, stack stopped).
- [x] Domain tests pure (no domain change; `quality.sh` 6b 100 %).
- [x] Integration tests hit a real `postgres:18.6` testcontainer and pass with the developer stack down.
- [x] Coverage ≥ 80 % domain (100 %), ≥ 60 % overall (99.15 %).
- [x] No Jest/Karma/Jasmine (no web change).

**C5 — closed cleanly**
- [x] No stray files: `find` for `*.bak|*.orig|*.tmp|*.rej` outside `node_modules`/`.venv`: 0; `git status` of gateway, projector, seed, packages, specs: clean (the implementer's `deep/` arm directory is gone).
- [x] `progress/history.md` has this feature's entry with its effort record (appended by me).
- [x] `feature_list.json` reflects the state (id 11 `done`, that line only; `git diff` read).
- [ ] The human is told what was done and how to test — the leader's next step (`impl_db_billing.md` "How to test by hand" is ready). **This closes Phase 6: the leader owes a phase report.**
- [x] Claude did not commit: `.git/index` mtime 10:07:33 (the last commit), reflog unchanged since `372a544`, `git stash list` empty, nothing staged.

**C6 — SDD:** N/A (`sdd: false`).

**C7 — second-reuse fidelity**
- [x] `specs/shared/` untouched (`git status` clean for `specs`; `init.sh` 5d `cmp` against #7 and #8 passes).
- [x] No deviation needing an `SA-n`: every deviation is a plan-delta type translation or a #7/#8-consistent width, on the ledger.
- [x] No `R<n>` claimed (schema feature; `test-matrix.md` unchanged, as features 9 and 10).
- [x] Every inherited #8 finding accounted for (A1–A6, ids 44, 45, 85, 104 below and in `history.md`).
- [x] Effort record honest (this feature was **not** faster than #7 or #8; written as such).

## Answers to the nine questions

### Q1. Four-database parity test (`tests/database_parity/test_reliability_table_parity.py`)

- **Live catalogs only, no service import.** Source imports are `asyncio, uuid, collections.abc, pathlib, typing, asyncpg, pytest, alembic` (full `grep -n "^import\|^from"` output in my notes: 9 lines, no `otc_*`). The reads are `information_schema.columns` ⨝ `pg_attribute` (`format_type`, `attnotnull`, `attidentity`, identity start/increment/min/max/cycle, default, generated, collation, length, precision), `pg_indexes` ⨝ `pg_index` ⨝ `pg_am` (whole `indexdef`, `indisunique`, `indisprimary`, `indnullsnotdistinct`, `indoption`, `indnkeyatts`, ordered columns) and `pg_constraint` (`pg_get_constraintdef`). No SQLAlchemy metadata. **N3** (nit): each service's `alembic/env.py` imports its own `models.Base`, so the parity process *loads* all four model modules through Alembic; the "imports no service package" claim is true at source level only. Harmless.
- **Identity, precision, indexes compared:** yes (above). My arm B (BY DEFAULT instead of ALWAYS on billing's `seq`) proves identity *kind* is compared, not just presence.
- **Populations literal and non-vacuous:** `sizes = {"outbox": 3, "processed_events": 4}` asserted against the tuples, and `present` is **re-derived from each live database's `pg_class`** and must equal the literal (`assert present == members`), so dropping a member raises. The reference must have >0 columns and >0 indexes. A separate test asserts the derived sets `{"orders","fulfillment","billing"}` and the four. Not vacuous.
- **My arms (source-level, on the migrations, the main test `test_outbox_and_processed_events_are_identical_across_the_four_databases`):**
  - A. `processed_events.consumer nullable=True` in **billing** only: `1 failed` — `"billing.processed_events: column consumer: is_nullable is 'YES', the reference has 'NO'"` (3 differences, incl. the PG18 NOT NULL constraint going missing). Restored, `cmp` identical, `1 passed`.
  - B. billing `outbox.seq` `Identity(always=False)` (sibling substitution): `"billing.outbox: column seq: identity is 'd', the reference has 'a'"`. Restored, green.
  - C. notifications (the fourth database) `created_at` gains `server_default now()` (an added optional element): `"notifications.processed_events: column created_at: col_default is 'now()', the reference has None"`. Restored, green.

### Q2. `otc_notifications` holds `processed_events` and nothing else

- Closed-set equality over `(relname, relkind)` for **every** relkind in `public`, `alembic_version`/`alembic_version_pkc` named; plus a separate "no enum type" test.
- **D1 (mine): a materialized view** in `upgrade()`: `extra: [('consumers_mv', 'm')]`, `1 failed`. Restored, green.
- **D2 (mine): `CREATE SCHEMA audit; CREATE TABLE audit.sent_emails (...)`** in `upgrade()`: **`1 passed`** — the closed set does not see it. → **M1** below.
- Live composed `otc_notifications`: namespaces other than system ones = `{public}` only; `public` holds 2 tables and 3 indexes. The *database* is right today; the *guard* has a hole.

### Q3. Billing schema vs Databases.EN.md §6 and the plan's delta, from the live catalog

- **Money, 7 `bigint`:** composed `otc_billing`, `information_schema.columns WHERE data_type='bigint'` returns 8 rows: the 7 money columns (`credit_items.amount, credits.credit_limit, invoice_items.price, invoices.amount/discount/total_amount, payments.amount`) + `outbox.seq`. `sed -n 241,305p Databases.EN.md | grep -n -i cents` = 5 lines (line 39 names three columns) = 7 columns. Orders = 6 (feature 9), fulfillment = 0 → **6 + 7 + 0 = 13 = #8 id 44's "all 13 money columns"** (`../order-to-cash-dotnet/feature_list.json:1246`). Reconciled.
- **3 FKs, closed:** live `count(*) FROM pg_constraint WHERE contype='f'` = 3. My arm F (`ondelete="RESTRICT"` on `credit_items`, a sibling of NO ACTION): `missing ... 'a', 'a' ... extra ... 'r', 'a'`, `1 failed`; restored green.
- **`payments` has no `updated_at`:** live count 0. My arm E (migration gains `payments.updated_at`): `"payments.updated_at: expected None, live ('timestamp(3) with time zone', False, '')"`, `1 failed`; restored green.
- **Ledger:** every deviation I found is on the implementer's deviation line (uuid, timestamptz(3), bigint money, `char(3)`, widths as §6, `invoice_number_sequences` `integer`/`integer` vs #7 `tinyint`/`int`, identity `seq`, `causation_id`/`trace_parent`, NO ACTION FKs, two FK-supporting indexes). N2's lesson is applied. Citations I re-read: #7 `apps/billing/drizzle/0000_brown_hammerhead.sql:94-96` (3 FKs: no action, cascade, no action), `0002_invoice_sequences_and_order_uniqueness.sql:14-18` (`id tinyint`), #8 `20260901110439_InitialCreate.cs:122/127, 145/150, 169/174` (Restrict, Cascade, Restrict), #7 `apps/notifications/drizzle/0000_sharp_rattler.sql:1-9`, #7 `apps/seed/src/outbox-parity.spec.ts:73-86`. All correct. Some rows lack a file:line on one half → **N2**.

### Q4. The template-database mitigation (root `conftest.py`)

- **Isolation is real.** `CREATE DATABASE … TEMPLATE` gives a private copy; the template is never handed out and has no open connection after Alembic (env.py disposes its `NullPool` engine). Pinned by `tests/database_templates/test_template_isolation.py` (3 tests). **My arm L** (a realistic "optimisation": reuse one copy per service per session): `assert 'otc_test_6aaf…' != 'otc_test_6aaf…'`, `1 failed`; restored, green. **Arm L2 (same mutation, billing's counter suite)**: `2 passed` — the service suites alone would not have noticed (the sentinel deletes before it runs), so the isolation pin is the only guard of this property, and it works. Recorded, no action.
- **Stale template?** No path. `_TEMPLATES` is process memory, names are `uuid4`-suffixed, and the container is session-scoped: a new pytest process builds new templates from the migration files on disk. No test edits a migration in-process. Python byte-code is mtime-checked, and every arm I ran restored and re-ran green after clearing `__pycache__`/`.mypy_cache` (defeat row 10). Even with testcontainers' reuse mode on, the fresh dict and fresh uuid names force a rebuild.
- **Concurrency.** PostgreSQL refuses `CREATE DATABASE … TEMPLATE` while another session is connected to the source (it fails loudly, it does not copy a half state). The suite is serial; under xdist each worker would own its own session container. Safe.
- **Orders and fulfillment still prove what they proved.** `grep` of `fresh_database`: the four lifecycle tests (`test_upgrade_downgrade_reupgrade_lifecycle`) take `fresh_database` + `alembic_runner` and begin with `assert await _relations(db.dsn) == set()` — they still migrate **from empty**. Every other test reads a copy of a database produced by the same `upgrade head`. No test body changed.
- **Ruling on the 4-line edits to the orders and fulfillment conftests:** accepted. The brief ordered the mitigation conditionally ("if it exceeds ~90 s, apply the reviewer's mitigation … This edits the root `conftest.py`") and the mitigation cannot reach orders' and fulfillment's tests without their `migrated_db` asking the root factory. The implementer flagged it. The gap was the brief's bound, not the implementer's discipline.
- **Measured worth.** Integration subset (`services/*/tests/integration tests/database_parity tests/database_templates`, 96 tests), stack down: **55.3 s with the template, 62.3 s with `make` temporarily reverted to `CREATE DATABASE` + `alembic upgrade head`** (conftest restored, `cmp` identical) → **−7.0 s (11 %)**. Whole gate: 95.2 s (implementer, before) → 85.5 s (implementer, after) → **84.6 s (mine)**. The saving is modest, the risk is low and pinned; **keep it**. The real cost is elsewhere: the three counter sentinels are 5.3–5.7 s each (16.4 s), plus the parity arms ~1.5 s each (`--durations`). → **A1**.

### Q5. 208(a): the widened index tuple

- Present in all four services' index tests: `grep -n "indoption\|indnkeyatts\|options\|key_columns"` hits `services/{orders,fulfillment,billing}/tests/integration/test_*_foreign_keys_and_indexes.py` (query + tuple) and `services/notifications/tests/integration/test_notifications_schema.py`.
- **My back-port arm I (orders, NULLS FIRST, a different `indoption` bit from the implementer's DESC):** `ix_orders_retailer_id_status` as `(retailer_id, status NULLS FIRST)`: `missing … (0, 0), 2 … extra … (0, 2), 2`, `1 failed`; restored, green. The implementer armed DESC and INCLUDE-vs-composite, green-before/red-after, on all three services.
- **208(a) met.**

### Q6. 208(b)

- Billing and notifications fixtures clear all six alias variables, and `test_the_fixture_clears_every_alias_the_settings_class_declares` closes the fixture list against the class. With `POSTGRES_HOST_PORT=5433 POSTGRES_HOST=elsewhere POSTGRES_APP_USER=bob POSTGRES_DB_BILLING=x POSTGRES_DB_NOTIFICATIONS=y` exported: **8 passed**. **My arm K** (a new `POSTGRES_SSLMODE` alias added to notifications' settings class): `Extra items in the left set: 'POSTGRES_SSLMODE'`, `1 failed`; restored green.
- Fulfillment with `POSTGRES_HOST_PORT=5433`: **1 failed, 2 passed** (`- alhost:5432/otc_fulfillment` / `+ alhost:5433/otc_fulfillment`), as the report says. Orders' unit tests: 10 passed with the same export.
- 208(b)'s text is "the settings-test fixture clears every alias variable", and review_db_fulfillment N4's disposition scoped it to *the copy feature 11 makes*. **208 is met as written.** The original fulfillment instance → **N1**, proposed **210**, folded into feature 15 (disposition and reason there).

### Q7. Range-guard parity and N5

- `MEMBERS = ("orders", "fulfillment", "billing")`; `assert len(expected) == 3`.
- Census: `glob("*/src/**/{module}")` for both `range_guards.py` and `types.py`, any depth, compared for **equality** with the literal member paths. **My arm J** (a `types.py` in a *member* at the wrong path, `services/orders/src/otc_orders/infrastructure/types.py`): `found [... 'services/orders/src/otc_orders/infrastructure/types.py'], listed [...]`, `1 failed`; file removed, green. CRLF: `test_a_copy_has_unix_line_endings` per member and module (implementer armed it).
- **Notifications' absence is asserted, not skipped:** it is not in `MEMBERS`, so a copy there is an extra path in `found` and fails the equality (implementer's arms X2/X3 named both files). Residual: the census is by file name, so a copy under another name escapes — inherent to a census, recorded, no action.

### Q8. Round trips per billing table

- 8 parametrised tables; `ROWS` is closed against the mappers (`set(row) == mapped`), values distinct within each row (uuids by `_id(n)`, strings, integers `2**32 + n`, instants `_ts(n)` distinct to the millisecond), read back by an independent asyncpg connection **and** by the ORM, every column compared including timestamps; one instant written at +02:00; `seq` separately.
- **My arm G** (model maps `Invoice.company_code` to column `retailer_code` and vice versa — a mapping swap, unlike the implementer's swapped literal values): `{'company_code': 'RET-I'} != {'company_code': 'CO-I'}`, `1 failed`; restored green.
- **My arm G2 (payload on the wire):** `RawJson.column_expression` reads `payload::jsonb::text` (normalised) instead of the raw text: `test_outbox_payload_is_read_back_byte_identical` `1 failed` — `At index 2 diff: b'l' != b'o'`; restored green.

### Q9. Counter seed for `invoice_number_sequences`

- 16 separate asyncpg connections behind an `asyncio.Barrier`, the real `SEED_INVOICE_SEQUENCE` / `LOCK_INVOICE_SEQUENCE` / `ADVANCE_INVOICE_SEQUENCE` strings. Sentinel run by me with `-s`: **`racy seed lost the race in 10 of 10 rounds`**.
- **My arm H** (advance by 2): `assert [1, 3, 5, 7, 9, 11, ...] == [1, 2, 3, 4, ...]`, `1 failed`; restored green.

## Acceptance → test mapping (verified)

| Acceptance (unit) | Test(s) | Seen to fail by |
|---|---|---|
| 1. both histories apply and re-apply (each history) | `services/billing/.../test_billing_migration_lifecycle.py::test_upgrade_downgrade_reupgrade_lifecycle`, `services/notifications/.../test_notifications_migration_lifecycle.py::test_upgrade_downgrade_reupgrade_lifecycle` (from an empty `fresh_database`); composed DBs at `0001` (my `psql`) | implementer (leftover table, view, stray table) |
| 2. outbox/processed_events parity, 4 databases, live catalogs | `tests/database_parity/test_reliability_table_parity.py` (8 tests) | my A, B, C; implementer's 5 permanent + 7 source arms |
| 3. `otc_notifications` = `processed_events` only | `test_otc_notifications_contains_processed_events_and_nothing_else` | my D1 (matview); **D2 escapes (M1)** |
| billing types/money | `test_every_column_of_every_table_has_the_planned_type`, `test_the_seven_money_columns_are_bigint_and_no_other_column_is`, `test_payload_columns_are_json_not_jsonb` | my E |
| billing FK set (3) / index set (22) | `test_the_foreign_key_set_is_exactly_the_three_planned`, `test_the_index_set_is_exactly_the_planned_one` | my F; my I (orders back-port) |
| round trip, JSON bytes | `test_every_column_of_the_table_round_trips[*]`, `test_outbox_payload_is_read_back_byte_identical` | my G, G2 |
| counter + sentinel | `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers`, `test_sentinel_check_then_insert_seed_loses_the_race` | my H; sentinel 10/10 |
| template isolation | `tests/database_templates/test_template_isolation.py` | my L |
| 208(b) | `test_the_fixture_clears_every_alias_the_settings_class_declares` | my K |
| range-guard census | `test_every_file_named_like_a_copy_is_a_listed_member_at_the_listed_path` | my J |

No `R<n>` is in scope (`sdd: false`, schema only).

## Defeat-list rows (my probes)

1 delete: covered by the implementer (FK, unique, seed, lock). 2 corrupt a field: A (nullability), C (default), G (mapping swap), G2 (payload bytes), H (advance step). 3 sibling: B (identity BY DEFAULT for ALWAYS), F (RESTRICT for NO ACTION), I (NULLS FIRST for ASC). 4/6 comment or string: N/A for catalog guards. 5 dead region: implementer measured. 7 optional element: C (default added), E (column added). 8 literal vs literal: none found; expected sets are literals against live catalogs. 9 premise stale: I (narrow tuple would stay green). 10 caches: every arm cleared `__pycache__`/`.mypy_cache` before both runs; template staleness analysed in Q4. 11 unrecognised form: **D2** (a schema-qualified table, the form a `public` filter does not recognise) → M1. 12 path never driven: L2 (service suites never drive cross-test leakage; the pin does).

## #8 db_billing advisories

- **A1 (index presence-only) → avoided.** Closed set of 22, widened tuple; notifications 2 of 2.
- **A2 (parity omits identity) → avoided.** Identity kind and sequence parameters in the shape; my arm B shows `'d'` vs `'a'` named.
- **A3 (no timestamp read-back) → avoided.** Every round trip compares instants; `paid_at`/`value_date` rounding pinned.
- **A4 (parity test inside one service) → avoided.** `tests/database_parity/`, no service import (N3 qualifies "import" to source level).
- **A5 (`current.md` one transition stale) → avoided.** `current.md` reads `in_review` with the reviewer launch.
- **A6 (coverage not gateable) → avoided.** One workspace coverage run, `fail_under = 60`, separate domain gate 80 (`quality.sh` 6/6b).
- Also **id 44 → avoided** (7 bigint money, 13 total reconciled), **id 45 → avoided** (sentinel 10/10, my H), **ids 85/104 → avoided** (Docker-held port, gate green with the stack down).

## Findings

### M1 — MINOR. The "nothing else" closed set of `otc_notifications` is scoped to the `public` schema

`services/notifications/tests/integration/test_notifications_migration_lifecycle.py:28-32` (`RELATIONS … WHERE n.nspname = 'public'`). My arm D2 put `CREATE SCHEMA audit; CREATE TABLE audit.sent_emails` in `upgrade()` and the test stayed **green** (`1 passed`). Acceptance item 3 is a claim about the database, and the brief named `pg_class/pg_namespace`; the namespace was filtered instead of enumerated, so the population is narrower than the unit of the claim. The same `public` filter is in the billing, orders and fulfillment lifecycle closed sets. Today the live database is right (only `public`, verified).
**Disposition: ACCEPTED, NOT FIXED → proposed backlog 209**, attached to **feature 23 `notifications_service`** (the next feature that adds to `otc_notifications`' history): the relation query enumerates every non-system namespace (`nspname NOT IN ('pg_catalog','information_schema','pg_toast') AND nspname NOT LIKE 'pg_temp%' AND nspname NOT LIKE 'pg_toast_temp%'`) and asserts the namespace set is `{public}`, in all four lifecycle tests; armed with my D2 mutation. Re-open trigger: any migration that runs `CREATE SCHEMA` or schema-qualified DDL before 209 closes. It is a test-only change of a few lines: the leader may take it earlier as a **light** change (`test_maintainer`) before the Phase 6 commit.

### N1 — NIT. Fulfillment's settings test still depends on the shell (208(b)'s origin)

`services/fulfillment/tests/unit/test_fulfillment_database_settings.py:11` clears 2 variables; with `POSTGRES_HOST_PORT=5433` exported it fails (measured above). Out of this feature's bound by the brief.
**Disposition: fold into feature 15 → proposed backlog 210**, attached to **feature 15 `orders_acceptance`**: fulfillment's (and orders') settings-test fixtures clear every alias, with billing's closure test `test_the_fixture_clears_every_alias_the_settings_class_declares` copied; armed by exporting `POSTGRES_HOST_PORT=5433` and by adding an alias. Reason for not fixing now: feature 15 already rewrites orders' settings class and test under 204(d)(e), so the four settings tests converge in one change; the failure needs a developer-exported variable that `quality.sh` and CI do not set. Re-open trigger: any CI or `quality.sh` environment that exports a `POSTGRES_*` variable.

### N2 — NIT. Some ledger rows lack a file:line on one half

`progress/impl_db_billing.md:53` (counter seed: #7's seed shape "ON DUPLICATE KEY UPDATE" and #8's "check-then-insert (id 45)" carry no file), `:61` (range guard "none / none" without the citation CLAUDE.md requires for "none owed"), `:62` (Alembic runner). I verified the #7 seed: `../order-to-cash-nestjs/apps/billing/src/infrastructure/persistence/invoice-number-allocator.ts:39-41` (`.onDuplicateKeyUpdate`). **Disposition:** ACCEPTED, NOT FIXED; the leader appends that citation to the row (as for features 9 and 10). No entry.

### N3 — NIT. The parity test loads all four services' models through Alembic

Each `services/*/alembic/env.py:15` imports its `models.Base`, so `tests/database_parity/` runs four services' model modules in one process. Not an import-linter violation (tests are outside the contracts) and harmless (four separate `DeclarativeBase`s). **Disposition:** ACCEPTED; the report's "imports no service package" is true at source level, and A4 is avoided. No entry.

### A1 — ADVISORY. Wall clock: 84.6 s, 5.4 s under the threshold

History: 45.8, 61.0, 69.5, 95.2, 85.5, **84.6** (mine). The template mitigation is worth ~7 s on the integration subset, at low, pinned risk. The three sentinels are 16.4 s, the largest single item. **Disposition:** no entry. Note for the feature 14 brief (the next to add integration tests on all four databases): re-open trigger `quality.sh` > 90 s; the lever to *measure* first is the sentinels' round count (each lost 10 of 10 rounds; a lower count must be proven by a change of kind, not of probability).


## Proposed backlog entries (for the leader to file; I did not write them)

- **209 `closed_set_namespace_scope`**, phase 11, attached to **notifications_service (id 23)**; acceptance: the four lifecycle closed sets enumerate every non-system namespace and assert `{public}`; armed with a schema-qualified table in `upgrade()`. (M1)
- **210 `settings_test_alias_closure_all_services`**, phase 8, attached to **orders_acceptance (id 15)** alongside 204(d)(e); acceptance: fulfillment's and orders' settings-test fixtures clear every alias and carry the alias-closure test; armed with `POSTGRES_HOST_PORT=5433` exported and with a new alias. (N1)
- **208 → `done`** (both items met as written; the residual moved to 210).

## Scope

Within the brief, with one ruled exception (Q4: the orders/fulfillment `migrated_db` edits, accepted). No `specs/shared/` or `CLAUDE.md` change. No git index or working-tree write (`.git/index` mtime 10:07:33, reflog unchanged, no stash).

---

**All applicable boxes are marked (C6 N/A; C5's fourth box is the leader's next step). Feature 11 `db_billing` is APPROVED and set `done`. Phase 6 is complete.**
