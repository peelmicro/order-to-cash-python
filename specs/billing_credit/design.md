# Design — `billing_credit` (feature 19, Python 3.14 / SQLAlchemy 2.1 / asyncpg / PostgreSQL 18.6 / nats-py 2.16 / aiokafka 0.14, assessment #9)

> **Stack-specific.** This file is where the Python, SQLAlchemy, PostgreSQL, nats-py, aiokafka and `otc_cqrs` detail lives. Nothing here belongs in `specs/shared/`.
>
> **A port with a delta analysis.** #8's design (`../order-to-cash-dotnet/specs/billing_credit/design.md`, 1 053 lines, its §15 ledger `L1` – `L27`), its gate record (`../order-to-cash-dotnet/progress/spec_billing_credit.md`: both recommendations overruled, producing `BC29` / `BC30`; two deferrals overturned, producing `BC31` / `BC32`) and its review (`progress/review_billing_credit.md`: rejected once, four blocking defects, all guards — D1 a prescribed mutation never run, D2 a backlog closure at the wrong sites, D3 identity fields of two facts unguarded, D4 a malformed `x-request-id` unguarded) were read first, then #7's (`../order-to-cash-nestjs/specs/billing_credit/`, its review: rejected once on the port-refusal branch emitting no fact, `D1`, plus the surviving `W3` / `N5` payload corruption). Everything stack-agnostic is ported as content. The effort went into §3 (the ledger, from an enumerated boundary list), §6 (PostgreSQL's locking measured, not assumed), §8.5 (every code is a saga decision), §11 (the client id in three services) and §16 (one gate point).
>
> **Measurements made for this spec** (throwaway `postgres:18.6` containers, the image the fixture and compose use, removed afterwards; 2026-10-08). Schema: `credits(id, credit_limit)`, `credit_items(…, credit_id REFERENCES credits, amount bigint, type)`. A first transaction locks the line (`SELECT … FROM credits … FOR UPDATE`), inserts a 60-unit `hold`, sleeps 3 s, commits; a second transaction starts 1 s later.
>
> | Run | Second transaction | Waited | Committed exposure it read |
> |---|---|---|---|
> | A | `READ COMMITTED`: lock the line, then `SUM` | 2 099 ms | **60** (current) |
> | B / B2 | `REPEATABLE READ`: lock the line (as first statement in B2), then `SUM` | 2 094 / 2 092 ms | **0** — stale, and **no error** (the line row was locked, never updated, so no 40001) |
> | C | `READ COMMITTED`: `SUM` first, then lock the line | 2 105 ms | **0** — stale |
> | D | An `INSERT INTO credit_items` that takes no line lock, while another transaction holds the line `FOR UPDATE` | **2 087 ms** (blocked: the FK check's `FOR KEY SHARE` conflicts with `FOR UPDATE`) | — |
> | E | The same insert while the line is held `FOR NO KEY UPDATE` | 109 ms (not blocked) | — |
>
> Also: `SELECT SUM(amount) … FOR UPDATE` → `ERROR: FOR UPDATE is not allowed with aggregate functions`; `'ORD-000001' = 'ord-000001'` → `f` (deterministic, case-sensitive collation); `pg_typeof(SUM(bigint))` → **`numeric`**, and through SQLAlchemy + asyncpg `select(func.sum(<BigInteger column expr>))` returns **`Decimal('50')`**, `func.coalesce(func.sum(…), 0)` returns `Decimal('50')`, only `cast(…, BigInteger)` returns `50` (`int`). aiokafka 0.14.0: `AIOKafkaProducer(client_id="")` keeps `''` as the client id; only `None` becomes `aiokafka-producer-<n>` (`producer.py:284-287`). Orders' and Fulfillment's `KafkaSettings` accept `KAFKA_CLIENT_ID=` / `FULFILLMENT_KAFKA_CLIENT_ID=` and yield `''` (measured with `uv run python -I`).

## 0. Scope

**In scope.** The `BuyerCredit` aggregate and its `CreditLedgerEntry` value, pure domain (**B1** – **B5** inside the aggregate); the one pure function `summarise` that is the feature's arithmetic; the three NATS responders (`billing.credit.hold`, `.release`, `.list`) as one asyncio task class; the hold and release transactions with their lock protocol; the credit-decision port (feature 20's seam) and its always-approve adapter; Billing's copies of the outbox family under the extended parity guard; the first Billing composition root, lifespan and readiness; the `otc_cqrs` registration carried from feature 43; a non-empty, per-service Kafka client id in Orders, Fulfillment and Billing (`BC34`); the live walkthrough of the parked `credit.hold` rows (`BC20`).

**Out of scope, and owned elsewhere.**

| Not here | Owner |
|---|---|
| The `.99` rule, `CREDIT_FAILURE_RATE`, `R42` – `R44` | feature 20 (§15.1) |
| `billing.invoice.issue`, the `Invoice` aggregate, `INV-` allocation, the `consume` caller | feature 21 (§15.2) |
| `billing.payment.register`, the `invoice_paid` release caller, #8 id 57 | feature 22 (§15.3) |
| The `orders.cancel` responder that will call `billing.credit.release`; `saga.md` §2's missing row | feature 41 (`requirements.md` §1.2) |
| Gateway callers of `billing.credit.list` | feature 25 |
| `traceparent`, `x-deadline-ms`, structlog, metrics, DLQ | feature 27 |
| Any Orders behaviour change | none: only `BC34`'s settings field in Orders and Fulfillment changes (§11.2) |

## 1. What already exists — checked, not assumed

**The phase-6 schema is sufficient: no migration.** Read from `services/billing/src/otc_billing/infrastructure/persistence/models.py:62-88`:

| This design needs | Exists as |
|---|---|
| one line per `(retailer_code, company_code)`, unique | `credits` + `UniqueConstraint("retailer_code", "company_code")` (`:64`), the row the lock takes |
| the line's business reference | `credits.code varchar(30)` unique (`:66`), seeded `CR-000001` … `CR-000154` (`services/seed/src/otc_seed/domain/data/credits.py`) |
| the limit in minor units | `credits.credit_limit bigint` (`:69`) |
| the line's currency | `credits.currency_code char(3)` (`:70`) |
| the ledger | `credit_items(order_reference varchar(20), amount bigint, type varchar(20), credit_date timestamptz(3), created_at, updated_at)` (`:75-87`) |
| "this line's entries for this order" | `ix_credit_items_credit_id_order_reference` (`:78`) |
| outbox (`seq` identity, `json` payload) and `processed_events` | `:140-167`; `processed_events` **unused** (§10.4) |

**`credit_items.updated_at` on an append-only ledger.** Kept, written equal to `created_at` at insert and never changed — exactly what #7 does (`apps/billing/src/infrastructure/persistence/buyer-credit.repository.ts:73`, `{ createdAt: now, updatedAt: now }`) and #8 does (`src/Billing/Infrastructure/Persistence/BuyerCreditRowMapper.cs:51-52`, `UpdatedAt = createdAt`). Decided, not a gate point: both agree and Python forces nothing. The append-only test compares every column of an earlier row, `updated_at` included, before and after a later operation (task D6).

**No `CR-` allocator.** Credit lines are master data: #7 and #8 create them only in the seed (#7 `apps/seed/src/data/credits.data.ts`; #8 `src/Seed/Domain/Data/Credits`), and `BC3` forbids creating one on demand. There is no `credit_number_sequences` table and none is needed; `INV-` is feature 21's allocator.

**What Phases 8 and 9 built that this feature reuses** (shapes, not lines): Fulfillment's composition root and runtime (`services/fulfillment/src/otc_fulfillment/composition.py:78-350`: settings bundle, explicit registration, boot validation, one `AsyncExitStack`, readiness from task state and the NATS connection, the single-relay guard, pool sized from the bound); its responder (`presentation/stock_responder.py:131-237`: subject table, one callback that enqueues, `flush()` after subscribing, one task per request under a semaphore, drain with `return_exceptions=True`, fault logged by a done-callback — #8 id 50 already solved: **ported, not re-derived**); its headers module (`presentation/stock_headers.py`); its transactions class (`infrastructure/persistence/stock_transactions.py`: `READ COMMITTED` pinned per transaction, `TRANSIENT_SQLSTATES`, `StoreUnavailableError`); its scope (`application/scope.py`); the nine outbox-family copies and their parity guard; the generated wire models (`otc_contracts.generated.asyncapi`: `CreditHoldRequestPayload` … `CreditListReplyPayload`, `CreditView`, `PageInfo`, `CreditApprovedPayload`, `CreditRejectedPayload`, `CreditReleasedPayload`, `RpcError`, `Code`); `otc_shared_kernel` (`Money`, `UniqueId`, `AggregateRoot`, `format_money`).

## 2. Layout

```text
services/billing/src/otc_billing/
  domain/
    __init__.py, value_objects/__init__.py     (kept: the money guard's nested-domain sentinel)
    credit_entry_type.py     CreditEntryType (enum.Enum, explicit tokens) + parse_credit_entry_type
    ledger_entry.py          CreditLedgerEntry (frozen, slots, kw_only; no mutator)
    snapshot.py              BuyerCreditSnapshot, CreditLedgerEntrySnapshot (frozen; tuples)
    exposure.py              OrderExposure, LedgerSummary, summarise(entries)  -- PURE, the arithmetic
    reasons.py               CreditRejectionReason, AdapterRejectionReason, to_rejection_reason, CreditReleaseReason
    buyer_credit.py          BuyerCredit(AggregateRoot), HoldRequest, CreditContext, HoldEvaluation variants
    events.py                CreditEventBase, CreditApproved, CreditRejected, CreditReleased
    errors.py                the DomainError subclasses of section 5.5
  application/
    __init__.py
    ports/clock.py           COPY of Orders' (parity-guarded)
    ports/ids.py             IdSource (new() -> UniqueId)
    ports/credit_store.py    CreditTransactions, CreditTransaction, CreditRepository, CreditReads,
                             StoreUnavailableError
    ports/credit_decision.py CreditDecisionPort, CreditDecisionRequest, Approve, Refuse
    messages.py              HoldCreditCommand, ReleaseCreditCommand, ListCreditQuery + result dataclasses
    handlers.py              the three handler classes (thin)
    credit_hold.py           the hold transactional unit
    credit_release.py        the release transactional unit
    errors.py                CreditLineNotFoundError, CreditCurrencyMismatchError
    scope.py                 BillingScope (the dispatcher's S), MissingBindingError
  infrastructure/
    settings.py              + OutboxRelaySettings, KafkaSettings, NatsSettings, ServerSettings, ResponderSettings
    clock.py                 COPY of Orders' SystemClock (parity-guarded)
    ids.py                   UuidIdSource
    credit/always_approve.py AlwaysApproveCreditDecision (feature 20 adds simulator.py beside it)
    persistence/             models.py, range_guards.py, types.py, sequences.py UNCHANGED
    persistence/credit_mapper.py        rows <-> snapshots; the ONLY constructor of CreditItem rows
    persistence/credit_repository.py    the lock protocol (section 6), save, outbox drain
    persistence/credit_reads.py         the list view (no lock, no write)
    persistence/credit_transactions.py  run(work): session, READ COMMITTED, commit, transient mapping
    outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py   COPIES of Orders'
    outbox/topic.py          BILLING_FACTS_TOPIC = "otc.billing.facts.v1"
    outbox/payloads.py       narrow + build_fact for the three credit events (service-specific)
    messaging/subjects.py    the three subjects + BILLING_QUEUE_GROUP = "otc-billing"
  presentation/
    app.py                   create_app(lifespan=...) with /health/live and /health/ready (Fulfillment's shape)
    credit_responder.py      CreditResponder: one task, three subscriptions, bound, drain
    credit_wire.py           decode request -> message (+ BC33's edge checks); result -> reply
    credit_headers.py        x-correlation-id / x-request-id extraction (BC1)
    credit_rpc_errors.py     exception -> RpcError (section 8.5)
  composition.py             settings bundle, register_handlers, build_dispatcher, start_runtime, BillingRuntime
  main.py                    the lifespan (`uvicorn otc_billing.main:app`)
```

**Layering.** `domain` imports only what the money guard allows and `otc_shared_kernel`; no `otc_contracts`, no `otc_cqrs` (`domain-purity`). `application` imports `otc_cqrs`, the domain and its own ports, never `otc_contracts` (results are application dataclasses mapped to wire models in `presentation/credit_wire.py`). Only `infrastructure/outbox/kafka_publisher.py` imports aiokafka (`fact-producer-confinement`, `test_kafka_client_confinement.py`). The lifespan lives in `main.py`, outside the layers (CLAUDE.md). **No import-linter contract changes**: `otc_billing` is already in `domain-purity`, `fact-producer-confinement`, `layers-billing` and `service-independence` (`pyproject.toml:172-358`).

## 3. The ported-idiom ledger

One row per idiom: *#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z*, each half cited, the guard named in `tasks.md` where #9 hand-builds the property. **Derived from an enumerated boundary list** (#8 history line 1255: every ported-idiom loss so far sat at a boundary where a value crosses into or out of the process), listed in §3.1 before any row was written.

### 3.1 The boundary enumeration

**Inbound decode** — B1 `billing.credit.hold` bytes → model; B2 `billing.credit.release` bytes → model; B3 `billing.credit.list` bytes → model (paging defaults); B4 request headers → correlation; B5 `amount` object → `Money` (int width, sign); B6 `orderReference` length vs `varchar(20)`.
**Store reads that decide** — B7 the `credits` row (identity, limit, currency) under lock; B8 the committed-exposure scalar (SQL type, unknown tokens, width); B9 the order's `credit_items` rows; B10 the list view's three reads; B11 `credit_date` → domain instant; B12 `type` token → enum; B13 `currency_code char(3)` vs request currency; B14 `order_reference` matching in SQL vs grouping in memory.
**Store writes** — B15 `credit_items` insert (width, `updated_at`); B16 `outbox` insert (order, payload bytes); B17 the `credits` row, never written.
**Outbound encode** — B18 success replies; B19 `RpcError` replies (codes the saga decides on); B20 the Kafka publish (key, producer client id).
**Process and host** — B21 request concurrency and the per-request scope; B22 shutdown drain; B23 transaction and isolation defaults; B24 the in-process hop to the credit-decision adapter; B25 `Σ` width; B26 settings → adapters; B27 event-loop affinity; B28 cancellation and exception propagation; B29 `Any` from nats-py / asyncpg / aiokafka; B30 identifiers minted for entries and facts.

### 3.2 The ledger

| # | Bnd | Property | #7 relied on | #8 supplied it by | #9 supplies it by | Guard (`tasks.md`) |
|---|---|---|---|---|---|---|
| L1 | B1–B3 | Bare-JSON request and reply | A hand-written bare-JSON NATS (de)serializer pair (`apps/billing/src/infrastructure/messaging/bare-json-nats.{de,}serializer.ts`) | Nothing: raw bytes (#8 `design.md` §4.3, L1) | Nothing: `Msg.data` is `bytes`, `Msg.respond(bytes)`; `from_wire_json` / `to_wire_json` | H7 (`BC2`) |
| L2 | B1–B3 | Declared keys are the keys read | Generated `@otc/contracts` types | Hand-transcribed records + `BC23`'s parse of `asyncapi.yaml` (#8 L2) | Generated pydantic models, drift-tested (`packages/contracts/tests/test_generation_drift.py`); no hand-written payload type exists | none owed (`BC23` not claimed) |
| L3 | B1–B3, B5 | A malformed request is refused, not half-processed | `class-validator` DTOs (`presentation/dto/credit.dto.ts`) | `CreditRequestValidator` (#8 L3) | The generated models (strict int, `minLength` / `maxLength` 20, patterns, `pageSize` ≤ 200) via `from_wire_json`, plus `BC33`'s two edge checks the schema cannot express | E3 (one case per constraint, each `VALIDATION_FAILED`, nothing dispatched) |
| L4 | B4 | A missing or malformed header mutates nothing | Controller read `ctx.getHeaders()` | `RpcMeta` copied from Fulfillment (#8 L4); the malformed-request-id case was missing (review D4) | `credit_headers.required_correlation` (Fulfillment's `stock_headers.py` shape) before dispatch, on `hold` and `release` only; both missing **and** malformed, **each header separately** | E5 (`BC1`), four arms |
| L5 | B5 | The amount cannot narrow or flip sign | JS numbers; no sign check (`credit.dto.ts:16`, `@IsInt()` only) | `long` end to end + `amount < 0` refused (`CreditRequestValidator.cs:110-115`) | Python `int` (no narrowing); the wire `Money` bounds it to int64 (`generated/asyncapi.py:16-18`); `BC33` refuses a negative amount at the edge | E3 (`BC33`) |
| L6 | B6 | A request value the column cannot hold is terminal, not retried | MySQL strict mode → `INTERNAL_ERROR` → retried | `nvarchar(20)` overflow → `UNAVAILABLE` → retried | `orderReference` > 20 → `VALIDATION_FAILED` at the edge (`BC33`, Fulfillment's FS28) | E3; arm: drop the check (the reply changes kind) |
| L7 | B7 | A blocking, current read of the line row | `SELECT … FOR UPDATE` (`buyer-credit.repository.ts:45`) under InnoDB `REPEATABLE READ` | `WITH (UPDLOCK, HOLDLOCK, ROWLOCK)` (`EfCoreBuyerCreditRepository.cs:37`) under RCSI | `select(Credit).where(…).with_for_update()` — one row; plain `FOR UPDATE` (not `key_share`), which also blocks an unlocked ledger insert through the FK's `FOR KEY SHARE` (measured D vs E) | I1 race; arm: drop `with_for_update` |
| L8 | B8 | The `Σ` is computed from committed state, after the lock | `FOR UPDATE` on the aggregate read (`buyer-credit.repository.ts:53-57`) | The same hint on a raw `SqlQueryRaw<long>` (`EfCoreBuyerCreditRepository.cs:53-55`); `SumAsync` forbidden (#8 L7) | **Cannot lock** (measured: `FOR UPDATE` is refused with an aggregate). Issued **after** the line lock at a pinned `READ COMMITTED`, whose fresh statement snapshot sees the competitor's committed entry (measured A); every ledger writer takes the line lock first (`BC35`) | I1; arms: read the sum before the lock (measured C); pin `REPEATABLE READ` (measured B2) |
| L9 | B8 | The `Σ` reaches the domain as an exact `int` | `Number(exposureRow.committedExposure)` over MySQL's `DECIMAL` sum (`buyer-credit.repository.ts:53, 65`) | `SqlQueryRaw<long>`: SQL Server's `SUM(bigint)` is `bigint` (`EfCoreBuyerCreditRepository.cs:53-54`) | `CAST(COALESCE(SUM(…), 0) AS bigint)` in SQL: PostgreSQL's `SUM(bigint)` is `numeric` and asyncpg returns `Decimal` even through `func.sum` over a `BigInteger` (measured); `Money` would refuse the `Decimal` (`money.py:44-45`) | D5 (`BC37`): `type(value) is int` read back **through the repository**; arm: drop the cast |
| L10 | B8 | An unknown ledger `type` is loud, also in the scalar | Union type on rows; the scalar's `CASE … ELSE 0` summed it as zero (`buyer-credit.repository.ts:53`) | Loud row parse (`CreditEntryType.cs:37-42`); the scalar's `ELSE 0` too (`EfCoreBuyerCreditRepository.cs:54`) | The scalar statement also returns `count(*) FILTER (WHERE type NOT IN ('hold','consume','release'))`; non-zero → `UnknownCreditEntryTypeError`; the order's rows are parsed through the closed map | D5 (`BC37`); arm: ignore the count |
| L11 | B8, B25 | An out-of-range sum is a terminal domain error, not a retried one | JS numbers do not wrap | `checked` arithmetic → `CreditLedgerOverflowError`, mapped `DOMAIN_ERROR` (`BillingErrorMapper.cs:111-114`) | The `CAST` raises SQLSTATE `22003`, which `credit_repository` maps to `CreditLedgerOverflowError` on that statement only; otherwise `22003` would fall to `INTERNAL_ERROR`, which the saga **retries forever** | D5 (`BC30`); arm: drop the mapping (the reply becomes `INTERNAL_ERROR`) |
| L12 | B9 | The idempotency predicate reads current rows | `FOR UPDATE` on the order's entries (`:63`) | `UPDLOCK, HOLDLOCK` (`:66`) | A plain read after the line lock, same reason as L8; two holds for one order serialise on the line row | I2 same-order race; arm: read the order's entries before the lock |
| L13 | B10 | The list view blocks nobody | MySQL consistent read | `AsNoTracking`, no hint (#8 L9) | Plain `SELECT`s in a short session, no transaction write, no `with_for_update` | H6 asserts the reconciliation; D7 forbids a lock in `credit_reads.py` and the reviewer greps for `with_for_update` |
| L14 | B11 | An instant read back equals the instant written | A `mysql2` pool with `timezone: 'Z'` (`infrastructure/persistence/client.ts:26`) | `new DateTimeOffset(value, TimeSpan.Zero)` (`BuyerCreditRowMapper.cs:40`); the first guard was decorative (review D1) | `timestamptz(3)` + asyncpg's binary decode → aware UTC `datetime`; the clock port truncates to whole ms (`wire_instant`), so `timestamptz(3)`'s rounding cannot move a written value | D6 (`BC24`), read **through the mapper** under a non-UTC session `TimeZone`; arms: the mapper drops `tzinfo`; the mapper shifts to local time |
| L15 | B12 | The `type` token parse is closed | Union type (`credit-ledger-entry.ts:17`) | `CreditEntryTypes.Parse` throws (`CreditEntryType.cs:37-42`) | `parse_credit_entry_type`: `type(token) is str`, then a literal `dict` lookup, else `UnknownCreditEntryTypeError` (the Orders / Fulfillment status convention) | B2; arm: `token.strip().lower()` |
| L16 | B13 | Currency codes compare equal iff the same currency | MySQL CI collation; JS `===` | Ordinal `Money.EnsureSameCurrency` vs CI column, closed at the edge (#8 L13) | Exact `==` on both sides: `^[A-Z]{3}$` on the wire, `char(3)` holds three capitals, PostgreSQL compares exactly. Nothing to normalise | E3 currency pattern; H3 `BC4` |
| L17 | B14 | In-memory grouping agrees with the database | JS `===` vs MySQL CI (latent, never stated) | `OrdinalIgnoreCase` vs MS-SQL CI (`CreditExposure.cs:55-57`) | Exact `==` (a `dict` keyed by the stored string) vs PostgreSQL's case-sensitive collation (measured): they agree. Feature 17's G2, adopted | B4 (`BC28`); arm: group by `.upper()` with two keys differing by case |
| L18 | B15 | Money never narrows or becomes a float on the way to the column | One JS number type | `long` → `bigint` | `int` → `bigint`; the ORM range guard (`range_guards.py`, `storage.integer_out_of_range`) fires on assignment; no `/`, no `Decimal` in `domain` (`tests/architecture/test_money_guard.py`) | quality.sh (money guard), D8 (write-path population) |
| L19 | B15, B17 | The ledger is append-only and the line row is never written | Drizzle inserts only (`buyer-credit.repository.ts:73`) | `Add` only; no `UPDATE` / `DELETE` (#8 §7.2) | `credit_mapper` constructs `CreditItem` rows; the repository `session.add`s them; no `update(`, `delete(`, `text(` DML in the service; `updated_at = created_at` | D8 (write-path population classifies every write); D6 (an earlier row is byte-equal after a later operation) |
| L20 | B16 | Facts are published in emission order | MySQL `AUTO_INCREMENT` | Per-row awaited insert (#8 L16) | Orders' writer, one `flush()` per row, **copied byte-identically** (`BC17`) | the parity guard; Orders' `seq` tests |
| L21 | B16, B18, B19 | One serializer on the wire and in the outbox | `JSON.stringify` | `JsonWire.Options` | `to_wire_json` for every reply, `RpcError` and outbox payload; payload column `RawJson` (`json`, not `jsonb`); `occurredAt` through `format_instant` | H7 (bytes); F3 (reply key sets) |
| L22 | B18 | An absent optional reply field is omitted, not `null` | `class-transformer` | Nullable records + `WhenWritingNull` (#8 L18) | `to_wire_json` omits `None` (the generated models' optional fields default to `None`); an `approved` reply has no `reason` key, a `rejected` one no `heldAmount` | F3; arm: build the approved reply with `reason=Reason5.over_limit` |
| L23 | B19 | A transient failure stays retryable; a business "no" is terminal | #7's orchestrator retried every code | Closed mapping, `CONFLICT` banned, transient → `UNAVAILABLE` (#8 L19) | §8.5's table; `TERMINAL_RPC_ERROR_CODES` imported from Orders by the test, never retyped | E6 (`BC27`); arm: map `StoreUnavailableError` to `CONFLICT` |
| L24 | B24 | An adapter cannot say `over_limit`, and cannot do I/O inside the lock | `Exclude<CreditRejectionReason,'over_limit'>`; `decide` may be sync or async (`application/ports/credit-decision.port.ts`) | A separate two-member enum; `ValueTask` (`ICreditDecisionPort.cs:24, 69`) | `AdapterRejectionReason(enum.Enum)` with the two simulator members and `to_rejection_reason` as an exhaustive `match` ending in `assert_never`; and `decide` is a **plain `def`** (not `async`), so an adapter cannot `await` a network call while the line row is locked | C2 (`BC14` type half); arm: add an `OVER_LIMIT` member (mypy and the member-set test fail) |
| L25 | B25 | Exposure sums raise rather than wrap | JS numbers do not wrap | `checked` regions + `checked` `Money` (#8 L25, gate-ordered) | Python `int` never wraps (free). The raise is hand-built: `summarise` checks every accumulated total against int64 and raises `CreditLedgerOverflowError` (`credit.ledger_overflow`); `Money` already refuses an out-of-range amount at construction (`money.py:44-45`) | B5 (`BC30`), driven directly; arm: delete the range check |
| L26 | B20 | Two services' producers never share an identity | The per-service `kafka.config.ts` default (`apps/billing/src/infrastructure/outbox/kafka.config.ts:32`, `'otc-billing'`) | A `required` `ClientId` (`KafkaOptions.cs:18`) supplied per service (`BillingOptions.cs:19`); an **empty variable still yielded an empty id** (#8 review A1) | A pydantic `pattern=r"^[A-Za-z0-9._-]+$"` on `client_id` in **all three** services' `KafkaSettings`, so `""` / blank fails the boot naming the variable; distinct defaults asserted together (`BC34`). aiokafka would send `""` verbatim (measured) | G2, G3 (`BC34`); arms: drop the pattern in one service; set Billing's default to `otc-orders` |
| L27 | B20 | Every fact lands on its order's partition | The relay's `correlationId` key | The same (#8 L20) | The copied relay keys by `correlation_id`; `BC1` refuses a header-less hold, which keeps the key non-arbitrary | F5 (key read back from the broker) |
| L28 | B21 | Independent requests run concurrently, each with its own unit of work | `@nestjs/microservices` per-request promise (`main.ts:32-33`) | `SemaphoreSlim` + one DI scope per request (`BillingRpcResponder.cs:56, 177`) | Fulfillment's responder: one task per request, `asyncio.Semaphore(BILLING_MAX_CONCURRENT_REQUESTS)` acquired before the unit of work opens a session; engine `pool_size = bound + 1`, `max_overflow = 0`; a fresh `BillingScope` per request | E8 (unit), I3 (held-lock integration); arms: serve inline; one scope per responder |
| L29 | B22 | Shutdown drains without one failure aborting it | `enableShutdownHooks()` (`main.ts:21`) | Each in-flight task awaited individually (`BillingRpcResponder.cs:74-102`, #8 id 50) | Fulfillment's `_drain` (`gather(…, return_exceptions=True)`) and `_log_fault`, ported | E7 (`BC22`), both halves; arms: `gather` without `return_exceptions`; skip the drain |
| L30 | B23 | One transaction per attempt at a stated isolation, no ambient session | Drizzle `TransactionContext`; InnoDB default `REPEATABLE READ` (Fulfillment ledger L1 cites `drizzle-unit-of-work.ts:75`) | `IsolationLevel.ReadCommitted` explicit (`EfCoreUnitOfWork.cs:39`) | `CreditTransactions.run(work)`: one `AsyncSession` per attempt, `session.connection(execution_options={"isolation_level": "READ COMMITTED"})` before the first statement (Fulfillment's `stock_transactions.py`), events cleared only after commit. **`REPEATABLE READ` would not raise here** (the line row is locked, not updated: measured B2) — it would silently approve over the limit, which is why this row is a guard and not a convention | D4 (`BC35`): the race, armed with `REPEATABLE READ`; and the isolation read back from `current_setting('transaction_isolation')` inside `run` |
| L31 | B23 | A deadlock victim is retried | `INTERNAL_ERROR` fall-through, orchestrator retried | 1205 → `UNAVAILABLE` | **No in-process re-run**: one row is locked per transaction, so no cycle can form (`BC9`); `40P01` is in `TRANSIENT_SQLSTATES` → `StoreUnavailableError` → `UNAVAILABLE` (retried by the saga). Fulfillment's re-run (FS23) was its own acceptance item for multi-row locks; neither #7 nor #8 re-ran in Billing | E6 (the transient population includes `40P01`) |
| L32 | B26 | Every setting reaches its adapter, and nothing else reads the environment | `env.BILLING_*` reads in `kafka.config.ts` etc. | `Program.cs` reads, guarded only after #8 id 56 / 67 / 68 | `load_settings()` builds every settings class; `test_composition_env_reads.py` (no other read, every class built); `test_billing_settings_env.py` (each variable sets exactly its field); `test_billing_host_lifespan.py` (the values reach the adapters through the real lifespan) | G1 – G4 |
| L33 | B27 | Engine, NATS client and producer belong to the lifespan's loop | One Node loop | Thread pool | Created in `start_runtime`, inside the lifespan, closed by its `AsyncExitStack`; no aiokafka object built in `__init__`; test hosts function-scoped, every engine disposed in the loop that made it | H1's host fixture; `PytestUnraisableExceptionWarning` is an error |
| L34 | B28 | Cancellation is never swallowed; one failure does not stop the others | Promises | `OperationCanceledException` excluded | `except Exception` only; cancelling `run` cancels the request tasks and re-raises (Fulfillment's `stock_responder.py:179-184`) | E7's cancellation case |
| L35 | B29 | `Any` does not leak from untyped clients | TypeScript types | C# types | nats-py ships `py.typed`; asyncpg reached only through SQLAlchemy's typed results (`scalar_one()` of a `cast(…, BigInteger)` is `int`); aiokafka only through the publisher copy's `Protocol`. `mypy --strict` | quality.sh |
| L36 | B30 | Every entry id and fact `eventId` is the one supplied | Entry ids from a `newId` closure (`buyer-credit.ts:172-185`); event ids minted inside the kernel's `createDomainEvent` (`domain/credit-events.ts:55, 90`), so no test could supply them | `Func<UniqueId> newId` used for entries **and** `EventId` at every site (`BuyerCredit.cs:148, 153, 191, 222, 238`), after #8 id 49 taught it on Fulfillment | `new_id: Callable[[], UniqueId]` a required parameter of `approve`, `refuse`, `release`, `consume`, used at all six sites; the handlers pass `scope.ids.new` | B6 (six per-site arms) + C3 / C4 (the two application seams, arms M1a / M1b) |
| L37 | — | Integer division | n/a | n/a | None: `min`, `+`, `-` only; paging offset `(page - 1) * page_size`; ms → s only in settings properties (Orders' shape) | quality.sh (money guard walks `otc_billing.domain`) |

**Python porting questions answered** (CLAUDE.md): integer division — L37; JSON serialisation — L1, L21, L22; event-loop affinity — L33; task cancellation and exception propagation — L29, L34, §8.3; typing gaps — L9, L35; numeric width — L5, L9, L11, L18, L25; case sensitivity — L16, L17; transaction and isolation defaults — L8, L30; connection and concurrency — L28, L31; single-statement atomicity — L19 (no upsert anywhere: every row written is a new ledger or outbox row inside a transaction that already holds the line lock).

**Rows the enumeration produced that recollection would not have:** L9 (the `Decimal` sum — #7 and #8 each got the integer type from their own engine), L10 (an unknown token summed as zero — present in **both** predecessors' scalars), L11 (the overflow that would have been retried forever), L30's "would not raise" (feature 17 measured `REPEATABLE READ` raising 40001 because its stock row is **updated**; Billing's line row is only **locked**, so the same arm is silent here).

## 4. Port the guards too

#8's tests of this mechanism, enumerated by file (`ls ../order-to-cash-dotnet/tests/Billing.UnitTests/*.cs ../order-to-cash-dotnet/tests/Billing.IntegrationTests/*.cs`: 84 files), classified. Invoice, payment and simulator files (`Invoice*`, `Payment*`, `SimulatorCreditDecisionTests`, `CreditSimulatorTests`, `CentsRuleFixtureGuard*`) are features 20 – 22's.

| #8 test | #9 |
|---|---|
| `BuyerCreditTests`, `CreditHoldTests` (unit), `CreditLedgerTests`, `CreditLedgerEntryTests`, `CreditExposureTests` | **Ported** (`unit/domain/`), plus `BC36`'s per-site provenance and `BC38` |
| `CreditHoldServiceTests`, `CreditReleaseServiceTests` | **Ported** (`unit/test_credit_hold_service.py`, `test_credit_release_service.py`), including #7's D1 (port refusal records the fact) and #8's C8 payload corruptions |
| `CreditDecisionPortTests`, `AlwaysApproveCreditDecisionTests` | **Ported** |
| `BillingErrorMapperTests` (BC27, reads the terminal set) | **Ported** as `tests/architecture/test_billing_rpc_error_retryability.py`, importing `TERMINAL_RPC_ERROR_CODES`; plus `unit/test_credit_rpc_errors.py` row by row |
| `BillingErrorMapperMoneyTextTests`, `DomainErrorMoneyTextTests` (#8 id 102) | **Ported** (`BC39`) |
| `CreditResponderHeaderTests`, `CreditResponderConcurrencyTests` (unit + integration), `CreditResponderShutdownTests` | **Ported** (E5, E7, E8, I3) |
| `CreditRequestValidatorTests` | **Replaced**: the generated models are the validator; one wire case per constraint plus `BC33` (E3) |
| `CreditRpcPayloadTests`, `AsyncApiSchema*` (#8 id 51) | **Not ported, avoided by construction**: generated models, drift-tested; the reply-shape half (exact key set per `outcome`) is ported as F3 |
| `CreditSubjectsTests`, `BillingFactTopicTests`, `BillingResponderSubjectCoverageTests` | **Ported** (pyyaml over `asyncapi.yaml`, E2, F2); subject coverage = the responder's route table equals the three subjects |
| `CreditClaimProjectionTests` (literal column lists in raw SQL) | **Not applicable**: the line lock and the order's entries are ORM `select(…)`; the one textual statement (the scalar) names no column list to drift |
| `BillingDispatcherRegistrationTests` | **Ported** (G5), plus the behavioural registration guard (G6) |
| `BillingProgramConfigurationTests`, `BillingDbContextFactoryTests` (#8 ids 56, 67, 68) | **Ported** as the settings → adapter reach test and the per-variable settings test (G1 – G4); Alembic's `env.py` reads only through `BillingDatabaseSettings` (`services/billing/alembic/env.py:16, 26`) |
| `BillingConsumesNoFactsTests` (#7 `billing-consumes-no-facts.spec.ts`) | **Ported** by an existing instrument: `test_kafka_client_confinement.py`'s literal importer set gains only Billing's publisher (a consumer import fails it) |
| `CreditHoldTests`, `CreditHoldRaceTests`, `CreditReleaseTests`, `CreditListTests`, `CreditWireTests`, `BuyerCreditRepositoryTests`, `BillingOutboxRelayTests` (integration) | **Ported** (groups D, F, H, I), with #8's D1 (read through the mapper), D3 (identity fields on every fact) and A6 / id 55 (discriminating field first) closed from the start |
| `BillingResponderReadinessRaceTests` (#8 id 63) | **Not applicable**: the host is reachable when `start()` returns (`flush()` after subscribing); no wait loop exists to pace |
| `OutboxSeqIdentityTests`, schema / FK / index / round-trip / migration tests, `NoMoneyColumnIsIntTests` | Already ported in phase 6 (`services/billing/tests/integration/`) |
| `BillingRpcResponderTraceContinuationTests`, `LogCorrelationTests`, `HealthProbesTests`, `HealthCheckAggregationTests` | **Feature 27** |
| `MsSqlContainerFixture`, `NatsContainerFixture`, `KafkaContainerFixture`, `SqlExceptionFactory`, `CapturedConsole`, `RepositoryPaths`, `Fakes`, collections | **Not applicable** (xUnit / EF plumbing); the root `conftest.py` fixtures are reused, ports held by Docker (#8 id 85) |
| `tests/Orders.UnitTests/OutboxRelayParityTests.cs` (`BC17`) | **Ported** by extending `tests/architecture/test_outbox_copy_parity.py` (§10.2) |
| `tests/SharedKernel.UnitTests/MoneyTests.cs` `BC30` cases (`checked` `Money`) | **Not applicable**: Python `Money` cannot wrap and already refuses an out-of-range amount (`money.py:44-45`, covered by the kernel's own tests) |

## 5. The domain

### 5.1 `BuyerCredit` — the aggregate root

```text
CreditContext(occurred_at: datetime, causation_id: UniqueId)            # frozen; from the clock port and x-request-id
HoldRequest(order_reference: str, amount: Money, correlation_id: UniqueId)
HoldEvaluation = AlreadyHeld(held_amount) | CurrencyMismatch(expected, received) | OverLimit(available_credit) | Fits

class BuyerCredit(AggregateRoot):
    rehydrate(snapshot: BuyerCreditSnapshot) -> BuyerCredit              # refuses B1/B3 breaches, foreign entries, unknown state
    code: str; retailer_code: str; company_code: str; currency: str
    credit_limit: Money; available_credit: Money                        # BC5: limit - committed_exposure
    summary: LedgerSummary                                              # BC6 over the loaded + appended entries
    evaluate_hold(request) -> HoldEvaluation                             # PURE; BC26 order
    approve(request, context, new_id) -> CreditLedgerEntry              # raises unless Fits
    refuse(request, reason: CreditRejectionReason, context, new_id) -> None
    release(order_reference, reason, correlation_id, context, new_id) -> CreditLedgerEntry | None
    consume(order_reference, context, new_id) -> CreditLedgerEntry
    appended_entries: tuple[CreditLedgerEntry, ...]                     # what the repository inserts
    to_snapshot() -> BuyerCreditSnapshot
```

- **What it holds** (#7's and #8's shape, `buyer-credit.ts:50-56`): the `credits` row, `committed_exposure` (one int, `BC5`'s two-term sum over the whole line, computed in SQL) and the entries of the **one order** the command names. It never loads the whole ledger. `rehydrate` refuses `credit_limit < 0`, `committed_exposure > credit_limit` (**B1**, the outer bound of `BC30`), an entry whose currency differs from the line's (**B3**) and an entry of another order (`InvalidBuyerCreditSnapshotError`).
- **`evaluate_hold`**, in `BC26`'s order: a recorded `hold` entry for the order → `AlreadyHeld(held_amount = that entry's amount)` (`BC7`, any later history); else the request currency differs → `CurrencyMismatch`; else `amount > credit_limit − committed_exposure` → `OverLimit`; else `Fits`. Pure: no mutation, no event, no port.
- **`approve`** re-evaluates and raises `CreditLimitExceededError` unless `Fits` (a caller cannot bypass **B1**), appends one `hold` entry (`new_id()` for its id, `context.occurred_at` for its date), adds the amount to `committed_exposure`, raises one `CreditApproved` (`new_id()` for its `event_id`) whose `available_credit_after` is computed **after** the addition (`BC10`).
- **`refuse`** raises `CreditRefusalMismatchError` if `reason` is `OVER_LIMIT` while the amount fits (a refusal may not lie), appends **nothing**, raises one `CreditRejected` carrying `requested_amount`, the unchanged `available_credit` and the reason. **One builder, one call site** for every refusal (`BC14`, `R44`).
- **`release`**: outstanding iff the order has a `hold` entry and no `release` entry (`BC11`'s own definition); none → `None`, nothing appended, nothing raised. Otherwise one `release` entry of `exposure(order)` (which `summarise` computes and which is never negative, **B5**; a negative exposure in a loaded snapshot raises `CreditReleaseUnderflowError`), `committed_exposure` reduced by it, one `CreditReleased` with the caller's reason and `context.causation_id` (feature 22 passes its own context: §15.3). A consumed hold is released like any other: `exposure` ignores `consume` (#7 `buyer-credit.ts:252-262`, #8 `BuyerCredit.Release`: both release a consumed order's exposure; §6.3 explains why the saga never asks it to on an operator cancel).
- **`consume`**: an active hold iff a `hold` entry and neither a `consume` nor a `release` entry (`BC12`); else `NoActiveHoldError`. One `consume` entry of `active_hold(order)`; raises **nothing** (`R40`); `committed_exposure` unchanged by construction.
- **Zero-amount hold (`BC38`, gate G1 as recommended).** `CreditLedgerEntry` refuses a **negative** amount (`NegativeLedgerAmountError`), not a zero one; the structural preconditions above then carry a zero hold through `consume` and `release` with one entry each and one `credit.released.v1`. On every ledger with positive amounts the structural predicates and #7's / #8's amount predicates select the same orders (the ledger only ever holds one `hold`, at most one full `consume`, at most one full `release` per order), so no positive-amount behaviour changes; B9's tests assert both readings agree on the four positive shapes.
- **All-or-nothing.** Every method computes and checks before assigning; a raised error leaves `to_snapshot()` unchanged (asserted).

### 5.2 `CreditLedgerEntry`

A `@dataclass(frozen=True, slots=True, kw_only=True)` with `entry_id: UniqueId`, `order_reference: str`, `amount: Money`, `type: CreditEntryType`, `entry_date: datetime`; constructed only by `BuyerCredit` (and by `rehydrate` from a snapshot). Attribute assignment raises `dataclasses.FrozenInstanceError`; the aggregate exposes entries only as a tuple. **`R37`'s "update or deletion attempted"** is read as #7 and #8 read it: through the aggregate's API a reversal appends a `release`, never rewrites (#8 `tasks.md` B7); the `R37` test also asserts the frozen refusal and the tuple. `order_reference` stays a `str`, never parsed by the kernel's canonical `OrderNumber` (which refuses `ORD-000000`): Fulfillment's L23 / FS28 decision, adopted (§16.2). `code` stays a `str` for the same reason.

### 5.3 `summarise` — the crux, one pure function

```text
OrderExposure(order_reference, exposure, open_exposure, active_hold, has_hold_entry, has_consume_entry, has_release_entry)
LedgerSummary(by_order: tuple[OrderExposure, ...], committed_exposure, active_holds, open_exposure)

summarise(entries: Sequence[CreditLedgerEntrySnapshot]) -> LedgerSummary
    exposure(order)      = Σ hold(order) − Σ release(order)
    open_exposure(order) = min(Σ consume(order), exposure(order))
    active_hold(order)   = exposure(order) − open_exposure(order)
    committed_exposure   = Σ_orders exposure(order)
```

The one place `BC5` / `BC6` are computed, by the aggregate and by the list view alike (#7's `credit-exposure.ts`, #8's `CreditExposure.Summarise`). Grouping is a `dict` keyed by the stored `order_reference`, first-seen order (L17). **Width (`BC30`, L25):** every accumulated value — each per-order `Σ hold`, `Σ release`, `Σ consume`, each `exposure`, and each cross-order total — is checked against `[-(1 << 63), (1 << 63) - 1]` as it is produced, raising `CreditLedgerOverflowError` (`credit.ledger_overflow`). Two direct-drive cases (#8's B12): two `hold` entries of one order each `(1 << 62) + 1` (the per-order sum overflows), and the same total split across two orders (only the cross-order sum overflows), so a check placed only on the inner accumulation passes the first and fails the second.

### 5.4 Events and reasons

`domain/events.py` mirrors Fulfillment's: frozen, slotted, keyword-only dataclasses over a `CreditEventBase` (`event_id`, `aggregate_id` = the line's id, `correlation_id` = the order id, `causation_id`, `occurred_at`), `EVENT_TYPE` constants `credit.approved.v1`, `credit.rejected.v1`, `credit.released.v1`, domain types only. Payload fields: `order_reference`, `retailer_code`, `company_code`, `credit_code`, `currency` (all from the **line**, `BC28`), then `held_amount` + `available_credit_after` / `requested_amount` + `available_credit` + `reason` / `released_amount` + `available_credit_after` + `reason`. `credit_code` is always set (the line is resolved before any refusal can be decided).

`domain/reasons.py`: `CreditRejectionReason` (`OVER_LIMIT`, `SIMULATED_CENTS_RULE`, `SIMULATED_FAILURE_RATE`), `AdapterRejectionReason` (`SIMULATED_CENTS_RULE`, `SIMULATED_FAILURE_RATE` — **only**), `to_rejection_reason(reason: AdapterRejectionReason) -> CreditRejectionReason` as a `match` with one arm per member and `assert_never` (L24), `CreditReleaseReason` (`INVOICE_PAID`, `ORDER_CANCELLED`). Plain `enum.Enum` with explicit tokens, parsed by literal lookup (the Orders convention).

### 5.5 Errors

`DomainError` subclasses with dotted lower-case codes (Orders' style): `CreditLimitExceededError` (`credit.limit_exceeded`), `CreditRefusalMismatchError` (`credit.refusal_mismatch`), `CreditReleaseUnderflowError` (`credit.release_underflow`), `NoActiveHoldError` (`credit.no_active_hold`), `InvalidBuyerCreditSnapshotError` (`buyer_credit.invalid_snapshot`), `FactAggregateMismatchError` (`credit.fact_aggregate_mismatch`), `CreditLedgerOverflowError` (`credit.ledger_overflow`), `UnknownCreditEntryTypeError` (`credit_entry.unknown_type`), `NegativeLedgerAmountError` (`credit_entry.negative_amount`). Every message that names an amount renders it with `format_money` (`BC39`, #8 id 102). Application errors (`application/errors.py`, #8 §5.4's placement): `CreditLineNotFoundError(retailer_code, company_code)` (`BC3`), `CreditCurrencyMismatchError(expected, received)` (`BC4`).

### 5.6 Invariants → enforced → proven

| Invariant | Enforced by | Proven by |
|---|---|---|
| **B1** | `evaluate_hold` decides, `approve` refuses, `rehydrate` refuses | `R37`, `R39` domain; `BC9` race |
| **B2** | frozen entry, tuple view, insert-only repository | `R37` domain; D6 (earlier row byte-equal); D8 (write paths) |
| **B3** | entries built in the line's currency; `evaluate_hold` answers `CurrencyMismatch` before `OverLimit` | `BC4`, `BC26`, `rehydrate`'s refusal |
| **B4** | `AlreadyHeld` on any recorded `hold` entry | `BC7` unit + integration, I2 same-order race |
| **B5** | `release` releases exactly `exposure(order)`; `None` when nothing is outstanding | `BC11`, `R41` |

## 6. Transactions and locks

### 6.1 `billing.credit.list` — reads that hold nothing

`CreditReads.list(page, page_size, retailer_code, company_code)`: one `select(Credit)` with the optional exact filters, `ORDER BY retailer_code, company_code`, `offset((page - 1) * page_size).limit(page_size)`; one `count()` for `PageInfo.total`; one `select(CreditItem.credit_id, CreditItem.order_reference, CreditItem.amount, CreditItem.type).where(CreditItem.credit_id.in_(page_ids))`, rows parsed through `parse_credit_entry_type` and folded per line through **the same** `summarise` (#8's shape, `EfCoreCreditReadRepository`; #7 grouped in SQL and converted with `Number(...)`, `credit-read.repository.ts:74-98` — reading rows avoids the `Decimal` sum altogether). `available_credit = credit_limit − committed_exposure`, never read from a column. A short session, no lock, no write (L13).

### 6.2 `billing.credit.hold` — the authoritative decision

Inside one `CreditTransactions.run(work)` attempt, in this order and nothing else:

```text
0. run() pins READ COMMITTED on the session's connection before any statement (BC35, L30)
1. SELECT credits.* FROM credits WHERE retailer_code = :r AND company_code = :c FOR UPDATE   # THE line lock
   -> no row: CreditLineNotFoundError (rollback, NOT_FOUND, nothing written, no fact)          # BC3
2. SELECT CAST(COALESCE(SUM(CASE type WHEN 'hold' THEN amount WHEN 'release' THEN -amount ELSE 0 END), 0) AS bigint),
          count(*) FILTER (WHERE type NOT IN ('hold', 'consume', 'release'))
   FROM credit_items WHERE credit_id = :id                                                     # BC37: int; unknown -> refuse
   -> SQLSTATE 22003 on this statement: CreditLedgerOverflowError                              # BC30, L11
3. SELECT credit_items.* FROM credit_items WHERE credit_id = :id AND order_reference = :ref ORDER BY created_at, id
4. rehydrate -> evaluate_hold:  AlreadyHeld -> reply, nothing written
                                CurrencyMismatch -> CreditCurrencyMismatchError (VALIDATION_FAILED, nothing written)
                                OverLimit -> refuse(OVER_LIMIT)
                                Fits -> port.decide(...) -> approve | refuse(to_rejection_reason(r))
5. save(): approved -> one credit_items row + one outbox row; refused -> one outbox row only
6. COMMIT, then the reply (built from the outcome, returned only after run() returns)
```

Step 1 is an ORM `select(Credit).where(…).with_for_update()` (plain `FOR UPDATE`, L7). Step 2 is the one textual statement (`text()` with bound parameters, a `SELECT`, so not a write for the population test). Step 3 is an ORM select.

**Why it is safe in PostgreSQL** (measured, header): a second hold on the same line waits at step 1; when the first commits, step 2 is a **new statement** with a fresh `READ COMMITTED` snapshot and sees the first's `hold` entry (run A); step 3 likewise sees the first's entry for the same order (B4 / `BC7`). Swapping steps 1 and 2 reads a stale sum (run C); pinning `REPEATABLE READ` reads a stale sum **silently** (runs B, B2: the line row is locked, never updated, so no serialization failure is raised). Both are arms of I1.

**Why one row lock is enough, and why no deadlock can form.** A hold or release transaction locks exactly one `credits` row and holds it to commit; a cycle needs two (#7 `BC9`, #8 §5.5). Billing satisfies `domain-model.md` §8 rule 6 literally — one transaction mutates one aggregate plus its outbox records — which Fulfillment had to argue against (F3); recorded so a reviewer from Fulfillment finds the absence explained (#8 gate row 10). The plain `FOR UPDATE` strength also blocks any ledger insert that skipped the line lock (measured D; `FOR NO KEY UPDATE` would not, E), so a future writer that forgets the lock waits instead of racing. **Rule for features 21 and 22:** every transaction that writes `credit_items` locks the line first, before any `invoices` row (#8 `BI8`'s order), so Billing's multi-row transactions keep one global lock order.

**The credit-decision port runs inside the lock.** `decide` is synchronous by type (L24): no I/O can be awaited while the row is held. The bound adapter is pure.

### 6.3 `billing.credit.release` — and SA-4

The same steps 0 – 3 (one protocol, not two: the line row is needed anyway for `BC3` and for `availableCreditAfter`, #8 §5.6, which is why there is no non-locking pre-read of Fulfillment's kind), then `release(order_reference, ORDER_CANCELLED, correlation_id, context, new_id)`; `None` → nothing written, reply `released: false` with the current `available_credit_after` (`BC25`).

**What SA-4 asks of Billing — and what it does not** (`saga.md` §4.3, lines 221 – 260; #8 id 79). An operator cancellation of a `credit_approved` / `confirmed` order releases the **stock first** and lets Fulfillment decide the race against the requested despatch under **Fulfillment's** one lock (the order's stock rows, built in feature 17, raced in 18). Only when the release wins does the orchestrator issue `credit.release`; when the despatch wins, *"no `credit.release` is issued"*. So `billing.credit.release` arbitrates nothing against despatch: the decision is already made when it arrives, and Billing's own lock (the line row) only serialises the release against holds, consumes and payments on the same line. The late-approval path (*"a `credit.approved.v1` for an order whose operator cancellation has already been accepted … issues `credit.release`"*) arrives at the same responder with the same semantics. **A release of an already-consumed hold** (invoice issued) cannot be issued by the saga — cancellation is impossible from `despatched` onwards and the invoice is issued only after `despatched` — and if it arrived anyway it releases the outstanding exposure, as #7 (`buyer-credit.ts:247-295`, `exposure` ignores `consume`) and #8 (`BuyerCredit.Release`, same summary) both do. Decided by their agreement; no refusal is invented.

### 6.4 `CreditTransactions.run(work)`

Fulfillment's `stock_transactions.py` shape **without the 40P01 re-run** (L31): one `AsyncSession` and one transaction per call, `READ COMMITTED` pinned before the first statement, `work(tx)` with `tx.credits: CreditRepository` bound to the session, commit, then `tx.credits.clear_saved_events()` (only after commit, OI9). A `DBAPIError` whose SQLSTATE is in `TRANSIENT_SQLSTATES` (`40P01`, `40001`, `55P03`, `57014`, `53300`, class `08`; a literal set copied from Fulfillment's module, not imported — service independence) or a pool timeout / `OSError` becomes `StoreUnavailableError` (no SQLAlchemy type crosses into `application`); any other error propagates. `CreditTransaction` is a `Protocol` with one property today, `credits`; feature 21 adds `invoices` and `invoice_numbers` exactly as feature 18 added `despatches` and `despatch_numbers` to `StockTransaction` (`stock_store.py:114-122`).

## 7. The application layer

### 7.1 Messages, handlers, registration

| Subject | Message (`otc_cqrs`) | Result (application dataclass) | Handler → unit |
|---|---|---|---|
| `billing.credit.hold` | `HoldCreditCommand(Command[HoldResult])` | `approved` / `rejected` / `already_held` + amounts, reason, line codes | `HoldCreditHandler` → `credit_hold.hold` |
| `billing.credit.release` | `ReleaseCreditCommand(Command[ReleaseResult])` | `released` + amounts, line codes | `ReleaseCreditHandler` → `credit_release.release` |
| `billing.credit.list` | `ListCreditQuery(Query[CreditPage])` | lines + page info | `ListCreditHandler` → `scope.reads.list` |

The two commands carry `correlation_id` and `request_id` as `UniqueId`; the query carries neither. `composition.register_handlers` registers the three, one plain statement each; `build_dispatcher` validates against `otc_billing.application` (a message with zero or two handlers fails the boot); `start_runtime` builds every registered factory once against a real scope before anything listens (feature 43's carried item). No events, no `EventHandler`: Billing owes no post-commit in-process hop.

### 7.2 Ports and scope

`CreditTransactions.run(work)`; `CreditTransaction.credits: CreditRepository` with `lock_for_order(retailer_code, company_code, order_reference) -> BuyerCredit | None` (§6.2 steps 1 – 3; `None` = no line) and `save(credit) -> None` (inserts `appended_entries`, writes the drained events through the outbox writer in raise order). `CreditReads.list(...)`. `CreditDecisionPort.decide(request: CreditDecisionRequest) -> CreditDecision` (sync; `CreditDecisionRequest` carries order reference, the line's codes, amount, currency and the available credit **before** the hold; `CreditDecision = Approve() | Refuse(reason: AdapterRejectionReason)`). `IdSource.new()`. `BillingScope(transactions, reads, clock, ids, credit_decision)` refuses an unbound port at construction (Fulfillment's `scope.py`).

### 7.3 The transactional units

`credit_hold.hold(command, scope)`: `await scope.transactions.run(work)` where `work` = `lock_for_order` → `None` raises `CreditLineNotFoundError` → `evaluate_hold` → `AlreadyHeld` returns the result (no `save`) → `CurrencyMismatch` raises `CreditCurrencyMismatchError` → `OverLimit` → `refuse(OVER_LIMIT, context, scope.ids.new)` → `Fits` → `scope.credit_decision.decide(request)` → `approve(…, scope.ids.new)` or `refuse(to_rejection_reason(decision.reason), …)` → `save(credit)` → result. `context = CreditContext(occurred_at=scope.clock.now(), causation_id=command.request_id)`. A business rejection is a **result**, never a raise (`saga.md` §7, SO6). `credit_release.release(command, scope)`: `run` with `lock_for_order` → `None` raises → `release(…, ORDER_CANCELLED, …)` → `None`: result `released=False` without `save`; else `save`, `released=True`. `work` touches only `tx` and its own arguments, mints ids per attempt.

### 7.4 The credit-decision port — feature 20's seam

The ordering is the guarantee (#7 gate row 6, #8 §6.2): `B1` is evaluated first, the port is consulted only on `Fits`, and its reason type cannot express `over_limit`, so an adapter can narrow approvals and never widen them. Bound today: `infrastructure/credit/always_approve.py`'s `AlwaysApproveCreditDecision` (pure, returns `Approve()`), chosen in `composition.start_runtime`, which also accepts an optional `credit_decision` argument so the integration host can bind a refusing port (#7's D1 was unreachable at integration level because every harness bound the approving adapter).

## 8. Presentation — the responder

### 8.1 One task class, three subjects

`CreditResponder` is Fulfillment's `StockResponder` (`stock_responder.py:131-237`) with Billing's route table: `start()` subscribes `billing.credit.hold`, `.release`, `.list` (queue group `otc-billing`) with one callback that enqueues `(subject, msg)`, then **awaits `connection.flush()`** (the host is reachable when startup returns, #8 id 63 / 95); `run(stop)` serves each message in its own tracked task; on `stop` it unsubscribes, serves what is queued and `_drain`s every in-flight task with `return_exceptions=True` (`BC22`); `_log_fault` logs a task that could not reply; cancelling `run` cancels the request tasks and re-raises. The route table is a `dict[str, Route]` literal so features 21 and 22 add their subjects as entries (#8 renamed its responder for this, `BI31`; here the class is `CreditResponder`, and feature 21 extends its route table without a rename, as feature 18 did with `StockResponder` — leader correction 2026-10-09, flagged by feature 21's spec author).

### 8.2 The bound

`asyncio.Semaphore(BILLING_MAX_CONCURRENT_REQUESTS)` acquired inside the request task before its unit of work opens a session; engine `pool_size = bound + 1` (the relay's session), `max_overflow = 0`. Default **16**, refused below 1 at boot (Fulfillment's figure and reasoning, `specs/fulfillment_stock/design.md` §8.2).

### 8.3 Per request

```text
no reply subject      -> log WARNING, drop
empty body            -> VALIDATION_FAILED
hold / release        -> headers first (BC1): both present and UniqueId.parse-able, else VALIDATION_FAILED, nothing dispatched
decode                -> from_wire_json(<generated request model>, data); ValueError -> VALIDATION_FAILED
edge checks (BC33)    -> orderReference <= 20 chars; hold amount.amount >= 0; else VALIDATION_FAILED
dispatch              -> dispatcher.send / ask with a fresh BillingScope
reply                 -> to_wire_json(<generated reply model>)  |  to_wire_json(RpcError) via section 8.5
```

### 8.4 Wire mapping (`credit_wire.py`)

`HoldResult` → `CreditHoldReplyPayload(outcome, order_reference, credit_code, currency, held_amount | None, available_credit, reason | None)`: `approved` carries `held_amount`, no `reason`; `rejected` carries `reason`, no `held_amount`; `already_held` carries the **recorded** `held_amount` and the **current** `available_credit` (`BC7`). `ReleaseResult` → `CreditReleaseReplyPayload(released, order_reference, credit_code, currency, released_amount | None, available_credit_after)`. `CreditPage` → `CreditListReplyPayload(items=[CreditView…], page=PageInfo)`. Request `amount` → `Money(amount, currency)`; `order_reference` stays a `str`.

### 8.5 The error mapping — every code is a saga decision

Orders splits the twelve codes into nine terminal (`TERMINAL_RPC_ERROR_CODES`, `nats_saga_commands.py:65-75`) and three transient (`TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`). Every failure this responder can answer:

| Failure | Code | Orders' class | #7 answered | #8 answered |
|---|---|---|---|---|
| Body not JSON / fails the generated model / missing or malformed header / `BC33` edge check | `VALIDATION_FAILED` | terminal | `VALIDATION_FAILED` (`rpc-error-mapper.ts:43`) | `VALIDATION_FAILED` (`BillingErrorMapper.cs:37`) |
| No line for the pair (`CreditLineNotFoundError`, `BC3`) | `NOT_FOUND` (+ `details.retailerCode`, `companyCode`) | **terminal** | `NOT_FOUND` (`:52-58`) — #7's orchestrator retried it | `NOT_FOUND`, terminal (`:41-46`) |
| Currency differs (`CreditCurrencyMismatchError`, `BC4`) | `VALIDATION_FAILED` (+ `details.expected`, `received`) | terminal | `VALIDATION_FAILED` (`:60-66`) | `VALIDATION_FAILED` (`:47-52`) |
| `CreditReleaseUnderflowError`, `NoActiveHoldError` | `PRECONDITION_FAILED` (+ `details.code`) | terminal | `PRECONDITION_FAILED` (`:68-73`) | `PRECONDITION_FAILED` (`:117-126`) |
| `CreditLedgerOverflowError` (`BC30`, incl. the scalar's `22003`) | `DOMAIN_ERROR` (+ `details.code`) | **terminal**, deliberately: it overflows again on every retry | n/a | `DOMAIN_ERROR`, terminal (`:111-114`) |
| Any other `DomainError` (`InvalidBuyerCreditSnapshotError`, `UnknownCreditEntryTypeError`, `storage.integer_out_of_range`, …) | `DOMAIN_ERROR` (+ `details.code`) | terminal | `DOMAIN_ERROR` (`:149-158`) | `DOMAIN_ERROR` (`:154-157`) |
| `StoreUnavailableError` (transient SQLSTATEs incl. `40P01`, pool timeout, refused connection) | `UNAVAILABLE` | transient | `INTERNAL_ERROR` by fall-through (`:164`) | `UNAVAILABLE` (`:161-163`) |
| Anything else | `INTERNAL_ERROR` (message never carries the exception text) | transient | `INTERNAL_ERROR` (`:164-165`) | `INTERNAL_ERROR` (`:167`) |
| `CONFLICT`, `TIMEOUT`, `ORDER_NOT_CANCELLABLE`, `STOCK_UNAVAILABLE`, `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH` | **never produced** by these three subjects | — | `CONFLICT` only for `payment.register` (`:138-145`, feature 22's) | `TIMEOUT` for its own deadline (`:165`); `CONFLICT` for `payment.register` (`:145`) |

A business rejection (`credit.rejected.v1`) is never an `RpcError`: it is the `rejected` outcome. **The retryability guard gets a Billing sibling**: `tests/architecture/test_billing_rpc_error_retryability.py`, the same instrument as `test_fulfillment_rpc_error_retryability.py` (imports both services, reads Orders' set): every transient input maps to a retried code, no input produces `CONFLICT`, and — new — every `DomainError` subclass defined in `otc_billing.domain.errors` and `otc_billing.application.errors` is in its input population (enumerated by `__subclasses__` walk, a literal expected count), so a new error cannot be added without its row.

## 9. Persistence adapters

### 9.1 `credit_repository.py`

Implements §6.2's statements; keeps the loaded `Credit` row and the `BuyerCredit` it built; on `save(credit)`: for each `appended_entries` member `session.add(credit_mapper.new_row(entry, credit_id, created_at=clock.now()))` (one constructor, `updated_at = created_at`), then `OutboxWriter.write(session, credit.domain_events)` in raise order (the copy flushes per row, L20). Domain events are cleared by `run()` only after commit. **Never** an `update(`, `delete(`, `text(` DML or an `on_conflict_*` in this service: every row written is a new ledger or outbox row (L19); the population test makes any other write path an unclassified hit. The `Credit` row is never assigned (B17).

### 9.2 `credit_mapper.py`

The only constructor of `CreditItem` rows; `to_snapshot(credit_row, committed_exposure, item_rows)` parses `type` through the closed map, builds `Money(row.amount, credit_row.currency_code)`, keeps `credit_date` as the aware datetime asyncpg returned (L14). Amounts are assigned as plain `int`; the range guard fires at assignment (L18).

### 9.3 `credit_reads.py`

§6.1's three queries; a session opened and closed per call; no `with_for_update`, no write.

## 10. The outbox: copies, the parity guard, and consumers

### 10.1 What is copied

From `services/orders/src/otc_orders/`: `application/ports/clock.py`, `infrastructure/clock.py` and `infrastructure/outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py` — the nine modules Fulfillment copies, each with a docstring naming its canonical. Service-specific, **not** copies: `infrastructure/outbox/topic.py` (`BILLING_FACTS_TOPIC = "otc.billing.facts.v1"`, #7's constant name, `apps/billing/src/infrastructure/outbox/kafka.config.ts:19`) and `infrastructure/outbox/payloads.py` (`narrow` + `build_fact` for the three credit events, `assert_never` over the union so feature 21's and 22's events are type errors until mapped). Billing's `KafkaSettings` has Orders' field names (`brokers`, `client_id`) so the publisher copy is unchanged.

### 10.2 The parity guard — extended, with a census

`tests/architecture/test_outbox_copy_parity.py` names its services as literals (`ORDERS`, `FULFILLMENT` at lines 41 – 42; one `TOKEN_MAP` at line 56), so a Billing copy is **not** found unless the guard changes. The change:

- `FULFILLMENT` and `TOKEN_MAP` become one literal `COPY_SERVICES: dict[str, tuple[str, dict[str, str]]]` — `"fulfillment": (FULFILLMENT, {"otc_orders": "otc_fulfillment", "ORDERS_FACTS_TOPIC": "FULFILLMENT_FACTS_TOPIC"})` and `"billing": ("services/billing/src/otc_billing", {"otc_orders": "otc_billing", "ORDERS_FACTS_TOPIC": "BILLING_FACTS_TOPIC"})`; `violations(root, service)`, `census(root, service)`, `expected_body(…, token_map)` take the service; the two real-tree tests are parametrised over `COPY_SERVICES`; the `tree` fixture copies every service's files.
- **New census case** (`BC17`'s "required from every service that owns a relational `outbox` table", #8's case 3): every `services/*/src/otc_*/infrastructure/persistence/models.py` containing `__tablename__ = "outbox"` belongs to `{"orders"} ∪ COPY_SERVICES` — found by glob, never from the literal; today `orders`, `fulfillment`, `billing` (`grep -rln '__tablename__ = "outbox"' services/*/src`, three hits).
- **The existing sentinels are re-pointed at Billing as well** (parametrised): the one-character change, the comment-only change, the dead `if False:` region, the triple-quoted string, the missing copy, the extra module, the token in a string the canonical does not hold, the docstring that names no canonical, the missing canonical — each must fail naming the Billing file. New sentinels: a service with an `outbox` table and no copies fails the census; a pristine three-service tree passes.
- `test_the_reflow_the_longer_topic_name_forces_is_real_and_is_what_the_copy_holds` stays Fulfillment's; whether Billing's longer names force a reflow is read, not assumed (`BILLING_FACTS_TOPIC` is one character longer than `ORDERS_FACTS_TOPIC`, `otc_billing` one longer than `otc_orders`); the formatter step already forgives it.

Arms (task F6): one per guarded Billing module (nine), plus the census, each recorded verbatim.

### 10.3 Relay deployment rule

At most one relay per process and no multi-worker server while `OUTBOX_RELAY_ENABLED=true`: `composition.py` carries the same `assert_single_outbox_relay` / `_claim_relay_slot` as Orders' and Fulfillment's (no shared runtime module).

### 10.4 Consumers — none, in 19 and in 21

Billing consumes no fact in #7 (`apps/billing/src/billing-consumes-no-facts.spec.ts`: no `@EventPattern`, no Kafka consumer import; its `BI1`), in #8 (`design.md` §9, `BillingConsumesNoFactsTests`) or in #9: `saga.md` §5 gives Billing no fact, and feature 21's *"issued on order.despatched"* is the orchestrator's `invoice.issue` **command** issued on that fact (`saga.md` §3.1 step 4), not a Billing subscription. No idempotent-consumer copy, `processed_events` unused. The parity guard (`services/orders/tests/unit/test_idempotent_consumer_parity.py`, services found by `glob("*/src/otc_*")`, line 47): case 1 compares copies found (Billing has none); case 3 requires a copy only from a write model with the ledger **and** a consumer — Billing has the ledger and only a producer, so its literal `{"otc_orders"}` stays true. **No case goes live in 19 or 21**; feature 22 dedups by `paymentReference` in `payments`, a different key and table; the cases go live at feature 23 (`notifications_service`). `test_kafka_client_confinement.py`'s literal importer set gains Billing's publisher only, so a consumer import in Billing fails it.

## 11. Composition, lifespan, settings, packages

### 11.1 Settings (`infrastructure/settings.py`)

| Class | Field ← variable | Default |
|---|---|---|
| `BillingDatabaseSettings` | existing (unchanged) | — |
| `OutboxRelaySettings` | `OUTBOX_RELAY_ENABLED`, `OUTBOX_POLL_INTERVAL_MS`, `OUTBOX_BATCH_SIZE`, `OUTBOX_PUBLISH_TIMEOUT_MS` | `true`, 250, 100, 5000 |
| `KafkaSettings` | `KAFKA_BROKERS`, `BILLING_KAFKA_CLIENT_ID` (`pattern=r"^[A-Za-z0-9._-]+$"`) | `localhost:9092`, `otc-billing` (#7 `kafka.config.ts:32`, #8 `BillingOptions.cs:19`) |
| `NatsSettings` | `NATS_URL` | `nats://localhost:4222` |
| `ServerSettings` | `WEB_CONCURRENCY` | 1 |
| `ResponderSettings` | `BILLING_MAX_CONCURRENT_REQUESTS` (≥ 1) | 16 |

Each field has a `validation_alias` and no `populate_by_name` (review_db_fulfillment A1). `.env.example` gains `BILLING_KAFKA_CLIENT_ID=otc-billing` and `BILLING_MAX_CONCURRENT_REQUESTS=16`, each with a comment.

### 11.2 The client id in all three services (`BC34`)

Measured: today `KAFKA_CLIENT_ID=` and `FULFILLMENT_KAFKA_CLIENT_ID=` both produce `client_id == ''` (Orders `infrastructure/settings.py:91`, Fulfillment `:93-95`: a default, no constraint), and aiokafka sends `''` verbatim. **Both need the same change**, made in this feature: `services/orders/src/otc_orders/infrastructure/settings.py` and `services/fulfillment/src/otc_fulfillment/infrastructure/settings.py` gain the same `pattern` on `client_id`, nothing else. A pattern, not `min_length=1`: `" "` passes a length check. Each service's settings test gains the empty and the blank case (failure names the variable); `tests/architecture/test_kafka_client_ids.py` (new) constructs the three `KafkaSettings` with every client-id variable removed from the environment and asserts the defaults are non-empty and pairwise distinct. This crosses into two shipped services on purpose (CLAUDE.md: a finding is fixed in the phase that detects it); feature 22's *"without changes under `services/orders`"* is 22's scope, and this edit is 19's.

### 11.3 `composition.py` and `main.py`

Fulfillment's shape: `BillingSettings` bundle and `load_settings()` (the only environment read); `register_handlers`, `_wire`, `build_dispatcher` (pure); `start_runtime(settings, *, credit_decision: CreditDecisionPort | None = None)`: single-relay check → dispatcher validated before anything opens → engine (`pool_size`, `max_overflow` per §8.2) → session factory → clock, ids, decision port (`credit_decision or AlwaysApproveCreditDecision()`) → NATS connect → transactions, reads → every registered factory built once against a real scope → `CreditResponder.start()` → tasks `nats-responder` and, when enabled, `outbox-relay` → `BillingRuntime` (readiness: a done task or a closed / reconnecting NATS connection is a reason; `stop()` sets the stop event, awaits both tasks, closes the stack). `main.py` is Fulfillment's (`start_runtime(load_settings())`, `app.state.runtime`); `presentation/app.py` gains `create_app(lifespan=…)` and `/health/ready`; the existing `test_billing_health.py` is adapted only if `create_app`'s signature forces it.

### 11.4 Packages

`services/billing/pyproject.toml` gains `aiokafka` and `nats-py>=2.16.0` (the pins Orders and Fulfillment already lock); `uv lock` changes only workspace metadata. `Packages installed: none`. No root `pyproject.toml` change.

## 12. Architecture guards and censuses this feature touches

| Instrument | Change | Why |
|---|---|---|
| `tests/architecture/test_composition_env_reads.py` | `EXPECTED_ROOTS` and `LOAD_SETTINGS_ROOTS` gain `billing`; `EXPECTED_SETTINGS["billing"]` = the six classes of §11.1 | #8 id 56 (recurred three times in #9's Phase 8): written **with** the root |
| `tests/architecture/test_registration_behaviour.py` | `SERVICES` gains `billing`; `TABLES["billing"]`: commands `HoldCreditCommand`, `ReleaseCreditCommand`; queries `ListCreditQuery`; events none | feature 43's carried item |
| `tests/architecture/test_write_path_population.py` | `EXPECTED["billing"]` gains every new hit, counts read from `scan_service("billing")`, each classified | feature 207; §9.1 |
| `tests/architecture/test_kafka_client_confinement.py` | `EXPECTED_IMPORTERS` gains `otc_billing.infrastructure.outbox.kafka_publisher` | the third producer |
| `tests/architecture/test_outbox_copy_parity.py` | extended (§10.2) | `BC17` |
| `tests/architecture/test_billing_rpc_error_retryability.py` | **new** | `BC27`, L23 |
| `tests/architecture/test_kafka_client_ids.py` | **new** | `BC34`, L26 |
| `test_range_guard_parity.py`, `test_money_guard.py`, `test_cqrs_registration_explicit.py`, `test_import_contract_coverage.py`, idempotent-consumer parity | **no edit**; must stay green | no range-guard change; the domain imports only allowed roots; no new decorator kind |

## 13. Testing

### 13.1 Files and levels

| File (under `services/billing/tests/`) | Level | Proves |
|---|---|---|
| `unit/domain/test_buyer_credit.py`, `test_credit_hold.py`, `test_credit_ledger.py`, `test_credit_exposure.py`, `test_credit_ledger_entry.py`, `test_credit_ids.py`, `test_domain_tests_are_pure.py` | domain unit, pure | R37 – R41, BC5 – BC7, BC10 – BC12, BC14, BC26, BC28, BC30, BC36, BC38 |
| `unit/test_credit_hold_service.py`, `test_credit_release_service.py`, `test_credit_decision_port.py`, `test_always_approve.py` | unit, fakes | BC7, BC13 – BC15, BC36's seams, reply after commit, rollback ⇒ no reply |
| `unit/test_credit_transactions.py` | unit, fake session factory | the transient mapping, events cleared only after commit |
| `unit/test_credit_responder.py`, `test_credit_requests.py`, `test_credit_subjects.py`, `test_fact_topic.py`, `test_credit_rpc_errors.py`, `test_credit_wire.py` | unit | BC1, BC21 scope, BC22, BC33, BC39, every row of §8.5, every schema constraint, reply key sets |
| `unit/test_outbox_payloads.py`, `test_credit_mapper.py` | unit | the three payload mappings field by field; row construction |
| `unit/test_billing_settings_env.py` | unit | every variable reaches exactly its field; BC34 |
| `integration/test_credit_hold.py`, `test_credit_hold_race.py`, `test_credit_release.py`, `test_credit_list.py`, `test_credit_wire.py`, `test_credit_responder_concurrency.py` | integration (real PostgreSQL + NATS through the real lifespan) | R38/R39 halves, BC1 – BC4, BC6 – BC9, BC14, BC21, BC25, BC28, BC35, BC38 |
| `integration/test_credit_repository.py` | integration (PostgreSQL) | BC10 rollback, BC24, BC30, BC35, BC37, append-only at SQL level |
| `integration/test_billing_outbox_relay.py` | integration (+ Kafka) | BC16 |
| `integration/test_billing_host_lifespan.py` | integration | boot validation, readiness, shutdown, the reach test, single relay |
| `tests/architecture/…` | architecture | §12 |

### 13.2 Fixtures and the synchronisation rule

A `billing_host` factory fixture (function loop, Fulfillment's `fulfillment_host_factory` shape) boots the **real** `start_runtime` against `migrated_db`, the root `nats_server` and, when asked, `kafka_server` (relay disabled by default; the relay test drives `run_once()` by hand), with an optional `credit_decision` (default: the always-approve adapter) so any test can bind a **refusing** port. Callers are raw `nats.connect()` clients. Integration suites pass with the developer stack down. The request helper refuses a hold amount with `amount % 100 == 99` unless the test passes `allow_cents_rule=True` (#7 `test-support/cents-rule-fixture-guard.ts`, #8 `CentsRuleFixtureGuard.cs`; #8 feature 20's N2: inherit the guard, not the search), so feature 20's simulator cannot silently change a feature-19 fixture.

**Synchronise only on terminal or monotonic evidence**: the reply; an outbox row (written in the reply's transaction); the count of the append-only `credit_items` rows; a lock request seen **ungranted** in `pg_locks` (`wait_for_lock_waiters`, Fulfillment's conftest helper, copied into Billing's conftest); never on a derived amount mid-flight, never on a sleep.

**Every emitting or suppressing branch opens its row** (#8 D3, #7 D1 / W3): the approved, rejected and released outbox rows are each read back and every payload field and the envelope's `aggregateId`, `correlationId`, `causationId` asserted against **test-supplied, pairwise-distinct** values (order id ≠ request id ≠ line id; `retailerCode` ≠ `companyCode`, neither containing the other; amounts distinct and non-zero except in `BC38`'s own case); each suppression (`already_held`, `NOT_FOUND`, `VALIDATION_FAILED`, `released: false`, list) asserts zero rows **with a control row** in the same test. **Every reply decode asserts the reply's own discriminating field first** (`outcome`, `released`, `page.total`, or `code` for an error) before any collection (`BC32`).

### 13.3 The constructed races (a change of kind, not of probability)

- **I1 — `BC9`, the line race.** The test's own connection holds `FOR UPDATE` on a line with room for exactly one of two holds; two holds for different orders are sent; the test waits until **two** lock waits are ungranted (any statement), then commits. Correct code: one `approved`, one `rejected` (`over_limit`), final `Σ hold − Σ release ≤ credit_limit`, exactly one `credit.approved.v1` and one `credit.rejected.v1`. Arms: (a) drop `with_for_update` — both read 0 and decide `approved`, both then wait at their insert on the FK's key-share (measured D), both commit: "exactly one approved" fails; (b) read the scalar before the lock (measured C); (c) pin `REPEATABLE READ` (measured B2). Each arm fails on the same named assertion; each is recorded.
- **I2 — B4, the same-order race.** As I1 with two holds for the **same** order and room for both: one `approved`, one `already_held`, exactly one `hold` row. Arm: read the order's entries before the lock.
- **I3 — `BC21`.** The test holds line A; a hold for A is sent and seen waiting; a hold for B must be **answered** while A still waits; then the test commits and A completes. Arm: serve inline in the loop — B times out (`asyncio.timeout` around B's request, the failure message names `BC21`).
- **I4 — the release lock.** The test holds the line; `credit.release` is sent and seen waiting before the test commits; then it completes. Arm: drop `with_for_update` — the release is never seen waiting.

### 13.4 Matrix name mapping

| `specs/shared/test-matrix.md` §5 path | #9 file |
|---|---|
| `billing/domain/buyer-credit.spec` | `services/billing/tests/unit/domain/test_buyer_credit.py` |
| `billing/domain/credit-hold.spec` | `services/billing/tests/unit/domain/test_credit_hold.py` |
| `billing/domain/credit-ledger.spec` | `services/billing/tests/unit/domain/test_credit_ledger.py` |

## 14. The live stack — designed, not discovered (`BC20`)

**Pre-state** (`progress/current.md`; `progress/impl_fulfillment_despatch.md` §11): `ORD-000008` is `stock_reserved` with one `reserved` reservation (`IBERFOODS` `PRD-0001` × 4) and a `parked` `credit.hold`; `ORD-000007` is `stock_reserved` with a `parked` `credit.hold`, but Fulfillment already holds `DES-000006` for it with both reservations `consumed`. **Both parked rows will be re-issued by the sweeper** as soon as a responder answers — `ORD-000007` cannot be "left parked" while Billing runs. The seed holds 154 lines at 500 000 minor units (`services/seed/src/otc_seed/domain/data/credits.py`); the seeded ledger rows net to zero per line (read, not assumed, in task K1).

**Expected, unattended,** once Orders (`--port 8101`), Fulfillment (`--port 8102`) and Billing (`uvicorn otc_billing.main:app --port 8103`) are up, within one sweeper interval of each row's `next_attempt_at`:

- **`ORD-000008`**: Billing answers `approved`; one `hold` row; one `credit.approved.v1` stamped published; the row `sent`; Orders `stock_reserved → credit_approved → confirmed`, `despatch.create` answered by Fulfillment (`DES-000007`, reservation `consumed`), `order.despatched.v1`, `despatched`, then `invoice.issue` → no responder → `parked`. **The second live proof of park-and-resume** (after `stock.reserve` in Phase 9).
- **`ORD-000007`**: Billing answers `approved` (one `hold` row, one fact); Orders reaches `confirmed` and issues `despatch.create`, which Fulfillment answers `created: false` with no fact (F8), so the order **stops at `confirmed`** with its hold placed. Recorded as the expected consequence of the Phase 9 out-of-band despatch, not as a failure.
- **Cross-service proof by query of all three databases**: each fact's `correlation_id` equals `otc_orders.orders.id` and its `causation_id` equals that order's `credit.hold` `saga_commands.id`; `available_credit` of `CR-000001` (the `CarrefourEs` / `IBERFOODS` line, if that is the pair — read from the orders) equals 500 000 minus the two holds, computed by hand and read back through `billing.credit.list`.
- **One genuine over-limit order, no simulator bound** (`R44`'s last clause before feature 20, #8 I3): a fresh order whose total exceeds the line's remaining credit and whose `total % 100 ≠ 99`, chosen from the read-back figures; observed `credit.rejected.v1` (`over_limit`) → `stock.release` → `stock.released.v1` → `cancelled` / `credit_rejected`, and `credit_items` gains **zero** rows for it.
- **One `billing.credit.release` over raw NATS** for a **throwaway** order the walkthrough itself held (never `ORD-000007` / `ORD-000008`, whose saga must not be disturbed): `released: true`, one `release` row, one `credit.released.v1`; an immediate repeat answers `released: false` with no second row or fact.

Hosts stopped by PID; the record goes to `progress/impl_billing_credit.md` § Live boot, **including a register entry of every live fixture the walkthrough changes** (#8 feature 21's lesson: the feature that alters a shared fixture records it in the same pass).

## 15. Seams for features 20, 21, 22 — and what each must not rediscover

### 15.1 Feature 20 `billing_credit_simulator`

Footprint: `infrastructure/credit/simulator.py` (new: the `.99` rule evaluated **before** the failure-rate draw, an injected random source), a `CreditSimulatorSettings` class in `infrastructure/settings.py` (`CREDIT_FAILURE_RATE`, `R43`'s boot validation as a pydantic validator; #8 feature 20's ledger row: `NaN` / `Infinity` must still be refused), `composition.py`'s default binding, and the env-reads literal. **No** `domain/`, `application/` or `presentation/` file changes (`BC15`). `decide` is synchronous (L24), so the random source is a plain callable. The fixture guard of §13.2 is already in place.

### 15.2 Feature 21 `billing_invoicing`

`BuyerCredit.consume` ships tested and uncalled; `lock_for_order` is callable inside 21's transaction; `CreditTransaction` gains `invoices` / `invoice_numbers`; **the line row is locked before the invoice row** (§6.2's rule); the route table takes `billing.invoice.issue` / `.list` as entries; `INV-` follows the `DES-` allocator and its guards (`sequences.py`'s seed statement is already backlog 211's). A zero-total order reaches 21 with a zero `hold` (G1 as recommended) and must consume (`BC38`).

### 15.3 Feature 22 `billing_remittance_intake`

`release` takes the reason and a `CreditContext` from its caller, so 22 can make `credit.released.v1`'s `causationId` the `payment.received.v1` `eventId` (#8 id 57) and give the two facts distinct, ordered envelopes; both rows go through the per-row writer in emission order on the same key (#8 §8.5); `release`'s `None` (nothing outstanding) must not be discarded (#8 feature 22's N3). The `billing.credit.release` responder already exists for feature 41's caller.

## 16. Gate points, and what was decided without one

**The rule** (maintainer, Phase 8): where #7 and #8 decided the behaviour identically and only the mechanism is Python's, it is decided with citations; only a question they disagree on, or one #9's engine forces, goes to the gate, with a recommendation and evidence from a command.

### 16.1 Open for the gate

**G1 — a zero-amount `credit.hold` (`BC38`, `BC11` / `BC12` notes).** *#7 and #8 disagree, and neither completes the cycle.* #7 approves a zero hold (no positivity check: `approveHold` appends whatever fits, `buyer-credit.ts:172-209`) and then cannot consume it (`consumeHold` throws `NoActiveHoldError` when `activeHold <= 0`, `:305-309`): the order stops at `despatched`. #8 refuses it (`CreditLedgerEntry.Create` throws when `amount <= 0`, `CreditLedgerEntry.cs:37-44`; `DOMAIN_ERROR`, terminal in Orders): the order stops at `stock_reserved` with a `rejected` saga row. **Reachable in #9:** `domain-model.md` **O3** allows `totalAmount = 0`; Orders refuses only a negative total (`services/orders/src/otc_orders/domain/order.py:244`, `grep -n "is_negative" …/order.py`); `orders.create` accepts `lineDiscount` and `orderDiscount` (`asyncapi.yaml:3147-3152`). **Recommendation: approve it, as `R38`'s text requires** (*"an order whose total amount is less than or equal to the retailer's available credit … SHALL append a `hold` ledger entry … and SHALL emit exactly one `credit.approved.v1`"* — `0 ≤ available`), and read `release` and `consume` by `BC11`'s own definition of outstanding (a `hold` entry and no `release` entry) and its `BC12` counterpart, so a zero-total order is consumed at invoice issue and released with one `credit.released.v1` at payment, and the saga completes. Cost: one entry rule (refuse negative, accept zero), two structural predicates, one domain test and one integration case; positive-amount behaviour is unchanged (§5.1, asserted on the four positive ledger shapes). No `SA-6`: `R38`, `R40` and `R41` are each satisfied literally. *If overruled (adopt #8):* `NegativeLedgerAmountError` becomes "non-positive", the zero hold answers `DOMAIN_ERROR` (terminal), `BC38` is withdrawn, the zero-total order stays stuck at `stock_reserved` as in #8, and that is recorded as an accepted divergence from `R38`'s literal text with a re-open trigger (any order placed with a zero total).

### 16.2 Decided (with the reason, never offered as an option)

The `BC` reuse and its texts (`requirements.md` §2); the two-term exposure identity over `domain-model.md` §5.1's literal formula (#7 and #8 gate row 2 / 3); `already_held` on any recorded `hold` entry (`BC7`, #7 gate row 4, #8 inherited); a rejected hold re-evaluated (`BC8`); the port consulted only on `Fits`, unable to say `over_limit` (#7 gate row 6, #8); `BC26`'s precedence (#7 review N1, #8 pinned); `billing.credit.release` built now (#8 gate row 13: the subject exists in the inherited contract); no consumer and no idempotent-consumer copy (#7, #8; §10.4); `NOT_FOUND` / `VALIDATION_FAILED` / `PRECONDITION_FAILED` / `DOMAIN_ERROR` as #7 and #8 answer, `CONFLICT` banned on these subjects (§8.5); `updated_at = created_at` on the ledger (§1); no `CR-` allocator (§1); release of a consumed exposure (§6.3); a negative hold amount refused (#8; #7 had no check and a negative entry would raise available credit — a defect, not a choice); exact, case-sensitive code matching (feature 17's G2 ruling, approved 2026-10-08, same engine and same reason); order reference and credit code routed as `str`, never kernel-parsed (feature 17's L23 / FS28); `READ COMMITTED` pinned (forced: `REPEATABLE READ` reads a stale sum silently, measured); no in-process deadlock re-run (one row per transaction; neither predecessor re-ran in Billing); `decide` synchronous (narrower than #7's "sync or async" and #8's `ValueTask`, and the narrowing is what makes "no I/O under the lock" structural); the relay-family parity extended now with a census (#9's guard exists since feature 17); the `BC34` pattern applied to Orders and Fulfillment in this feature (a finding is fixed in the phase that detects it); no migration (§1).

## 17. Inherited findings → decision or task

### 17.1 #8's backlog, Billing area — one row per entry

**Population, enumerated** (not the keyword sample): (a) every #8 entry whose `phase` is 10 — `python3 -c "import json; …[f['id'] for f in fs if f.get('phase')==10 and f['id']>38]"` → 48 – 55; (b) every entry opened during #8's Phase 10 per its history (`../order-to-cash-dotnet/progress/history.md` lines 1215 – 1410): 55 (feature 21's review), 56 (feature 20's A1), 57 (feature 22's N1); (c) every later entry whose text names a Billing mechanism — a full-text search of every entry with id ≥ 39 for `billing|credit|invoice|remittance|payment|phase 10` (run this session: 31 hits, `31, 41, 50, 52, 55, 56, 57, 62, 63, 64, 66, 67, 68, 70, 71, 72, 74, 76, 77, 78, 79, 83, 84, 85, 86, 91, 92, 100, 102, 110, 111`) plus a title read of every entry 58 – 111 for a Billing mechanism the keywords miss, which added **87** (the outbox relay, copied into Billing). Union: 37 entries. Each is classified below.

| #8 id | Billing-area? | Disposition in #9 |
|---|---|---|
| 31 `api_tests` | No — a plan feature; its Billing mention is the API script's duplicate `paymentReference` | #9 feature 31 |
| 41 `orders_cancel_responder` | No — Orders; it is the caller of `billing.credit.release` | #9 feature 41; this feature builds the responder it calls (`BC25`) |
| 48 fresh `NatsHeaders` per call | No — Orders' adapter | Already avoided by feature 16 (`nats_saga_commands.py:143`, its L19); `BC31` not claimed |
| 49 release fact minted its own id | Yes, by class (the id port at every fact and entry site) | **Avoided**: `BC36`, six per-site arms (B6) + the two application seams (C3, C4) |
| 50 responder shutdown rethrew | Yes — the third responder copy | **Avoided** by porting Fulfillment's `_drain`: `BC22`, E7 |
| 51 hand-retyped payload key lists | Yes — Billing's payload tests would have been the fourth copy | **Avoided by construction** (generated models, drift-tested); `BC23` not claimed; reply key sets per outcome in F3 |
| 52 retroactive ledger sweep | No — pre-ledger services | n/a: every #9 port carries its ledger from the start (CLAUDE.md) |
| 53 reply-shape assertions that only throw | Yes, by class | **Avoided**: `BC32`, the enumeration task H8 |
| 54 un-hinted in-transaction re-read | Yes, by class (every Billing ledger read is after the lock) | **Avoided**: `BC35`, measured, armed with `REPEATABLE READ` (D4, I1) |
| 55 `BC32` false at six sites (three in Billing's `CreditListTests`) | Yes | **Avoided**: H8 enumerates every reply decode in Billing's tests, rooted at the decode, before the feature is submitted |
| 56 composition-root env reads unguarded | Yes — Billing's root | **Avoided**: the env-reads guard, the per-variable settings test and the lifespan reach test, written with the root (G1 – G4) |
| 57 completion pair has no causal edge | Yes | **Assigned to feature 22** (the payment caller); 19 leaves the seam (`release` takes the caller's `CreditContext`, §15.3) |
| 62 operator cancel races saga progress | No — Orders' serialisation | #9 feature 41 (Orders) |
| 63 readiness retry loops unpaced (incl. `BillingHostFixture`) | Yes — Billing's test host | **Avoided**: the host is reachable when `start()` returns (`flush()` after subscribing, E8); no wait loop exists |
| 64 Orders' wire-key theory compares a list to itself | No — Orders | n/a (generated models) |
| 66 operator note to the timeline | No | #9 feature 41 / 24 |
| 67 design-time `DbContext` factory env reads (incl. Billing's) | Yes — Billing's migration tooling | **Avoided**: `alembic/env.py` reads only through `BillingDatabaseSettings` (`env.py:16, 26`), whose fields are guarded by the settings test |
| 68 composition-root delegation and wiring unguarded | Yes — Billing's `Program.cs` | **Avoided**: no `Program.cs`; `main.py`'s lifespan calls `start_runtime(load_settings())` and the lifespan reach test drives it (G4) |
| 70 retyped key lists in three more files | No — Orders' and Fulfillment's files | n/a |
| 71 operator note across compensation | No | #9 feature 41 |
| 72 matrix rows outliving their closer | No — R61 / R1 | n/a here |
| 74 DLQ tests select by position | No for 19 (Billing has no consumer or DLQ) | The relay integration test selects its record by `correlationId`, never by position (F5); DLQ is feature 27 |
| 76 application layer depends on infrastructure (Billing had 10 files) | Yes | **Avoided** by the existing `layers-billing` import-linter contract (`pyproject.toml:303-310`); `application` imports no `otc_contracts` either (§2) |
| 77 test hosts exhaust inotify | No — .NET reload watchers | n/a (no reload in any fixture, CLAUDE.md) |
| 78 doc-comment crefs never checked | No — .NET | n/a |
| 79 SA-4 release order in #7 | No — #7's Orders | Read for this feature: §6.3 records what SA-4 asks of Billing (nothing under its own lock against despatch) |
| 83 layering rule blind inside async lambdas (Billing's dominant shape) | Yes | n/a in #9: import-linter reads the import graph, not call shapes |
| 84 Gateway's third copy of RPC payloads (`CreditListReplyPayload`) | No — Gateway | #9 feature 25 (generated models are shared in `otc_contracts`) |
| 85 container fixtures self-assign ports (Billing's Kafka fixture) | Yes — Billing's test fixtures | **Avoided**: the root `conftest.py` fixtures, ports held by Docker (CLAUDE.md), reused |
| 86 delegation guard anchors a call shape | No — a guard instrument | n/a |
| 87 relay deadlock victim escapes `run_once` | Yes — the relay is copied into Billing | **Avoided**: the canonical relay classifies `40P01` (`services/orders/src/otc_orders/infrastructure/outbox/relay.py:46-48`), and the parity guard keeps Billing's copy identical |
| 91 #7's `hasAcceptedOperatorCancel` unguarded | No — #7's Orders | n/a |
| 92 #7's late approval uncovered | No — #7's Orders | n/a (Billing's half of the late-approval path is `BC25`) |
| 100 timeline money in minor units | No — projector | #9 feature 24 |
| 102 problem-detail money in minor units | Yes — Billing errors name amounts | **Avoided**: `BC39`, E6's message cases |
| 110 saga adapter reply decode unguarded | No — Orders | Already avoided by feature 16 (SO15) |
| 111 relay poison row unverified | Yes — the relay copy | **Avoided** by the canonical: `run_once` handles a poison row per row (`specs/outbox_and_idempotency/design.md` L21, `OI18`), inherited through the parity guard |

### 17.2 #7's and #8's feature-19 review findings

| Finding | Disposition |
|---|---|
| #7 **D1** (port-refusal branch emitted no fact; every harness bound the approving adapter) | **Avoided**: C3 asserts the fact on the saved aggregate, armed by deleting the `refuse` call; the host fixture binds a refusing port (H3) |
| #7 **W3 / N5**, #8 **D3** (fact payload corruption survived; identity fields of two facts unguarded) | **Avoided**: every field of every fact asserted against distinct supplied values; per-fact corruption arms (B8, C3, C4, H2, H3, H5) |
| #7 **N1** (`already_held` vs currency precedence unpinned) | **Avoided**: `BC26`, armed in B8 |
| #8 **D1** (the prescribed mutation was never run; the guard re-implemented the conversion) | **Avoided**: D6 reads through the mapper; every arm names its exact mutation and the implementer runs it (tasks preamble) |
| #8 **D2** (a backlog closure at the wrong sites) | n/a: this feature closes no #8 backlog entry by editing named sites; each avoided row above names the instrument |
| #8 **D4** (malformed `x-request-id` unguarded) | **Avoided**: E5 has a case per header per failure |
| #8 **A1** (empty client id at runtime) | **Avoided**: `BC34` in all three services |
| #8 **A2** (`BC23` did not reach nested schemas) | n/a: generated models cover nested schemas |
| #8 **A6** / id 55 | **Avoided**: H8 |
| #9 feature 17 rejection (three mutations survived: a lock method's read order, the id port at the application seam, a refusal branch) | **Avoided by task J1**: every call site of every hand-built seam is mutated, not only the seam |

## 18. Non-goals

No migration and no change to `models.py`, `range_guards.py`, `types.py`, `sequences.py` or `alembic/`. No change under `services/orders/src/` or `services/fulfillment/src/` except the one `client_id` field each (`BC34`). No change to `packages/`. No idempotent-consumer copy, no Kafka consumer. No invoice, payment or simulator code. No `traceparent`, `x-deadline-ms`, structlog or metrics. No edit to `specs/shared/` beyond column 5 of `R37` – `R41` and the derived counts.
