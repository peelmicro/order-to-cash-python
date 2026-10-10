# Design — `billing_invoicing` (feature 21, Python 3.14 / SQLAlchemy 2.1 / asyncpg / PostgreSQL 18.6 / nats-py 2.16, assessment #9)

> **Stack-specific.** This file is where the Python, SQLAlchemy, PostgreSQL, nats-py and `otc_cqrs` detail lives. Nothing here belongs in `specs/shared/`.
>
> **A port with a delta analysis.** #8's design (`../order-to-cash-dotnet/specs/billing_invoicing/design.md`, 788 lines, ledger `L1` – `L32`), its gate record (`../order-to-cash-dotnet/progress/spec_billing_invoicing.md`: 27 open points, one GATE — the responder rename) and its review (`progress/review_billing_invoicing.md`: rejected once, three blocking — `D1` the `payment.received.v1` payload survived corruption, `D2` the request's discount could be dropped with both suites green, `D3` the matrix summary hand-incremented) were read first, then #7's (`../order-to-cash-nestjs/specs/billing_invoicing/`, its code under `apps/billing/src/`, its review: rejected once on `N2` — the discount check inside the transaction — and `N1` — no box ticked). **And above all [`specs/billing_credit/design.md`](../billing_credit/design.md), which is this service's shape**: invoicing extends the Billing host feature 19 built — the same responder task, the same transactions object, the same repository-writes-the-outbox discipline, the same error mapping, the same outbox copies. Every section below says either "feature 19's, reused" or "new, and why".
>
> **Measurements made for this spec** (a throwaway `postgres:18.6` container, removed afterwards; 2026-10-09; script under the session scratchpad, run with `uv run --no-sync python -I`): through SQLAlchemy + asyncpg, `select(…).offset(2**63 - 1)` returns `[]`, `offset(2**63)` raises `sqlalchemy.exc.DBAPIError` *"invalid input for query argument $2: 9223372036854775808 (value out of int64 range)"*, SQLSTATE `22000`; a `timestamptz(3)` column read under `SET TIME ZONE 'Europe/Madrid'` comes back `datetime(2026, 10, 9, 10, 0, 0, 123000, tzinfo=datetime.timezone.utc)` with `utcoffset() == 0:00:00`, and a `NULL` comes back `None`; `SELECT 'paid' = 'Paid'` is `false`; `select(func.count())` returns `int`; an inclusive `paid_at <= :cutoff` with the cutoff equal to the stored instant counts the row. Without a container: `datetime(2026,10,9,10,tzinfo=UTC) - timedelta(minutes=2_000_000_000)` raises `OverflowError: date value out of range`, and `timedelta(minutes=2**63)` raises `OverflowError: Python int too large to convert to C int`.

## 0. Scope

**In scope.** The `Invoice` aggregate root, its `InvoiceLine` values and its two-case `InvoiceState`, invariants **B6** – **B9**, the `InvoiceIssued` and `PaymentReceived` domain facts, `Invoice.mark_paid` (delivered, uncalled — feature 22's seam); the two NATS subjects `billing.invoice.issue` (`R45`) and `billing.invoice.list` as two entries of the existing responder's route table; the `consume` call that gives `R40` its first live caller, inside the issue transaction; the `INV-` allocator class over the existing counter SQL; the invoice repository, mapper and reads; the extension of `CreditTransaction`, `BillingScope`, the error mapping, the fact mapping and the architecture instruments that enumerate Billing; the out-of-range list requests of gate point **G1** on all three list subjects; the live walkthrough of the parked `invoice.issue` row (`BI22`).

**Out of scope, and owned elsewhere.**

| Not here | Owner |
|---|---|
| `billing.payment.register`, the `payments` rows, dedup by `paymentReference`, the `invoice_paid` release and its `credit.released.v1`, `R47` – `R49`, #8 id 57's causal edge (the caller half) | feature 22 (§15.1) |
| The Gateway's callers of `billing.invoice.list` and the "Register payment" action | features 25 and 29 |
| The projector's timeline entries for `invoice.issued.v1` | feature 24 |
| `traceparent`, `x-deadline-ms`, structlog, metrics, DLQ | feature 27 |
| Credit notes, dunning, partial payment or invoicing, invoice cancellation | out of the model (`domain-model.md` §9) |
| Any Orders behaviour change | none: `BI21`'s guard already exists in Orders' tests (`requirements.md` `BI21` note) |

## 1. What already exists — checked, not assumed

**The phase-6 schema is sufficient: no migration.** Read from `services/billing/src/otc_billing/infrastructure/persistence/models.py:90-138`:

| This design needs | Exists as |
|---|---|
| one invoice per order | `invoices.order_reference varchar(20)` **unique** (`:98`) — **B7** made mechanical, the last line of defence |
| the reference, unique | `invoices.invoice_reference varchar(20)` unique (`:94`); `INV-` + up to 16 digits fits, and the counter is `integer`, so at most 10 digits are ever allocated |
| party codes, date, currency | `company_code`, `retailer_code` `varchar(20)`, `invoice_date timestamptz(3)`, `currency_code char(3)` |
| the three totals | `amount`, `discount`, `total_amount` `bigint` (`:99-101`) |
| the state | `status varchar(20)` + `paid_at timestamptz(3) NULL` (`:103-104`) — two columns for one value: §5.2 and §9.2 say where they meet |
| the robot's poll | `ix_invoices_status_invoice_date` (`:92`) |
| the lines | `invoice_items(id, invoice_id → invoices ON DELETE CASCADE, product_code varchar(30), units integer, price bigint, created_at, updated_at)` (`:109-119`). `price` is the **unit** price (the seed writes `line.unit_price` into it, `services/seed/src/otc_seed/domain/data/sagas.py:634`; #8 `InvoiceRowMapper.cs:88`). **No per-line discount column and no position column**: the discount is the invoice's (`invoices.discount`), and line order on a reload is canonical (§9.2) |
| the counter | `invoice_number_sequences(id integer, next_value integer)` (`:122-125`) and its three statements, already written and guarded (`sequences.py:30-40`; `tests/integration/test_billing_counter_seed.py`, backlog 211) |
| `payments` | `:128-137` — feature 22's; not written here |

`invoice_number_sequences.next_value` is `integer`, not `bigint`: a counter, not money, exactly as `order_number_sequences` and `despatch_number_sequences` (and #8's, its gate record row 27). Left alone.

**`invoices.updated_at`** is written equal to `created_at` at insert (feature 19's `credit_items` rule; #7 and #8 do the same). Feature 22's `mark_paid` update moves it.

**The seed** writes `INV-000001` … `INV-000005`, all `paid`, each with `amount = Σ(price × units)`, `discount` = the order's initial discount and `total_amount = amount − discount` (`sagas.py:624-640`), and **no counter row**, so the first live allocation is `INV-000006` unless the live database has moved (read in task K1, never assumed).

**What features 19 and 20 built that this feature reuses** (shapes, not lines): the responder task and its route table (`presentation/credit_responder.py:88-92`), the headers module (`credit_headers.required_correlation`), the transactions object (`infrastructure/persistence/credit_transactions.py:74-89`: one session, `READ COMMITTED` pinned at `:77`, events cleared only after commit at `:81`), `lock_for_order` (`credit_repository.py`, the line `FOR UPDATE`, the committed-exposure scalar, the order's entries), `BuyerCredit.consume` (`domain/buyer_credit.py:386-409`, tested, uncalled), the error mapping (`presentation/credit_rpc_errors.py:29-66`), the fact mapping (`infrastructure/outbox/payloads.py:35-115`, whose `assert_never` makes an unmapped invoice event a type error), the outbox writer copy (unchanged: parity-guarded), the clock copy (`infrastructure/clock.py`: `wire_instant(datetime.now(UTC))`, whole milliseconds), `UuidIdSource`, the composition root, the host fixture and its request helper with the `.99` guard, `wait_for_lock_waiters`, the `Decode` helpers that assert a reply's discriminating field first.

## 2. Layout

```text
services/billing/src/otc_billing/
  domain/
    invoice_state.py        Issued, Paid (frozen, slotted; a subclass raises `TypeError` in `__init_subclass__`), type InvoiceState = Issued | Paid,
                            InvoiceStatus tokens, state_token(state), parse_invoice_state(token, paid_at)
    invoice.py              InvoiceLine, IssueInvoiceInput, InvoiceContext, PaymentInput, PaymentSource,
                            Invoice(AggregateRoot): issue / rehydrate / mark_paid / to_snapshot
    invoice_snapshot.py     InvoiceSnapshot, InvoiceLineSnapshot (frozen; tuples)
    invoice_events.py       InvoiceIssued, PaymentReceived (+ type InvoiceEvent)
    invoice_errors.py       the ten DomainError subclasses of section 5.6
  application/
    ports/invoice_store.py  InvoiceRepository, InvoiceNumberAllocator, InvoiceReads (Protocols)
    ports/credit_store.py   CreditTransaction gains `invoices` and `invoice_numbers`
    messages.py             + IssueInvoiceCommand, IssueLine, InvoiceIssueResult, InvoiceSummary,
                              ListInvoicesQuery, InvoiceViewData, InvoicePage
    handlers.py             + IssueInvoiceHandler, ListInvoicesHandler (thin)
    invoice_issue.py        the issue transactional unit (section 6)
    errors.py               + InvoiceCurrencyMismatchError
    scope.py                BillingScope gains `invoice_reads`
  infrastructure/
    persistence/invoice_mapper.py            rows <-> snapshots; the ONLY constructor of Invoice / InvoiceItem rows;
                                             the one place `status` and `paid_at` meet
    persistence/invoice_repository.py        load_invoice(session, ref); SqlAlchemyInvoiceRepository: find / save
    persistence/invoice_number_allocator.py  SqlAlchemyInvoiceNumberAllocator (despatch_number_allocator.py's shape)
    persistence/invoice_reads.py             find_by_order_reference (fast path) + list (no lock, no write)
    persistence/credit_transactions.py       builds all three adapters on the one session; clears both repositories' events
    persistence/credit_reads.py              G1: the offset clamp (one line)
    outbox/payloads.py                       + InvoiceIssued, PaymentReceived arms; narrow() over BillingEvent
    messaging/subjects.py                    + INVOICE_ISSUE_SUBJECT, INVOICE_LIST_SUBJECT
  presentation/
    invoice_wire.py         decode issue / list (+ the edge checks of BI2 / BI33), encode replies,
                            InvalidInvoiceRequestError
    credit_responder.py     ROUTES gains two entries; docstring names five subjects
    credit_rpc_errors.py    + the invoice rows of section 8.4
  composition.py            registers two handlers; binds SqlAlchemyInvoiceReads into the scope

services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py   G1: the offset clamp (one line)
```

**Layering.** Unchanged from feature 19: `domain` imports only the kernel; `application` imports `otc_cqrs`, the domain and its ports, never `otc_contracts`; only `presentation/invoice_wire.py` maps results to generated wire models; only `infrastructure/outbox/kafka_publisher.py` imports aiokafka. No import-linter contract changes (`otc_billing` is already in `domain-purity`, `fact-producer-confinement`, `layers-billing`, `service-independence`). **No responder rename** (§16.2). **No settings class, no environment variable, no package**: everything is already declared by features 19 – 20 (§11).

## 3. The ported-idiom ledger

One row per idiom: *#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z*, each half cited, the guard named in `tasks.md` where #9 hand-builds the property. **Derived from an enumerated boundary list** (#8 history line 1255: every ported-idiom loss sat at a boundary where a value crosses into or out of the process), written in §3.1 before any row. Rows whose answer is "nothing special, and this is why" are rows: a boundary considered and dismissed is a row; a boundary never listed is the failure mode.

### 3.1 The boundary enumeration

**Inbound decode** — B1 `billing.invoice.issue` bytes → model; B2 `billing.invoice.list` bytes → model (paging defaults); B3 request headers → correlation; B4 `lines[]` → `Quantity` + `Money` (`units` width, `unitPrice` sign); B5 `discount` (optional) → `Money` (sign, ≤ `Σ`); B6 `currency` vs the line's; B7 `orderReference` length vs `varchar(20)`; B8 the `Σ` width.
**Store reads that decide** — B9 the fast-path invoice read (no transaction); B10 the in-transaction invoice re-read after the line lock; B11 the line row, the committed-exposure scalar and the order's entries (`lock_for_order`, reused); B12 the counter row and its seed `MAX`; B13 `invoice_items` → lines (unit price column, order); B14 `invoice_date` / `paid_at` → instants; B15 `status` → `InvoiceState`; B16 `currency_code char(3)`; B17 `order_reference` matching in SQL; B18 the list page and its count; B19 `issuedBeforeMinutes` → a cutoff; B20 the paging offset's width; B21 ids read back (asyncpg's `UUID` subclass).
**Store writes** — B22 `invoices` insert; B23 `invoice_items` insert; B24 the `consume` entry (first live call); B25 `outbox` insert; B26 the counter's seed and advance (textual DML); B27 the `credits` row, never written.
**Outbound encode** — B28 the issue reply (`invoiceId`, `created`, `invoiceDate`); B29 the list reply (`paidAt`); B30 `RpcError` codes → Orders' terminal / transient split; B31 the Kafka publish and its key.
**Process and host** — B32 request concurrency and scope for two more subjects; B33 the transaction, its isolation, and the two-aggregate composition; B34 the one clock read; B35 event-loop affinity; B36 cancellation and exception propagation; B37 `Any` from the drivers; B38 integer division; B39 ids minted per site; B40 the closure of `InvoiceState`.

### 3.2 The ledger

| # | Bnd | Property | #7 relied on | #8 supplied it by | #9 supplies it by | Guard (`tasks.md`) |
|---|---|---|---|---|---|---|
| L1 | B1–B2 | Bare-JSON request and reply | A hand-written bare-JSON NATS (de)serializer (`apps/billing/src/infrastructure/messaging/bare-json-nats.{de,}serializer.ts`) | Nothing new: raw bytes on the existing responder (#8 `design.md` §16 L1) | Nothing new: `Msg.data` / `Msg.respond(bytes)` through `from_wire_json` / `to_wire_json`, two more entries on the same path | G3 (`BI16`) |
| L2 | B1–B2 | Declared keys are the keys read | Generated `@otc/contracts` types the DTO `implements` | Hand-transcribed records + `BI28`'s parse of `asyncapi.yaml` (#8 L2) | Generated `InvoiceIssueRequestPayload` … `InvoiceListReplyPayload`, `InvoiceView` (`packages/contracts/src/otc_contracts/generated/asyncapi.py:486-500, 746-778`), drift-tested; no hand-written payload type | none owed (`BI28` not claimed) |
| L3 | B1, B4–B5, B7–B8 | A malformed request is refused before dispatch, not half-processed | `class-validator` DTOs + the custom `DiscountWithinComputedAmount` constraint (`presentation/dto/invoice.dto.ts:39-41, 58-82, 112-115`) — after `N2` | `InvoiceRequestValidator` (`InvoiceRequestValidator.cs:61-80`), before `SendAsync` | The generated model (patterns, `minItems`, `units ≥ 1`, strict ints) plus `invoice_wire.decode_issue`'s edge checks: `unitPrice ≥ 0`, `discount ≥ 0`, `discount ≤ Σ`, `Σ ≤ 2⁶³ − 1`, `units ≤ 2³¹ − 1`, `orderReference ≤ 20` (`BI2`, `BI33`) | E3 (one case per check, dispatcher called **zero** times); arms in E3 |
| L4 | B3 | A missing or malformed header mutates nothing | `ctx.getHeaders()` in the controller (`presentation/invoice.controller.ts:60-62`) | `RequireMeta` before deserialising (`BillingRpcResponder.cs:267`) | `credit_headers.required_correlation` called first in the `_invoice_issue` route (feature 19's `BC1` shape), each header missing **and** malformed; `billing.invoice.list` needs neither | E5, four arms |
| L5 | B4 | A unit count cannot narrow, and a count the column cannot hold is refused before the transaction | JS numbers; `@Min(1)` | `int` on the wire and in the column, no cast (#8 L6) | Python `int` (no narrowing) — and **unbounded**: `Quantity` has no maximum, `invoice_items.units` is `integer`, and its ORM range guard (`range_guards.py`, `quantity.out_of_range`) would refuse only at row construction, **inside** the transaction after the counter lock — #7's `N2` placement one column over. Refused at the edge (`BI33`) | E3; arm: drop the bound (the reply becomes `DOMAIN_ERROR` from inside the transaction) |
| L6 | B5, B8 | `Σ` and `amount − discount` cannot wrap, and an out-of-range total is a terminal domain error | JS numbers do not wrap below 2⁵³ | `checked` regions in `Invoice.Issue` (`Invoice.cs:143-157`) converting to `InvoiceTotalOverflowError`, and in the validator (`InvoiceRequestValidator.cs:74-80`) | Python `int` never wraps (free). The **code** is hand-built: `Invoice.issue` checks `amount` against `[-(1<<63), (1<<63)-1]` and raises `InvoiceTotalOverflowError` (`invoice.total_overflow`) → `DOMAIN_ERROR`; the edge refuses `Σ > 2⁶³ − 1` first, so the domain check is defence in depth (reachable by a direct-drive unit test) | B5 (`BI25`, direct drive), E3 (edge); arms: delete the domain range check (the test sees `money.invalid_amount` or a bare `int`), delete the edge bound |
| L7 | B6, B16 | Currency codes compare equal iff the same currency | MySQL CI collation; `!==` (`invoice-issue.handler.ts:99`) | `string.Equals(…, Ordinal)` vs a CI column, closed at the edge (#8 L14) | Exact `==` on both sides: `^[A-Z]{3}$` on the wire, `char(3)` holds capitals, PostgreSQL compares exactly. Nothing to normalise | E3 currency pattern; F2 (`BI4`) |
| L8 | B7 | A request value the column cannot hold is terminal, not retried | MySQL strict mode → `INTERNAL_ERROR` → retried | `nvarchar(20)` overflow → `UNAVAILABLE` → retried | `orderReference` > 20 → `VALIDATION_FAILED` at the edge (`BI33`; feature 19's `BC33`, Fulfillment's FS28) | E3; arm: drop the check |
| L9 | B9 | The fast path blocks nobody and opens no transaction | A plain read on the shared handle (`invoice.repository.ts:3`, `findByOrderReference`, handler `:74`) | `AsNoTracking`, no hint (`EfCoreInvoiceRepository.cs:41-56`) | `InvoiceReads.find_by_order_reference`: a short session, pinned `READ COMMITTED`, one plain `SELECT` for the header and one for the lines; no `with_for_update`, no write (Fulfillment's `despatch_of_order`) | C2 (the unit log shows **zero** `run` calls on a hit); D7 forbids `with_for_update` in `invoice_reads.py` (search result) |
| L10 | B10 | The **B7** authority read sees the competitor's committed invoice | `SELECT … FOR UPDATE` on `invoices` (`invoice.repository.ts:56`) under InnoDB `REPEATABLE READ` | `UPDLOCK, HOLDLOCK, ROWLOCK` (`EfCoreInvoiceRepository.cs:71`), explicitly **not** load-bearing (#8 L8) | A plain `SELECT` **after** the line lock is granted, at the pinned `READ COMMITTED`: a new statement takes a fresh snapshot and sees what the line's previous holder committed (feature 19's measured run A; Fulfillment's F8 in-lock re-read). The line lock is the mechanism; the unique constraint the belt | I1 race, three arms: re-read before the lock; drop the line lock; pin `REPEATABLE READ` |
| L11 | B11 | The active-hold predicate reads current, committed rows | `FOR UPDATE` on the order's entries (`buyer-credit.repository.ts:63`) | `UPDLOCK, HOLDLOCK` (#8 L9) | `lock_for_order`, **reused unchanged** (feature 19's `BC35`, `L8`, `L12`, armed there) | inherited `BC35` / `BC9`; I1 re-exercises the path |
| L12 | B11, B24 | A `consume` moves neither term of `availableCredit` | `credit-exposure.ts`'s formula + no consume fact builder | `CreditExposure.Summarise` + three structural absences (#8 L10) | `summarise`'s two-term identity (`BC5`) + **three** structural absences: `BuyerCredit.consume` raises nothing (`buyer_credit.py:386-409`), `payloads.narrow` has no arm for a consume event, `FACT_MODELS` has no `credit.consumed.v1` key (`packages/contracts/src/otc_contracts/facts.py:47-62`) | F3 / F4 whole-table outbox delta of exactly 1, at the repository and through the host; F10 inverted arm (add a spurious row) |
| L13 | B12 | The counter row is seeded once under concurrency and continues past the highest reference | `INSERT … ON DUPLICATE KEY UPDATE` + a numeric `MAX` (`invoice-number-allocator.ts:30, 41`) | `INSERT … SELECT … WHERE NOT EXISTS (… UPDLOCK, HOLDLOCK …)` + `MAX(CAST(SUBSTRING …))` (`EfCoreInvoiceNumberAllocator.cs:39-42`), after #8 id 45 | **Already built**: `SEED_INVOICE_SEQUENCE` (`sequences.py:30-36`, `ON CONFLICT (id) DO NOTHING`, numeric `bigint` `MAX`, the scan skipped once the row exists, backlog 211). The allocator class only executes it | existing `test_billing_counter_seed.py` (five cases, armed in backlog 211) re-run (D6); the allocator's own six (D6) |
| L14 | B12, B26 | A rolled-back invoice burns no number; allocations serialise | `FOR UPDATE` + `UPDATE` in `tx` (`invoice-number-allocator.ts:47`) | `UPDLOCK, ROWLOCK` + increment (#8 §6.4) | `LOCK_INVOICE_SEQUENCE … FOR UPDATE` then `ADVANCE_INVOICE_SEQUENCE` in the caller's session (Fulfillment's `despatch_number_allocator.py` shape), never a PostgreSQL `SEQUENCE` (not transactional, `sequences.py` docstring) | D6: rollback burns none; an uncommitted allocation holds the next back; the allocation belongs to `CreditTransactions.run`'s transaction |
| L15 | B13 | Lines read back in a defined order | Unordered (`invoice.repository.ts:48`, no `orderBy`) | Unordered (`EfCoreInvoiceRepository.cs:51-55`) | **Canonical** `(product_code, line id)`, sorted in Python, never by the database's collation — Fulfillment's `line_order_key` precedent (`despatch_advice.py:35`). The aggregate keeps the **request's** order for the fact it raises at issue; a reload is canonical. No wire output is built from a reload's lines (the issue reply, `InvoiceView` and `payment.received.v1` carry none) | D3 (reload order asserted with lines whose request order is not canonical) |
| L16 | B14 | An instant read back equals the instant written, and `NULL` stays `NULL` | A `mysql2` pool with `timezone: 'Z'` (`infrastructure/persistence/client.ts:26`) | `SpecifyKind(…, Utc)` in both branches (`InvoiceRowMapper.cs:28, 31`) | `timestamptz(3)` + asyncpg's binary decode → aware UTC or `None` (measured, header); the clock port's `wire_instant` truncates to whole milliseconds so `timestamptz(3)`'s rounding cannot move a written value; the mapper neither attaches nor converts a zone | D3 (`BI24`) through the mapper under session `TimeZone = 'Europe/Madrid'`, null and non-null; arms: the mapper drops `tzinfo`; the mapper maps `None` to `invoice_date` |
| L17 | B15 | The status token is a closed set, parsed loudly; `paid_at` exists iff `paid` | A TS union (`domain/invoice.ts:57`) + `Reconstitute`'s two checks (`:161-165`) | `InvoiceStatuses.Parse` throws; `Reconstitute` refuses (#8 L5, `BI10`) | `parse_invoice_state(token, paid_at)` in `invoice_state.py`: `type(token) is str`, a literal `dict` lookup, then the pairing — `issued` + `None` → `Issued()`, `paid` + aware instant → `Paid(…)`, anything else → `UnknownInvoiceStatusError` or `InvalidInvoiceSnapshotError`. The mapper calls it, so **a disagreeing row cannot even become a snapshot** | B3 (`BI27`), D3 (`BI10` store half); arms: `token.strip().lower()`; return `Issued()` for a `paid` row with `NULL` |
| L18 | B17 | In-SQL matching of `order_reference` agrees with the domain's | JS `===` vs MySQL CI (latent) | `OrderNumber.Parse` + an uppercase-only alphabet (#8 L15) | PostgreSQL's deterministic collation is case-sensitive (measured in feature 19 and again here for `status`); `order_reference` stays a `str`, never kernel-parsed (feature 17's L23 / FS28, feature 19 §5.2). Nothing to normalise | F6 (`BI9` repeat by exact reference) |
| L19 | B18 | The list blocks nobody and mutates nothing | MySQL consistent read | `AsNoTracking`, no hint (#8 L12) | Plain `SELECT`s in a short session pinned `READ COMMITTED`, no `with_for_update`, no write | G1 re-reads a row afterwards; D7 (search result) |
| L20 | B19 | `issuedBeforeMinutes` filters against a clock a test controls | The handler passes `now` (`invoice-read.repository.ts:20, 37-38`) | `ListAsync(query, now, ct)` (#8 L28) | `ListInvoicesHandler` reads `scope.clock.now()` once and passes `now` to `InvoiceReads.list`; the cutoff is `now - timedelta(minutes=m)`, inclusive. **Python-specific**: a cutoff before year 1 raises `OverflowError` (measured) — **G1** | D5 (fixed `now`; arm: the adapter reads `datetime.now(UTC)`); G1 / G4 (`BI37`) |
| L21 | B20 | A page past the end is a page, not a crash | JS numbers (`offset((page - 1) * pageSize)`, `:50`) | `int` paging, unchecked (`EfCoreInvoiceReadRepository.cs:55`) | **Python-specific**: `(page − 1) × page_size` is exact and unbounded, and asyncpg refuses an offset ≥ 2⁶³ with SQLSTATE `22000` (measured) → `INTERNAL_ERROR`. **G1**: clamp the offset to `2⁶³ − 1`, which PostgreSQL answers with `[]` (measured), on all three list readers | G4, G6 (`BI37`), one case per list subject; arm: remove the clamp in each |
| L22 | B21 | An id read back is the domain's `UniqueId` | Strings | `Guid` | asyncpg returns its own `UUID` subclass, which `UniqueId`'s `type(...) is uuid.UUID` refuses (feature 19's `credit_mapper._unique_id`); `invoice_mapper` rebuilds `UUID(int=value.int)` | F6 (`BI9`'s repeat reads the stored row back and replies its `invoiceId`) |
| L23 | B22–B23 | Rows are written once; no upsert anywhere on this path | Drizzle inserts (`invoice.repository.ts`) | `Add` only, no `MERGE` (#8 L17) | `invoice_mapper` constructs `Invoice` and `InvoiceItem` rows (the range guard fires on `units` and `price` at assignment); the repository `session.add`s them, header first and flushed (the lines' FK), then lines, then the outbox. No `update(`, `delete(`, `on_conflict_*` | D7 (search result), D8 (write-path population) |
| L24 | B24 | The first live `consume` writes exactly the order's active hold | `consumeHold` (`invoice-issue.handler.ts:135`) | `credit.Consume(...)` (`InvoiceIssueService.cs:93`) | `credit.consume(order_reference, credit_context, new_id)`, called **before** the allocator so `NoActiveHoldError` never reaches the counter (§6.2); the entry is `Money(order.active_hold, line currency)`, its date the one clock read | F4 (exactly one `consume` row of the hold amount); C4 order log |
| L25 | B25 | Facts are stored in raise order, one serializer | `AUTO_INCREMENT` + `JSON.stringify` | Per-row awaited insert (#8 L16) | Feature 19's writer copy, **unchanged** (one `flush()` per row, `to_wire_json`, `json` column). This transaction writes exactly one outbox row; feature 22 writes two and is the first to exercise the order | the parity guard (unchanged); F4 |
| L26 | B26 | The counter's textual DML is the **only** textual DML in Billing and is classified | n/a (the ORM) | n/a | `invoice_number_allocator.py` executes `sequences.py`'s three statements through `text()`, bypassing the ORM range guard on `next_value` (the residual `range_guards.py` and `sequences.py` already name; the engine refuses an overflow). Feature 19's "no `text(` DML in this service" (`specs/billing_credit/tasks.md` preamble; `credit_repository.py:19`'s docstring) is narrowed here to *"none outside the counter allocator"* — the docstring is reworded in the same pass (D1) — and the population test classifies the three hits | D8 (counts read from `scan_service("billing")`); arm: a second `execute(text(…))` in the repository |
| L27 | B27 | The `credits` row is never written | `save` inserts entries only | Unchanged (#8 L29) | Unchanged: `credit_repository.save` adds `CreditItem` rows only | D7 (search result); F3 (the line row's `updated_at` unmoved) |
| L28 | B28 | The issue reply carries the invoice's identity on every outcome | `invoiceId` in both builders (`invoice-issue.handler.ts:19-41`) | Not sent (`BuildReply` passes no id; the record defaults to `null`, omitted) although #8's `BI9` text names it | Sent on every reply, `created` true or false (`BI9` note); `invoiceDate` through `format_instant` | E4 (both outcomes); arm: build the repeat's reply without `invoice_id` |
| L29 | B29 | An `issued` view's `paidAt` | `null` (`invoice-read.repository.ts:66`) | Omitted (`WhenWritingNull`, #8 L19 / `BI28`) | `null`, by #9's ratified wire rule (`wire.py` docstring; `generated/nullable.py`: `InvoiceView.paidAt`) — #7's bytes (`BI32`) | E4 (exact key set and value for both states, read from `to_wire_json` bytes); arm: map an issued view's `paid_at` to its `invoice_date` |
| L30 | B30 | A transient failure stays retryable; a business "no" stops the row | #7's orchestrator retried every code and parked | Closed mapping; `PRECONDITION_FAILED` terminal (#8 L21, `BI26`) | §8.4's table; `TERMINAL_RPC_ERROR_CODES` imported from Orders by the test, never retyped | E6 (`BI26`, the extended retryability guard) |
| L31 | B31 | Every fact lands on its order's partition | The relay's `correlationId` key | The same (#8 L22) | The relay copy, unchanged; `BI2` refuses a header-less issue, so the key is never arbitrary | F5 (the key read back from the broker) |
| L32 | B32 | Two more subjects get the bound, the per-request scope and the drain | Nest's per-request promise and a second `@Controller` | The renamed single responder (#8 L24 – L25, gate row 1) | Two `ROUTES` entries on the one `CreditResponder` task (feature 18's precedent); the `Semaphore`, `scope_factory()` per request and `_drain(return_exceptions=True)` already cover every entry (`credit_responder.py:109, 167-201`) | E2 (route table == five subjects); inherited `BC21` / `BC22` re-run unchanged (L1) |
| L33 | B33 | Two aggregates' writes share one transaction, visibly | An explicit `TransactionContext` passed to both repositories (`invoice-issue.handler.ts:138-139`) | The ambient scoped `DbContext` + `ValidateScopes` (#8 L20) | **The explicit object again**: `work(tx)` receives one `CreditTransaction` whose `credits`, `invoices`, `invoice_numbers` are built by `run()` on **one** `AsyncSession` (`credit_transactions.py:76-79`, extended). The signature shows the sharing, as in #7 | F3 (`BI7`) forced rollback after both saves; arm: build the invoice repository on a second session |
| L34 | B33 | One transaction per attempt at a stated isolation; events forgotten only after commit | Drizzle's callback; InnoDB `REPEATABLE READ` | `IsolationLevel.ReadCommitted` (#8 L26) | `run()` pins `READ COMMITTED` before the first statement (`:77`) and, extended, clears **both** repositories' saved events after the commit returns | D2 (unit: a commit that raises leaves both aggregates' events in place); arm: clear the invoice's events before commit |
| L35 | B34 | The invoice date, the fact's `occurredAt` and the `consume` entry's date are one instant | `this.clock.now()` once (`invoice-issue.handler.ts:113`) | `clock.UtcNow` once (`InvoiceIssueService.cs:77`) | `scope.clock.now()` read once in `invoice_issue.issue`, before `run()`; `InvoiceContext` and `CreditContext` built from it | B8 (`BI13`), C3 (a clock fake that returns a different instant per call: all three equal the first) |
| L36 | B35 | Engines, clients and producers belong to the lifespan's loop | One Node loop | Thread pool | Nothing new is created: the issue and list paths use the session factory and NATS client `start_runtime` already owns | F1's host fixture; `PytestUnraisableExceptionWarning` is an error |
| L37 | B36 | Cancellation is never swallowed; a failure is an `RpcError`, a failure to reply is logged | Promises | `OperationCanceledException` excluded | Unchanged responder: `except Exception` only (`credit_responder.py:172-198`); no new `except` anywhere except the `OverflowError` of G1, which is caught at the one statement that raises it (in `invoice_reads.list`, not in the issue path) | inherited `BC22` cancellation case; G4 |
| L38 | B37 | `Any` does not leak from untyped clients | TS types | C# types | Rows through SQLAlchemy's typed `Mapped[...]`; no `func.sum` anywhere on this path (totals are computed in Python from the lines, so the `numeric` → `Decimal` hazard of feature 19's L9 does not arise); `func.count()` is `int` (measured). `mypy --strict` | quality.sh |
| L39 | B38 | Integer division | n/a | n/a | None: `+`, `-`, `*` only; the offset `(page - 1) * page_size`; `timedelta(minutes=m)` | quality.sh (money guard walks `otc_billing.domain`) |
| L40 | B39 | Every id is the one supplied | Minted in the domain (`domain/invoice.ts:102`) | `newId` for lines and events (`Invoice.cs:136, 180, 339`); the invoice id minted in the service | `new_id: Callable[[], UniqueId]` a required parameter of `Invoice.issue` and `mark_paid`, used for the invoice id, each line id and each event id; the unit passes `scope.ids.new` to both aggregates (`BI34`) | B6 (one arm per site), C5 (the application seam) |
| L41 | B40 | No third state, no `paid` without its instant | TS structural union — no zero value (`domain/invoice.ts:57`) | Closed abstract hierarchy, `private protected` base constructor (`InvoiceState.cs:56`) — because `default(T)` of a struct satisfies neither case | `type InvoiceState = Issued \| Paid` over two frozen slotted dataclasses whose `__init_subclass__` raises `TypeError` (armed by B2d); **Ruling (review §4.7): the maintainer is told; the census allow-list is not extended** (mypy accepts a subclass declaration but class creation raises; exhaustiveness does not depend on `final`). Every `match` ends in `assert_never`, so a third case is a `mypy --strict` error at every site; `Paid.__post_init__` refuses a non-`datetime` or naive value — the runtime counterpart of #8's `default(T)` is a `None` that slipped past the type checker (e.g. from an untyped row), and it is refused, not stored | B2 (`BI23`): the alias's members are exactly the two classes; a `mypy` run over a fixture `match` that omits `Paid` fails; arms: add a third alias member; drop the `__post_init__` check |

**Python porting questions answered** (CLAUDE.md): integer division — L39; JSON serialisation — L1, L25, L28, L29; event-loop affinity — L36; task cancellation and exception propagation — L32, L37; typing gaps — L22, L38, L41; numeric width — L5, L6, L21; case sensitivity — L7, L17, L18; transaction and isolation defaults — L10, L34; connection and concurrency — L32; single-statement atomicity — L13, L23 (no upsert outside the counter seed); ordering — L15, L25; serialisation shape — L28, L29.

**Rows the enumeration produced that recollection would not have:** L5 (an `integer` column behind an unbounded wire count, refused only inside the transaction), L15 (line order on a reload: both predecessors left it undefined), L20 and L21 (two Python-only overflows, gate point G1), L22 (asyncpg's `UUID` subclass on a new mapper), L26 (the first textual DML in Billing, which feature 19's rule forbade without scope).

## 4. Port the guards too

#8's tests of this mechanism, enumerated by file (`ls ../order-to-cash-dotnet/tests/Billing.UnitTests ../order-to-cash-dotnet/tests/Billing.IntegrationTests | grep -i "invoice\|Consumes\|SubjectCoverage\|CentsRule\|ErrorMapper\|Payment"`: 25 hits), classified. `Payment*` files are feature 22's.

| #8 test | #9 |
|---|---|
| `InvoiceTests` (R45 / R46 halves, `BI10`, `BI11`, `BI14`, `BI25`) | **Ported** (`unit/domain/test_invoice.py`), with #8's review `D1` closed from the start (every `PaymentReceived` field asserted and corrupted) |
| `InvoiceStateTests` (`BI23` reflection, `BI27`) | **Ported by property, not mechanism** (`unit/domain/test_invoice_state.py`): the alias's members, the `assert_never` check by `mypy` over a fixture, the `__post_init__` refusal, the closed token parse |
| `InvoiceFactTests` (`BI13` provenance) | **Ported** (`unit/domain/test_invoice_facts.py`), plus `test_invoice_ids.py` per site (`BI34`) |
| `InvoiceIssueServiceTests` (`BI5` unit, fast path, three-lock order, reply after commit) | **Ported** (`unit/test_invoice_issue_service.py`), the log covering the **three** calls (#7 `N4`) and asserting **zero** saves on both repositories on `BI5` (#7 `N3`) |
| `InvoiceResponderValidationTests` (`BI2` entry observation, `BI25` validator half) | **Ported** (`unit/test_invoice_requests.py`): one case per schema constraint and per edge check, dispatcher called zero times; the "checked region" half has no Python counterpart and becomes `BI33`'s `Σ` bound |
| `InvoiceSubjectsTests` | **Ported** by extending `unit/test_credit_subjects.py` |
| `InvoiceRpcPayloadTests` (`BI28`) | **Not ported, avoided by construction** (generated models); its key-set half becomes `BI32`'s reply bytes case (`unit/test_invoice_wire.py`) |
| `InvoiceNumberAllocatorTests` (unit formatting) | **Not applicable**: formatting is `InvoiceReference.from_sequence`, the kernel's, tested by `packages/shared_kernel/tests/test_business_reference.py` |
| `BillingConsumesNoFactsTests` (`BI1`) | **Ported by existing instruments**: `test_kafka_client_confinement.py` and the host task-set case (feature 19); armed here |
| `BillingResponderSubjectCoverageTests` (`BI31`) | **Ported** (`test_credit_subjects.py`: the route table equals the five subjects) |
| `CentsRuleFixtureGuard(Tests)` (`BI17`) | **Not ported**: feature 19's request helper already checks the body as sent (`requirements.md` §2.3) |
| `BillingErrorMapperTests`, `BillingErrorMapperMoneyTextTests` | **Ported** into `unit/test_credit_rpc_errors.py` (one case per §8.4 row, `details` asserted; `BI36`) and the retryability guard (`BI26`) |
| `InvoiceIssueTests` (R45 integration, `BI2` – `BI6`, `BI9`) | **Ported** (`integration/test_invoice_issue.py`), with #8's `D2` closed from the start: **non-zero** discount, three distinct totals (`BI38`) |
| `InvoiceIssueRaceTests` | **Ported as a constructed race** (held line lock + `wait_for_lock_waiters`, feature 19's I1 shape), not ten repetitions |
| `InvoiceListTests`, `InvoiceReadRepositoryTests` | **Ported** (`integration/test_invoice_list.py`, `integration/test_invoice_reads.py`) |
| `InvoiceWireTests` | **Ported** (`integration/test_invoice_wire.py`) |
| `InvoiceRepositoryTests` (`BI7`, `BI10` store, `BI24`) | **Ported** (`integration/test_invoice_repository.py`) |
| `InvoiceNumberAllocatorTests` (integration, `BI12`, `BI29`) | `BI29` **already ported** by backlog 211 (`test_billing_counter_seed.py`); the allocator half **ported from Fulfillment's** six (`integration/test_invoice_number_allocator.py`) |
| `tests/Orders.UnitTests/SagaCommandPayloadTests` (`BI21`) | **Already present** in Orders (feature 16) and stronger than #8's; armed, not edited |

## 5. The domain

### 5.1 `Invoice` — the aggregate root

```text
InvoiceContext(occurred_at: datetime, causation_id: UniqueId)      # frozen; clock port + x-request-id
InvoiceLine(line_id: UniqueId, product_code: str, units: Quantity, unit_price: Money)   # frozen; line_total property
IssueInvoiceInput(invoice_reference: InvoiceReference, order_reference: str, retailer_code: str,
                  company_code: str, currency: str, lines: tuple[IssueLineInput, ...],
                  discount: Money, correlation_id: UniqueId)        # IssueLineInput(product_code, units: Quantity, unit_price: Money)
PaymentInput(payment_reference: str, amount: Money, value_date: datetime, source: PaymentSource,
             correlation_id: UniqueId)

class Invoice(AggregateRoot):
    issue(input, context, new_id) -> Invoice          # classmethod: the ONLY way an invoice comes into being
    rehydrate(snapshot) -> Invoice                    # classmethod: refuses B6 disagreements (section 5.4)
    invoice_reference, invoice_date, order_reference, retailer_code, company_code, currency
    lines: tuple[InvoiceLine, ...]
    amount, discount, total_amount: Money             # read-only properties, derived at issue
    state: InvoiceState                               # ONE attribute; status / paid_at are projections
    status -> InvoiceStatus; paid_at -> datetime | None
    mark_paid(payment, context, new_id) -> PaymentReceived
    to_snapshot() -> InvoiceSnapshot
```

`issue` mints the invoice id with `new_id()` first, then one id per line in the request's order, derives the totals (§5.4), refuses every **B6** violation, and raises exactly one `InvoiceIssued` (its `event_id` from `new_id()`) **before returning**, so a caller can never hold an `Invoice` whose fact was not recorded (feature 18's `despatch_order` precedent). `invoice_date = context.occurred_at`. There is no `cancel`, no `void`, no credit note: `domain-model.md` §5.3 gives the invoice one edge.

### 5.2 `InvoiceState` — the closed pair (`BI10`, `BI23`, `BI27`)

```text
@dataclass(frozen=True, slots=True) class Issued: pass  # __init_subclass__ raises TypeError
@dataclass(frozen=True, slots=True) class Paid:  # __init_subclass__ raises TypeError
    paid_at: datetime                 # __post_init__: type(...) is datetime and utcoffset() is not None, else InvalidInvoiceStateError
type InvoiceState = Issued | Paid

class InvoiceStatus(enum.Enum): ISSUED = "issued"; PAID = "paid"
state_token(state) -> InvoiceStatus                 # match ... case Issued() / case Paid() / case _: assert_never(state)
parse_invoice_state(token: object, paid_at: object) -> InvoiceState   # the store's two columns -> one value
```

- `Paid` cannot be built without an aware instant; `Issued` has nothing to set. `mark_paid` assigns `self._state = Paid(context.occurred_at)` in **one** statement; nothing else assigns `_state` after `issue` / `rehydrate`.
- **Closure.** Python has no sealed classes. The property #7 got from a structural union and #8 built with an inaccessible constructor is built here from the type checker: the `type` alias names exactly two classes that refuse a subclass at runtime (`__init_subclass__` raises `TypeError`, armed by B2d; `typing.final` would need an entry in the decorator census and gives no runtime refusal), and every consumer (`state_token`, the mapper, `mark_paid`) matches with `assert_never` on the fall-through, so adding a third member makes `mypy --strict` fail at each site. The runtime half is the structural test that the alias's `__value__` arguments are exactly `(Issued, Paid)`.
- **The zero-value question, asked of Python.** #8 rejected a `struct` because `default(T)` is always constructible. Python's counterpart is a `None` reaching a field typed `datetime` past the type checker — an `Any` from a driver row, a `cast`. `Paid.__post_init__` refuses it, so the hole is a raise, not a state (ledger L41).
- **The store side** is the remaining hole, as in #7 and #8: `status` and `paid_at` are two columns. `parse_invoice_state` is the only function that combines them, the mapper is its only caller, and it refuses a disagreeing pair outright (`InvalidInvoiceSnapshotError`, naming the invoice), so a `paid` row with `NULL` `paid_at` cannot become a snapshot, let alone an aggregate. The outbound direction cannot disagree, because both columns are derived from `state` by `state_token` and `paid_at`.

### 5.3 `InvoiceLine`

A frozen value (`line_id`, `product_code: str`, `units: Quantity`, `unit_price: Money`) with `line_total = unit_price.multiply(units)` — the only arithmetic on a line. Named `InvoiceLine` after `domain-model.md` §5.2; the table is `invoice_items` and its row `InvoiceItem`; `invoice_mapper` is the one place the two vocabularies meet (feature 19's `CreditItem` / `CreditLedgerEntry` split).

### 5.4 Totals — derived, never assigned (**B6**)

```text
amount       = Σ (unit_price.amount × units.value)      # Python int, exact; one currency
total_amount = amount − discount
```

Computed in `issue` as plain `int`s over the lines, then checked: `amount` and `total_amount` within `[-(1 << 63), (1 << 63) - 1]` else `InvoiceTotalOverflowError` (`BI25`); every line's `unit_price.currency` equals the invoice currency else `InvoiceLineCurrencyMismatchError`; `discount.currency` likewise; `lines` non-empty else `EmptyInvoiceLinesError`; `total_amount ≥ 0` else `NegativeInvoiceTotalError`. Only then are `Money` values built and assigned. No setter exists for any of the three. `rehydrate` recomputes `amount` and `total_amount` from the snapshot's lines and discount and refuses a snapshot whose stored totals disagree (`InvalidInvoiceSnapshotError`). The seed's five invoices satisfy this (§1). A zero total is legal (`BI35`).

### 5.5 `mark_paid` — feature 22's seam, delivered uncalled (`R46`, `BI14`)

`mark_paid(payment, context, new_id) -> PaymentReceived`: `Paid` already → `InvoiceAlreadyPaidError`; `payment.amount.currency != currency` → `InvoicePaymentCurrencyMismatchError`; `payment.amount.amount != total_amount.amount` → `InvoicePaymentAmountMismatchError` (B10, partial payment out of scope); each refusal changes nothing and raises nothing. Otherwise one assignment `self._state = Paid(context.occurred_at)` and exactly one `PaymentReceived` raised and **returned** (#8 id 57's seam: feature 22 makes `credit.released.v1`'s `causationId` its `event_id`; #7 `invoice.ts:284-311`). `paymentReference` uniqueness and the `payments` row are feature 22's (**B10**'s other half).

### 5.6 Facts and errors

`domain/invoice_events.py`, Fulfillment's and feature 19's shape: frozen, slotted, keyword-only dataclasses with `event_id`, `aggregate_id` (the **invoice's** id — `domain-model.md` §7.2 names `Invoice` as the producer of facts 10 and 11), `correlation_id` (the order id), `causation_id`, `occurred_at`, and `EVENT_TYPE` constants `invoice.issued.v1` / `payment.received.v1`. `InvoiceIssued` carries `order_reference`, `invoice_reference`, `invoice_date`, `retailer_code`, `company_code`, `currency`, `lines` (a tuple of `(product_code, units, unit_price)` in the request's order), `amount`, `discount`, `total_amount` — domain types only. `PaymentReceived` carries `order_reference`, `invoice_reference`, `payment_reference`, `amount`, `currency`, `value_date`, `source`. `type InvoiceEvent = InvoiceIssued | PaymentReceived`.

`domain/invoice_errors.py` — dotted lower-case codes (Orders' and feature 19's convention), every amount in a message through `format_money` (`BI36`): `EmptyInvoiceLinesError` (`invoice.empty_lines`), `InvoiceLineCurrencyMismatchError` (`invoice.line_currency_mismatch`), `NegativeInvoiceTotalError` (`invoice.negative_total`, names two amounts), `InvoiceTotalOverflowError` (`invoice.total_overflow`), `InvalidInvoiceSnapshotError` (`invoice.invalid_snapshot`), `InvalidInvoiceStateError` (`invoice_state.invalid_paid_at`), `UnknownInvoiceStatusError` (`invoice_status.unknown`), `InvoiceAlreadyPaidError` (`invoice.already_paid`), `InvoicePaymentAmountMismatchError` (`invoice.payment_amount_mismatch`, names two amounts), `InvoicePaymentCurrencyMismatchError` (`invoice.payment_currency_mismatch`). Application: `InvoiceCurrencyMismatchError(expected, received)` (`invoice.currency_mismatch`) in `application/errors.py`. `NoActiveHoldError` and `CreditLineNotFoundError` are **reused** (feature 19), not re-declared.

### 5.7 Invariants → enforced → proven

| Invariant | Enforced by | Proven by |
|---|---|---|
| **B6** | `issue` derives and checks; `rehydrate` refuses a disagreeing snapshot; no setter; the edge refuses `discount > Σ` | `R45` domain, `BI11`, `BI25`, `BI38` |
| **B7** | the fast path; the in-transaction re-read after the line lock; the unique constraint | `BI9`, `BI8` race |
| **B8** | `mark_paid` is the only transition; a `Paid` invoice refuses it | `R46` domain, `BI14` |
| **B9** | one `state` attribute; `Paid` requires its instant; `parse_invoice_state` refuses a disagreeing row | `BI10`, `BI23`, `BI24` |
| **B10** (amount half) | `mark_paid` refuses a mismatched amount or currency | `BI14` (the `paymentReference` half is feature 22's) |

## 6. The issue transaction, the locks, and the two-aggregate deviation

### 6.1 The fast path (no transaction)

`invoice_issue.issue(command, scope)` first calls `scope.invoice_reads.find_by_order_reference(command.order_reference)`: a short session, pinned `READ COMMITTED`, two plain `SELECT`s, no lock. A hit returns `InvoiceIssueResult(created=False, …)` from the stored row (its current `status`, `paid` included) without opening a transaction — the sweeper's retries make repeats routine (`saga.md` §6 layer 3). #7 (`invoice-issue.handler.ts:74`), #8 (`InvoiceIssueService.cs:37`) and Fulfillment's `despatch_creation.create` all do this.

### 6.2 Inside one `CreditTransactions.run(work)` attempt

```text
0. run() pins READ COMMITTED on the session's connection before any statement            (feature 19, BC35)
1. tx.credits.lock_for_order(retailer, company, order_ref)                               -- THE FIRST LOCK (BI8)
     credits row FOR UPDATE; then the committed-exposure scalar; then the order's entries
   None -> CreditLineNotFoundError -> NOT_FOUND (BI3); nothing written, no fact
2. tx.invoices.find_by_order_reference(order_ref)                                         -- the B7 authority, NO lock
   hit  -> InvoiceIssueResult(created=False, stored values); nothing written; commit of nothing (BI9)
3. command.currency != credit.currency -> InvoiceCurrencyMismatchError -> VALIDATION_FAILED (BI4)
4. credit.consume(order_ref, credit_context, new_id)                                      -- in memory
   no active hold -> NoActiveHoldError -> PRECONDITION_FAILED (BI5); the counter is never touched
5. tx.invoice_numbers.next_reference()                                                    -- THE LAST LOCK (BI8)
     seed (one atomic statement), counter row FOR UPDATE, advance
6. Invoice.issue(input, invoice_context, new_id)        -> raises exactly one InvoiceIssued
7. tx.invoices.save(invoice)   -> INSERT invoices (flush) + INSERT invoice_items + ONE outbox row
   tx.credits.save(credit)     -> INSERT one credit_items row (consume); drains an EMPTY event list
8. COMMIT; then both repositories forget their events; then the result is returned (reply after commit)
```

- **One clock read** (`BI13`, L35): `now = scope.clock.now()` in `issue`, before `run`; `invoice_context = InvoiceContext(occurred_at=now, causation_id=command.request_id)` and `credit_context = CreditContext(occurred_at=now, causation_id=command.request_id)`. The invoice date, the fact's `occurredAt` and the `consume` entry's date are one instant.
- **Why `consume` before the allocator.** #7 and #8 checked `activeHold` with a separate read and then consumed after `Invoice.issue`. In #9 `consume` is itself the check (`BC12`'s structural predicate, G1 of feature 19, which a separate amount check would contradict for a zero hold), and calling it before step 5 means a `NO_ACTIVE_HOLD` request never locks the service's hottest row. Its effect is in memory only until step 7, and any later failure rolls the transaction back.
- **Why the line is locked first.** Two concurrent issues for one order serialise on the `credits` row; the loser waits at step 1, and when the winner commits, the loser's step 2 is a **new statement** whose fresh `READ COMMITTED` snapshot sees the winner's invoice, so it answers `created: false`. Re-reading before the lock, dropping the lock, or pinning `REPEATABLE READ` each let the loser fail instead of answering `created: false`. **Measured outcomes** (review `progress/review_billing_invoicing.md` F6-repro row; the implementer's I1 rows in `progress/impl_billing_invoicing.md`): the F6 arm (no fast path, no re-read) answers `PRECONDITION_FAILED` (`credit.no_active_hold`), because `consume` precedes the insert; the I1 arms answer `PRECONDITION_FAILED`, `INTERNAL_ERROR` (`23505` from the `invoices.order_reference` unique constraint) or `UNAVAILABLE` (`40001`: under `REPEATABLE READ` the loser fails on the **counter** row the winner updated, which the line lock does not protect). Every outcome is safe (terminal on a consumed hold, or transient and then the fast path answers). The race test asserts **one `created: true` and one `created: false`**, so all three arms fail it (I1).
- **Why the allocator is last.** The counter row is a global hot spot: taken last, it is held briefly and can never be the first edge of a cycle. With step 2 taking no lock, the issue path's lock order is *credits row → counter row*; feature 22's path is *credits row → invoices row (its update)*; no transaction takes the counter before a `credits` row, and none takes an `invoices` row before one, so no cycle can form (`BI8`). The `credit.hold` / `.release` paths lock one row each.
- **The unique constraint is the belt to those braces**: unreachable in normal operation; if a future change removes the line lock, a silent double invoice becomes a loud error.

### 6.3 Statement order within step 7

`invoices.save` adds the header and **flushes** it (the lines' foreign key needs it — the despatch repository's shape), adds the lines, flushes, then writes the outbox row through the writer (which flushes per row). `credits.save` then adds the `consume` row. Statement order between the two aggregates does not matter (no foreign key between `credit_items` and `invoices`), and outbox `seq` order is not exercised: this transaction writes **one** outbox row. Feature 22 writes two (`payment.received.v1` then `credit.released.v1`, `R47`) and inherits the writer's per-row flush (§15.1).

### 6.4 `CreditTransactions.run`, extended

`SqlAlchemyCreditTransactions.__init__` gains `invoice_repository_factory` (default `SqlAlchemyInvoiceRepository`) and `allocator_factory` (default `SqlAlchemyInvoiceNumberAllocator`), keyword-only with defaults, so feature 19's existing construction sites and `unit/test_credit_transactions.py`'s fake factory are untouched. Inside the one `async with self._sessions() as session, session.begin():` it builds all three on `session` and hands `work` one `SqlAlchemyCreditTransaction(credits, invoices, invoice_numbers)`. After the block (the commit returned) it calls `clear_saved_events()` on **both** repositories. The transient mapping is unchanged; a `23505` is not transient and propagates to `INTERNAL_ERROR` (Fulfillment's F8 precedent).

### 6.5 The two-aggregate deviation, re-derived against #9's code

`domain-model.md` §8 rule 6: *"one transaction mutates exactly one aggregate instance plus its outbox records"*. This transaction mutates an `Invoice` and a `BuyerCredit`. #7's and #8's gates approved the deviation; that is not evidence about #9, so the argument is rebuilt from this repository.

| Alternative | Why not, in #9 |
|---|---|
| Invoice first, `consume` in a second transaction | A crash between them leaves an issued invoice over an active hold, and nothing can detect it: `consume` raises no event (`buyer_credit.py:386-409`), `payloads.narrow` has no consume arm, and `FACT_MODELS` has no `credit.consumed.v1` key, so the writer would refuse to store one even if raised (`UndeclaredFactError`, `writer.py`) |
| `consume` first, invoice in a second transaction | Worse: the hold is converted for an invoice that may never exist, and every retry then hits `NoActiveHoldError` — **terminal** in Orders (`PRECONDITION_FAILED`), so the saga stops on the first retry |
| `consume` emits a fact that drives the invoice | A fourteenth fact, a Billing Kafka consumer `saga.md` §5 forbids and `BI1` guards against, and a trilogy-wide contract change |
| Merge the invoice and the credit ledger into one aggregate | Collapses two independent lifecycles (an invoice per order; a credit line per party pair, outliving every order) and makes the line a write hot spot for every invoice |
| **One transaction, two aggregates, one lock order** | **Chosen** |

**What makes it cheaper in #9:** (1) the transaction object is explicit, as in #7 — `work(tx)` receives one `CreditTransaction` whose three adapters `run()` built on one session, so the sharing is in the signature (ledger L33), where #8 had to replace that visibility with a container rule; (2) the composition already exists in this codebase: Fulfillment's `despatch_creation._despatch_work` saves the stock rows and the despatch advice in one `run()` (feature 18, approved); (3) `READ COMMITTED` is pinned per transaction, not inherited (`credit_transactions.py:77`). **What it costs:** nothing structural forces a future caller to use one `run()` — that is guarded behaviourally by `BI7`'s forced rollback (F3), armed by building the invoice repository on a second session. The invariant is one no single aggregate owns — *an issued invoice's hold is consumed* — as feature 17's **F3** was for Fulfillment; the deviation is justified by an invariant, never by convenience. `invoice_issue.py`'s module docstring cites rule 6, states the deviation and names the invariant.

## 7. The application layer

### 7.1 Messages, handlers, registration

| Subject | Message (`otc_cqrs`) | Result | Handler → unit |
|---|---|---|---|
| `billing.invoice.issue` | `IssueInvoiceCommand(Command[InvoiceIssueResult])`: `order_reference`, `retailer_code`, `company_code`, `currency`, `lines: tuple[IssueLine, ...]` (`product_code`, `units: int`, `unit_price: int`), `discount: int` (0 when absent), `correlation_id`, `request_id` | `InvoiceIssueResult(created: bool, invoice: InvoiceSummary)`; `InvoiceSummary(invoice_id, invoice_reference, invoice_date, order_reference, currency, total_amount: int, status: InvoiceStatus)` | `IssueInvoiceHandler` → `invoice_issue.issue` |
| `billing.invoice.list` | `ListInvoicesQuery(Query[InvoicePage])`: `page`, `page_size`, `status: InvoiceStatus \| None`, `retailer_code`, `company_code`, `order_reference`, `issued_before_minutes: int \| None` | `InvoicePage(items: tuple[InvoiceViewData, ...], page, page_size, total)` | `ListInvoicesHandler`: `now = scope.clock.now()` once, then `scope.invoice_reads.list(..., now=now)` |

`composition.register_handlers` gains two plain statements; `build_dispatcher` validates against `otc_billing.application`, so a message with zero or two handlers fails the boot; `start_runtime` builds every registered factory once. No events, no `EventHandler`.

### 7.2 Ports and scope

`application/ports/invoice_store.py`:

```text
InvoiceRepository.find_by_order_reference(order_reference) -> InvoiceSnapshot | None   # in-transaction, NO lock
InvoiceRepository.save(invoice) -> None        # header + lines + drained events, all in this transaction; never an UPDATE
InvoiceNumberAllocator.next_reference() -> InvoiceReference                            # in the caller's transaction
InvoiceReads.find_by_order_reference(order_reference) -> InvoiceSnapshot | None        # fast path: own short session
InvoiceReads.list(*, page, page_size, status, retailer_code, company_code, order_reference,
                  issued_before_minutes, now) -> InvoicePage
```

`CreditTransaction` (`ports/credit_store.py`) gains the properties `invoices: InvoiceRepository` and `invoice_numbers: InvoiceNumberAllocator` (feature 19's hand-over, `specs/billing_credit/design.md` §6.4). `BillingScope` gains `invoice_reads: InvoiceReads`; `__post_init__` already refuses an unbound field (`MissingBindingError`). The three test files that construct a `BillingScope` (`unit/test_credit_hold_service.py`, `unit/test_credit_release_service.py`, `integration/test_credit_repository.py`) gain the keyword argument and **no assertion change**.

### 7.3 The issue unit

`invoice_issue.issue(command, scope)` = §6.1 then `scope.transactions.run(partial(_issue_work, command=…, invoice_context=…, credit_context=…, new_id=scope.ids.new))`; `_issue_work(tx, …)` is §6.2 steps 1 – 7, touching only `tx` and its own arguments. The `Invoice` input is built from the command: `Quantity(units)`, `Money(unit_price, currency)`, `Money(discount, currency)`, `InvoiceReference` from the allocator; the party codes from the resolved line (`credit.retailer_code`, `credit.company_code`, equal to the request's by exact match — `BC28`'s rule); the currency from the line (equal to the request's after step 3).

## 8. Presentation

### 8.1 Two route entries (`BI31`)

`credit_responder.py`'s `ROUTES` gains `INVOICE_ISSUE_SUBJECT: _invoice_issue` and `INVOICE_LIST_SUBJECT: _invoice_list` (`messaging/subjects.py` gains the two constants). `_invoice_issue` calls `required_correlation(headers)` **first**, then `invoice_wire.decode_issue(body, correlation)`, then `dispatcher.send`; `_invoice_list` reads no header (`billing.credit.list`'s shape). The class, the bound, the per-request scope, the drain, the empty-body refusal and the error path are unchanged; the module docstring now names five subjects.

### 8.2 `invoice_wire.py`

`decode_issue`: `from_wire_json(InvoiceIssueRequestPayload, body)` (`ValueError` → `InvalidInvoiceRequestError`), then the edge checks, each `InvalidInvoiceRequestError` naming the field: `len(order_reference) ≤ 20`; every `units ≤ 2_147_483_647`; every `unit_price ≥ 0`; `discount` (absent → 0) `≥ 0`; `Σ(unit_price × units) ≤ 9_223_372_036_854_775_807`; `discount ≤ Σ`. `decode_list`: `from_wire_json(InvoiceListRequestPayload, body)`, defaults page 1 / size 25, `status` the generated enum mapped to `InvoiceStatus`. `issue_reply(result)` → `InvoiceIssueReplyPayload` with `invoice_id` always set, `created`, `status`; `list_reply(page)` → `InvoiceListReplyPayload` of `InvoiceView`s, `paid_at` `None` for an `issued` view (written `null`, `BI32`). `encode` is `to_wire_json(...).encode("utf-8")`. No `json.dumps`, no `isoformat()`.

### 8.3 The order of the refusals

Headers, then schema, then edge checks — all before `dispatcher.send`, so `BI2`'s and `BI33`'s refusals are observable as **zero** dispatcher calls (the entry, not the residue: #7's `N10`).

### 8.4 The error mapping — every code is a saga decision

Orders splits the twelve codes into nine terminal (`TERMINAL_RPC_ERROR_CODES`, `nats_saga_commands.py:65-75`) and three transient. Every failure `billing.invoice.issue` can answer (`billing.invoice.list` is Gateway-called; its failures are the generic ones):

| Failure | Code (`details`) | Orders' class | #7 answered | #8 answered |
|---|---|---|---|---|
| Body not JSON / fails the model / missing or malformed header / an edge check (`BI2`, `BI33`) | `VALIDATION_FAILED` | terminal | `VALIDATION_FAILED` (`rpc-error-mapper.ts`) | `VALIDATION_FAILED` (`BillingErrorMapper.cs:39`) |
| No line for the pair (`CreditLineNotFoundError`) | `NOT_FOUND` (`retailerCode`, `companyCode`) | terminal | `NOT_FOUND`, then retried by its orchestrator | `NOT_FOUND`, terminal |
| Currency differs from the line (`InvoiceCurrencyMismatchError`) | `VALIDATION_FAILED` (`expected`, `received`) | terminal | `VALIDATION_FAILED` (`:89`) | `VALIDATION_FAILED` (`:53`) |
| No active hold (`NoActiveHoldError`, reused) | `PRECONDITION_FAILED` (`code`) | **terminal**: the row is rejected and the order stays `despatched` for a human (`BI26`) | `PRECONDITION_FAILED` (`:78`), retried then parked | `PRECONDITION_FAILED` (`:123`), terminal |
| `EmptyInvoiceLinesError`, `InvoiceLineCurrencyMismatchError`, `NegativeInvoiceTotalError` (statements about the request's lines; unreachable past the edge) | `VALIDATION_FAILED` (`code`) | terminal | `VALIDATION_FAILED` (`:98`) | `VALIDATION_FAILED` (`:61-73`) |
| `InvoiceTotalOverflowError` | `DOMAIN_ERROR` (`code`) | **terminal**, deliberately: it overflows again on every retry | n/a | `DOMAIN_ERROR` (`:81`) |
| Any other `DomainError` (`InvalidInvoiceSnapshotError`, `UnknownInvoiceStatusError`, `InvalidInvoiceStateError`, `storage.integer_out_of_range`, `quantity.out_of_range`, the three payment errors, feature 19's) | `DOMAIN_ERROR` (`code`) | terminal | `DOMAIN_ERROR` | `DOMAIN_ERROR` (`:154-158`) — #8 mapped its payment errors `PRECONDITION_FAILED` early; feature 22 decides their codes at its own subject |
| `StoreUnavailableError` (transient SQLSTATEs, pool timeout) | `UNAVAILABLE` | transient | `INTERNAL_ERROR` | `UNAVAILABLE` (`:162-163`) |
| A unique-constraint race (`23505`) or anything else | `INTERNAL_ERROR` (no exception text) | transient: the retry meets the fast path | `INTERNAL_ERROR` | `UNAVAILABLE` (every `SqlException`, `:163`) |
| `CONFLICT`, `TIMEOUT`, `ORDER_NOT_CANCELLABLE`, `STOCK_UNAVAILABLE`, `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH` | **never produced** by the five subjects | — | — | — |

`map_error` gains, ahead of `case DomainError()`: `InvalidInvoiceRequestError()` beside `InvalidCreditRequestError()`; `InvoiceCurrencyMismatchError()` with `expected` / `received`; the three request-shaped domain errors → `VALIDATION_FAILED`; `InvoiceTotalOverflowError` needs no arm (the generic `DomainError` row is already `DOMAIN_ERROR`) but gets an explicit test row. **The retryability guard is extended** (`tests/architecture/test_billing_rpc_error_retryability.py`): its `__subclasses__` walk today covers two modules by name (`otc_billing.domain.errors`, `otc_billing.application.errors`) with a literal count of 11, so an error in a new module (`domain/invoice_errors.py`) would be **invisible** to it. **The instrument changes** — and changing an instrument swaps its premises (lesson 9): the walk now imports every module of the `otc_billing` package (`pkgutil.walk_packages` with an `onerror` that raises, so a module that fails to import fails the test instead of shrinking the population) and collects every `DomainError` subclass whose `__module__` starts with `otc_billing.`; its expected count is re-derived as a literal from the classes on disk (it now also includes `range_guards.IntegerOutOfRangeError` and `QuantityOutOfRangeError`, real inputs that were outside the old population). New premises, each armed in E6: (a) the walk reaches a new module (a probe error in a new module raises the count); (b) a module that cannot import fails the walk rather than vanishing; (c) every walked class has an instance in the input list. New case `test_bi26_no_active_hold_is_answered_with_a_code_in_the_saga_adapters_terminal_set`.

## 9. Persistence adapters

### 9.1 `invoice_repository.py`

`load_invoice(session, order_reference) -> InvoiceSnapshot | None`: one `select(Invoice).where(Invoice.order_reference == order_reference)`, one `select(InvoiceItem).where(InvoiceItem.invoice_id == row.id)`, through the mapper (both the in-transaction re-read and the reads' fast path call it — Fulfillment's `load_despatch`). `SqlAlchemyInvoiceRepository(session, outbox, clock)`: `find_by_order_reference` = `load_invoice` on the transaction's session; `save(invoice)` per §6.3; `clear_saved_events()` after commit. **Never** `with_for_update`, `update(`, `delete(`, `on_conflict_*` or textual SQL in this file.

### 9.2 `invoice_mapper.py`

The only constructor of `Invoice` and `InvoiceItem` rows (`new_invoice_row(invoice, created_at)`, `new_item_row(line, invoice_id, created_at)`, `updated_at = created_at`) and the only reader: `invoice_snapshot(row, items)` builds `InvoiceSnapshot` with `state = parse_invoice_state(row.status, row.paid_at)`, `Money(row.amount, row.currency_code)` (and discount, total), lines sorted by `(product_code, line id)` in Python (L15), ids rebuilt from asyncpg's `UUID` subclass (L22), instants kept exactly as asyncpg returned them (L16). `state_token(state).value` and `paid_at` are written from the one `state`, so the two columns cannot disagree on the way out.

### 9.3 `invoice_number_allocator.py`

`SqlAlchemyInvoiceNumberAllocator(session).next_reference()`: `execute(text(SEED_INVOICE_SEQUENCE))`, `scalar_one()` of `text(LOCK_INVOICE_SEQUENCE)`, `execute(text(ADVANCE_INVOICE_SEQUENCE))`, `InvoiceReference.from_sequence(allocated)`. A copy of `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_number_allocator.py`'s shape with the three constants substituted; its docstring names that source and why (#8 ids 45 and 47, backlog 211). Not added to a parity guard: each allocator names its own table and prefix (#8 §6.4, Fulfillment's own record); the shape is three lines.

### 9.4 `invoice_reads.py`

`SqlAlchemyInvoiceReads(sessions)`: each call opens and closes a short session pinned `READ COMMITTED`. `find_by_order_reference` = `load_invoice`. `list`: the optional exact filters (`status` by its token), `invoice_date <= cutoff` when `issued_before_minutes` is given, `ORDER BY invoice_date DESC, invoice_reference DESC`, `offset(min((page - 1) * page_size, MAX_OFFSET)).limit(page_size)` (G1), and one `count()` over the same filters for `page.total`. **G1's cutoff**: `now - timedelta(minutes=m)` inside `try`; `OverflowError` → no invoice can qualify, so the query returns the page with **no items and the true `total` of zero rows matching** (the count is run with an always-false cutoff predicate — no row precedes year 1). Lines are not read (`InvoiceView` carries none). No lock, no write.

## 10. The outbox, and consumers

### 10.1 Fact mapping (`payloads.py`, service-specific, not a copy)

`narrow` widens to `type BillingEvent = CreditEvent | InvoiceEvent` and accepts the two new classes; `build_fact` gains two `case` arms building `Envelope[asyncapi.InvoiceIssuedPayload]` and `Envelope[asyncapi.PaymentReceivedPayload]` through the one `_envelope` site; `lines` map to `asyncapi.InvoiceLine(product_code, units, unit_price)`; `invoice_date` and `value_date` through `wire_instant`; references through `.value`; `source` to the generated `PaymentSource`. `assert_never` stays on the fall-through, so a third invoice event is a type error until mapped. `FACT_MODELS` already declares both event types (`facts.py:57-58`); **no `otc_contracts` change**.

### 10.2 The writer, the relay, the parity guard

Unchanged. The writer copy calls `narrow` / `build_fact` from `payloads.py`, so the widened union reaches it without touching the copy; `tests/architecture/test_outbox_copy_parity.py` must stay green with no edit.

### 10.3 Consumers — none (`BI1`)

Confirmed in all three: #7 (`apps/billing/src/billing-consumes-no-facts.spec.ts`), #8 (`BillingConsumesNoFactsTests`, its design §9), #9 (`grep -rn "AIOKafkaConsumer" services/billing/src` → no hit; the only aiokafka import is `infrastructure/outbox/kafka_publisher.py:16`). *"Issued on order.despatched"* is the orchestrator's `invoice.issue` command on that fact (`saga.md` §3.1 step 4; Orders' `step_table.py:166`, `command_payloads.py:65-78`). **No idempotent-consumer parity case goes live in 21** (`services/orders/tests/unit/test_idempotent_consumer_parity.py`: case 3's literal stays `{"otc_orders"}` because Billing has the ledger and only a producer); feature 22's dedup is by `paymentReference` in `payments`, a different key and table; the cases go live at feature 23.

## 11. Composition, settings, packages

`composition.py`: two `register_*` statements; `reads = SqlAlchemyCreditReads(sessions)` gains a sibling `invoice_reads = SqlAlchemyInvoiceReads(sessions)` bound into `scope_factory`; nothing else. No settings class, no environment variable (`tests/architecture/test_composition_env_reads.py` needs no edit and must stay green), no `.env.example` change. **Packages: none** (everything is in `services/billing/pyproject.toml` since feature 19); `uv.lock` unchanged. The engine's pool is unchanged: the issue path uses one session per attempt, the fast path and the list one short session each, all inside the responder's bound.

## 12. Architecture guards and censuses this feature touches

| Instrument | Change | Why |
|---|---|---|
| `tests/architecture/test_registration_behaviour.py` | `TABLES["billing"]` gains `IssueInvoiceCommand` and `ListInvoicesQuery` | feature 43's carried guard, new messages |
| `tests/architecture/test_write_path_population.py` | `EXPECTED["billing"]` gains every new hit, counts **read from `scan_service("billing")`**, each classified (the invoice repository's two `add`s: guarded; the allocator's three `text` + three `execute`: the counter, L26) | L23, L26 |
| `tests/architecture/test_billing_rpc_error_retryability.py` | the widened walk, the re-derived literal, the new inputs, `BI26`'s case (§8.4) | `BI26`, L30, lesson 9 |
| `services/billing/tests/unit/test_credit_subjects.py` | five subjects equal their channel addresses; the route table equals exactly those five | `BI16`, `BI31` |
| `test_kafka_client_confinement.py`, `test_outbox_copy_parity.py`, `test_composition_env_reads.py`, `test_money_guard.py`, `test_range_guard_parity.py`, `test_cqrs_registration_explicit.py`, `test_import_contract_coverage.py`, idempotent-consumer parity | **no edit**; each must stay green (the first is `BI1`'s guard and is armed) | — |

## 13. Testing

### 13.1 Files and levels (under `services/billing/tests/` unless stated)

| File | Level | Proves |
|---|---|---|
| `unit/domain/test_invoice.py` | domain unit, pure | `R45`, `R46` (matrix names verbatim), `BI10`, `BI11`, `BI14`, `BI25`, `BI35`, `BI38` (domain half) |
| `unit/domain/test_invoice_state.py` | domain unit + type checker | `BI23`, `BI27` |
| `unit/domain/test_invoice_facts.py`, `unit/domain/test_invoice_ids.py` | domain unit | `BI13`, `BI34` |
| `unit/test_invoice_issue_service.py` | unit, fakes | `BI5`, `BI8`'s order log, fast path opens no transaction, one clock read, reply after commit, rollback ⇒ no reply, `BI34`'s seam |
| `unit/test_invoice_requests.py`, `unit/test_invoice_wire.py` | unit | `BI2`, `BI33` (dispatcher zero calls), `BI9`'s `invoiceId` on both outcomes, `BI32` bytes |
| `unit/test_credit_subjects.py`, `unit/test_credit_rpc_errors.py`, `unit/test_outbox_payloads.py`, `unit/test_invoice_mapper.py` | unit | `BI16`, `BI31`, §8.4 rows, `BI36`, both new payload mappings field by field, row construction |
| `integration/test_invoice_issue.py` | integration (real PostgreSQL + NATS through the real lifespan) | `R45` through the host, `BI2` – `BI6`, `BI9`, `BI35`, `BI38` |
| `integration/test_invoice_issue_race.py` | integration | `BI8` |
| `integration/test_invoice_repository.py` | integration (PostgreSQL) | `BI7`, `BI10` store half, `BI24`, line reload order |
| `integration/test_invoice_number_allocator.py` | integration | `BI12` (six ported cases) |
| `integration/test_invoice_list.py`, `integration/test_invoice_reads.py`, `integration/test_invoice_wire.py` | integration | `BI15`, `BI16`, `BI32`, `BI37` |
| `integration/test_billing_outbox_relay.py` (extended) | integration (+ Kafka) | `invoice.issued.v1` published, key read from the broker |
| `tests/architecture/…` | architecture | §12 |

### 13.2 Fixtures and the synchronisation rule

The `billing_host` factory, the `rpc` helper (with its `.99` guard), `Db` and `Decode` are feature 19's; `Decode` gains `invoice_issue` (asserts `created` is present first) and `invoice_list` (asserts `page.total` first), and `Db` gains `invoices_of(order_reference)`, `invoice_items_of(invoice_id)`, `seed_invoice(...)` (a stored `issued` or `paid` row, for the repeat and the list) and `issue_body(...)`. **Every issue fixture is built from lines, never from a total**: the helper takes lines and a discount, computes `Σ` and `total`, and asserts — at fixture-build time — that `amount`, `discount` and `total` are pairwise distinct, non-zero and none contains another as a decimal substring (CLAUDE.md fixture rule; `BI38`), unless the test passes `zero_discount_on_purpose=True` / `zero_total_on_purpose=True` (`BI35`). The hold for the order is placed either through `rpc("billing.credit.hold", …)` with the computed total (so the `.99` guard sees the computed value) or planted with `db.plant_entry`.

**Synchronise only on terminal or monotonic evidence**: the reply; the presence of an `invoices` row; the count of the append-only `credit_items`; an outbox row (written in the reply's transaction); a lock request seen **ungranted** in `pg_locks` (`wait_for_lock_waiters`). Never on a derived amount, never on a sleep.

**Every emitting or suppressing branch opens its row.** The issued fact is read back and **every** payload field and the envelope's `aggregateId`, `correlationId`, `causationId` asserted against test-supplied, pairwise-distinct values (order id ≠ request id ≠ invoice id; `retailerCode` ≠ `companyCode`, neither containing the other; three distinct non-zero totals; at least two lines with distinct products, units and prices, in a request order that is not the canonical order). Each suppression (`created: false`, every refusal) asserts zero new rows **with a control row** in the same test. Every reply decode asserts its discriminating field first (`BC32`).

### 13.3 The constructed race (`BI8`)

The test's own connection holds the order's `credits` row `FOR UPDATE`; two `invoice.issue` requests for the **same** order are sent (distinct `x-request-id`s, one `x-correlation-id`); the test waits until **two** lock waits are ungranted; commits. Correct code: exactly one `created: true` and one `created: false` naming the same `invoiceReference`; exactly one `invoices` row, one `consume` entry and one `invoice.issued.v1` for the order; neither reply an `RpcError`. Three arms, each failing the "one `created: false`" assertion (the loser's reply is not `created: false`: measured `PRECONDITION_FAILED`, `INTERNAL_ERROR` (`23505`) or `UNAVAILABLE` (`40001` on the counter row), every outcome safe; see §6.2): re-read `invoices` before `lock_for_order`; drop `with_for_update` from `lock_for_order`; pin `REPEATABLE READ`. **The file's header states that the race cannot see a lock-order inversion** (two instances of one transaction taking locks in a consistently inverted order cannot cycle — #7's review `N5`) and names the unit order log (C4) as the sole guard of `BI8`'s ordering clause.

### 13.4 The fact guards — deletion **and** corruption, three branches

1. `Invoice.issue`'s `invoice.issued.v1` (live caller): delete the raise; corrupt `lines[0].unit_price`, `retailer_code`, `discount` and `aggregate_id` one at a time.
2. `Invoice.mark_paid`'s `payment.received.v1` (**no caller**, double force): delete the raise; corrupt each of `payment_reference`, `amount`, `currency`, `value_date`, `source`, `order_reference`, `invoice_reference` and `correlation_id` (#8's `D1`: two of these survived there).
3. `BuyerCredit.consume`'s deliberate **suppression** (`R40`): deleting an absent fact is impossible, so the guard is a whole-table outbox delta of exactly 1 across an issue, armed by **adding** a spurious row with the line's own `aggregate_id` and a different `correlation_id` in `credit_repository.save` (#7's `N7`: a `correlationId`-scoped assertion cannot see it) — at the repository level (F3) and through the host (F4).

**The discount, end to end (`BI38`).** Four arms, each failing a named test: the wire decode passes `discount=0`; `Invoice.issue` ignores the discount (`total = amount`); the mapper writes `discount=0` to the column; the payload builder writes `discount=0` into the fact.

**Coverage:** ≥ 80 % domain, ≥ 60 % overall, via `./quality.sh`.

## 14. The live stack — designed, not discovered (`BI22`)

**Pre-state, from K5's register** (`progress/impl_billing_credit.md` §8, lines 535 – 544, 2026-10-09 06:53): `ORD-000008` is `despatched` with its `invoice.issue` saga command `parked` (attempts 3); it holds a `hold` of 99 996 on `CR-000001` (`CarrefourEs` / `IBERFOODS`, EUR) and its despatch is `DES-000007` (4 × `PRD-0001`). `CR-000001` has 155 541 of active holds and an available credit of 344 459. `ORD-000007` is `confirmed` and issues no `invoice.issue` (stopped by design, feature 19 §14). `ORD-000009` is `cancelled` / `credit_rejected`. `ORD-000090` is a throwaway Billing ledger fixture (hold and release of 1 000), with no Orders row. `otc_billing.invoices` holds the five seeded rows and no counter row (expected; read in K1). **No other live order is named by this design.**

**Expected, unattended,** once Orders (8101), Fulfillment (8102) and Billing (8103) are up, within one sweeper interval of the row's `next_attempt_at`: Billing answers the re-issued `invoice.issue` for `ORD-000008` with `created: true`; one `invoices` row (`INV-000006` if the counter has not moved — read, not assumed), its line row(s) mirroring the order's lines, `discount` as Orders sent it; one `consume` row of exactly 99 996; one `invoice.issued.v1` published to `otc.billing.facts.v1` keyed by `ORD-000008`'s order id, its `correlation_id` equal to `otc_orders.orders.id` and its `causation_id` equal to the `invoice.issue` row's `saga_commands.id` (both read from the databases); Orders moves `ORD-000008` to **`invoiced`**; `CR-000001`'s available credit read through `billing.credit.list` is **still 344 459** (`R40`'s neutrality, live for the first time).

**And then it stops** (`saga.md` §3.1 step 5): no `payment.received.v1`, no new `credit.released.v1`, no order at `paid` or `completed`, no new `saga_commands` row beyond those the control order creates. A saga that stalls at `invoiced` is the **designed** end state of this phase, and the record says so next to the citation.

**A fresh control order with a non-zero discount** (`BI38`'s live half, #8's review `D2`, `../order-to-cash-dotnet/progress/review_billing_invoicing.md:183`: *"all ten rows of `otc_billing.invoices` carry `discount = 0`"*): placed through `orders.create` with a `lineDiscount` on at least one line, a total within `CR-000001`'s remaining credit and `total % 100 ≠ 99`, chosen from K1's figures. It must traverse `placed → stock_reserved → credit_approved → confirmed → despatched → invoiced` unattended, and its `invoices` row and its `invoice.issued.v1` must carry `amount`, `discount` and `total_amount` as three distinct values equal to the order's `initialAmount`, `initialDiscount` and `totalAmount`.

Hosts stopped by PID; the record goes to `progress/impl_billing_invoicing.md` § Live boot, **including the register of altered live fixtures, extended** (K5's, with every row this walkthrough changes).

## 15. Seams for later features — and what each must not rediscover

### 15.1 Feature 22 `billing_remittance_intake`

`Invoice.mark_paid(payment, context, new_id) -> PaymentReceived` ships tested and uncalled; it returns the fact so `credit.released.v1`'s `causationId` can be its `event_id` (#8 id 57). `InvoiceRepository` gains the `UPDATE` of `status`, `paid_at`, `updated_at` (the first `update` in this repository; the population test will classify it) and the `payments` insert. **Lock order** (`BI8`): read the invoice unlocked to find its party pair, `lock_for_order` the line, re-read the invoice (plain, after the lock), verify `issued`, `mark_paid`, `release(order, INVOICE_PAID, …)`, save both. Two outbox rows in one transaction, `payment.received.v1` first: the writer's per-row flush keeps the order (feature 19 L20) — 22 is the first to exercise it. The payment errors' subject codes (the `RpcError` codes `INVOICE_NOT_PAYABLE` and `PAYMENT_MISMATCH`, `asyncapi.yaml:2856-2857`; the Gateway later maps them to the HTTP codes of `openapi.yaml:673-675`, `PAYMENT_REFERENCE_REUSED`, `INVOICE_ALREADY_PAID`, `PAYMENT_MISMATCH` — leader correction 2026-10-10, found by the feature 22 premise check) are 22's to map; today they fall to `DOMAIN_ERROR`. `release`'s `None` must not be discarded (#8 feature 22's N3, feature 19 §15.3).

### 15.2 Features 24, 25, 33

`invoice.issued.v1` carries the full line list (the projector needs no call back). An `issued` `InvoiceView` carries `"paidAt":null` (`BI32`): the Gateway and the n8n bank robot read `null` as "not paid", as from #7. `issuedBeforeMinutes` and an out-of-range page answer an empty page (G1).

## 16. Gate points, and what was decided without one

**The rule** (maintainer, Phase 8): where #7 and #8 decided the behaviour identically and only the mechanism is Python's, it is decided with citations; only a question they disagree on, or one #9's engine forces, goes to the gate, with a recommendation and evidence from a command.

### 16.1 Open for the gate

**G1 — out-of-range list requests (`BI37`): a page past `2⁶³ − 1` and an `issuedBeforeMinutes` before year 1.** *Forced by Python and asyncpg; neither predecessor decided it.* Both requests are schema-valid (`PageRequest.page` has `minimum: 1` and no maximum, `asyncapi.yaml:2920-2932`; `issuedBeforeMinutes` `minimum: 0`, no maximum). Measured for this spec (header): `offset(2**63)` → `DBAPIError` SQLSTATE `22000`, which every list responder answers `INTERNAL_ERROR` (logged with a traceback, and a code the protocol calls retryable for what is a client's mistake); `offset(2**63 - 1)` → `[]`; `now - timedelta(minutes=2_000_000_000)` → `OverflowError`. The same offset gap exists today in `billing.credit.list` (`credit_reads.py:46`) and `fulfillment.stock.list` (`stock_reads.py:79`) — `grep -rn "\.offset(" services/*/src`: those two hits and no other. #7 computed the offset in JavaScript numbers (`invoice-read.repository.ts:50`), #8 in unchecked `int` (`EfCoreInvoiceReadRepository.cs:55`). **Recommendation: answer a page past the end, not an error** — clamp the offset to `2⁶³ − 1` (PostgreSQL then returns no rows, measured) and treat a cutoff before year 1 as "no invoice qualifies" — with the true `page.total`, on all three list subjects in this feature (one line in each reader, one case each, armed), because the finding is detected now and the fix is one line per site (CLAUDE.md: findings are fixed in the phase that detects them). *Alternative if overruled:* refuse both at the edge as `VALIDATION_FAILED` (one check per decoder, same three sites); `BI37`'s text changes to that outcome. Either way the three sites change together.

### 16.2 Decided (with the reason, never offered as an option)

- **The `BI` reuse and texts** (`requirements.md` §2): #8's ids, verbatim where the obligation is the same.
- **One transaction, two aggregates**, re-derived against #9 (§6.5): #7 gate row 1, #8 gate row 2, and #9's own feature 18 precedent.
- **Billing consumes no fact; no idempotent-consumer case goes live** (§10.3): #7, #8, #9's `saga.md` §5.
- **No responder rename** (`BI31`): #7 forked a controller, #8 renamed four types (its gate row 1) because its behaviour was hand-built per class; #9's responder is a route table and **feature 18 extended `StockResponder`'s table with `despatch.create` without renaming it** (`stock_responder.py:121-128`), so #9's own approved precedent decides. *A finding for the leader, not a gate point:* `specs/billing_credit/design.md` §8.1 says *"here the class is named for the service from the start"*, but the class is `CreditResponder` (its own §2 line 98 and the code say so) — that clause is stale and should be corrected to say feature 21 extends it by entries (feature 18's precedent).
- **`invoiceId` on every issue reply** (`BI9`): #7 sends it; #8's requirement text names it and its code omitted it (`InvoiceIssueService.cs` `BuildReply`).
- **`paidAt: null` for an issued view** (`BI32`): #9's ratified wire rule (feature 8), which lands on #7's bytes; #8's omission followed #8's own ratified rule. Following a ratified rule is not a new decision (#8 gate record row 4).
- **`unitPrice ≥ 0`, `discount ≥ 0`, `discount ≤ Σ` at the edge, before dispatch** (`BI2`): #7 after its `N2` (`invoice.dto.ts:39-41, 58-82, 112-115`), #8 (`InvoiceRequestValidator.cs:61-80`).
- **`orderReference ≤ 20`, `units ≤ 2³¹ − 1`, `Σ ≤ 2⁶³ − 1` at the edge** (`BI33`): forced by the columns and Python's unbounded `int`; feature 19's `BC33` and Fulfillment's FS28 are the approved precedent for the first, and the other two follow #7's `N2` lesson (no refusal after the counter lock).
- **No lock on the in-transaction invoice re-read** (L10): the line lock is the mechanism (#8 L8 says its hint was not load-bearing; feature 19 measured the fresh-statement snapshot; Fulfillment's F8 re-read is plain).
- **`consume` before the allocator** (§6.2): forced by feature 19's G1 ruling (the structural predicate is the check) and by #7's `N2` lesson.
- **Line order on a reload is canonical `(product_code, line id)`; the issued fact keeps the request's order** (L15): Fulfillment's `line_order_key` precedent; #7 and #8 left reload order undefined and emitted the request's order.
- **`InvoiceState` as a closed `type` alias over two dataclasses that refuse a subclass at runtime, with `assert_never` and a runtime instant check** (L41): the property #7 and #8 agree on, in Python's only available form. **Ruling (review §4.7): the maintainer is told; the census allow-list is not extended** (mypy accepts a subclass declaration but class creation raises; exhaustiveness does not depend on `final`).
- **`InvoiceTotalOverflowError` with its own code** (`BI25`): #8; feature 19's `BC30` shape in #9.
- **`mark_paid` delivered and uncalled, returning its fact** (`BI14`): #7 and #8 deliver it here; #7's A1 / #8 id 57 shape.
- **`BI21` guarded without an Orders change**: feature 16's tests already bite (`requirements.md` `BI21` note).
- **Zero-total invoice** (`BI35`): feature 19's gate ruling G1.
- **`invoice_number_sequences.next_value` stays `integer`** (§1): a counter, as in Orders, Fulfillment and #8 (its gate row 27).
- **No migration, no settings, no packages** (§1, §11).

## 17. Inherited findings → decision or task

### 17.1 #8's backlog, re-checked for feature 21

**Population.** Feature 19's §17.1 classified 37 #8 entries (Billing area or not); none was assigned to feature 21. Re-checked for entries #8 opened or touched during its feature 21: `python3 -c "…json over ../order-to-cash-dotnet/feature_list.json, id > 38, text ~ invoice|allocator|paid_at|paidat|discount|47…"` (run this session) → `41, 45, 47, 57, 65, 72, 75, 78, 84, 85, 102, 108, 110`; and `id > 38, text ~ billing_invoicing|feature 21|invoice.issue|InvoiceIssue|Invoice\b|INV-|invoice_number|BI[0-9]` → `78, 110`. #8's history for its feature 21 (lines 1305 – 1375) opened **no** new entry and closed **55**. Union, one row each where it bears on this feature:

| #8 id | Bears on 21? | Disposition in #9 |
|---|---|---|
| 41 `orders_cancel_responder` | No — Orders | #9 feature 41 |
| 45 allocator seed race | Yes — the `INV-` seed | **Avoided**: backlog 211's one-statement seed + `test_billing_counter_seed.py`'s sentinel (re-run in D6, `BI29`) |
| 47 allocator scan cost | Yes — the `INV-` seed | **Avoided**: the `MAX` runs only when the row is absent, pinned by `EXPLAIN (ANALYZE)` (`test_the_max_scan_never_runs_when_the_counter_row_exists`, re-run in D6) |
| 49 the id port at every site | Yes, by class | **Avoided**: `BI34`, per-site arms (B6) and the application seam (C5) |
| 53 / 55 reply-shape assertions; `BC32` false at six sites | Yes, by class | **Avoided**: `Decode.invoice_issue` / `invoice_list` assert the discriminating field first; G5 extends feature 19's enumeration (rooted at the decode) to every new file |
| 54 un-hinted in-transaction re-read | Yes — the `B7` re-read | **Avoided**: L10, measured mechanism, three race arms (I1) |
| 57 completion pair has no causal edge | Seam only | **Seam provided** (`mark_paid` returns its fact, `BI14`); the caller half is **feature 22's** (feature 19 §17.1) |
| 65 Gateway totals transposition | By class — `amount` / `discount` / `totalAmount` in `InvoiceView` and the fact | **Avoided**: three distinct non-zero totals in every fixture (`BI38`); a transposition arm in E4 |
| 72 matrix rows outliving their closer | By class | **Avoided**: L2 re-derives the summary from the rows (#8's `D3`) |
| 75 DLQ `first_failed_at` | No — feature 27 | n/a |
| 78 doc-comment crefs | No — .NET | n/a |
| 84 Gateway third copy of RPC payloads | No — Gateway | feature 25 (generated models are shared) |
| 85 container fixtures self-assign ports | Yes — test fixtures | **Avoided**: the root fixtures, ports held by Docker (feature 19) |
| 102 money text in problem details | Yes — invoice errors name amounts | **Avoided**: `BI36` |
| 108 domain `var` rule | No — .NET | n/a |
| 110 saga adapter reply decode | No — Orders | already avoided by feature 16 (SO15) |

### 17.2 #7's and #8's feature-21 review findings

| Finding | Disposition |
|---|---|
| #7 **N1** (0 of 60 boxes ticked) / #8 **N1** (ticks over stale text) | **Avoided**: `tasks.md` preamble — tick, or reword the box and argue the rewording on it |
| #7 **N2** (discount check inside the transaction) / **N10** (residue cannot prove placement) | **Avoided**: `BI2` / `BI33` at the edge, proven by zero dispatcher calls (E3, E5) |
| #7 **N3** (`BI5`'s "ledger rows unchanged" never asserted) | **Avoided**: F2 re-reads the order's rows; C2 asserts zero saves on **both** repositories |
| #7 **N4** (two-element lock log) / **N5** (the race cannot see an inversion) | **Avoided**: C4's three-call log with two arms; I1's header says so |
| #7 **N7** (`correlationId`-scoped outbox assertion) | **Avoided**: whole-table deltas at both layers, inverted arm F10 |
| #7 **N8** (text-scan guard for "no consumer") | **Avoided**: two existing behavioural / import-graph instruments (`BI1`) |
| #8 **D1** (`payment.received.v1` payload survived corruption) | **Avoided**: every field asserted and corrupted (B9, F9) |
| #8 **D2** (discount dropped at the responder, 273 tests green) | **Avoided**: `BI38`, non-zero fixtures and four arms (F7) |
| #8 **D3** (matrix summary hand-incremented) | **Avoided**: L2 derives the counts from the rows |
| #8 **R2-N1** (`git diff` as restore evidence for untracked files) | **Avoided**: the arming protocol uses `.arm/` backups, `sha256` and `cmp` |
| #8 **R2-N3** (an enumeration targeting a proxy) | **Avoided**: G5 roots the enumeration at the decode call, not at a member name |
| #8 **N6** (an altered live fixture not registered) | **Avoided**: K5 extends the register in the same pass |

## 18. Non-goals

No migration and no change to `models.py`, `range_guards.py`, `types.py`, `sequences.py` or `alembic/`. No change to `packages/`, to `specs/shared/` beyond column 5 of `R45` / `R46` and the derived counts, or to any file under `services/orders/`. Under `services/fulfillment/` only G1's one line in `stock_reads.py` and its test. No Kafka consumer, no idempotent-consumer copy. No payment intake, no `payments` write, no `invoice_paid` release. No `traceparent`, `x-deadline-ms`, structlog or metrics. No responder rename.
