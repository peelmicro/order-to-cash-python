# Implementation report — feature 21 `billing_invoicing`

Implementer run of 2026-10-09 (Sonnet 5.5). Status set to `in_review`; nothing committed. **Packages installed: none** (`pyproject.toml`, `services/billing/pyproject.toml` and `uv.lock` untouched by this feature).

## 0. Result

- `./quality.sh` exit **0**, 386 s wall (A2 baseline: exit 0, 365 s). Pytest: **3415 passed** (baseline 3234, **+181**). Overall coverage 97.46 % (baseline 97.42 %, gate 60 %); domain coverage 98 % (baseline 99 %, gate 80 %); `services/billing/src/otc_billing/domain` alone was 96 % in the B11 run. Log: `.arm/bc21/q2.log`.
- **54 of 54 `[ARM]` tasks** were armed; **158 arm rows** were run (one mutation each, several per task) and every one was **seen red**, restored from its `.arm/bc21/backups/<id>/` copy with `cmp` identical, and re-run green. Full verbatim blocks: `.arm/bc21/arms.md`; the table below carries the first failing assertion of each. The sweep was re-run end to end on the final tree (L1): `.arm/bc21/sweep.log`.
- All 65 boxes of `tasks.md` are ticked; the nine boxes whose wording proved wrong, unachievable or incomplete carry a note on the box (A1, B2, C1, C6, D7, F1, F6, I1, K2; see § 2).
- **Gate point G1 applied as decided** (clamp the offset, cutoff before year 1 means no invoice qualifies, the true `page.total`), on all three list subjects.
- No `SA-6`, no migration, no settings, no `services/orders/` change (arm-and-restore only).

## 1. What was built

New, `services/billing/src/otc_billing/`: `domain/{invoice_state,invoice,invoice_snapshot,invoice_events,invoice_errors}.py`; `application/{invoice_issue}.py`, `application/ports/invoice_store.py`; `infrastructure/persistence/{invoice_mapper,invoice_repository,invoice_number_allocator,invoice_reads}.py`; `presentation/invoice_wire.py`.

Extended: `application/{messages,handlers,errors,scope}.py`, `application/ports/credit_store.py` (`CreditTransaction.invoices`, `.invoice_numbers`), `infrastructure/persistence/credit_transactions.py` (three adapters on one session, both repositories' events cleared after the commit), `credit_reads.py` (G1 clamp), `credit_repository.py` (docstring sentence only), `infrastructure/outbox/payloads.py` (two arms, `BillingEvent`), `infrastructure/messaging/subjects.py`, `presentation/credit_responder.py` (two `ROUTES` entries, no rename), `presentation/credit_rpc_errors.py` (§8.4 rows), `composition.py` (two registrations, `invoice_reads`). `services/fulfillment/src/.../stock_reads.py`: the G1 clamp only.

Tests, new: `unit/domain/{test_invoice,test_invoice_state,test_invoice_ids,test_invoice_facts}.py`; `unit/{test_invoice_issue_service,test_invoice_requests,test_invoice_wire,test_invoice_mapper,test_invoice_fixture_guard,test_invoice_list_handler}.py`; `integration/{test_invoice_issue,test_invoice_issue_race,test_invoice_repository,test_invoice_reads,test_invoice_number_allocator,test_invoice_list,test_invoice_wire}.py`. Extended: `unit/test_credit_subjects.py`, `test_credit_rpc_errors.py`, `test_outbox_payloads.py`, `test_credit_responder.py`, `test_credit_transactions.py`; `integration/{conftest,test_billing_outbox_relay,test_billing_host_lifespan,test_credit_list}.py`; `services/fulfillment/tests/integration/test_stock_list.py`; `tests/architecture/{test_registration_behaviour,test_write_path_population,test_billing_rpc_error_retryability}.py`. The two unit files and one integration file that build a `BillingScope` gained the new keyword (C1, diffs below). Docs: `specs/shared/test-matrix.md` (`R45`, `R46`, derived counts), `specs/billing_invoicing/{requirements,tasks}.md`.

## 2. Deviations from the design, each argued

1. **`@final` became a runtime refusal (B2).** `design.md` §5.2 says "two `@final` frozen slotted dataclasses". The `@final` decorator is a new decorator under `services/*/src`; `tests/architecture/test_cqrs_registration_explicit.py` (the census, which §12 says takes no edit and which is not on the file list) failed on it in my first `quality.sh` run (`@final` at `invoice_state.py` lines 35 and 41). I used `__init_subclass__` raising `TypeError` on both classes: closure is enforced at runtime (stronger than the `__final__` flag), `assert_never` still turns a third alias member into a type error (arm B2a, below), and arm B2d deletes the refusal and goes red. **For the leader:** if the decorator form is preferred, `final` takes one entry in `ALLOWED_DECORATORS` with a reason (CLAUDE.md names that procedure).
2. **`PaymentSource` lives in `domain/invoice_events.py`** and is re-exported by `domain/invoice.py`: `invoice.py` imports the events, the events carry the enum, so the design's placement in `invoice.py` is an import cycle.
3. **C1 could not be "the keyword argument only".** `CreditTransaction` gained two properties, and `mypy --strict` checks the two unit files' `FakeTransactions` against that protocol. Both therefore also gained the two refusing properties and a refusing `NoInvoiceReads` class; no assertion changed. The three diffs (against the copies taken before the edit, `.arm/bc21/c1/`):

```text
=== unit/test_credit_hold_service.py
19c19,24
< from otc_billing.application.messages import CreditPage, HoldCreditCommand, HoldOutcomeKind
---
> from otc_billing.application.messages import (
>     CreditPage,
>     HoldCreditCommand,
>     HoldOutcomeKind,
>     InvoicePage,
> )
26a32
> from otc_billing.application.ports.invoice_store import InvoiceNumberAllocator, InvoiceRepository
30a37
> from otc_billing.domain.invoice_snapshot import InvoiceSnapshot
94a102,109
>     @property
>     def invoices(self) -> InvoiceRepository:
>         raise AssertionError("the hold touched the invoice repository")
> 
>     @property
>     def invoice_numbers(self) -> InvoiceNumberAllocator:
>         raise AssertionError("the hold touched the invoice number allocator")
> 
111a127,136
> class NoInvoiceReads:
>     """The invoice reads: the hold must never touch them."""
> 
>     async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
>         raise AssertionError("the hold read an invoice")
> 
>     async def list(self, **kwargs: object) -> InvoicePage:
>         raise AssertionError("the hold read the invoice list")
> 
> 
152a178
>             invoice_reads=NoInvoiceReads(),
=== unit/test_credit_release_service.py
14c14
< from otc_billing.application.messages import CreditPage, ReleaseCreditCommand
---
> from otc_billing.application.messages import CreditPage, InvoicePage, ReleaseCreditCommand
16a17
> from otc_billing.application.ports.invoice_store import InvoiceNumberAllocator, InvoiceRepository
20a22
> from otc_billing.domain.invoice_snapshot import InvoiceSnapshot
81a84,91
>     @property
>     def invoices(self) -> InvoiceRepository:
>         raise AssertionError("the release touched the invoice repository")
> 
>     @property
>     def invoice_numbers(self) -> InvoiceNumberAllocator:
>         raise AssertionError("the release touched the invoice number allocator")
> 
92a103,112
> class NoInvoiceReads:
>     """The invoice reads: the release must never touch them."""
> 
>     async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
>         raise AssertionError("the release read an invoice")
> 
>     async def list(self, **kwargs: object) -> InvoicePage:
>         raise AssertionError("the release read the invoice list")
> 
> 
121a142
>         invoice_reads=NoInvoiceReads(),
=== integration/test_credit_repository.py
43a44
> from otc_billing.infrastructure.persistence.invoice_reads import SqlAlchemyInvoiceReads
198a200
>         invoice_reads=SqlAlchemyInvoiceReads(store.sessions),
```

4. **`parse_invoice_state` takes a keyword-only `invoice_reference`** (default `None`) so the refusal "names the invoice" (`BI10`), which the two-argument signature in B3 cannot do.
5. **`Invoice.rehydrate` additionally refuses** a negative stored total and a foreign-currency amount (B6); §5.4 names only the disagreeing totals. Both are covered (`test_bi10_...`).
6. **Extra conftest helpers** beyond F1's list: `Db.invoice_counter`, `Db.hold_counter` (I1), the `make_invoice_store` fixture (D3, D6, F3). The issue-fixture builder keeps `amount`, `discount`, `total` pairwise distinct, non-zero and substring-free with ONE containment check (equal values contain one another), a zero-gross refusal and the flag-with-a-non-zero-figure refusals; its separate "zero" and "equality" branches were equivalent mutants (a zero always equals another figure) and were removed rather than left to survive.
7. **I1 holds the counter row as well** as the line (see the box): without it the arm that drops the line lock dies in `wait_for_lock_waiters` instead of reaching the assertion about the loser's reply.
8. **F5's arm mutates an outbox copy.** The prescribed arm "key by `aggregate_id`" lives in `infrastructure/outbox/wire.py`, a copy on the must-not-touch list. It was armed and restored from its backup with `cmp` (the same exception `tasks.md` grants `services/orders/` in C6); `tests/architecture/test_outbox_copy_parity.py` is green on the final tree.
9. **`Invoice.rehydrate` has no production caller** in this feature (the issue path summarises a stored invoice from its snapshot and never rebuilds the aggregate); it is feature 22's seam, covered by unit tests only.

### Findings about the design text (not defects of the code)

- **F6's arm outcome.** §6.2 and `tasks.md` F6 say a request that skips both the fast path and the re-read answers `INTERNAL_ERROR` from the unique constraint. Observed: `PRECONDITION_FAILED` (`credit.no_active_hold`), because `consume` runs before the insert and the order's hold is already consumed.
- **I1's three losers.** Only one of the three arms ends in `INTERNAL_ERROR`. Observed loser replies: re-read before the lock: `PRECONDITION_FAILED`; no line lock: `INTERNAL_ERROR` (`23505`); `REPEATABLE READ`: `UNAVAILABLE` (`40001`, SQLSTATE read in the reply message). All three fail the "exactly one `created: false`" assertion.
- **K1 pre-state.** `ORD-000008`'s `invoice.issue` row was `parked` with attempts **6**, not 3 as §14 says; the counter row was absent as expected.
- **Billing logs no request lines** (feature 27), so K2's "Billing's log line" cannot exist; the evidence is the databases.

## 3. Requirement to test map

Names are the matrix names verbatim where the matrix prescribes one. `U` = `services/billing/tests/unit/`, `I` = `services/billing/tests/integration/`, `A` = `tests/architecture/`.

| Id | Proved by |
|---|---|
| R45 | `U/domain/test_invoice.py::test_r45_creates_exactly_one_issued_invoice_mirroring_the_despatched_lines_with_a_non_negative_total_and_returns_the_existing_reference_emitting_no_second_fact_on_a_repeat` (aggregate half; its docstring says the repeat half is C2 and F6); `I/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` |
| R46 | `U/domain/test_invoice.py::test_r46_allows_only_the_transition_from_issued_to_paid_sets_paid_at_exactly_then_and_raises_on_every_other_transition_changing_and_emitting_nothing` |
| BI1 | `A/test_kafka_client_confinement.py`, `I/test_billing_host_lifespan.py::test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown` (armed H3a, H3b) |
| BI2 | `U/test_invoice_requests.py::test_bi2_refuses_a_malformed_issue_request_with_validation_failed_without_calling_the_dispatcher` (dispatcher called zero times); `U/test_credit_responder.py::test_bi2_billing_invoice_issue_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`; `I/test_invoice_issue.py::test_bi2_answers_validation_failed_and_writes_nothing_for_an_invalid_header_or_payload` (its comment says it does not prove placement) |
| BI3, BI4, BI5, BI6 | `I/test_invoice_issue.py::test_bi3_...`, `test_bi4_...`, `test_bi5_replies_precondition_failed_for_no_active_hold_and_leaves_the_orders_ledger_rows_unchanged`, `test_bi6_emits_no_fact_of_any_type_on_every_refusal_path`; `U/test_invoice_issue_service.py::test_bi5_no_active_hold_raises_before_the_allocator_and_saves_nothing` |
| BI7 | `I/test_invoice_repository.py::test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback` |
| BI8 | `U/test_invoice_issue_service.py::test_bi8_locks_the_credit_line_then_re_reads_the_invoice_then_allocates_the_number` (the ordering clause's only guard); `I/test_invoice_issue_race.py::test_bi8_two_concurrent_issues_for_one_order_yield_one_invoice_one_consume_and_one_fact` (its header says it cannot see an inversion) |
| BI9 | `I/test_invoice_issue.py::test_bi9_a_repeat_returns_the_existing_invoice_with_created_false_and_writes_nothing_whether_issued_or_paid` |
| BI10, BI11 | `U/domain/test_invoice.py::test_bi10_...`, `test_bi11_...`; `I/test_invoice_repository.py::test_bi10_a_stored_row_whose_status_and_paid_at_disagree_is_refused_by_the_mapper` |
| BI12, BI29 | `I/test_invoice_number_allocator.py` (six cases, ported from Fulfillment's), `I/test_billing_counter_seed.py` (five cases, re-run: 11 passed together) |
| BI13, BI34 | `U/domain/test_invoice_facts.py::test_bi13_...`, `U/domain/test_invoice_ids.py::test_bi34_...`, `U/test_invoice_issue_service.py::test_bi34_the_issue_hands_the_scope_id_port_to_both_aggregates` |
| BI14 | `U/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field`, `::test_bi14_mark_paid_refuses_a_paid_invoice_a_wrong_amount_and_a_wrong_currency_changing_and_emitting_nothing` |
| BI15 | `I/test_invoice_list.py::test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now`, `I/test_invoice_reads.py::test_bi15_the_cutoff_is_the_supplied_now_and_nothing_is_written`, `U/test_invoice_list_handler.py` |
| BI16, BI31 | `U/test_credit_subjects.py` (five channels, the route table), `I/test_invoice_wire.py::test_bi16_both_invoice_subjects_answer_bare_json_and_a_refusal_is_a_bare_rpc_error` |
| BI21 | Orders' `test_command_payloads.py`, armed in C6 (two arms), no file changed |
| BI22 | § 9 below (live) |
| BI23, BI27 | `U/domain/test_invoice_state.py` (three tests, one of them a real `mypy --strict` subprocess) |
| BI24 | `I/test_invoice_repository.py::test_bi24_...` (session `TimeZone = 'Europe/Madrid'`, through the mapper, null and non-null) |
| BI25 | `U/domain/test_invoice.py::test_bi25_...`, the overflow row of `U/test_credit_rpc_errors.py` |
| BI26 | `A/test_billing_rpc_error_retryability.py::test_bi26_no_active_hold_is_answered_with_a_code_in_the_saga_adapters_terminal_set` |
| BI32 | `U/test_invoice_wire.py::test_bi32_...`, `I/test_invoice_list.py::test_bi32_an_issued_view_writes_paid_at_null_and_a_paid_view_the_instant_in_the_raw_reply` (raw bytes through the host) |
| BI33 | `U/test_invoice_requests.py::test_bi33_...` |
| BI35 | `U/domain/test_invoice.py::test_bi35_a_zero_total_invoice_is_issued`, `I/test_invoice_issue.py::test_bi35_a_zero_hold_is_consumed_and_a_zero_total_invoice_issued` |
| BI36 | `U/test_credit_rpc_errors.py::test_bi36_invoice_error_messages_render_amounts_with_the_money_text_formatter` (EUR, JPY, BHD) |
| BI37 | `I/test_invoice_list.py::test_bi37_...`, `I/test_credit_list.py::test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total`, `services/fulfillment/tests/integration/test_stock_list.py::test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total` |
| BI38 | the `R45` unit and host cases (non-zero discount), `U/test_invoice_fixture_guard.py`, and arms F7a - F7d |

## 4. Fixtures: the plausible wrong values and why the expected value differs from each

Every issue fixture is built from lines by `issue_body`, which refuses a fixture whose `amount`, `discount` and `totalAmount` coincide, are zero or contain one another (BI38; #8's `D2`). Used throughout: gross **8465** (3 x 1999 + 2 x 1234, sent as PRD-ZZ then PRD-AA, not canonical), discount **350**, net **8115** (also the hold).

| Assertion | Plausible wrong values | Fixture's expected value differs from each |
|---|---|---|
| `totalAmount` | gross (discount ignored); gross minus twice the discount; the discount (transposed) | 8115 vs 8465, 7765, 350 (arms B5a, F7a, F7b, F7c, F7d, E4c) |
| `discount` column and fact | 0; the total; the gross | 350 vs 0, 8115, 8465 (F7a, F7c, F7d) |
| `invoice_items.price` | the line total (5997, 2468) | 1999, 1234 (arm D4a) |
| available credit before and after an issue | the limit; the gross; the net; another line's value; the other order's hold | 221 864 (limit 250 000, other hold 20 021, net 8115, second line 120 000) differs from every one |
| `retailerCode` / `companyCode` | each other | `RETAIL-77` is neither `SUPPLY-CO` nor contained in it (arms B8c, J1-S5) |
| order id, request id, invoice id | each other | three different UUIDs in every host test |
| payment fields (`mark_paid`) | `value_date` = the instant; `source` the first enum member | `value_date` is a day and seven minutes later; `source` is `ROBOT`, not `OPERATOR` (arms B9b, B9c) |
| list cutoff | the wall clock; `<` for `<=` | `now` is 2031-03-15, five years from any run; two invoices sit exactly at the 60-minute cutoff (arms D5a, D5b) |

## 5. Searches, as search results

### 5.1 A1 — `design.md` §1 against the tree (read 2026-10-09, before any edit)

- `models.py:90-138`: `invoices` (`:90`) has `invoice_reference` unique (`:94`), `order_reference` unique (`:98`), `amount`/`discount`/`total_amount` bigint, `currency_code` CHAR(3), `status` String(20), `paid_at` nullable `_ts()`, `created_at`, `updated_at`; `invoice_items` (`:109`) `id, invoice_id FK ON DELETE CASCADE, product_code String(30), units Integer, price BigInteger, created_at, updated_at`; `invoice_number_sequences` (`:122`) `id, next_value Integer`; `payments` (`:128`). All present as §1's table says. No migration owed.
- `sequences.py:30-40`: `SEED_INVOICE_SEQUENCE`, `LOCK_INVOICE_SEQUENCE`, `ADVANCE_INVOICE_SEQUENCE` present (seed is the one-statement `WHERE NOT EXISTS ... ON CONFLICT DO NOTHING`).
- `credit_transactions.py`: `READ COMMITTED` pinned at `:77`, `repository.clear_saved_events()` at `:81` (after the `async with` block). `credit_responder.py`: `ROUTES` at `:88`, `Semaphore` `:109`, `_drain` `:167`, `except Exception` `:185`. `buyer_credit.py`: `consume` at `:386`. `credit_rpc_errors.py`: `match error` `:43`, `case DomainError()` `:60`. `payloads.py`: `narrow` `:35`, `build_fact` `:96`. `facts.py:57-58`: `invoice.issued.v1`, `payment.received.v1` in `FACT_MODELS`. `nats_saga_commands.py:65-75`: `TERMINAL_RPC_ERROR_CODES` (nine codes). `stock_responder.py:121-128`: `ROUTES` with `DESPATCH_CREATE_SUBJECT`. `despatch_number_allocator.py`: three-statement allocator as §9.3 describes.
- Absence claims (search results):
  - `grep -rn "AIOKafkaConsumer" services/billing/src` -> no output (zero hits).
  - `grep -rn "\.offset(" services/*/src` -> `services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py:46` and `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py:79` (exactly the two sites §16.1 names).
  - `grep -rln "BillingScope(" services/billing/tests tests` -> `services/billing/tests/integration/test_credit_repository.py`, `services/billing/tests/unit/test_credit_release_service.py`, `services/billing/tests/unit/test_credit_hold_service.py` (exactly the three §7.2 names).
- Result: no false item.

### 5.2 A2 — baseline (developer stack down; only `otcpy-n8n` running)

`./quality.sh` exit code **0**, duration **365 s**, `3234 passed in 337.69s`, total coverage 97.42 % (gate 60 %), web gates green. Log: `.arm/bc21/a2_quality.log`.

The three absence greps have a sentinel (a scratch file under `.arm/bc21/a1_sentinel/` with `AIOKafkaConsumer`, `.offset(` and `BillingScope(` planted), and each finds it:

```text
$ grep -rn "AIOKafkaConsumer" .arm/bc21/a1_sentinel   # sentinel
.arm/bc21/a1_sentinel/planted.py:1:from aiokafka import AIOKafkaConsumer
.arm/bc21/a1_sentinel/planted.py:2:x = AIOKafkaConsumer
$ grep -rn "\.offset(" .arm/bc21/a1_sentinel
.arm/bc21/a1_sentinel/planted.py:3:rows = q.offset(3)
$ grep -rln "BillingScope(" .arm/bc21/a1_sentinel
.arm/bc21/a1_sentinel/planted.py

=== the real populations, final tree ===
$ grep -rn "AIOKafkaConsumer" services/billing/src
[exit 1]
$ grep -rln "BillingScope(" services/billing/tests tests
services/billing/tests/integration/test_credit_repository.py
services/billing/tests/unit/test_credit_release_service.py
services/billing/tests/integration/test_invoice_repository.py
services/billing/tests/unit/test_invoice_issue_service.py
services/billing/tests/unit/test_credit_hold_service.py
```

### 5.3 D7 — the countable claims (command and full output)

Expected sets: (1) zero; (2) exactly `range_guards.py:14`, `credit_repository.py:19` (both docstrings) and `outbox/relay.py:162`; (3) `credit_mapper.py:5`, `range_guards.py:15` (docstrings), `credit_repository.py:37` (the scalar, a `SELECT`) and the three allocator calls; (4) exactly `types.py:3` (docstring). Classification, one per hit: every hit of (2), (3) and (4) is in the expected set. Two reconciliations, both fixed at the source: `credit_repository.py` is now line 38 (the D1 rewording added a line), and the first run found two extra DOCSTRING hits (`invoice_number_allocator.py:13` and `invoice_wire.py:19`), which were reworded so the sets equal the expected ones; the second block is the re-run. The sentinel (`with_for_update()` in a scratch copy) is found by the first command.

```text
$ grep -n "with_for_update" services/billing/src/otc_billing/infrastructure/persistence/invoice_*.py
[exit 1]

$ grep -rnE "\bupdate\(|\bdelete\(|on_conflict" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/outbox/relay.py:162:                            update(Outbox)
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:19:No `update(`, `delete(`, `on_conflict_*` or textual DML exists in this service outside
services/billing/src/otc_billing/infrastructure/persistence/range_guards.py:14:2's bulk insert), `update(Model)` (with `.where().values()` or bulk-by-primary-key), and
[exit 0]

$ grep -rnE "\btext\(" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:38:_COMMITTED_EXPOSURE = text(
services/billing/src/otc_billing/infrastructure/persistence/range_guards.py:15:`session.bulk_insert_mappings` / `bulk_update_mappings`. So does raw `text()` SQL. They are not
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:13:These are the only textual DML statements in the Billing service (L26): `text()` bypasses the ORM
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:34:        await self._session.execute(text(SEED_INVOICE_SEQUENCE))
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:35:        allocated = (await self._session.execute(text(LOCK_INVOICE_SEQUENCE))).scalar_one()
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:36:        await self._session.execute(text(ADVANCE_INVOICE_SEQUENCE))
services/billing/src/otc_billing/infrastructure/persistence/credit_mapper.py:5:event). An `insert(...).values(...)`, a `text()` or a SQL expression bypasses it and surfaces as the
[exit 0]

$ grep -rn "func.sum\|isoformat()\|json.dumps" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/persistence/types.py:3:SQLAlchemy's own `JSON` type calls `json.dumps` on bind and `json.loads` on read, which would
services/billing/src/otc_billing/presentation/invoice_wire.py:19:`InvoiceView.paidAt` is declared nullable (BI32). No `json.dumps`, no `isoformat()` here.
[exit 0]
$ grep -n "with_for_update" .arm/bc21/d7/sentinel/invoice_*.py    # the SENTINEL: a scratch copy plus one planted file
.arm/bc21/d7/sentinel/invoice_sentinel.py:3:query = select(1).with_for_update()
[exit 0]

=== D7 re-run after the docstring rewording ===
$ grep -n "with_for_update" services/billing/src/otc_billing/infrastructure/persistence/invoice_*.py
[exit 1]
$ grep -rnE "\btext\(" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:38:_COMMITTED_EXPOSURE = text(
services/billing/src/otc_billing/infrastructure/persistence/credit_mapper.py:5:event). An `insert(...).values(...)`, a `text()` or a SQL expression bypasses it and surfaces as the
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:34:        await self._session.execute(text(SEED_INVOICE_SEQUENCE))
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:35:        allocated = (await self._session.execute(text(LOCK_INVOICE_SEQUENCE))).scalar_one()
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:36:        await self._session.execute(text(ADVANCE_INVOICE_SEQUENCE))
services/billing/src/otc_billing/infrastructure/persistence/range_guards.py:15:`session.bulk_insert_mappings` / `bulk_update_mappings`. So does raw `text()` SQL. They are not
[exit 0]
$ grep -rn "func.sum\|isoformat()\|json.dumps" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/persistence/types.py:3:SQLAlchemy's own `JSON` type calls `json.dumps` on bind and `json.loads` on read, which would
[exit 0]
```

### 5.4 G5 — `BC32`'s population, rooted at the decode

Full population: 144 hits under `services/billing/tests` (`grep -rnE "from_wire_json|json\.loads|Decode\.|decode\." services/billing/tests | wc -l`); below, the hits in the files this feature added or extended. Classification: every `decode.<x>(...)` call goes through a `Decode` method whose first statement is an `assert` on the reply's discriminating field (`conftest.py` lines 521 - 548: `"code" in reply`, `"outcome" in reply`, `"released" in reply`, `"created" in reply`, `"page"` then `"total"`), so a wrong-shaped or error-shaped reply fails on a named assertion; the raw `json.loads` sites are (a) `test_invoice_wire.py:60, 70, 81`, each followed within two lines by an `assert "created" in` / `"page" in` / `"code" in` before any other use, (b) `test_invoice_list.py:159, 167, 171`, each reading `["page"]["total"]` or asserting it before the items, (c) `test_billing_outbox_relay.py:82, 144, 242, 251`: Kafka records, not RPC replies, (d) `conftest.py:257, 481, 509`: the outbox payload column, the request body and the transport helper, (e) `unit/test_invoice_wire.py:71, 102`: bytes written by the serializer, the key set asserted first. The sentinel (a decode with no check, planted under `.arm/bc21/g5_sentinel/`) is found by the same command. Arm G5 (the list handler raises) goes red on the named `BC32: expected an invoice list reply (a \`page\`)` assertion, not on a `KeyError`.

```text
$ grep -rnE "from_wire_json|json\.loads|Decode\.|decode\." services/billing/tests   # full population, then the new files
integration/test_billing_outbox_relay.py:82:                    if json.loads(r.value)["correlationId"] == correlation_id
integration/test_billing_outbox_relay.py:105:    assert decode.hold(reply).outcome.value == "approved"
integration/test_billing_outbox_relay.py:144:    envelope = json.loads(record.value)
integration/test_billing_outbox_relay.py:203:    assert decode.hold(held).outcome.value == "approved"
integration/test_billing_outbox_relay.py:228:        issued = decode.invoice_issue(reply)
integration/test_billing_outbox_relay.py:242:        r for r in records if json.loads(r.value)["eventType"] == "invoice.issued.v1"
integration/test_billing_outbox_relay.py:251:    envelope = json.loads(record.value)
integration/test_credit_list.py:62:    listed = decode.list(reply)  # asserts the reply's own `page.total` first
integration/test_credit_list.py:83:    filtered = decode.list(await rpc("billing.credit.list", {"retailerCode": "RETAIL-C3"}))
integration/test_credit_list.py:87:    by_company = decode.list(await rpc("billing.credit.list", {"companyCode": "SUPPLY-CO"}))
integration/test_credit_list.py:89:    none = decode.list(await rpc("billing.credit.list", {"companyCode": "SUPPLY-XX"}))
integration/test_credit_list.py:93:    second = decode.list(await rpc("billing.credit.list", {"page": 2, "pageSize": 3}))
integration/test_credit_list.py:96:    first = decode.list(await rpc("billing.credit.list", {"page": 1, "pageSize": 3}))
integration/test_credit_list.py:106:    listed = decode.list(await rpc("billing.credit.list", {}, headers=None))
integration/test_credit_list.py:119:    far = decode.list(await rpc("billing.credit.list", {"page": past_int64, "pageSize": 25}))
integration/test_credit_list.py:124:    first = decode.list(await rpc("billing.credit.list", {"page": 1, "pageSize": 25}))
integration/test_invoice_issue.py:19:asserts its discriminating field first (`Decode.invoice_issue`: `created`).
integration/test_invoice_issue.py:68:        assert decode.hold(reply).outcome.value == "approved"
integration/test_invoice_issue.py:85:    listed = decode.list(reply)
integration/test_invoice_issue.py:114:    issued = decode.invoice_issue(reply)  # asserts `created` is present first
integration/test_invoice_issue.py:202:    first = decode.invoice_issue(
integration/test_invoice_issue.py:213:    second = decode.invoice_issue(
integration/test_invoice_issue.py:245:    paid = decode.invoice_issue(
integration/test_invoice_issue.py:302:        error = decode.error(reply)  # asserts the reply is an RpcError first
integration/test_invoice_issue.py:308:    control = decode.invoice_issue(await rpc("billing.invoice.issue", good.body, headers=headers))
integration/test_invoice_issue.py:326:    error = decode.error(reply)
integration/test_invoice_issue.py:333:    control = decode.invoice_issue(
integration/test_invoice_issue.py:350:    error = decode.error(reply)
integration/test_invoice_issue.py:356:    control = decode.invoice_issue(
integration/test_invoice_issue.py:367:    released = decode.release(
integration/test_invoice_issue.py:383:    error = decode.error(reply)
integration/test_invoice_issue.py:393:    control = decode.invoice_issue(
integration/test_invoice_issue.py:413:        error = decode.error(await rpc("billing.invoice.issue", payload, headers=headers))
integration/test_invoice_issue.py:419:    control = decode.invoice_issue(await rpc("billing.invoice.issue", good.body, headers=ids()[0]))
integration/test_invoice_issue.py:441:    hold = decode.hold(await rpc("billing.credit.hold", hold_body(ORDER, 0), headers=ids()[0]))
integration/test_invoice_issue.py:449:    issued = decode.invoice_issue(reply)
integration/test_invoice_wire.py:3:The replies are decoded with plain `json.loads` FIRST: no `response`, `isDisposed` or `id` key (the
integration/test_invoice_wire.py:14:from otc_contracts import from_wire_json
integration/test_invoice_wire.py:54:    assert decode.hold(held).outcome.value == "approved"
integration/test_invoice_wire.py:60:    issue_reply = json.loads(issue_bytes)
integration/test_invoice_wire.py:65:    parsed = from_wire_json(asyncapi.InvoiceIssueReplyPayload, issue_bytes)
integration/test_invoice_wire.py:70:    list_reply = json.loads(list_bytes)
integration/test_invoice_wire.py:73:    assert from_wire_json(asyncapi.InvoiceListReplyPayload, list_bytes).page.total == 1
integration/test_invoice_wire.py:81:        decoded = json.loads(refusal)
integration/test_invoice_wire.py:84:        error = from_wire_json(asyncapi.RpcError, refusal)
integration/test_invoice_list.py:60:    everything = decode.invoice_list(await rpc("billing.invoice.list", {}))
integration/test_invoice_list.py:65:    by_status = decode.invoice_list(await rpc("billing.invoice.list", {"status": "paid"}))
integration/test_invoice_list.py:68:    issued = decode.invoice_list(await rpc("billing.invoice.list", {"status": "issued"}))
integration/test_invoice_list.py:72:    by_retailer = decode.invoice_list(await rpc("billing.invoice.list", {"retailerCode": R77}))
integration/test_invoice_list.py:75:    by_company = decode.invoice_list(await rpc("billing.invoice.list", {"companyCode": S_CO}))
integration/test_invoice_list.py:78:    by_order = decode.invoice_list(
integration/test_invoice_list.py:84:    combined = decode.invoice_list(
integration/test_invoice_list.py:93:    old = decode.invoice_list(await rpc("billing.invoice.list", {"issuedBeforeMinutes": 60}))
integration/test_invoice_list.py:96:    older = decode.invoice_list(
integration/test_invoice_list.py:102:    second = decode.invoice_list(await rpc("billing.invoice.list", {"page": 2, "pageSize": 2}))
integration/test_invoice_list.py:105:    last = decode.invoice_list(await rpc("billing.invoice.list", {"page": 3, "pageSize": 2}))
integration/test_invoice_list.py:159:    assert json.loads(both)["page"]["total"] == 2  # the discriminating field, first
integration/test_invoice_list.py:167:    only_issued = json.loads(await raw({"status": "issued"}))
integration/test_invoice_list.py:171:    only_paid = json.loads(await raw({"status": "paid"}))
integration/test_invoice_list.py:184:    listed = decode.invoice_list(far)  # asserts `page.total` is present: NOT an RpcError
integration/test_invoice_list.py:189:    ancient = decode.invoice_list(
integration/test_invoice_list.py:196:    first = decode.invoice_list(await rpc("billing.invoice.list", {"page": 1, "pageSize": 25}))
integration/test_invoice_list.py:199:    sane = decode.invoice_list(await rpc("billing.invoice.list", {"issuedBeforeMinutes": 60}))
integration/test_invoice_issue_race.py:58:    assert decode.hold(held).outcome.value == "approved"
integration/test_invoice_issue_race.py:81:    decoded = [decode.invoice_issue(reply) for reply in replies]
integration/conftest.py:40:from otc_contracts import from_wire_json
integration/conftest.py:257:        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
integration/conftest.py:481:    parsed = json.loads(body) if isinstance(body, bytes) else body
integration/conftest.py:509:        parsed: dict[str, Any] = json.loads(reply.data)
integration/conftest.py:522:        return from_wire_json(asyncapi.RpcError, json.dumps(reply).encode())
integration/conftest.py:527:        return from_wire_json(asyncapi.CreditHoldReplyPayload, json.dumps(reply).encode())
integration/conftest.py:532:        return from_wire_json(asyncapi.CreditReleaseReplyPayload, json.dumps(reply).encode())
integration/conftest.py:537:        return from_wire_json(asyncapi.InvoiceIssueReplyPayload, json.dumps(reply).encode())
integration/conftest.py:543:        return from_wire_json(asyncapi.InvoiceListReplyPayload, json.dumps(reply).encode())
integration/conftest.py:549:        return from_wire_json(asyncapi.CreditListReplyPayload, json.dumps(reply).encode())
unit/test_invoice_wire.py:71:    decoded = json.loads(invoice_wire.encode(reply))
unit/test_invoice_wire.py:102:    reply = json.loads(text)
$ grep -rnE "from_wire_json|json\.loads|Decode\.|decode\." .arm/bc21/g5_sentinel   # the sentinel
.arm/bc21/g5_sentinel/test_sentinel.py:5:    reply = json.loads((await nats_client.request("billing.invoice.list", b"{}")).data)
[exit 0]
```

### 5.5 G6 — the offset sites after the change (three hits, three clamps)

```text
$ grep -rn "\.offset(" services/*/src
services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py:48:                    .offset(min((page - 1) * page_size, MAX_OFFSET))
services/billing/src/otc_billing/infrastructure/persistence/invoice_reads.py:79:                    .offset(min((page - 1) * page_size, MAX_OFFSET))
services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py:81:                    .offset(min((page - 1) * page_size, MAX_OFFSET))
```

### 5.6 J1 — every call site of the hand-built seams

The command (full output, 70 lines, `.arm/bc21/j1_population.out`):

```text
$ grep -rnE "find_by_order_reference|lock_for_order|next_reference|\.consume\(|Invoice\.issue|\.mark_paid|rehydrate|parse_invoice_state|state_token|\.save\(|required_correlation|decode_issue|decode_list|scope\.ids\.new|scope\.clock\.now|\.offset\(" services/billing/src --include='*.py'
services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py:48:                    .offset(min((page - 1) * page_size, MAX_OFFSET))
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:71:    async def lock_for_order(
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:91:        credit = BuyerCredit.rehydrate(
services/billing/src/otc_billing/application/ports/invoice_store.py:21:    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
services/billing/src/otc_billing/application/ports/invoice_store.py:33:    async def next_reference(self) -> InvoiceReference:
services/billing/src/otc_billing/application/ports/invoice_store.py:41:    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
services/billing/src/otc_billing/application/ports/ids.py:4:`new_id`); the transactional units pass `scope.ids.new`, so a test that supplies known identifiers
services/billing/src/otc_billing/application/credit_hold.py:46:    credit = await credits.lock_for_order(
services/billing/src/otc_billing/application/credit_hold.py:87:                    await credits.save(credit)
services/billing/src/otc_billing/application/credit_hold.py:100:    await credits.save(credit)
services/billing/src/otc_billing/application/credit_hold.py:116:        context=CreditContext(occurred_at=scope.clock.now(), causation_id=command.request_id),
services/billing/src/otc_billing/application/credit_hold.py:117:        new_id=scope.ids.new,
services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py:33:    async def next_reference(self) -> InvoiceReference:
services/billing/src/otc_billing/domain/buyer_credit.py:8:  `Fits`, `rehydrate` refuses a stored line already over its limit.
services/billing/src/otc_billing/domain/buyer_credit.py:135:    def rehydrate(cls, snapshot: BuyerCreditSnapshot) -> Self:
services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:3:* `find_by_order_reference` is a plain SELECT. Called INSIDE the transaction after the `credits`
services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:7:  `SqlAlchemyInvoiceReads.find_by_order_reference` it is the fast path. Never locks.
services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:48:    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
services/billing/src/otc_billing/infrastructure/persistence/invoice_reads.py:6:* `find_by_order_reference` is `load_invoice` on that session: the issue path's fast path.
services/billing/src/otc_billing/infrastructure/persistence/invoice_reads.py:35:    async def find_by_order_reference(self, order_reference: str) -> InvoiceSnapshot | None:
services/billing/src/otc_billing/infrastructure/persistence/invoice_reads.py:79:                    .offset(min((page - 1) * page_size, MAX_OFFSET))
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:5:  the one place they meet. Reading, `parse_invoice_state(row.status, row.paid_at)` is the only
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:7:  snapshot. Writing, both columns are derived from the one `state` (`state_token(...).value` and
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:29:from otc_billing.domain.invoice_state import paid_at_of, parse_invoice_state, state_token
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:72:        state=parse_invoice_state(row.status, row.paid_at, invoice_reference=row.invoice_reference),
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:78:    state = parse_invoice_state(row.status, row.paid_at, invoice_reference=row.invoice_reference)
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:90:        status=state_token(state),
services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py:107:        status=state_token(invoice.state).value,
services/billing/src/otc_billing/application/handlers.py:63:        now = self._scope.clock.now()
services/billing/src/otc_billing/domain/invoice_state.py:13:`parse_invoice_state` is the only function that combines the store's two columns. It is loud: an
services/billing/src/otc_billing/domain/invoice_state.py:15:`state_token` writes only the lower-case contract tokens (BI27).
services/billing/src/otc_billing/domain/invoice_state.py:59:def state_token(state: InvoiceState) -> InvoiceStatus:
services/billing/src/otc_billing/domain/invoice_state.py:79:def parse_invoice_state(
services/billing/src/otc_billing/application/credit_release.py:28:    credit = await credits.lock_for_order(
services/billing/src/otc_billing/application/credit_release.py:49:    await credits.save(credit)
services/billing/src/otc_billing/application/credit_release.py:64:        context=CreditContext(occurred_at=scope.clock.now(), causation_id=command.request_id),
services/billing/src/otc_billing/application/credit_release.py:65:        new_id=scope.ids.new,
services/billing/src/otc_billing/presentation/credit_wire.py:82:def decode_list(body: bytes) -> ListCreditQuery:
services/billing/src/otc_billing/application/ports/credit_store.py:30:    async def lock_for_order(
services/billing/src/otc_billing/presentation/credit_responder.py:46:from otc_billing.presentation.credit_headers import optional_correlation_id, required_correlation
services/billing/src/otc_billing/presentation/credit_responder.py:65:    correlation = required_correlation(headers)  # BC1: headers first, nothing dispatched on failure
services/billing/src/otc_billing/presentation/credit_responder.py:76:    correlation = required_correlation(headers)
services/billing/src/otc_billing/presentation/credit_responder.py:87:    result = await dispatcher.ask(credit_wire.decode_list(body), scope)
services/billing/src/otc_billing/presentation/credit_responder.py:97:    correlation = required_correlation(headers)  # BI2: headers first, nothing dispatched on failure
services/billing/src/otc_billing/presentation/credit_responder.py:98:    result = await dispatcher.send(invoice_wire.decode_issue(body, correlation), scope)
services/billing/src/otc_billing/presentation/credit_responder.py:108:    result = await dispatcher.ask(invoice_wire.decode_list(body), scope)
services/billing/src/otc_billing/presentation/credit_headers.py:48:def required_correlation(headers: Mapping[str, str] | None) -> RpcCorrelation:
services/billing/src/otc_billing/presentation/invoice_wire.py:55:def decode_issue(body: bytes, correlation: RpcCorrelation) -> IssueInvoiceCommand:
services/billing/src/otc_billing/presentation/invoice_wire.py:95:def decode_list(body: bytes) -> ListInvoicesQuery:
services/billing/src/otc_billing/application/invoice_issue.py:6:  1. lock_for_order            -- THE FIRST LOCK (BI8): the credits row FOR UPDATE
services/billing/src/otc_billing/application/invoice_issue.py:7:  2. invoices.find_by_order_reference   -- the B7 authority read, NO lock, a new statement
services/billing/src/otc_billing/application/invoice_issue.py:10:  5. invoice_numbers.next_reference     -- THE LAST LOCK (BI8): the counter row FOR UPDATE
services/billing/src/otc_billing/application/invoice_issue.py:11:  6. Invoice.issue             -- raises exactly one InvoiceIssued
services/billing/src/otc_billing/application/invoice_issue.py:49:from otc_billing.domain.invoice_state import state_token
services/billing/src/otc_billing/application/invoice_issue.py:61:        status=state_token(snapshot.state),
services/billing/src/otc_billing/application/invoice_issue.py:85:    credit = await tx.credits.lock_for_order(  # 1. THE FIRST LOCK
services/billing/src/otc_billing/application/invoice_issue.py:90:    existing = await tx.invoices.find_by_order_reference(command.order_reference)  # 2. no lock
services/billing/src/otc_billing/application/invoice_issue.py:95:    credit.consume(command.order_reference, credit_context, new_id)  # 4. before the counter
services/billing/src/otc_billing/application/invoice_issue.py:96:    reference = await tx.invoice_numbers.next_reference()  # 5. THE LAST LOCK
services/billing/src/otc_billing/application/invoice_issue.py:97:    invoice = Invoice.issue(  # 6.
services/billing/src/otc_billing/application/invoice_issue.py:118:    await tx.invoices.save(invoice)  # 7.
services/billing/src/otc_billing/application/invoice_issue.py:119:    await tx.credits.save(credit)
services/billing/src/otc_billing/application/invoice_issue.py:124:    existing = await scope.invoice_reads.find_by_order_reference(command.order_reference)
services/billing/src/otc_billing/application/invoice_issue.py:127:    now = scope.clock.now()  # the ONE clock read
services/billing/src/otc_billing/application/invoice_issue.py:133:        new_id=scope.ids.new,
services/billing/src/otc_billing/domain/invoice.py:13:  one statement and nothing else assigns it after `issue` / `rehydrate`.
services/billing/src/otc_billing/domain/invoice.py:47:    state_token,
services/billing/src/otc_billing/domain/invoice.py:242:    def rehydrate(cls, snapshot: InvoiceSnapshot) -> Self:
services/billing/src/otc_billing/domain/invoice.py:247:        total. The state is already ONE value (`parse_invoice_state` refused a disagreeing pair).
services/billing/src/otc_billing/domain/invoice.py:343:        return state_token(self._state)
```

Classification of the 70 hits: **definitions, imports, docstrings and comments** (no mutation applies): `invoice_store.py:21, 33, 41`, `credit_store.py:30`, `ids.py:4`, `invoice_repository.py:3, 7, 48` (the def at 48 is a site: S17), `invoice_reads.py:6`, `invoice_mapper.py:5, 7, 29`, `invoice_state.py:13, 15, 59, 79`, `invoice_issue.py:6, 7, 10, 11, 49`, `invoice.py:13, 47, 242, 247`, `buyer_credit.py:8, 135`, `credit_responder.py:46`, `credit_headers.py:48`, `credit_wire.py:82`, `invoice_wire.py:55, 95`, `credit_repository.py:71`, `invoice_number_allocator.py:33`. **Call sites**, one mutation each, with the test that killed it (arms in the table, ids `J1-*`; the first failing test is the killer):

| Site | Mutation | Killed by |
|---|---|---|
| `invoice_issue.py:85` `lock_for_order` | another order reference (the company code) | `test_bi8_locks_the_credit_line_...` (it now asserts the arguments) |
| `:90` in-transaction `find_by_order_reference` | the retailer code | `test_bi8_...` (asserts the argument) |
| `:95` `consume` | the company code | `test_the_clock_is_read_exactly_once_...` (a real `BuyerCredit`) |
| `:96` `next_reference` | not called | `test_bi8_...` (the log) |
| `:97` `Invoice.issue` | retailer from company | **survived the unit file at first**; `test_bi8_...` now asserts the aggregate's party codes, currency, lines and totals (a missing test, added, then armed); the host's `test_r45_...` also kills it |
| `:118` `invoices.save`, `:119` `credits.save` | not called | `test_the_clock_is_read_exactly_once_...`; F3c |
| `:124` fast-path `find_by_order_reference` | another reference | `test_bi8_...` (`rig.reads.finds`) |
| `:127` `scope.clock.now` | the wall clock | `test_the_clock_is_read_exactly_once_...` |
| `:133` `scope.ids.new` | `UniqueId.new` | `test_bi34_the_issue_hands_the_scope_id_port_to_both_aggregates` |
| `handlers.py:63` `scope.clock.now` (list) | the wall clock | **no test killed it before**; `unit/test_invoice_list_handler.py` added, then armed |
| `invoice_mapper.py:72, 78` `parse_invoice_state` | no `paid_at` | `test_a_paid_row_maps_to_the_paid_state_...` |
| `:90`, `:107` `state_token` | constant | `test_a_paid_row_maps_...`; D4b |
| `invoice_reads.py:35`, `invoice_repository.py:48` | fixed reference | `test_find_by_order_reference_takes_no_lock`, `test_a_reload_returns_the_lines_in_canonical_order_...` |
| `invoice_reads.py:79`, `credit_reads.py:48`, `stock_reads.py:81` `.offset(` | no clamp | G4a, G6a, G6b |
| `credit_responder.py:97` `required_correlation` | after `send` | E5a |
| `:98` `decode_issue` | fresh ids | `test_bi2_billing_invoice_issue_dispatches_a_command_carrying_the_header_ids` |
| `:108` `decode_list` | ignores the body | `test_bi15_filters_pages_orders_...` |
| `invoice.py:343` `state_token(self._state)` | constant | `test_r46_...` |
| `credit_hold.py:46, 87, 100, 116, 117`, `credit_release.py:28, 49, 64, 65` (feature 19's sites) | argument / delete / wall clock / `UniqueId.new` | the unit hold and release service tests; `credit_release.py:28`'s order reference is **not** seen by the unit fake and is killed by `I/test_credit_release.py::test_bc25_...` (recorded as `J1-F19-release-lock`) |
| `Invoice.rehydrate` | n/a | **no production call site** (feature 22's seam); unit-tested and armed in B7 |

## 6. Instruments this feature extended, and their new premises

- **`unit/test_credit_subjects.py`**: premises: the population is `ROUTES` (set equality with the five channel addresses read from `asyncapi.yaml`), not a list in the test; the count is five. Armed: E2a (substitute `billing.invoice.list`), E2b (delete the route entry), E2c (an undeclared sixth route).
- **`tests/architecture/test_billing_rpc_error_retryability.py`** (the instrument changed from two named modules to a walk): (a) the walk reaches a module nobody named: probe `domain/_arm_probe.py` raises the count (E6p-a); (b) a module that cannot be imported fails the walk (E6p-b, `ImportError` propagates); (c) every walked class has an input (E6p-c: the count is raised to match and the set equality still fails). The expected count is a literal re-derived from the classes on disk: 24 (9 + 3 + 10 + 2).
- **`tests/architecture/test_write_path_population.py`**: `EXPECTED["billing"]` gains the allocator's three `text` + three `execute` and the invoice repository's two `add`s, counts read from `scan_service("billing")`; armed D8a, D8b.
- **`tests/architecture/test_registration_behaviour.py`**: `TABLES["billing"]` gains `IssueInvoiceCommand` and `ListInvoicesQuery`; premise: Billing's root registers each message by a direct statement; armed H2 (helper loop draining two registrations: `WIRE: 2 registrations share one statement`) and H2b (a message dropped from the literal).
- **The conftest `Decode`**: `invoice_issue` and `invoice_list` assert the discriminating field first (G5, G4a, I1a - I1c all go red on `BC32: expected ...`).
- **`unit/test_credit_transactions.py`**: premises: the three adapters share one session by identity; both repositories' events are cleared only after the commit; armed D2a, D2b.

## 7. Arming table

All 158 rows: result **RED**, restore by `cp` from `.arm/bc21/backups/<id>/` (sha256 recorded below, 12 hex digits of 64), `cmp` identical, `__pycache__` under `services/*/src` and `.mypy_cache` cleared, re-run green. Verbatim blocks: `.arm/bc21/arms.md`.

Three extra records the table cannot hold:

- **B2a under mypy (every `assert_never` site in `src` when a third member is added to the alias):**

```text
61df05301495e9b6d913077e7a0990844b91ca164d572ddec9046781edd16b48  services/billing/src/otc_billing/domain/invoice_state.py
services/billing/src/otc_billing/domain/invoice_state.py:75: error: Argument 1 to "assert_never" has incompatible type "Voided"; expected "Never"  [arg-type]
services/billing/src/otc_billing/domain/invoice_state.py:85: error: Argument 1 to "assert_never" has incompatible type "Voided"; expected "Never"  [arg-type]
services/billing/src/otc_billing/domain/invoice.py:364: error: Argument 1 to "assert_never" has incompatible type "Voided"; expected "Never"  [arg-type]
Found 3 errors in 2 files (checked 71 source files)
```

- **F11 (delete the `InvoiceIssued` raise, whole Billing suites, no `-x`):** 12 named tests failed: `test_f5_publishes_invoice_issued_...`, `test_r45_issues_one_invoice_through_the_real_host_...`, `test_bi6_emits_no_fact_...`, `test_bi35_a_zero_hold_...`, `test_bi8_two_concurrent_issues_...`, `test_bi7_commits_invoice_lines_...`, `test_r45_creates_exactly_one_issued_invoice_...` (B5), `test_bi35_a_zero_total_invoice_is_issued`, `test_bi13_stamps_invoice_issued_...`, `test_bi34_every_invoice_line_and_event_id_...`, `test_the_clock_is_read_exactly_once_...`, `test_bi34_the_issue_hands_the_scope_id_port_...` (raw list: `.arm/bc21/F11.out`). Both B5 and F4 are among them.
- **C6 (Orders, arm-and-restore):** `git diff --stat services/orders` before and after both arms is identical (feature 20's uncommitted settings edits are in it), and `command_payloads.py` was restored from its backup (sha256 `a3b14623d66620bd8f65e0fdcc29c876b55967d6a14e63bdcc2c41b06e7faee6`) with `cmp`:

```text
 .../orders/src/otc_orders/infrastructure/settings.py |  6 +++++-
 .../orders/tests/unit/test_orders_settings_env.py    | 20 ++++++++++++++++++++
 2 files changed, 25 insertions(+), 1 deletion(-)
```

| Arm | Mutation | Test run | Verbatim failure (first assertion line) | sha256 of backup (12) | cmp / re-run |
|---|---|---|---|---|---|
| B2a | a third member is added to the InvoiceState alias | `unit/domain/test_invoice_state.py::test_bi23_the_state_is_exactly_issued_or_paid_and_paid_cannot_exist_without_an_aware_instant` | AssertionError: BI23: the InvoiceState alias must name exactly (Issued, Paid) | `61df05301495` | identical / green |
| B2a-mypy | a third member is added to the InvoiceState alias (mypy-fixture half) | `unit/domain/test_invoice_state.py::test_bi23_mypy_rejects_a_match_that_omits_a_case` | AssertionError: BI23 control: a complete match was rejected by mypy --strict: | `61df05301495` | identical / green |
| B2c | the mypy fixture's match no longer omits a case (the checker would accept it) | `unit/domain/test_invoice_state.py::test_bi23_mypy_rejects_a_match_that_omits_a_case` | AssertionError: BI23: mypy --strict accepted a match over InvoiceState that omits `Paid` | `9f5b939ef59c` | identical / green |
| B2d | Issued is no longer final (its __init_subclass__ refusal is deleted) | `unit/domain/test_invoice_state.py::test_bi23_the_state_is_exactly_issued_or_paid_and_paid_cannot_exist_without_an_aware_instant` | Failed: DID NOT RAISE TypeError | `61df05301495` | identical / green |
| B2b | Paid.__post_init__ no longer checks the instant | `unit/domain/test_invoice_state.py::test_bi23_the_state_is_exactly_issued_or_paid_and_paid_cannot_exist_without_an_aware_instant` | Failed: DID NOT RAISE InvalidInvoiceStateError | `61df05301495` | identical / green |
| B3a | the token parse is strip().lower() | `unit/domain/test_invoice_state.py::test_bi27_the_status_token_parse_is_exact_and_closed_and_only_lower_case_tokens_are_written` | AssertionError: BI27: the unknown token 'Paid' (paid_at None) was not refused as unknown: InvalidInvoiceSnapshotError('The stored invoice cannot be restored: the stored invoice is paid but its paid_a… | `61df05301495` | identical / green |
| B3b | (paid, None) returns Issued() | `unit/domain/test_invoice_state.py::test_bi27_the_status_token_parse_is_exact_and_closed_and_only_lower_case_tokens_are_written` | Failed: DID NOT RAISE InvalidInvoiceSnapshotError | `61df05301495` | identical / green |
| B5a | total = amount (the discount is ignored) | `unit/domain/test_invoice.py::test_r45_creates_exactly_one_issued_invoice_mirroring_the_despatched_lines_with_a_non_negative_total_and_returns_the_exi…` | AssertionError: assert Money(amount=...urrency='EUR') == Money(amount=...urrency='EUR') | `c3ca9162a617` | identical / green |
| B5b | the empty-lines check is deleted | `unit/domain/test_invoice.py::test_bi11_derives_amount_and_total_from_the_lines_and_refuses_empty_lines_a_foreign_currency_and_a_negative_total` | AssertionError: BI11: expected invoice.empty_lines (EmptyInvoiceLinesError), got NegativeInvoiceTotalError('A discount of 3.50 EUR exceeds the invoice amount of 0.00 EUR: the total would be negative.… | `c3ca9162a617` | identical / green |
| B5c | the negative-total check is deleted | `unit/domain/test_invoice.py::test_bi11_derives_amount_and_total_from_the_lines_and_refuses_empty_lines_a_foreign_currency_and_a_negative_total` | AssertionError: BI11: expected invoice.negative_total (NegativeInvoiceTotalError), got AssertionError('the aggregate began constructing an invoice that should have been refused (id minted)') | `c3ca9162a617` | identical / green |
| B5d | the int64 range checks are deleted | `unit/domain/test_invoice.py::test_bi25_an_out_of_range_line_total_raises_invoice_total_overflow_with_its_code` | AssertionError: BI25: expected invoice.total_overflow, got InvalidMoneyAmountError('18446744073709551616 is not a valid money amount: it must be an int count of minor units within the signed 64-bit r… | `c3ca9162a617` | identical / green |
| B5e | a total_amount setter is added | `unit/domain/test_invoice.py::test_the_totals_state_and_lines_of_an_issued_invoice_have_no_setter` | Failed: DID NOT RAISE AttributeError | `c3ca9162a617` | identical / green |
| B6a | site 1: the invoice id is UniqueId.new() | `unit/domain/test_invoice_ids.py::test_bi34_every_invoice_line_and_event_id_is_the_one_the_id_source_supplied` | AssertionError: site 1: the invoice id is not the supplied one | `c3ca9162a617` | identical / green |
| B6b | site 2: the line id is UniqueId.new() | `unit/domain/test_invoice_ids.py::test_bi34_every_invoice_line_and_event_id_is_the_one_the_id_source_supplied` | AssertionError: site 2: the first line id is not the supplied one | `c3ca9162a617` | identical / green |
| B6c | site 3: the InvoiceIssued event id is UniqueId.new() | `unit/domain/test_invoice_ids.py::test_bi34_every_invoice_line_and_event_id_is_the_one_the_id_source_supplied` | AssertionError: site 3: the InvoiceIssued event id is not the supplied one | `c3ca9162a617` | identical / green |
| B6d | site 4: the PaymentReceived event id is UniqueId.new() | `unit/domain/test_invoice_ids.py::test_bi34_every_invoice_line_and_event_id_is_the_one_the_id_source_supplied` | AssertionError: site 4: the PaymentReceived event id is not the supplied one | `c3ca9162a617` | identical / green |
| B7a | mark_paid on a paid invoice overwrites instead of raising | `unit/domain/test_invoice.py::test_r46_allows_only_the_transition_from_issued_to_paid_sets_paid_at_exactly_then_and_raises_on_every_other_transition_c…` | Failed: DID NOT RAISE InvoiceAlreadyPaidError | `c3ca9162a617` | identical / green |
| B7b | rehydrate skips the totals check | `unit/domain/test_invoice.py::test_bi10_status_and_paid_at_are_one_value_and_a_disagreeing_snapshot_is_refused` | Failed: DID NOT RAISE InvalidInvoiceSnapshotError | `c3ca9162a617` | identical / green |
| B8a | aggregate_id and correlation_id are swapped | `unit/domain/test_invoice_facts.py::test_bi13_stamps_invoice_issued_from_the_supplied_ids_clock_and_headers` | AssertionError: aggregate_id must be the invoice's own id | `c3ca9162a617` | identical / green |
| B8b | the fact's lines are built in canonical order | `unit/domain/test_invoice_facts.py::test_bi13_stamps_invoice_issued_from_the_supplied_ids_clock_and_headers` | AssertionError: assert (InvoiceFactL...t_price=1999)) == (InvoiceFactL...t_price=1234)) | `c3ca9162a617` | identical / green |
| B8c | retailer_code is taken from company_code in the fact | `unit/domain/test_invoice_facts.py::test_bi13_stamps_invoice_issued_from_the_supplied_ids_clock_and_headers` | AssertionError: assert 'SUPPLY-CO' == 'RETAIL-77' | `c3ca9162a617` | identical / green |
| B9a | mark_paid raises no PaymentReceived (the raise is deleted) | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: BI14: expected exactly one event, got 0 | `c3ca9162a617` | identical / green |
| B9b | value_date + 1 day | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: assert datetime.datetime(2026, 10, 11, 10, 22, 30, 123000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 10, 10, 22, 30, 123000, tzinfo=datetime.timezone.utc) | `c3ca9162a617` | identical / green |
| B9c | source is the constant OPERATOR | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: assert <PaymentSource.OPERATOR: 'operator'> is <PaymentSource.ROBOT: 'robot'> | `c3ca9162a617` | identical / green |
| B9d | payment_reference is corrupted | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: assert 'PAY-77-ABCx' == 'PAY-77-ABC' | `c3ca9162a617` | identical / green |
| B9e | amount = amount.amount + 1 (a different invoice field) | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: assert 8466 == 8115 | `c3ca9162a617` | identical / green |
| B9f | mark_paid returns a fresh copy, not the raised object | `unit/domain/test_invoice.py::test_bi14_mark_paid_moves_issued_to_paid_with_paid_at_in_one_step_and_one_fact_carrying_every_payment_field` | AssertionError: mark_paid must RETURN the object it raised (#8 id 57) | `c3ca9162a617` | identical / green |
| B9g | the amount check is deleted | `unit/domain/test_invoice.py::test_bi14_mark_paid_refuses_a_paid_invoice_a_wrong_amount_and_a_wrong_currency_changing_and_emitting_nothing` | Failed: DID NOT RAISE InvoicePaymentAmountMismatchError | `c3ca9162a617` | identical / green |
| B10 | total <= 0 is refused | `unit/domain/test_invoice.py::test_bi35_a_zero_total_invoice_is_issued` | otc_billing.domain.invoice_errors.NegativeInvoiceTotalError: A discount of 59.97 EUR exceeds the invoice amount of 59.97 EUR: the total would be negative. | `c3ca9162a617` | identical / green |
| C2a | the fast path is deleted | `unit/test_invoice_issue_service.py::test_a_hit_on_the_fast_path_returns_created_false_and_opens_no_transaction` | AssertionError: BI9: a fast-path hit opened a transaction | `89f5bf98d8a8` | identical / green |
| C2b | consume is moved after next_reference | `unit/test_invoice_issue_service.py::test_bi5_no_active_hold_raises_before_the_allocator_and_saves_nothing` | AssertionError: BI5: the counter was touched for an order with no active hold | `89f5bf98d8a8` | identical / green |
| C2c | credits.save is called before NoActiveHoldError can raise | `unit/test_invoice_issue_service.py::test_bi5_no_active_hold_raises_before_the_allocator_and_saves_nothing` | AssertionError: BI5: the credit repository saved | `89f5bf98d8a8` | identical / green |
| C2d | an in-transaction hit allocates anyway | `unit/test_invoice_issue_service.py::test_an_in_transaction_hit_returns_created_false_and_saves_nothing` | AssertionError: BI9: a repeat allocated a number | `89f5bf98d8a8` | identical / green |
| C3 | the clock is read again for the credit context | `unit/test_invoice_issue_service.py::test_the_clock_is_read_exactly_once_and_the_invoice_date_the_fact_and_the_entry_share_it` | AssertionError: BI13: the clock was read 2 times | `89f5bf98d8a8` | identical / green |
| C4a | next_reference moves above the re-read | `unit/test_invoice_issue_service.py::test_bi8_locks_the_credit_line_then_re_reads_the_invoice_then_allocates_the_number` | AssertionError: BI8: the issue path's calls are not lock, re-read, allocate, save, save | `89f5bf98d8a8` | identical / green |
| C4b | the first two calls are swapped (re-read before the lock) | `unit/test_invoice_issue_service.py::test_bi8_locks_the_credit_line_then_re_reads_the_invoice_then_allocates_the_number` | AssertionError: BI8: the issue path's calls are not lock, re-read, allocate, save, save | `89f5bf98d8a8` | identical / green |
| C5a | M1a: UniqueId.new is passed to Invoice.issue | `unit/test_invoice_issue_service.py::test_bi34_the_issue_hands_the_scope_id_port_to_both_aggregates` | AssertionError: the invoice's id is not from the scope's id port | `89f5bf98d8a8` | identical / green |
| C5b | M1b: UniqueId.new is passed to credit.consume | `unit/test_invoice_issue_service.py::test_bi34_the_issue_hands_the_scope_id_port_to_both_aggregates` | AssertionError: the consume entry's id is not from the scope's id port | `89f5bf98d8a8` | identical / green |
| C5c | the result is returned from inside work before the save | `unit/test_invoice_issue_service.py::test_the_result_is_returned_only_after_run_returns_with_both_saves_done` | AssertionError: both saves must have happened before the commit | `89f5bf98d8a8` | identical / green |
| C5d | a failing run is swallowed and the in-work result is returned anyway | `unit/test_invoice_issue_service.py::test_a_rollback_after_work_yields_no_result` | Failed: DID NOT RAISE CommitFailed | `89f5bf98d8a8` | identical / green |
| C6a | Orders' invoice.issue discount is replaced by 0 (BI21) | `services/orders/tests/unit/saga/test_command_payloads.py::test_invoice_issue_lines_carry_units_and_unit_price_and_the_initial_discount` | AssertionError: assert 0 == 350 | `a3b14623d666` | identical / green |
| C6b | Orders' credit.hold amount is the initial amount, not the total (BI21) | `services/orders/tests/unit/saga/test_command_payloads.py::test_credit_hold_amount_is_the_total_not_the_initial_amount_or_the_discount` | AssertionError: assert (8465, 'EUR') == (8115, 'EUR') | `a3b14623d666` | identical / green |
| D2a | the invoice repository's events are cleared before the commit | `unit/test_credit_transactions.py::test_a_successful_commit_clears_both_aggregates_events_after_it unit/test_credit_transactions.py::test_a_commit_tha…` | AssertionError: L34: the invoice repository's events were cleared before the commit returned | `7f23068c9ce1` | identical / green |
| D2b | the invoice repository is built on a second session | `unit/test_credit_transactions.py::test_the_three_adapters_work_receives_share_one_session` | AssertionError: L33: the credit repository, the invoice repository and the allocator are on two sessions | `7f23068c9ce1` | identical / green |
| D4a | price is written from line_total | `unit/test_invoice_mapper.py::test_new_rows_mirror_the_aggregate_with_the_unit_price_and_updated_at_equal_to_created_at` | AssertionError: price must be the UNIT price (not the line total 5997 / 2468) | `8c394267bd20` | identical / green |
| D4b | status is written as the constant 'issued' | `unit/test_invoice_mapper.py::test_status_and_paid_at_are_written_from_the_one_state_of_a_paid_invoice` | AssertionError: a paid invoice must write the lower-case token 'paid' | `8c394267bd20` | identical / green |
| D4c | updated_at is not created_at | `unit/test_invoice_mapper.py::test_new_rows_mirror_the_aggregate_with_the_unit_price_and_updated_at_equal_to_created_at` | AssertionError: a new row's updated_at must equal created_at | `8c394267bd20` | identical / green |
| D4d | the reload's Python sort is removed | `unit/test_invoice_mapper.py::test_a_row_maps_to_a_snapshot_field_by_field_with_lines_in_canonical_order` | AssertionError: L15: the reload is not in canonical (product_code, id) order | `8c394267bd20` | identical / green |
| D3a | the mapper drops tzinfo from invoice_date | `integration/test_invoice_repository.py::test_bi24_invoice_date_and_paid_at_read_back_unchanged_through_the_mapper_under_a_non_utc_session_and_null_st…` | AssertionError: BI24: wrote 2026-10-09 10:15:30.123000+00:00, read 2026-10-09 10:15:30.123000 | `8c394267bd20` | identical / green |
| D3a2 | the mapper drops tzinfo from paid_at | `integration/test_invoice_repository.py::test_bi24_invoice_date_and_paid_at_read_back_unchanged_through_the_mapper_under_a_non_utc_session_and_null_st…` | AssertionError: BI24: the paid row did not load: InvalidInvoiceSnapshotError('The stored invoice cannot be restored: invoice INV-000401 is paid but its paid_at is datetime.datetime(2026, 10, 11, 17, … | `8c394267bd20` | identical / green |
| D3b | the mapper maps a NULL paid_at to invoice_date | `integration/test_invoice_repository.py::test_bi24_invoice_date_and_paid_at_read_back_unchanged_through_the_mapper_under_a_non_utc_session_and_null_st…` | AssertionError: BI24: a NULL paid_at did not stay NULL, the read raised InvalidInvoiceSnapshotError('The stored invoice cannot be restored: invoice INV-000402 is issued but carries paid_at.') | `8c394267bd20` | identical / green |
| D3c | the Python sort is removed from the mapper (integration) | `integration/test_invoice_repository.py::test_a_reload_returns_the_lines_in_canonical_order_for_an_invoice_saved_in_another_order` | AssertionError: L15: the reload is not in canonical (product_code, id) order | `8c394267bd20` | identical / green |
| D3d | the mapper returns Issued() for every row (a disagreeing row loads) | `integration/test_invoice_repository.py::test_bi10_a_stored_row_whose_status_and_paid_at_disagree_is_refused_by_the_mapper` | AssertionError: BI10: a `paid` row with a NULL paid_at became InvoiceSnapshot(id=UniqueId(value=UUID('bffd516a-ff9c-4782-a71b-24902a6e6bb0')), invoice_reference=InvoiceReference(value='INV-000301'), … | `8c394267bd20` | identical / green |
| F3a | the invoice repository is built on a second session | `integration/test_invoice_repository.py::test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback` | AssertionError: expected exactly one new invoices row | `7f23068c9ce1` | identical / green |
| F3b | the invoice header is written by a separate session that commits at once | `integration/test_invoice_repository.py::test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback` | AssertionError: BI7: a rolled-back issue left an invoice, a line, a consume row or an outbox row | `b5780e031931` | identical / green |
| F3c | credits.save is deleted from the issue work (no consume row) | `integration/test_invoice_repository.py::test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback` | AssertionError: expected exactly one consume row | `89f5bf98d8a8` | identical / green |
| D5a | the adapter reads the wall clock instead of the supplied now | `integration/test_invoice_reads.py::test_bi15_the_cutoff_is_the_supplied_now_and_nothing_is_written` | AssertionError: assert (0, []) == (1, ['502']) | `c11e18561107` | identical / green |
| D5b | the cutoff is exclusive (< instead of <=) | `integration/test_invoice_reads.py::test_bi15_the_cutoff_is_the_supplied_now_and_nothing_is_written` | AssertionError: assert (0, []) == (1, ['502']) | `c11e18561107` | identical / green |
| D5c | with_for_update() is added to the fast-path read | `integration/test_invoice_reads.py::test_find_by_order_reference_takes_no_lock` | AssertionError: L9: the fast-path read blocked on a row another transaction holds FOR UPDATE: it must take no lock and wait for none | `b5780e031931` | identical / green |
| D6a | the allocator skips the seed statement | `integration/test_invoice_number_allocator.py::test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique` | sqlalchemy.exc.NoResultFound: No row was found when one was required | `db8aba447078` | identical / green |
| D6b | the allocator opens its own session (the allocation is not the transaction's) | `integration/test_invoice_number_allocator.py::test_the_allocation_belongs_to_the_credit_transactions_transaction` | AssertionError: assert 'INV-000002' == 'INV-000001' | `db8aba447078` | identical / green |
| D6c | from_sequence(allocated + 1) | `integration/test_invoice_number_allocator.py::test_seeding_over_a_non_empty_invoices_table_continues_above_its_maximum` | AssertionError: assert 'INV-000044' == 'INV-000043' | `db8aba447078` | identical / green |
| F1a | the pair refusal (equal or contained figures) of the issue-fixture builder is deleted | `unit/test_invoice_fixture_guard.py::test_the_issue_fixture_refuses_coinciding_or_zero_totals_unless_told` | Failed: BI38: the fixture builder accepted a zero discount | `e8911ca3ed26` | identical / green |
| F1b | the flag-with-a-non-zero-figure refusals are deleted | `unit/test_invoice_fixture_guard.py::test_the_issue_fixture_refuses_coinciding_or_zero_totals_unless_told` | Failed: DID NOT RAISE AssertionError | `e8911ca3ed26` | identical / green |
| F1c | the zero-gross refusal is deleted | `unit/test_invoice_fixture_guard.py::test_the_issue_fixture_refuses_coinciding_or_zero_totals_unless_told` | Failed: BI38: the fixture builder accepted lines that sum to zero | `e8911ca3ed26` | identical / green |
| F2a | a NoActiveHoldError is answered created: true with no invoice | `integration/test_invoice_issue.py::test_bi5_replies_precondition_failed_for_no_active_hold_and_leaves_the_orders_ledger_rows_unchanged` | AssertionError: BC32: expected an RpcError (a `code`), got {'orderReference': 'ORD-000101', 'invoiceId': '69516047-9315-4ba3-a0f6-c9f3f5bea58d', 'invoiceReference': 'INV-000009', 'invoiceDate': '2026… | `89f5bf98d8a8` | identical / green |
| F2b | an outbox row is written on the currency refusal | `integration/test_invoice_issue.py::test_bi6_emits_no_fact_of_any_type_on_every_refusal_path` | AssertionError: a refusal path emitted a fact | `89f5bf98d8a8` | identical / green |
| F4a | credits.save(credit) is deleted from the issue work | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | AssertionError: expected exactly one consume row, got 0 | `89f5bf98d8a8` | identical / green |
| F6a | the fast path AND the in-transaction re-read are dropped | `integration/test_invoice_issue.py::test_bi9_a_repeat_returns_the_existing_invoice_with_created_false_and_writes_nothing_whether_issued_or_paid` | AssertionError: BC32: expected an invoice-issue reply (`created`), got {'code': 'PRECONDITION_FAILED', 'message': 'Order ORD-000101 has no active hold: it was never held, or its hold was already cons… | `89f5bf98d8a8` | identical / green |
| F6b | the repeat replies the current request's id as invoiceId | `integration/test_invoice_issue.py::test_bi9_a_repeat_returns_the_existing_invoice_with_created_false_and_writes_nothing_whether_issued_or_paid` | AssertionError: BI9: the repeat did not carry the invoiceId | `89f5bf98d8a8` | identical / green |
| F7a | decode_issue passes discount=0 | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | AssertionError: assert ('EUR', 8465) == ('EUR', 8115) | `4ea88c47cbfb` | identical / green |
| F7b | Invoice.issue sets total = amount | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | AssertionError: assert ('EUR', 8465) == ('EUR', 8115) | `c3ca9162a617` | identical / green |
| F7c | invoice_mapper writes discount=0 to the column | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | assert (8465, 0, 8115) == (8465, 350, 8115) | `8c394267bd20` | identical / green |
| F7d | payloads writes discount=0 into the fact | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | AssertionError: a field of the invoice.issued.v1 payload is not the supplied / computed value | `2ee64054ccd5` | identical / green |
| F8 | invoice_issue refuses an active hold of amount 0 | `integration/test_invoice_issue.py::test_bi35_a_zero_hold_is_consumed_and_a_zero_total_invoice_issued` | AssertionError: BC32: expected an invoice-issue reply (`created`), got {'code': 'PRECONDITION_FAILED', 'message': 'Order ORD-000101 has no active hold: it was never held, or its hold was already cons… | `89f5bf98d8a8` | identical / green |
| F5 | the relay keys the record by aggregate_id instead of correlation_id (outbox copy wire.py, armed and restored) | `integration/test_billing_outbox_relay.py::test_f5_publishes_invoice_issued_to_the_billing_topic_keyed_by_the_order_id_read_from_the_broker` | AssertionError: F5: keyed by b'3f2f6abe-2998-4ed4-8abd-16df7553650b', not by the order id (correlationId) 3a603928-7933-4f76-abd8-9e9eb1ff44fb | `bc12b7db4a7f` | identical / green |
| G1a | the status filter is dropped | `integration/test_invoice_list.py::test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now` | AssertionError: assert 5 == 2 | `c11e18561107` | identical / green |
| G1b | the list is ordered ascending | `integration/test_invoice_list.py::test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now` | AssertionError: newest first | `c11e18561107` | identical / green |
| G2 | every view's paid_at is mapped to None in list_reply | `integration/test_invoice_list.py::test_bi32_an_issued_view_writes_paid_at_null_and_a_paid_view_the_instant_in_the_raw_reply` | AssertionError: BI32: expected exactly one `"paidAt":null` | `4ea88c47cbfb` | identical / green |
| G3 | the issue reply is wrapped as {"response": ...} | `integration/test_invoice_wire.py::test_bi16_both_invoice_subjects_answer_bare_json_and_a_refusal_is_a_bare_rpc_error` | AssertionError: BI16: not an issue reply: {'response': {'orderReference': 'ORD-000101', 'invoiceId': '77403acb-95f8-4930-9b77-dfb00d664ae1', 'invoiceReference': 'INV-000001', 'invoiceDate': '2026-10-… | `7a7b550621ee` | identical / green |
| G4a | the offset clamp is removed from invoice_reads | `integration/test_invoice_list.py::test_bi37_a_page_past_int64_and_an_age_before_year_one_answer_an_empty_page_with_the_true_total` | AssertionError: BC32: expected an invoice list reply (a `page`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'occurredAt': '2026-10-09T18:32:27.415Z'} | `c11e18561107` | identical / green |
| G4b | the OverflowError handling is removed from invoice_reads | `integration/test_invoice_list.py::test_bi37_a_page_past_int64_and_an_age_before_year_one_answer_an_empty_page_with_the_true_total` | AssertionError: BC32: expected an invoice list reply (a `page`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'occurredAt': '2026-10-09T18:32:49.099Z'} | `c11e18561107` | identical / green |
| G6a | the offset clamp is removed from credit_reads | `integration/test_credit_list.py::test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total` | AssertionError: BC32: expected a list reply (a `page`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'occurredAt': '2026-10-09T18:33:10.597Z'} | `2192cdbca066` | identical / green |
| G6b | the offset clamp is removed from fulfillment stock_reads | `services/fulfillment/tests/integration/test_stock_list.py::test_bi37_a_page_past_int64_answers_an_empty_page_with_the_true_total` | AssertionError: BI37: expected an empty page, got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'occurredAt': '2026-10-09T18:33:31.695Z'} | `3daad5bbd647` | identical / green |
| E3a | the discount <= sum check is dropped | `unit/test_invoice_requests.py::test_bi2_refuses_a_malformed_issue_request_with_validation_failed_without_calling_the_dispatcher` | AssertionError: BI2: discount one minor unit above the sum: the request was dispatched | `4ea88c47cbfb` | identical / green |
| E3b | the discount >= 0 check is dropped | `unit/test_invoice_requests.py::test_bi2_refuses_a_malformed_issue_request_with_validation_failed_without_calling_the_dispatcher` | AssertionError: BI2: a negative discount: the request was dispatched | `4ea88c47cbfb` | identical / green |
| E3c | the unitPrice >= 0 check is dropped | `unit/test_invoice_requests.py::test_bi2_refuses_a_malformed_issue_request_with_validation_failed_without_calling_the_dispatcher` | AssertionError: BI2: a negative unitPrice: the request was dispatched | `4ea88c47cbfb` | identical / green |
| E3d | the sum <= int64 bound is dropped | `unit/test_invoice_requests.py::test_bi33_an_order_reference_over_twenty_characters_units_above_int32_and_a_line_sum_above_int64_are_validation_failed` | AssertionError: a line sum above int64: dispatched | `4ea88c47cbfb` | identical / green |
| E3e | the units <= int32 bound is dropped | `unit/test_invoice_requests.py::test_bi33_an_order_reference_over_twenty_characters_units_above_int32_and_a_line_sum_above_int64_are_validation_failed` | AssertionError: units above int32: dispatched | `4ea88c47cbfb` | identical / green |
| E3f | the orderReference length check is dropped | `unit/test_invoice_requests.py::test_bi33_an_order_reference_over_twenty_characters_units_above_int32_and_a_line_sum_above_int64_are_validation_failed` | AssertionError: an orderReference of 21 characters: dispatched | `4ea88c47cbfb` | identical / green |
| E4a | the issue reply is built without invoice_id | `unit/test_invoice_wire.py::test_the_issue_reply_carries_invoice_id_and_the_exact_key_set_for_created_true_and_false` | AssertionError: created=True: the key set differs | `4ea88c47cbfb` | identical / green |
| E4b | an issued view's paid_at is mapped to its invoice_date | `unit/test_invoice_wire.py::test_bi32_an_issued_view_writes_paid_at_null_and_a_paid_view_writes_the_instant` | AssertionError: assert '2026-10-09T08:15:30.123Z' is None | `4ea88c47cbfb` | identical / green |
| E4c | discount and total_amount are transposed in the view | `unit/test_invoice_wire.py::test_amount_discount_and_total_amount_land_on_their_own_keys` | assert (8465, 8115, 350) == (8465, 350, 8115) | `4ea88c47cbfb` | identical / green |
| E5a | required_correlation is called after dispatcher.send in _invoice_issue | `unit/test_credit_responder.py::test_bi2_billing_invoice_issue_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_i…` | AssertionError: billing.invoice.issue: correlation malformed was dispatched | `7a7b550621ee` | identical / green |
| E5b | a fresh id is substituted for a malformed x-request-id | `unit/test_credit_responder.py::test_bi2_billing_invoice_issue_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_i…` | AssertionError: billing.invoice.issue: request malformed | `ce757af97b98` | identical / green |
| E6a | NoActiveHoldError is mapped to UNAVAILABLE (BI26 reads Orders' terminal set) | `arch/test_billing_rpc_error_retryability.py::test_bi26_no_active_hold_is_answered_with_a_code_in_the_saga_adapters_terminal_set` | AssertionError: BI26: a NoActiveHoldError is answered UNAVAILABLE, which Orders' saga adapter would retry instead of stopping the row | `1304606007f1` | identical / green |
| E6a2 | NoActiveHoldError is mapped to UNAVAILABLE (the unit row) | `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details` | AssertionError: no active hold | `1304606007f1` | identical / green |
| E6b | an explicit arm maps InvoiceTotalOverflowError to INTERNAL_ERROR | `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details` | AssertionError: invoice total overflow | `1304606007f1` | identical / green |
| E6c | details are dropped from InvoiceCurrencyMismatchError | `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details` | AssertionError: invoice currency mismatch | `1304606007f1` | identical / green |
| E6d | one message renders a raw minor-unit amount | `unit/test_credit_rpc_errors.py::test_bi36_invoice_error_messages_render_amounts_with_the_money_text_formatter` | AssertionError: EUR: A discount of 18490 exceeds the invoice amount of 92.45 EUR: the total would be negative. | `1d5eda52c16d` | identical / green |
| E6p-a | premise (a): a probe DomainError in a NEW module raises the walked count | `arch/test_billing_rpc_error_retryability.py::test_bc27_no_input_produces_conflict` | AssertionError: a DomainError subclass was added or removed: ['CreditCurrencyMismatchError', 'CreditLedgerOverflowError', 'CreditLimitExceededError', 'CreditLineNotFoundError', 'CreditRefusalMismatch… | `a9d2d379bcc7` | identical / green |
| E6p-b | premise (b): a module that fails to import FAILS the walk | `arch/test_billing_rpc_error_retryability.py::test_bc27_no_input_produces_conflict` | ImportError: arming probe: this module cannot be imported | `a9d2d379bcc7` | identical / green |
| E6p-c | premise (c): a walked class with no input fails the set equality (the count is raised to match) | `arch/test_billing_rpc_error_retryability.py::test_bc27_no_input_produces_conflict` | AssertionError: a walked class has no input here: ['ProbeArmError'] | `a9d2d379bcc7` | identical / green |
| F9a | lines[0].unit_price + 1 | `unit/test_outbox_payloads.py::test_invoice_issued_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the invoice.issued.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9b | retailer_code is read from company_code in the invoice.issued.v1 payload | `unit/test_outbox_payloads.py::test_invoice_issued_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the invoice.issued.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9c | aggregate_id is read from correlation_id for invoice events only (in _envelope) | `unit/test_outbox_payloads.py::test_invoice_issued_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: assert '00000000-000...-000000000003' == '00000000-000...-000000000002' | `2ee64054ccd5` | identical / green |
| F9d | payment_reference is a constant | `unit/test_outbox_payloads.py::test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the payment.received.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9e | value_date is read from occurred_at | `unit/test_outbox_payloads.py::test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the payment.received.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9f | source is a constant | `unit/test_outbox_payloads.py::test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the payment.received.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9g | the payment amount is read from the wrong field (currency swapped with amount order) | `unit/test_outbox_payloads.py::test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: a field of the payment.received.v1 payload is not the supplied value | `2ee64054ccd5` | identical / green |
| F9h | order_reference of the payment is read from the invoice reference text | `unit/test_outbox_payloads.py::test_payment_received_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | pydantic_core._pydantic_core.ValidationError: 1 validation error for PaymentReceivedPayload | `2ee64054ccd5` | identical / green |
| F9i | correlation_id of the envelope is read from causation_id (invoice events) | `unit/test_outbox_payloads.py::test_invoice_issued_becomes_its_payload_with_every_field_equal_to_the_supplied_value` | AssertionError: assert '00000000-000...-000000000004' == '00000000-000...-000000000003' | `2ee64054ccd5` | identical / green |
| F10a | a spurious extra outbox row is written when the entries contain a consume (repository layer, F3) | `integration/test_invoice_repository.py::test_bi7_commits_invoice_lines_consume_entry_and_one_outbox_row_together_and_leaves_none_after_a_rollback` | AssertionError: expected a whole-table outbox delta of exactly 1 | `42cfe6ffb542` | identical / green |
| F10b | the same spurious row (host layer, F4) | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_reaching_row_fact_and_reply` | AssertionError: expected a whole-table outbox delta of exactly 1, got 2 | `42cfe6ffb542` | identical / green |
| H4a | register_command(IssueInvoiceCommand, ...) is removed from Billing's root | `integration/test_billing_host_lifespan.py::test_the_billing_root_registers_every_message_and_a_missing_or_doubled_one_fails_by_name` | otc_cqrs.errors.DispatcherValidationError: No command handler is registered for IssueInvoiceCommand. Exactly one is required. | `be1d64b1c3fb` | identical / green |
| H4a2 | register_command(IssueInvoiceCommand, ...) is removed from Billing's root (the host boot) | `integration/test_billing_host_lifespan.py::test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown` | otc_cqrs.errors.DispatcherValidationError: No command handler is registered for IssueInvoiceCommand. Exactly one is required. | `be1d64b1c3fb` | identical / green |
| H4b | BillingScope no longer refuses an unbound invoice_reads | `integration/test_billing_host_lifespan.py::test_an_invoice_reads_port_bound_to_nothing_fails_the_boot_naming_it` | Failed: the host must not come up with the invoice reads port unbound | `483925fd6f7f` | identical / green |
| H3a | an AIOKafkaConsumer import is added to a new module under otc_billing/infrastructure (BI1) | `arch/test_kafka_client_confinement.py` | assert ["the modules..._publisher']"] == [] | `43115838260a` | identical / green |
| H3b | a third transport task is started in start_runtime (BI1: the task set is exactly the responder and the relay) | `integration/test_billing_host_lifespan.py::test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown` | AssertionError: assert {'fact-consum...outbox-relay'} == {'nats-respon...outbox-relay'} | `be1d64b1c3fb` | identical / green |
| H2 | IssueInvoiceCommand is registered through a helper loop (F-g + F-j) in Billing's own root | `arch/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[billing]` | assert ["WIRE: 2 reg...iceCommand']"] == [] | `be1d64b1c3fb` | identical / green |
| H2b | ListInvoicesQuery is dropped from the TABLES literal | `arch/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[billing]` | AssertionError: assert ['otc_billing...nvoicesQuery'] == ['otc_billing...tCreditQuery'] | `5b8dffddb8bc` | identical / green |
| D8a | a second session.add(...) is added in invoice_repository.py | `arch/test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[billing]` | AssertionError: services/billing/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'infrastructu… | `b5780e031931` | identical / green |
| D8b | a second execute(text(ADVANCE_INVOICE_SEQUENCE)) is added in the allocator | `arch/test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[billing]` | AssertionError: services/billing/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'infrastructu… | `db8aba447078` | identical / green |
| I1a | the invoices re-read is moved before lock_for_order | `integration/test_invoice_issue_race.py::test_bi8_two_concurrent_issues_for_one_order_yield_one_invoice_one_consume_and_one_fact` | AssertionError: BC32: expected an invoice-issue reply (`created`), got {'code': 'PRECONDITION_FAILED', 'message': 'Order ORD-000101 has no active hold: it was never held, or its hold was already cons… | `89f5bf98d8a8` | identical / green |
| I1b | with_for_update is dropped from lock_for_order | `integration/test_invoice_issue_race.py::test_bi8_two_concurrent_issues_for_one_order_yield_one_invoice_one_consume_and_one_fact` | AssertionError: BC32: expected an invoice-issue reply (`created`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'correlationId': '0e47ab2e-b9af-4d15-b4ec-edae5d0ad… | `42cfe6ffb542` | identical / green |
| I1c | run() pins REPEATABLE READ | `integration/test_invoice_issue_race.py::test_bi8_two_concurrent_issues_for_one_order_yield_one_invoice_one_consume_and_one_fact` | AssertionError: BC32: expected an invoice-issue reply (`created`), got {'code': 'UNAVAILABLE', 'message': 'the credit store is temporarily unavailable (40001)', 'correlationId': '5cc198aa-01f7-49b1-9… | `7f23068c9ce1` | identical / green |
| G5 | the invoice list handler answers an RpcError (the request fails inside the handler) | `integration/test_invoice_list.py::test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now` | AssertionError: BC32: expected an invoice list reply (a `page`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'occurredAt': '2026-10-09T18:37:56.426Z'} | `7a564e4950d7` | identical / green |
| J1-S1 | lock_for_order is handed another order reference (the company code) | `unit/test_invoice_issue_service.py` | AssertionError: assert [('RETAIL-77'... 'SUPPLY-CO')] == [('RETAIL-77'...'ORD-000101')] | `89f5bf98d8a8` | identical / green |
| J1-S2 | the in-transaction re-read is handed another order reference (the retailer code) | `unit/test_invoice_issue_service.py` | AssertionError: assert ['RETAIL-77'] == ['ORD-000101'] | `89f5bf98d8a8` | identical / green |
| J1-S3 | consume is handed another order reference (the company code) | `unit/test_invoice_issue_service.py` | otc_billing.domain.errors.NoActiveHoldError: Order SUPPLY-CO has no active hold: it was never held, or its hold was already consumed or released. | `89f5bf98d8a8` | identical / green |
| J1-S4 | next_reference is not called (a fixed reference is used) | `unit/test_invoice_issue_service.py` | AssertionError: BI8: the issue path's calls are not lock, re-read, allocate, save, save | `89f5bf98d8a8` | identical / green |
| J1-S5 | Invoice.issue is handed the company code as the retailer code | `unit/test_invoice_issue_service.py` | AssertionError: assert ('SUPPLY-CO', 'SUPPLY-CO') == ('RETAIL-77', 'SUPPLY-CO') | `89f5bf98d8a8` | identical / green |
| J1-S6 | invoices.save is not called | `unit/test_invoice_issue_service.py` | ValueError: not enough values to unpack (expected 1, got 0) | `89f5bf98d8a8` | identical / green |
| J1-S8 | the fast-path read is handed another order reference (the retailer code) | `unit/test_invoice_issue_service.py` | AssertionError: the fast path read happens once, outside the transaction | `89f5bf98d8a8` | identical / green |
| J1-S9 | the clock read is the wall clock | `unit/test_invoice_issue_service.py` | AssertionError: BI13: the clock was read 0 times | `89f5bf98d8a8` | identical / green |
| J1-S10 | the id source handed to the work is UniqueId.new | `unit/test_invoice_issue_service.py` | AssertionError: the consume entry's id is not from the scope's id port | `89f5bf98d8a8` | identical / green |
| J1-S11 | the list handler reads the wall clock instead of the clock port | `unit/test_invoice_list_handler.py` | AssertionError: the clock must be read exactly once | `7a564e4950d7` | identical / green |
| J1-S12 | parse_invoice_state is handed no paid_at when mapping a snapshot | `unit/test_invoice_mapper.py` | otc_billing.domain.invoice_errors.InvalidInvoiceSnapshotError: The stored invoice cannot be restored: invoice INV-000321 is paid but its paid_at is None, not an aware instant. | `8c394267bd20` | identical / green |
| J1-S13 | parse_invoice_state is handed no paid_at when mapping a view | `unit/test_invoice_mapper.py` | otc_billing.domain.invoice_errors.InvalidInvoiceSnapshotError: The stored invoice cannot be restored: invoice INV-000321 is paid but its paid_at is None, not an aware instant. | `8c394267bd20` | identical / green |
| J1-S14 | the view's status token is the constant ISSUED | `unit/test_invoice_mapper.py` | AssertionError: assert <InvoiceStatus.ISSUED: 'issued'> is <InvoiceStatus.PAID: 'paid'> | `8c394267bd20` | identical / green |
| J1-S16 | the fast-path read is handed a fixed order reference | `integration/test_invoice_reads.py::test_find_by_order_reference_takes_no_lock` | assert None is not None | `c11e18561107` | identical / green |
| J1-S17 | the repository's re-read is handed a fixed order reference | `integration/test_invoice_repository.py::test_a_reload_returns_the_lines_in_canonical_order_for_an_invoice_saved_in_another_order` | assert None is not None | `b5780e031931` | identical / green |
| J1-S18 | decode_issue is handed a fresh correlation instead of the header ids | `unit/test_credit_responder.py::test_bi2_billing_invoice_issue_dispatches_a_command_carrying_the_header_ids` | AssertionError: assert 'ab1b138b-e93...-e3e3680d8f81' == '00000000-000...-0000000000c0' | `7a7b550621ee` | identical / green |
| J1-S19 | decode_list ignores the request body | `integration/test_invoice_list.py::test_bi15_filters_pages_orders_and_applies_issued_before_minutes_against_the_supplied_now` | AssertionError: assert 5 == 2 | `7a7b550621ee` | identical / green |
| J1-S21 | Invoice.status is the constant ISSUED | `unit/domain/test_invoice.py` | AssertionError: assert <InvoiceStatus.ISSUED: 'issued'> is <InvoiceStatus.PAID: 'paid'> | `c3ca9162a617` | identical / green |
| J1-F19-hold-lock | credit_hold: lock_for_order is handed another order reference | `unit/test_credit_hold_service.py` | AssertionError: assert [('RETAIL-77'... 'SUPPLY-CO')] == [('RETAIL-77'...'ORD-000101')] | `65ffb022f2ed` | identical / green |
| J1-F19-hold-save-approve | credit_hold: the approved branch does not save | `unit/test_credit_hold_service.py` | assert 0 == 1 | `65ffb022f2ed` | identical / green |
| J1-F19-hold-save-reject | credit_hold: the rejected branch does not save | `unit/test_credit_hold_service.py` | AssertionError: BC14: the refusal branch did not save the aggregate | `65ffb022f2ed` | identical / green |
| J1-F19-hold-clock | credit_hold: the clock read is the wall clock | `unit/test_credit_hold_service.py` | AssertionError: BC14: a field of the port-refusal fact is wrong | `65ffb022f2ed` | identical / green |
| J1-F19-hold-ids | credit_hold: the id source is UniqueId.new | `unit/test_credit_hold_service.py` | AssertionError: BC14: a field of the port-refusal fact is wrong | `65ffb022f2ed` | identical / green |
| J1-F19-release-lock | credit_release: lock_for_order is handed another order reference | `integration/test_credit_release.py` | AssertionError: assert False is True | `9afffa0b5090` | identical / green |
| J1-F19-release-save | credit_release: the release is not saved | `unit/test_credit_release_service.py` | AssertionError: the release must save the aggregate exactly once | `9afffa0b5090` | identical / green |
| J1-F19-release-clock | credit_release: the clock read is the wall clock | `unit/test_credit_release_service.py` | AssertionError: a field of the credit.released.v1 fact is wrong | `9afffa0b5090` | identical / green |
| J1-F19-release-ids | credit_release: the id source is UniqueId.new | `unit/test_credit_release_service.py` | AssertionError: exactly one release entry | `9afffa0b5090` | identical / green |
| F11 | the InvoiceIssued raise is deleted from Invoice.issue (Billing unit and integration suites, no -x) | `services/billing/tests` | 12 failed, 586 passed in 55.52s | `c3ca9162a617` | identical / green |
| E2a | the billing.invoice.issue constant is substituted with the sibling billing.invoice.list | `unit/test_credit_subjects.py::test_each_of_the_five_subjects_is_the_address_of_its_asyncapi_channel` | AssertionError: channel invoiceIssue: the subject Billing answers is not the spec's address | `2cd75e95008f` | identical / green |
| E2b | the INVOICE_LIST_SUBJECT route entry is deleted | `unit/test_credit_subjects.py::test_the_five_subjects_are_pairwise_distinct_and_are_exactly_the_route_table` | AssertionError: assert {'billing.cre...nvoice.issue'} == {'billing.cre...invoice.list'} | `7a7b550621ee` | identical / green |
| E2c | a sixth, undeclared route is added (a subject no channel declares) | `unit/test_credit_subjects.py::test_the_five_subjects_are_pairwise_distinct_and_are_exactly_the_route_table` | AssertionError: assert {'billing.cre...invoice.void'} == {'billing.cre...invoice.list'} | `7a7b550621ee` | identical / green |

## 8. L2 — the matrix summary, derived one row at a time

`R45` and `R46` flipped (names verbatim), `R47` - `R49` left `TODO`. The counts were re-derived by a script that reads every `| **R<n>** |` row of `test-matrix.md` and takes its Status cell's first word (never incremented by hand); its output, matching the summary table (63 rows, 41 green, 1 scoped, 21 not yet green):

```text
Derived from the Status column, one row per line (statuses by first word):
  R1   SCOPED  [1 `orders_aggregate` — R1 – R10]
  R2   DONE    [1 `orders_aggregate` — R1 – R10]
  R3   DONE    [1 `orders_aggregate` — R1 – R10]
  R4   DONE    [1 `orders_aggregate` — R1 – R10]
  R5   DONE    [1 `orders_aggregate` — R1 – R10]
  R6   DONE    [1 `orders_aggregate` — R1 – R10]
  R7   DONE    [1 `orders_aggregate` — R1 – R10]
  R8   DONE    [1 `orders_aggregate` — R1 – R10]
  R9   DONE    [1 `orders_aggregate` — R1 – R10]
  R10  DONE    [1 `orders_aggregate` — R1 – R10]
  R11  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R12  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R13  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R14  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R15  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R16  TODO    [2 `outbox_and_idempotency` — R11 – R18]
  R17  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R18  DONE    [2 `outbox_and_idempotency` — R11 – R18]
  R19  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R20  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R21  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R22  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R23  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R24  INTEGRATION [3 `order_saga_orchestrator` — R19 – R29]
  R25  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R26  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R27  DONE    [3 `order_saga_orchestrator` — R19 – R29]
  R28  INTEGRATION [3 `order_saga_orchestrator` — R19 – R29]
  R29  RETRY   [3 `order_saga_orchestrator` — R19 – R29]
  R30  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R31  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R32  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R33  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R34  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R35  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R36  DONE    [4 `fulfillment_stock` — R30 – R36, R61]
  R61  NOT     [4 `fulfillment_stock` — R30 – R36, R61]
  R37  DONE    [5 `billing_credit` — R37 – R44]
  R38  DONE    [5 `billing_credit` — R37 – R44]
  R39  DONE    [5 `billing_credit` — R37 – R44]
  R40  DONE    [5 `billing_credit` — R37 – R44]
  R41  DONE    [5 `billing_credit` — R37 – R44]
  R42  DONE    [5 `billing_credit` — R37 – R44]
  R43  DONE    [5 `billing_credit` — R37 – R44]
  R44  DONE    [5 `billing_credit` — R37 – R44]
  R45  DONE    [6 `billing_invoicing` — R45 – R49]
  R46  DONE    [6 `billing_invoicing` — R45 – R49]
  R47  TODO    [6 `billing_invoicing` — R45 – R49]
  R48  TODO    [6 `billing_invoicing` — R45 – R49]
  R49  TODO    [6 `billing_invoicing` — R45 – R49]
  R50  TODO    [7 `projector_read_model` — R50 – R55]
  R51  TODO    [7 `projector_read_model` — R50 – R55]
  R52  TODO    [7 `projector_read_model` — R50 – R55]
  R53  TODO    [7 `projector_read_model` — R50 – R55]
  R54  TODO    [7 `projector_read_model` — R50 – R55]
  R55  TODO    [7 `projector_read_model` — R50 – R55]
  R56  TODO    [8 `observability_reliability` — R56 – R60,]
  R57  TODO    [8 `observability_reliability` — R56 – R60,]
  R58  TODO    [8 `observability_reliability` — R56 – R60,]
  R59  TODO    [8 `observability_reliability` — R56 – R60,]
  R60  TODO    [8 `observability_reliability` — R56 – R60,]
  R62  TODO    [8 `observability_reliability` — R56 – R60,]
  R63  TODO    [8 `observability_reliability` — R56 – R60,]

1 `orders_aggregate` — R1 – R10                         rows=10 green=9 scoped=1 not-yet=0
2 `outbox_and_idempotency` — R11 – R18                  rows=8 green=7 scoped=0 not-yet=1
3 `order_saga_orchestrator` — R19 – R29                 rows=11 green=8 scoped=0 not-yet=3
4 `fulfillment_stock` — R30 – R36, R61                  rows=8 green=7 scoped=0 not-yet=1
5 `billing_credit` — R37 – R44                          rows=8 green=8 scoped=0 not-yet=0
6 `billing_invoicing` — R45 – R49                       rows=5 green=2 scoped=0 not-yet=3
7 `projector_read_model` — R50 – R55                    rows=6 green=0 scoped=0 not-yet=6
8 `observability_reliability` — R56 – R60,              rows=7 green=0 scoped=0 not-yet=7
TOTAL rows 63 green 41 scoped 1 not-yet 21
```

`requirements.md` §3.2: 32 rows, all `DONE` with real names (every cited test name was checked to have a `def` in the repository); `BI22` is `DONE` on the strength of § 9.

## 9. Live boot (BI22; tasks K1 - K5)

Stack: `docker ps` before: `otcpy-n8n Up 13 hours (unhealthy)` (`.arm/bc21/live/docker_before.txt`); started with `docker compose -p otcpy -f docker-compose.infra.yml start`, which starts the whole infrastructure (postgres, nats, kafka, mongodb, mailpit, jaeger, otel-collector, prometheus, grafana, kafka-console, kafka-exporter); `docker ps` after: `otcpy-n8n Up 14 hours (healthy)` and nothing else (`docker_after.txt`). Hosts: `uvicorn otc_billing.main:app --port 8103`, `otc_fulfillment.main:app --port 8102`, `otc_orders.main:app --port 8101`, each `/health/ready` 200; stopped by PID (`kill -TERM`, each log ends `Application shutdown complete`), ports 8101 - 8103 free. Raw outputs: `.arm/bc21/live/`.

### K1 pre-state (before anything started)

```text
== K1 pre-state, 2026-10-09T20:20:33+02:00
ERROR:  column "retailer_code" does not exist
LINE 1: SELECT id, order_reference, status, retailer_code, company_c...
                                            ^
HINT:  Perhaps you meant to reference the column "orders.retailer_id".
ERROR:  column i.product_code does not exist
LINE 1: SELECT o.order_reference, i.product_code, i.quantity, i.unit...
                                  ^
HINT:  Perhaps you meant to reference the column "i.product_id".
 order_reference |     command     | status | attempts |      next_attempt_at       |                  id                  |                                     last_error                                      
-----------------+-----------------+--------+----------+----------------------------+--------------------------------------+-------------------------------------------------------------------------------------
 ORD-000007      | credit.hold     | sent   |       12 |                            | 37a3ed86-d3c1-459d-bc9b-e1e36d28860b | billing.credit.hold: no responder is subscribed to billing.credit.hold.
 ORD-000007      | despatch.create | sent   |        0 |                            | 3b0a203c-f978-4206-bf88-c2826341cdf8 | 
 ORD-000007      | stock.reserve   | sent   |        6 |                            | bccaadb5-0354-4f91-b2bd-482a8ef26edb | fulfillment.stock.reserve: no responder is subscribed to fulfillment.stock.reserve.
 ORD-000008      | credit.hold     | sent   |       12 |                            | 5f3bceaa-2c9e-4320-8b65-71c2870dc731 | billing.credit.hold: no responder is subscribed to billing.credit.hold.
 ORD-000008      | despatch.create | sent   |        0 |                            | fb49e95a-9595-4710-990a-e597ec1db2b5 | 
 ORD-000008      | invoice.issue   | parked |        6 | 2026-10-09 04:55:17.148+00 | d44f20f5-3863-4d42-8b4b-4be6d2c154f0 | billing.invoice.issue: no responder is subscribed to billing.invoice.issue.
 ORD-000008      | stock.reserve   | sent   |        0 |                            | 70e5aa5f-c4e9-4857-a52c-c6de0ae82c58 | 
 ORD-000009      | credit.hold     | sent   |        0 |                            | cc94f261-0cfb-4942-9c6b-b81a472e6aad | 
 ORD-000009      | stock.release   | sent   |        0 |                            | 14d27095-d61b-49b8-9ab9-110578e189be | 
 ORD-000009      | stock.reserve   | sent   |        0 |                            | 6eedd915-e90b-49bc-8a3e-5ac9be3e2989 | 
(10 rows)

   [the 154-row `credits` listing is omitted here: CR-000001 is CarrefourEs / IBERFOODS, limit 500000 EUR]

   code    | order_reference |  type   | amount 
-----------+-----------------+---------+--------
 CR-000001 | ORD-000001      | consume |  16130
 CR-000001 | ORD-000001      | hold    |  16130
 CR-000001 | ORD-000001      | release |  16130
 CR-000001 | ORD-000007      | hold    |  55545
 CR-000001 | ORD-000008      | hold    |  99996
 CR-000001 | ORD-000090      | hold    |   1000
 CR-000001 | ORD-000090      | release |   1000
 CR-000002 | ORD-000002      | consume |  10374
 CR-000002 | ORD-000002      | hold    |  10374
 CR-000002 | ORD-000002      | release |  10374
 CR-000003 | ORD-000003      | consume |  19450
 CR-000003 | ORD-000003      | hold    |  19450
 CR-000003 | ORD-000003      | release |  19450
 CR-000006 | ORD-000004      | consume |  23972
 CR-000006 | ORD-000004      | hold    |  23972
 CR-000006 | ORD-000004      | release |  23972
 CR-000007 | ORD-000005      | consume |  10055
 CR-000007 | ORD-000005      | hold    |  10055
 CR-000007 | ORD-000005      | release |  10055
(19 rows)

 committed 
-----------
    155541
(1 row)

 invoice_reference | order_reference | status | amount | discount | total_amount 
-------------------+-----------------+--------+--------+----------+--------------
 INV-000001        | ORD-000001      | paid   |  16130 |        0 |        16130
 INV-000002        | ORD-000002      | paid   |  10374 |        0 |        10374
 INV-000003        | ORD-000003      | paid   |  19450 |        0 |        19450
 INV-000004        | ORD-000004      | paid   |  23972 |        0 |        23972
 INV-000005        | ORD-000005      | paid   |  10055 |        0 |        10055
(5 rows)

 id | next_value 
----+------------
(0 rows)

 id | next_value 
----+------------
  1 |         10
(1 row)

== K1 pre-state (continued), 2026-10-09T20:20:49+02:00
 order_reference |   status   | initial_amount | initial_discount | total_amount |         order_date         
-----------------+------------+----------------+------------------+--------------+----------------------------
 ORD-000007      | confirmed  |          55545 |                0 |        55545 | 2026-10-07 09:48:55.11+00
 ORD-000008      | despatched |          99996 |                0 |        99996 | 2026-10-08 04:46:12.087+00
 ORD-000009      | cancelled  |         374985 |                0 |       374985 | 2026-10-09 04:52:27.333+00
(3 rows)

 order_reference | product  | quantity | price | discount 
-----------------+----------+----------+-------+----------
 ORD-000008      | PRD-0001 |        4 | 24999 |        0
(1 row)

  retailer   |  company  
-------------+-----------
 CarrefourEs | IBERFOODS
(1 row)

 order_reference | type | amount |        credit_date         
-----------------+------+--------+----------------------------
 ORD-000007      | hold |  55545 | 2026-10-09 04:51:45.558+00
 ORD-000008      | hold |  99996 | 2026-10-09 04:51:45.554+00
(2 rows)

 invoices_rows | with_discount 
---------------+---------------
             5 |             0
(1 row)

 outbox_rows | unpublished 
-------------+-------------
          26 |           0
(1 row)

 status | count 
--------+-------
 parked |     1
 sent   |     9
(2 rows)

== billing.credit.list (CarrefourEs / IBERFOODS), 2026-10-09T20:21:05+02:00
{"items":[{"creditCode":"CR-000001","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","creditLimit":500000,"activeHolds":155541,"openExposure":0,"availableCredit":344459}],"page":{"page":1,"pageSize":25,"tot…
hand: 500000 - 99996 - 55545 = 344459
== billing.invoice.list (the five seeded, before) ==
{"items":[{"invoiceId":"7f28af0c-4d7b-457d-bd4c-273fd6c3771b","invoiceReference":"INV-000005","invoiceDate":"2026-06-05T09:04:00.000Z","orderReference":"ORD-000005","retailerCode":"AldiGb","companyCode":"UKDISTRIB","currency":"GB…
```

`ORD-000008`: `despatched`, one line 4 x PRD-0001 @ 24999, `initialDiscount` 0, total 99996, `invoice.issue` `parked` with attempts 6 (the design says 3: a moved state). `CR-000001` available credit 344459 both computed (500000 - 99996 - 55545) and through `billing.credit.list`. `invoices`: the five seeded rows, all `paid`, all `discount` 0; `invoice_number_sequences` absent; order counter 10.

### K2 the unattended re-issue (hosts started 20:21:1x; Billing first, then Fulfillment, then Orders)

Within seconds of starting Orders, with no operator action (Billing logs no request lines; the evidence is the two databases):

```text
== K2 evidence 2026-10-09T20:21:30+02:00
                  id                  | invoice_reference | order_reference | retailer_code | company_code | currency_code | amount | discount | total_amount | status | paid_at |        invoice_date        
--------------------------------------+-------------------+-----------------+---------------+--------------+---------------+--------+----------+--------------+--------+---------+----------------------------
 e2bc577c-7ee2-45af-870a-e279a4411e7f | INV-000006        | ORD-000008      | CarrefourEs   | IBERFOODS    | EUR           |  99996 |        0 |        99996 | issued |         | 2026-10-09 18:21:13.289+00
(1 row)

 product_code | units | price 
--------------+-------+-------
 PRD-0001     |     4 | 24999
(1 row)

 id | next_value 
----+------------
  1 |          7
(1 row)

 order_reference |  type   | amount |        credit_date         
-----------------+---------+--------+----------------------------
 ORD-000008      | hold    |  99996 | 2026-10-09 04:51:45.554+00
 ORD-000008      | consume |  99996 | 2026-10-09 18:21:13.289+00
(2 rows)

    event_type     |             aggregate_id             |            correlation_id            |             causation_id             | published |        occurred_at         |                                                                                                                         …
-------------------+--------------------------------------+--------------------------------------+--------------------------------------+-----------+----------------------------+-------------------------------------------------------------------------------------------------------------------------…
 invoice.issued.v1 | 772f43e4-c5e5-4aca-b46e-41af6b9bc854 | 1741d5aa-cfba-4205-a1c0-82e7a5cb8984 | 8a0fd807-222e-4b5f-af0f-c91119bdb645 | t         | 2026-06-01 09:04:00+00     | {"orderReference":"ORD-000001","invoiceReference":"INV-000001","invoiceDate":"2026-06-01T09:04:00.000Z","retailerCode":"…
 invoice.issued.v1 | 0a7d74df-1107-4df3-95ec-2dbe9152dc99 | cf826257-6521-4471-9292-d5a81919eba6 | d3799173-5363-4d0a-bfc1-284eed0ddf76 | t         | 2026-06-02 09:04:00+00     | {"orderReference":"ORD-000002","invoiceReference":"INV-000002","invoiceDate":"2026-06-02T09:04:00.000Z","retailerCode":"…
 invoice.issued.v1 | 3b3f04a6-21b0-4c8a-9952-7dcdec7c82f0 | 321abe6d-ee7b-465f-86d7-d65d6707d131 | 0e53f361-0646-4cba-b5f3-64873ddd707c | t         | 2026-06-03 09:04:00+00     | {"orderReference":"ORD-000003","invoiceReference":"INV-000003","invoiceDate":"2026-06-03T09:04:00.000Z","retailerCode":"…
 invoice.issued.v1 | 277d4604-11e8-4d35-bcf8-2f8042425d6e | d69b8a2a-b0c8-47d5-bf66-82720335518c | 4695bec9-4953-4edf-9a3a-22669db52f24 | t         | 2026-06-04 09:04:00+00     | {"orderReference":"ORD-000004","invoiceReference":"INV-000004","invoiceDate":"2026-06-04T09:04:00.000Z","retailerCode":"…
 invoice.issued.v1 | 7f28af0c-4d7b-457d-bd4c-273fd6c3771b | 6baf7a6d-aeff-46af-a629-8abe050c8699 | 33e87954-5774-43ac-bc72-320d56f765cb | t         | 2026-06-05 09:04:00+00     | {"orderReference":"ORD-000005","invoiceReference":"INV-000005","invoiceDate":"2026-06-05T09:04:00.000Z","retailerCode":"…
 invoice.issued.v1 | e2bc577c-7ee2-45af-870a-e279a4411e7f | b7117514-a2a0-49e5-a41f-bab72062b246 | d44f20f5-3863-4d42-8b4b-4be6d2c154f0 | t         | 2026-10-09 18:21:13.289+00 | {"orderReference":"ORD-000008","invoiceReference":"INV-000006","invoiceDate":"2026-10-09T18:21:13.289Z","retailerCode":"…
(6 rows)

               order_id               | order_reference |  status  
--------------------------------------+-----------------+----------
 b7117514-a2a0-49e5-a41f-bab72062b246 | ORD-000008      | invoiced
(1 row)

           saga_command_id            |     command     | status | attempts 
--------------------------------------+-----------------+--------+----------
 5f3bceaa-2c9e-4320-8b65-71c2870dc731 | credit.hold     | sent   |       12
 fb49e95a-9595-4710-990a-e597ec1db2b5 | despatch.create | sent   |        0
 d44f20f5-3863-4d42-8b4b-4be6d2c154f0 | invoice.issue   | sent   |        6
 70e5aa5f-c4e9-4857-a52c-c6de0ae82c58 | stock.reserve   | sent   |        0
(4 rows)

```

Exactly one new `invoices` row (`INV-000006`: the seed's maximum 5 plus one; the counter row appeared and reads 7), one `consume` of 99996, one `invoice.issued.v1` stamped published with `correlation_id` = `otc_orders.orders.id` (`b7117514...`) and `causation_id` = the `invoice.issue` row's `saga_commands.id` (`d44f20f5...`), `ORD-000008` = `invoiced`.

```text
== K2/K3 after-state 2026-10-09T20:21:38+02:00
{"items":[{"creditCode":"CR-000001","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","creditLimit":500000,"activeHolds":55545,"openExposure":99996,"availableCredit":344459}],"page":{"page":1,"pageSize":25,"total":1}}
-- unpublished outbox, billing:
 unpublished 
-------------
           0
(1 row)

-- K3: everything the saga could have done next:
     event_type      | count 
---------------------+-------
 credit.approved.v1  |     8
 credit.rejected.v1  |     2
 credit.released.v1  |     6
 invoice.issued.v1   |     6
 payment.received.v1 |     5
(5 rows)

 order_reference |  status   
-----------------+-----------
 ORD-000001      | completed
 ORD-000002      | completed
 ORD-000003      | completed
 ORD-000004      | completed
 ORD-000005      | completed
 ORD-000006      | cancelled
 ORD-000007      | confirmed
 ORD-000008      | invoiced
 ORD-000009      | cancelled
(9 rows)

 status | count 
--------+-------
 sent   |    10
(1 row)

 order_reference | saga_commands 
-----------------+---------------
 ORD-000008      |             4
(1 row)

 payments 
----------
        5
(1 row)

  type   | count 
---------+-------
 consume |     6
 hold    |     8
 release |     6
(3 rows)


```

`CR-000001`'s available credit is 344459 before and after (activeHolds 155541 -> 55545, openExposure 0 -> 99996): numerically unchanged.

### K3 the designed end state (saga.md section 3.1 step 5)

`| 5 | invoice.issued.v1 | despatched | Move to invoiced. **The saga now waits for the outside world** — no internal timer, no polling | — | — | invoiced |`. Observed after the K2 block: Billing's outbox holds 27 rows = the 26 of K1 + the one `invoice.issued.v1`; the `payment.received.v1` count is 5 (the seed's) and `credit.released.v1` 6 (unchanged); `payments` 5; no order moved to `paid` or `completed`; `ORD-000008` still has its four `saga_commands` rows. The saga stopped at `invoiced`.

### K4 a fresh control order with a non-zero discount

```text
== K4 control order 2026-10-09T20:22:03+02:00: PRD-0002 x5 @1849 = 9245; PRD-0001 x2 @24999 = 49998 with lineDiscount 777
{"orderId":"9537652c-3e14-4491-a09a-6eea14bbf3de","orderReference":"ORD-000010","status":"placed","currency":"EUR","initialAmount":59243,"initialDiscount":777,"totalAmount":58466,"orderDate":"2026-10-09T18:22:03.956Z"}
== K4 evidence 2026-10-09T20:22:16+02:00
 order_reference |  status  | initial_amount | initial_discount | total_amount 
-----------------+----------+----------------+------------------+--------------
 ORD-000010      | invoiced |          59243 |              777 |        58466
(1 row)

-- the facts of the order, in time order (all three outboxes):
     db     |     event_type     |        occurred_at         | published 
------------+--------------------+----------------------------+-----------
 otc_orders | order.placed.v1    | 2026-10-09 18:22:03.956+00 | t
 otc_orders | order.confirmed.v1 | 2026-10-09 18:22:04.284+00 | t
(2 rows)

       db        |     event_type      |        occurred_at        | published 
-----------------+---------------------+---------------------------+-----------
 otc_fulfillment | stock.reserved.v1   | 2026-10-09 18:22:04.06+00 | t
 otc_fulfillment | order.despatched.v1 | 2026-10-09 18:22:04.56+00 | t
(2 rows)

     db      |     event_type     |        occurred_at         | published 
-------------+--------------------+----------------------------+-----------
 otc_billing | credit.approved.v1 | 2026-10-09 18:22:04.284+00 | t
 otc_billing | invoice.issued.v1  | 2026-10-09 18:22:04.822+00 | t
(2 rows)

-- the invoice row and its line rows:
 invoice_reference | order_reference | amount | discount | total_amount | status | currency_code 
-------------------+-----------------+--------+----------+--------------+--------+---------------
 INV-000007        | ORD-000010      |  59243 |      777 |        58466 | issued | EUR
(1 row)

 product_code | units | price 
--------------+-------+-------
 PRD-0001     |     2 | 24999
 PRD-0002     |     5 |  1849
(2 rows)

-- the fact's amount, discount, totalAmount:
 amount | discount | total_amount |                                                     lines                                                      
--------+----------+--------------+----------------------------------------------------------------------------------------------------------------
 59243  | 777      | 58466        | [{"productCode":"PRD-0001","units":2,"unitPrice":24999},{"productCode":"PRD-0002","units":5,"unitPrice":1849}]
(1 row)

-- consume rows:
 order_reference |  type   | amount 
-----------------+---------+--------
 ORD-000010      | hold    |  58466
 ORD-000010      | consume |  58466
(2 rows)

{"items":[{"creditCode":"CR-000001","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","creditLimit":500000,"activeHolds":55545,"openExposure":158462,"availableCredit":285993}],"page":{"page":1,"pageSize":25,"total":1}}
hand: 500000 - 99996 - 55545 - 58466 = 285993 (a consume moves nothing)
```

`ORD-000010` traversed placed -> stock_reserved -> credit_approved -> confirmed -> despatched -> invoiced unattended in under ten seconds (the facts above are in that order by `occurred_at`); its `invoices` row and `invoice.issued.v1` carry `amount` 59243, `discount` 777, `totalAmount` 58466: the order's `initialAmount`, `initialDiscount` and `totalAmount`, three distinct values (the live half of `BI38`). Available credit afterwards 285993 = 500000 - 99996 - 55545 - 58466.

### K5 teardown, and the register of known-altered live fixtures (extends `progress/impl_billing_credit.md` section 8)

```text
== K5 final fixture state 2026-10-09T20:22:25+02:00
 order_reference |  status   | cancellation_reason 
-----------------+-----------+---------------------
 ORD-000007      | confirmed | 
 ORD-000008      | invoiced  | 
 ORD-000009      | cancelled | credit_rejected
 ORD-000010      | invoiced  | 
(4 rows)

 saga_commands_total 
---------------------
                  14
(1 row)

 id | next_value 
----+------------
  1 |         11
(1 row)

 id | next_value 
----+------------
  1 |          8
(1 row)

 invoice_reference | order_reference | status | amount | discount | total_amount 
-------------------+-----------------+--------+--------+----------+--------------
 INV-000006        | ORD-000008      | issued |  99996 |        0 |        99996
 INV-000007        | ORD-000010      | issued |  59243 |      777 |        58466
(2 rows)

 order_reference |  type   | amount 
-----------------+---------+--------
 ORD-000008      | hold    |  99996
 ORD-000008      | consume |  99996
 ORD-000010      | hold    |  58466
 ORD-000010      | consume |  58466
(4 rows)

 credit_items_total | consumes 
--------------------+----------
                 22 |        7
(1 row)

 outbox_total | unpublished 
--------------+-------------
           29 |           0
(1 row)

 company_code | product_code | units | reserved_units 
--------------+--------------+-------+----------------
 IBERFOODS    | PRD-0001     |   492 |              0
 IBERFOODS    | PRD-0002     |   487 |              0
(2 rows)

 despatch_reference | order_reference 
--------------------+-----------------
 DES-000008         | ORD-000010
 DES-000007         | ORD-000008
 DES-000006         | ORD-000007
(3 rows)


```

Rows this walkthrough CHANGED in the developer databases (recreate them to repeat it):

- `otc_billing`: `invoices` + 2 rows (`INV-000006` for `ORD-000008`, `INV-000007` for `ORD-000010` with discount 777) and their `invoice_items`; `invoice_number_sequences` gained its row (now `next_value` 8); `credit_items` + 4 rows (`consume` 99996 for `ORD-000008`, `hold` + `consume` 58466 for `ORD-000010`); `outbox` 26 -> 29 rows (all published). `CR-000001`: active holds 55545, open exposure 158462, available credit 285993.
- `otc_orders`: `ORD-000008` `despatched` -> `invoiced` (its `invoice.issue` row `parked` -> `sent`); new order `ORD-000010` (`CarrefourEs` / `IBERFOODS`, 5 x PRD-0002 + 2 x PRD-0001 with a 777 line discount) now `invoiced`; `saga_commands` 10 -> 14; `order_number_sequences` next value 11.
- `otc_fulfillment`: `DES-000008` for `ORD-000010`; its reservation `consumed`; stock `IBERFOODS` PRD-0001 494 -> 492, PRD-0002 492 -> 487.
- Kafka topics carry the new facts; `otcpy-n8n` untouched. `ORD-000007` still stops at `confirmed` (feature 19's register).

## 10. Inherited findings (`design.md` section 17), avoided or recurred

| Finding | Disposition | Guard |
|---|---|---|
| #8 id 45 (seed race), id 47 (scan cost) | avoided | one-statement seed; `test_billing_counter_seed.py` re-run with the allocator's six (D6) |
| #8 id 49 (id port at every site) | avoided | B6 one arm per site (four), C5, J1-S10 |
| #8 ids 53 / 55 (reply shape; `BC32`) | avoided | `Decode` asserts first; G5 rooted at the decode; sentinel found |
| #8 id 54 (un-hinted re-read) | avoided | measured mechanism; three I1 arms, each red (replies in § 2) |
| #8 id 57 | seam provided | `mark_paid` returns the raised object (B9f red when a copy is returned) |
| #8 id 65 (totals transposition) | avoided | three distinct totals; arm E4c, B5a, F7* |
| #8 id 72, `D3` (summary by hand) | avoided | § 8 derivation |
| #8 id 85 (self-assigned container ports) | avoided | the root fixtures |
| #8 id 102 (money text) | avoided | BI36 (EUR, JPY, BHD), arm E6d |
| #7 `N1` (no box ticked) / #8 `N1` (ticks over stale text) | avoided | 65 of 65 ticked, nine annotated or reworded on the box |
| #7 `N2` / `N10` (placement) | avoided | E3 / E5 count dispatcher calls (zero) |
| #7 `N3` (BI5 ledger rows) | avoided | F2 re-reads the order's rows; C2 zero saves on both repositories |
| #7 `N4` / `N5` | avoided | C4's five-call log with two arms; I1's header says the race cannot see an inversion |
| #7 `N7` (scoped outbox assertion) | avoided | whole-table deltas at F3 and F4; F10 inverted arm red at both layers |
| #7 `N8` (text-scan for "no consumer") | avoided | two existing behavioural instruments, armed (H3a, H3b) |
| #8 `D1` (payment fact survived) | avoided | every field asserted and corrupted (B9a - B9g, F9a - F9i) |
| #8 `D2` (discount dropped, 273 green) | avoided | `issue_body` refuses coinciding totals; four arms F7a - F7d red |
| #8 `R2-N1` (`git diff` as restore evidence) | avoided | `.arm/` backups, sha256, `cmp` |
| #8 `R2-N3` (enumeration of a proxy) | avoided | G5 rooted at the decode |
| #8 `N6` (altered live fixture unregistered) | avoided | § 9 K5 register |
| **Recurred / found this run** | | (a) the `@final` decorator failed the census (§ 2.1); (b) the unit-service tests initially let a substituted argument and a swapped party code through (J1-S5, handler clock): found by J1, fixed by new assertions and a new test, then armed; (c) two of my own first arms were equivalent mutants of the fixture builder (§ 2.6) and one prescribed arm text (F6) described an outcome the code does not produce (§ 2) |

This phase's own rejections: **feature 19 round 1 `D1`** (a fixture satisfying the relation by accident): § 4; **`D2` / `D3` / `R2-1`** (changing an instrument swaps its premises): § 6; **feature 20 `N1`** (failure arriving as a timeout): every arm's failure is a named assertion (the one that timed out, a degenerate "advance in its own session" arm, was dropped because it deadlocked instead of failing by name).

## 11. What I could not do, and what surprised me

- **`@final`** (§ 2.1) and **C1's "keyword only"** (§ 2.3): the two places the text and the repository disagree; both argued above.
- The prescribed **F6 / I1 loser outcomes** differ from the design text (§ 2). The code is right by the assertions that matter; the prose is stale.
- `quality.sh` was run twice on the tree: the first run had the two census failures (`@final`); the second, after the fix, is green. The suites ran with the developer stack down (only `otcpy-n8n` running).
- `./init.sh` exits 0 after the final edits (`.arm/bc21/init.out`); `feature_list.json` changed only on feature 21's `status` line (`in_progress` -> `in_review`).

## 12. L3 — `git status --porcelain` (outside `progress/`) walked against the file list

Every changed path is on `tasks.md`'s list or is feature 19/20's uncommitted work in the same tree (untracked or already modified before this run): the Billing source and test files above; `services/fulfillment/src/.../stock_reads.py` (G1 clamp) and `.../tests/integration/test_stock_list.py` (G6 twin); `specs/shared/test-matrix.md`; `specs/billing_invoicing/{requirements,tasks}.md`; `tests/architecture/{test_registration_behaviour,test_write_path_population,test_billing_rpc_error_retryability}.py`; `feature_list.json` (one line). `services/orders/` shows only feature 20's settings files, unchanged by this run. `pyproject.toml`, `uv.lock`, `models.py`, `range_guards.py`, `types.py`, `sequences.py`, `alembic/`, the outbox copies, `domain/buyer_credit.py` and `packages/` show no change from this run.

```text
 M .env.example
 M feature_list.json
 M services/billing/pyproject.toml
 M services/billing/src/otc_billing/infrastructure/settings.py
 M services/billing/src/otc_billing/presentation/app.py
 M services/billing/tests/integration/conftest.py
 M services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py
 M services/fulfillment/src/otc_fulfillment/infrastructure/settings.py
 M services/fulfillment/tests/integration/test_stock_list.py
 M services/fulfillment/tests/unit/test_fulfillment_settings_env.py
 M services/orders/src/otc_orders/infrastructure/settings.py
 M services/orders/tests/unit/test_orders_settings_env.py
 M specs/shared/test-matrix.md
 M tests/architecture/test_composition_env_reads.py
 M tests/architecture/test_kafka_client_confinement.py
 M tests/architecture/test_outbox_copy_parity.py
 M tests/architecture/test_registration_behaviour.py
 M tests/architecture/test_write_path_population.py
 M uv.lock
?? services/billing/src/otc_billing/application/credit_hold.py
?? services/billing/src/otc_billing/application/credit_release.py
?? services/billing/src/otc_billing/application/errors.py
?? services/billing/src/otc_billing/application/handlers.py
?? services/billing/src/otc_billing/application/invoice_issue.py
?? services/billing/src/otc_billing/application/messages.py
?? services/billing/src/otc_billing/application/ports/
?? services/billing/src/otc_billing/application/scope.py
?? services/billing/src/otc_billing/composition.py
?? services/billing/src/otc_billing/domain/buyer_credit.py
?? services/billing/src/otc_billing/domain/credit_entry_type.py
?? services/billing/src/otc_billing/domain/errors.py
?? services/billing/src/otc_billing/domain/events.py
?? services/billing/src/otc_billing/domain/exposure.py
?? services/billing/src/otc_billing/domain/invoice.py
?? services/billing/src/otc_billing/domain/invoice_errors.py
?? services/billing/src/otc_billing/domain/invoice_events.py
?? services/billing/src/otc_billing/domain/invoice_snapshot.py
?? services/billing/src/otc_billing/domain/invoice_state.py
?? services/billing/src/otc_billing/domain/ledger_entry.py
?? services/billing/src/otc_billing/domain/reasons.py
?? services/billing/src/otc_billing/domain/snapshot.py
?? services/billing/src/otc_billing/infrastructure/clock.py
?? services/billing/src/otc_billing/infrastructure/credit/
?? services/billing/src/otc_billing/infrastructure/ids.py
?? services/billing/src/otc_billing/infrastructure/messaging/
?? services/billing/src/otc_billing/infrastructure/outbox/
?? services/billing/src/otc_billing/infrastructure/persistence/credit_mapper.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_transactions.py
?? services/billing/src/otc_billing/infrastructure/persistence/invoice_mapper.py
?? services/billing/src/otc_billing/infrastructure/persistence/invoice_number_allocator.py
?? services/billing/src/otc_billing/infrastructure/persistence/invoice_reads.py
?? services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py
?? services/billing/src/otc_billing/main.py
?? services/billing/src/otc_billing/presentation/credit_headers.py
?? services/billing/src/otc_billing/presentation/credit_responder.py
?? services/billing/src/otc_billing/presentation/credit_rpc_errors.py
?? services/billing/src/otc_billing/presentation/credit_wire.py
?? services/billing/src/otc_billing/presentation/invoice_wire.py
?? services/billing/tests/integration/test_billing_host_lifespan.py
?? services/billing/tests/integration/test_billing_outbox_relay.py
?? services/billing/tests/integration/test_credit_hold.py
?? services/billing/tests/integration/test_credit_hold_race.py
?? services/billing/tests/integration/test_credit_list.py
?? services/billing/tests/integration/test_credit_release.py
?? services/billing/tests/integration/test_credit_repository.py
?? services/billing/tests/integration/test_credit_responder_concurrency.py
?? services/billing/tests/integration/test_credit_simulator.py
?? services/billing/tests/integration/test_credit_wire.py
?? services/billing/tests/integration/test_invoice_issue.py
?? services/billing/tests/integration/test_invoice_issue_race.py
?? services/billing/tests/integration/test_invoice_list.py
?? services/billing/tests/integration/test_invoice_number_allocator.py
?? services/billing/tests/integration/test_invoice_reads.py
?? services/billing/tests/integration/test_invoice_repository.py
?? services/billing/tests/integration/test_invoice_wire.py
?? services/billing/tests/unit/domain/
?? services/billing/tests/unit/test_always_approve.py
?? services/billing/tests/unit/test_billing_settings_env.py
?? services/billing/tests/unit/test_cents_rule_fixture_guard.py
?? services/billing/tests/unit/test_credit_decision_port.py
?? services/billing/tests/unit/test_credit_hold_service.py
?? services/billing/tests/unit/test_credit_mapper.py
?? services/billing/tests/unit/test_credit_release_service.py
?? services/billing/tests/unit/test_credit_requests.py
?? services/billing/tests/unit/test_credit_responder.py
?? services/billing/tests/unit/test_credit_rpc_errors.py
?? services/billing/tests/unit/test_credit_simulator.py
?? services/billing/tests/unit/test_credit_simulator_settings.py
?? services/billing/tests/unit/test_credit_subjects.py
?? services/billing/tests/unit/test_credit_transactions.py
?? services/billing/tests/unit/test_credit_wire.py
?? services/billing/tests/unit/test_fact_topic.py
?? services/billing/tests/unit/test_invoice_fixture_guard.py
?? services/billing/tests/unit/test_invoice_issue_service.py
?? services/billing/tests/unit/test_invoice_list_handler.py
?? services/billing/tests/unit/test_invoice_mapper.py
?? services/billing/tests/unit/test_invoice_requests.py
?? services/billing/tests/unit/test_invoice_wire.py
?? services/billing/tests/unit/test_outbox_payloads.py
?? specs/billing_credit/
?? specs/billing_invoicing/
?? tests/architecture/test_billing_rpc_error_retryability.py
?? tests/architecture/test_kafka_client_ids.py
```

`git diff --stat` (tracked files; the untracked files are the `??` lines above):

```text
 .env.example                                       |  15 +
 feature_list.json                                  |  20 +-
 services/billing/pyproject.toml                    |   2 +
 .../src/otc_billing/infrastructure/settings.py     | 135 ++++-
 .../billing/src/otc_billing/presentation/app.py    |  37 +-
 services/billing/tests/integration/conftest.py     | 608 +++++++++++++++++++-
 .../infrastructure/persistence/stock_reads.py      |   4 +-
 .../src/otc_fulfillment/infrastructure/settings.py |   4 +-
 .../tests/integration/test_stock_list.py           |  17 +
 .../tests/unit/test_fulfillment_settings_env.py    |  19 +
 .../src/otc_orders/infrastructure/settings.py      |   6 +-
 .../orders/tests/unit/test_orders_settings_env.py  |  20 +
 specs/shared/test-matrix.md                        |  26 +-
 tests/architecture/test_composition_env_reads.py   |  16 +-
 .../architecture/test_kafka_client_confinement.py  |  21 +-
 tests/architecture/test_outbox_copy_parity.py      | 624 ++++++++++++++++++---
 tests/architecture/test_registration_behaviour.py  |  21 +-
 tests/architecture/test_write_path_population.py   |  37 ++
 uv.lock                                            |   4 +
 19 files changed, 1523 insertions(+), 113 deletions(-)
```

## Review findings

Closed N1 - N5 of `progress/review_billing_invoicing.md` §6 (light; no production behaviour change; `feature_list.json` untouched).

- **N1**: `design.md` §6.2 and §13.3 and `tasks.md` F6 now state the measured outcomes (F6 `PRECONDITION_FAILED`; I1 `PRECONDITION_FAILED`, `INTERNAL_ERROR` 23505 or `UNAVAILABLE` 40001 on the counter row), every one safe; the claim that `REPEATABLE READ` cannot raise 40001 is removed.
- **N2**: `design.md` §3 tree, §5.2 (class listing and Closure bullet), L41, §16.2 and `requirements.md` BI23's note replace `@final` with the runtime refusal (`__init_subclass__` raises `TypeError`, armed by B2d) and record the ruling: the maintainer is told, the census allow-list is not extended.
- **N3**: `test_bc27_no_input_produces_conflict` now asserts every `DOMAIN_ERRORS` input's mapped code is in Orders' imported `TERMINAL_RPC_ERROR_CODES`, naming the class. Arm Q6f (`case DomainError()` -> `Code.internal_error`, `credit_rpc_errors.py:82`; backup `.arm/bc21f/`, sha256 `1304606007f1c7d1…da6e9`): `AssertionError: CreditLimitExceededError is answered INTERNAL_ERROR, which Orders' saga adapter would retry; BI25/BI26 require a terminal code`. Restored by `cp`, `cmp` clean, sha equal, caches cleared, re-run 3 passed.
- **N4**: comments reworded in `integration/test_invoice_issue.py` (residue assertion; placement guard `test_bi5_*`) and the header of `integration/test_invoice_issue_race.py` ("cannot see an inversion in general"; C4 is the guard).
- **N5**: `credit_repository.py` docstring names the outbox relay's `update(Outbox)` stamp.

Checks: retryability file 3 passed; `ruff check`, `ruff format --check`, `mypy` clean on the four Python files touched.
