# Design — `orders_aggregate` (feature 13)

> **Where the value of this document is.** The requirements were inherited (R5 – R10); the realisation was not. Everything below is Python 3.14 / `mypy --strict` specific: which modules, which `Enum` and which frozen dataclass, how Table T-1 is held, how a property C# and TypeScript enforced at compile time is enforced here, how the aggregate will map onto the PostgreSQL schema feature 9 already migrated, and which `DomainError` codes features 15, 16, 41 and 42 will branch on. §2, the ported-idiom ledger, is the part a reviewer should read first.

## 0. Scope

| In scope | Out of scope (and who owns it) |
|---|---|
| `services/orders/src/otc_orders/domain/**` — the `Order` aggregate root, `OrderLine`, the closed vocabularies, Table T-1, four domain events, the domain errors, the snapshot types | The repository port and adapter, the row↔snapshot mapper, code↔id resolution (§9 is their binding contract) — features 14 / 15 |
| `services/orders/tests/unit/domain/**` and one contract-parity test file beside it — pure domain unit tests | Outbox rows, Kafka, NATS, the dispatcher, handlers, the RPC error mapper — features 14, 43, 15, 16, 41 |
| The architecture-test edits this code forces (money-guard import allow-list gains `enum`; write-path census classifies the domain's `Money.add` calls) and, under OP-1 A, the kernel's `money_text` module | Any change to `infrastructure/`, the migration, the seed's data |

The boundary is inherited: #7 drew it at its own gate (*"the repository adapter deliberately not built — port interface only, adapter deferred to feature 15"*, #7 `progress/history.md:760`), and #8 drew the same line (#8 `specs/orders_aggregate/design.md` §0).

The aggregate is **synchronous and pure**: no I/O, no `async def`, no clock read. CLAUDE.md's *"async throughout"* governs layers that do I/O; a coroutine in the domain would be a design error, not compliance (#7 `apps/orders/src/domain/order.ts:1-4`; #8 `src/Orders/Domain/Order.cs:13-18`).

## 1. Layout

```
services/orders/src/otc_orders/domain/
  __init__.py                      exists; stays empty (no re-export surface to drift)
  value_objects/__init__.py        exists; MUST survive (tests/architecture/test_money_guard.py:308 lists it)
  value_objects/order_status.py    OrderStatus (Enum) + parse_order_status
  value_objects/cancellation_reason.py   CancellationReason (Enum) + parse_cancellation_reason
  value_objects/compensation_step.py     CompensationStepKind (Enum) + CompensationStep (frozen dataclass)
  state_machine.py                 Edge (NamedTuple), LEGAL_EDGES (frozenset), is_legal
  instants.py                      require_utc
  totals.py                        OrderTotals (frozen dataclass) + compute_totals
  order_line.py                    OrderLine (Entity), OrderLineInput (frozen dataclass)
  snapshot.py                      OrderSnapshot, OrderLineSnapshot (frozen dataclasses, no totals)
  events.py                        OrderEventBase + OrderPlaced/OrderPlacedLine/OrderConfirmed/OrderCompleted/OrderCancelled + OrderEvent alias
  errors.py                        the twelve DomainError subclasses of §10
  order.py                         Order (AggregateRoot)
```

Every file is under `domain/`, so the domain-purity import-linter contract (`pyproject.toml`, `id = "domain-purity"`), the layers contract and the AST money guard (`tests/architecture/test_money_guard.py`, walking `services/*/src/otc_*/domain/**`) cover each one the moment it exists. No file under `domain/` imports anything but the standard-library roots of the guard's allow-list, `otc_shared_kernel`, and `otc_orders.domain` itself.

## 2. The ported-idiom ledger

One row per idiom: *#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z.* Each half is cited from the checkouts on disk (`../order-to-cash-nestjs`, `../order-to-cash-dotnet`). Where #9 must hand-build a property that #7 or #8 got from a compiler, an engine or a library, the **Guard** column names the test in `tasks.md`; every such guard is a flagged arming task.

| # | Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Guard |
|---|---|---|---|---|---|
| L1 | Closed status set, with storage/wire tokens | A string-literal union plus `isOrderStatus` (`order-status.ts:8-25`); the token **is** the value | `enum OrderStatus` plus an explicit token `switch` and an ordinal `Parse` (`OrderStatus.cs:13-72`) | `enum.Enum` (**not** `StrEnum`) with each token written as an explicit `.value` (no `auto()`, no `.name.lower()`); `parse_order_status` is a literal `dict` lookup that first requires `type(token) is str`. Plain `Enum` so a raw `"placed"` from a row never compares equal to `OrderStatus.PLACED` and must be parsed; `mypy --strict` (`strict_equality`) flags a stray `status == "placed"`. | 2.2 token tests (spec transcription + generated contracts, both directions) |
| L2 | Closed cancellation-reason set | Literal union + `isCancellationReason` (`order-cancellation-reason.ts:6-13`) | `enum` + `Parse(string?)` with two codes (`CancellationReason.cs:11-58`) | As L1; `parse_cancellation_reason` raises `order.cancellation_reason_required` on `None`/blank and `order.cancellation_reason_unknown` on anything else outside the set. | 2.2, 4.10 |
| L3 | Token comparison is exact (case, whitespace) | `Array.includes` strict equality (`order-status.ts:24`) | `StringComparison.Ordinal` / exact `switch` (`OrderStatus.cs:60-72`) | `dict` lookup after `type(token) is str`: case- and whitespace-exact by construction, and a `str` subclass (an `Enum` of another package, a `StrEnum` member) is refused. | 2.3 |
| L4 | `status` cannot be assigned from outside | TypeScript `private props` (`order.ts:114`), compile-time | `public OrderStatus Status { get; private set; }` (`Order.cs:68`), compile-time | **No compiler does this here.** A read-only `@property` with no setter; `__slots__` on `Order` (the kernel's `AggregateRoot` already has slots, `entity.py:36`), so no stray attribute can be added; the backing `_status` is written in exactly two functions (`__init__`, `_transition_to`) and read nowhere outside the class. Python privacy is a convention, so the single-writer property is a **structural test**. | 3.13, 3.14 |
| L5 | Totals and reason cannot be assigned from outside | Getters only (`order.ts:289-303`) | `private set` (`Order.cs:71-80`) | As L4: read-only properties, `_initial_amount`/`_initial_discount`/`_total_amount`/`_lines` written only by `__init__` and `_commit_lines`; `_cancellation_reason` only by `__init__` and `_transition_to`. | 3.13, 3.14 |
| L6 | Table T-1 as immutable data | An array plus a `Map` built at module load (`order-transitions.ts:25-132`) | `FrozenSet<readonly record struct>` (`OrderStateMachine.cs:29-52`) | `LEGAL_EDGES: frozenset[Edge]` where `Edge(NamedTuple)` has value equality and hashing. The set is immutable; the module **name** can still be rebound (residual: no Python construct prevents it; nothing in `otc_orders` rebinds it, and the transcription test reads the bound value at run time). | 2.5 |
| L7 | Exhaustive dispatch over a closed set | TS union narrowing | `switch` expression with a throwing default (`OrderStatus.cs:35-47`) | `match` with `case _: assert_never(x)` (`typing.assert_never`), checked by `mypy --strict`; tables over all members (`OrderStatus` → frozen-or-not) are `frozenset` literals compared against the spec in tests. | 2.2, 3.9 |
| L8 | Collections handed in are not aliased; collections handed out cannot mutate the aggregate | `Object.freeze` on line views (`order.ts:274-287`, its OA5) and `[...compensationSteps]` (`order-events.ts:121`) | `IReadOnlyList` over a private `List` (`Order.cs:87`) and `new List<>(compensationSteps)` (`Order.cs:242`) | Every sequence parameter is copied with `tuple(...)` on entry; every sequence on the aggregate, a snapshot or an event is a `tuple`; `OrderLine` is immutable (read-only properties, `__slots__`). A frozen dataclass holding a `list` would still be mutable through the list, so **no `list` field exists** on any domain dataclass. | 3.12, 4.13 |
| L9 | Integer width and overflow of money | `Money.of` refuses any non-safe integer (`packages/shared-kernel/src/domain/money.ts:50-59`), so an overflow surfaces as `InvalidMoneyAmountError` at 2^53 | `checked` arithmetic (`src/SharedKernel/Money.cs:46-60`), so an overflow is an `OverflowException` (not a domain error) | Python `int` never wraps; the kernel's `Money.__post_init__` refuses anything outside signed 64-bit (`packages/shared_kernel/src/otc_shared_kernel/money.py:44`), so an overflowing product or sum raises `InvalidMoneyAmountError` (`money.invalid_amount`) **inside** `compute_totals`. Candidate-then-commit (§5.3) is what makes that refusal leave the order unchanged; the Money half is already guarded in the kernel (`test_r1_money_refuses_an_amount_beyond_the_bigint_column`). | 3.11 |
| L10 | No division, no float in money | No `number` arithmetic on amounts (`order-totals.ts:1-4`) | `long` only; reflection rules over the domain (#8 `tests/Architecture.Tests/DomainDecimalTests.cs`) | Integer division question answered by construction: totals use only `Money.add`/`subtract`/`multiply`; the AST money guard refuses `/`, `float`, `round`, `pow` in every domain file. Nothing new owed. | existing `test_money_guard.py` |
| L11 | Money arithmetic is type-checked | TS types on `add(other: Money)` | C# overloads take `Money` | **Typing gap:** the kernel's dunders are typed `other: object` (`money.py:77-110`), so `mypy` accepts `money + 5` and only the run time refuses it. The domain therefore uses the **named** methods `.add()`/`.subtract()`/`.multiply()`, which `mypy --strict` checks (`packages/shared_kernel/tests/test_mypy_rejects_float.py`). Consequence: `test_write_path_population.py` counts every `.add(` call in `services/orders/src` (`CALL_NAMES` includes `"add"`, line 78), so `totals.py`'s calls are classified there. | 1.3 |
| L12 | Absent cancellation reason is reachable | Yes: `reason === undefined` checked in `cancel` (`order.ts:402-407`) | No: an `enum` parameter cannot be absent, so the check lives only in `Parse` (`CancellationReason.cs:44-50`) | Yes, as in #7: an annotation does not stop `None` at run time. `cancel` checks `reason is None` then `type(reason) is not CancellationReason` before anything else, and the parse function exists too for the boundary. | 4.7, 4.10 |
| L13 | An instant is unambiguous UTC | `Date` is an epoch-millisecond count, always UTC (`order.ts:42-47`) | `DateTimeOffset` carries its offset (`Order.cs:106`) | **A naive `datetime` type-checks and means local time.** `require_utc` refuses `tzinfo is None` and any non-zero `utcoffset()` with `InstantNotUtcError` (`order.instant_not_utc`) on every instant parameter of `place`, the transitions, the line mutators, `CompensationStep` and `rehydrate`. New code, language-forced (requirements.md §6). | 3.15, 5.9 |
| L14 | Instant precision | `Date` holds milliseconds | `DateTimeOffset` 100 ns, stored `datetime2(3)` | `datetime` holds microseconds; `timestamptz(3)` rounds while the wire formatter truncates. The aggregate stores the instant it is given and stamps `updated_at` and the event's `occurred_at` from the **same object**; truncation to whole milliseconds is backlog 205, carried as feature 14's acceptance. None owed here. | — (feature 14) |
| L15 | Line order on load | Unordered item query (`apps/orders/src/infrastructure/persistence/order.repository.ts:217-228`) | `lines.OrderBy(line => line.Id.Value)` inside `Rehydrate` (`Order.cs:394`) | `rehydrate` sorts by `line.id.value.int` (the 128-bit value; PostgreSQL's `uuid` order is the same big-endian byte order). Whether that equals .NET's `Guid.CompareTo` order is **not claimed**: no fact or response carries rehydrated line order (§8.4). | 5.11 |
| L16 | Totals cannot be supplied on load | `OrderSnapshot` has no totals fields (`order-snapshot.ts:6-9, 23-36`, its OA3) | `Rehydrate` has no totals parameters (`Order.cs:353-367`) | `OrderSnapshot` is a frozen dataclass with no totals field; a test pins its field set as a literal, so a field added later fails by name. | 5.3 |
| L17 | Load-time checks each have a guard | `reconstitute` checks status, O1, O6 (`order.ts:182-203`) and lacks O2 (#7 review D3) | `Rehydrate` checks status, O1, O2, O6 (`Order.cs:369-392`); two survived deletion until `orders_acceptance` added tests (#8 `progress/history.md` §orders_aggregate, *"the one defect"*) | One named test **per check**, O2 split per field, plus O3 (§8.2) and L13 instants; each armed by deleting that check alone. | 5.4 – 5.10, 6.2 |
| L18 | Events are immutable values | Plain objects from `createDomainEvent` | `sealed record` (`Events/FactEvent.cs:60-69`, `OrderCancelled.cs:21-37`) | `@dataclass(frozen=True, slots=True, kw_only=True)`; `kw_only` so the optional `note`/`notes` fields need no ordering trick and no positional mix-up is possible. | 4.13 |
| L19 | Event collection typed | `pullDomainEvents()` returns typed envelopes | `IReadOnlyList<IDomainEvent>` | **Typing gap:** the kernel's `AggregateRoot.domain_events` is `tuple[object, ...]` (`entity.py:42-44`). `events.py` exports the closed alias `type OrderEvent = OrderPlaced \| OrderConfirmed \| OrderCompleted \| OrderCancelled`; consumers narrow with `match`/`isinstance`, never `cast`, never `Any`. | 4.13 |
| L20 | Event loop affinity, cancellation, `Any` from untyped libraries | n/a: pure, synchronous (`order.ts:1-4`) | n/a: *"Synchronous and pure"* (`Order.cs:13-18`) | n/a: no `async def`, no task, no third-party import (the money guard's allow-list makes the last one structural). None owed. | — |
| L21 | Aggregate identity generated in the domain | Supplied by the caller in `PlaceOrderInput.id` (`order.ts:65, 150`) | `UniqueId.New()` inside `Place` (`Order.cs:127`) | As #8: `UniqueId.new()` inside `place` (v4, kernel `unique_id.py:26-28`). The caller reads `order.id`. Both satisfy domain-model §2.5. | 3.5 |

**Ported guards.** #8's 26 domain-aggregate cases (`tests/Orders.UnitTests/Order{,Totals,StateMachine,Cancellation,Events,Rehydration}Tests.cs`) are all **ported**, each mapped by name in `tasks.md`, with three strengthened: the O2 load check split per field (#8's single case corrupts the order currency, so both fields mismatch and a deleted `lineDiscount` check survives), the R7 case run on a one-line order (#8 history: its first R7 test could not see guard order), and the pairing case asserting the legal pairings as well as the illegal ones (#8 history: same). #7's cases are ported in kind: `order-status.spec.ts` (domain ↔ contracts parity) as task 2.2's contract half; `domain-error-money-text.spec.ts` as task 3.10 (whole-string, EUR and JPY); `order.spec.ts` OA5 (frozen lines) as task 3.12; `order-state-machine.spec.ts`'s *"9 (from, placed) pairs ... no public command method"* as task 3.9's structural assertion that no method targets `placed`. **Deliberately not ported:** #7's and #8's `recordSagaFailure` tests (`order.spec.ts:381-418`, `OrderSagaFailureTests.cs`): the method belongs to the dead-letter feature in both builds (§13).

## 3. Type shapes

| Type | Python shape | Reason |
|---|---|---|
| `Order` | class subclassing `otc_shared_kernel.AggregateRoot`, `__slots__`, read-only properties | Identity equality and collected events come from the kernel; slots forbid stray attributes (L4). |
| `OrderLine` | class subclassing `otc_shared_kernel.Entity`, `__slots__`, read-only properties | `domain-model.md` §3.1: identity within the aggregate. Two lines with the same product and price are different lines; a dataclass with value equality would collapse them. Changing a line replaces it with a new `OrderLine` carrying the same id (#7 `order-line.ts:47-50`, #8 `Order.cs:334-338`). |
| `OrderLineInput` | `@dataclass(frozen=True, slots=True, kw_only=True)` | The per-line input of `place` (#8 `OrderLineRequest.cs`, #7 `PlaceOrderLineInput`, `order.ts:49-55`). |
| `OrderStatus`, `CancellationReason`, `CompensationStepKind` | `enum.Enum`, explicit string values | L1 – L3. |
| `Edge` | `NamedTuple(source: OrderStatus, target: OrderStatus)` | Value equality and hashing for set membership (L6). |
| `OrderTotals` | frozen dataclass of three `Money` | The return of the pure totals function. |
| `CompensationStep` | frozen dataclass: `step`, `event_id: UniqueId \| None`, `event_type: str`, `occurred_at: datetime`, `summary: str \| None` | `asyncapi.yaml` `CompensationStep` (required `step`, `eventType`, `occurredAt`). |
| `OrderSnapshot`, `OrderLineSnapshot` | frozen dataclasses, `tuple` for lines, **no totals field** | L16; the input of `rehydrate`, built by feature 15's mapper. |
| Events | frozen, slotted, keyword-only dataclasses with `EVENT_TYPE: ClassVar[str]` | L18. |
| Errors | subclasses of `otc_shared_kernel.DomainError`, each with a class constant `CODE` | The kernel's convention (`errors.py:24-89`). |

**Runtime type checks: exactly where the type system cannot see the violation.** Every caller of the domain is first-party code under `mypy --strict`, so the domain does not re-check that a `Quantity` is a `Quantity`. It checks at run time only what `mypy` cannot: a `None` reason (L12), a status or reason read from storage (L1, L2, §8), and a naive or non-UTC instant (L13). Anything else is a type error caught before the code runs.

## 4. The status state machine

### 4.1 The encoding

```python
class OrderStatus(Enum):
    PLACED = "placed"
    STOCK_RESERVED = "stock_reserved"
    CREDIT_APPROVED = "credit_approved"
    CONFIRMED = "confirmed"
    DESPATCHED = "despatched"
    INVOICED = "invoiced"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Edge(NamedTuple):
    source: OrderStatus
    target: OrderStatus

# Table T-1 rows 2-12. Row 1 ((none) -> placed) is creation: it is Order.place, with no source.
LEGAL_EDGES: frozenset[Edge] = frozenset({
    Edge(PLACED, STOCK_RESERVED),          # T-1 row 2
    ...                                    # rows 3-11, one per line, each with its row number
    Edge(CONFIRMED, CANCELLED),            # T-1 row 12
})

def is_legal(source: OrderStatus, target: OrderStatus) -> bool:
    return Edge(source, target) in LEGAL_EDGES
```

Row 1 is deliberately **not** in the table: `place` has no source to look up, and a creation row nothing consults is #7's review defect D1 (`CREATION_TRANSITION` dead code, `order-transitions.ts:134-141`). Row 1's *Fact* cell is guarded by behaviour instead (task 4.11: `place` appends exactly one `order.placed.v1`).

### 4.2 No method names a target

| T-1 row | Method | Target (constant in its body) | Event |
|---|---|---|---|
| 1 | `Order.place(...)` (classmethod) | `PLACED` | `OrderPlaced` |
| 2 | `mark_stock_reserved(*, occurred_at)` | `STOCK_RESERVED` | — |
| 3 | `approve_credit(*, occurred_at)` | `CREDIT_APPROVED` | — |
| 4 | `confirm(*, occurred_at, causation_id)` | `CONFIRMED` | `OrderConfirmed` |
| 5 | `mark_despatched(*, occurred_at)` | `DESPATCHED` | — |
| 6 | `mark_invoiced(*, occurred_at)` | `INVOICED` | — |
| 7 | `mark_paid(*, occurred_at)` | `PAID` | — |
| 8 | `complete(*, occurred_at, causation_id)` | `COMPLETED` | `OrderCompleted` |
| 9–12 | `cancel(*, reason, compensation_steps, occurred_at, causation_id, note=None)` | `CANCELLED` | `OrderCancelled` |

No public method takes an `OrderStatus` parameter (task 3.9 asserts it over `inspect.signature` of every public callable of `Order`). The silent edges take no `causation_id`, as in #8 (`Order.cs:159-194`).

### 4.3 The single writer

```python
def _transition_to(
    self, target, *, occurred_at, build_event=None, cancellation_reason=None
) -> None:
    if not is_legal(self._status, target):
        raise IllegalOrderTransitionError(self._status, target)
    self._status = target
    if cancellation_reason is not None:
        self._cancellation_reason = cancellation_reason  # inside the accepted branch (#8 A2)
    self._updated_at = occurred_at
    if build_event is not None:
        self._raise_event(build_event())  # built from the aggregate's state
```

The guard is the first statement and every mutation is below it, so R9's three legs hold structurally. `cancel` performs its own refusals first (§7.1) and then calls `_transition_to`, whose legality check is then redundant but kept: it is the one funnel.

### 4.4 The arithmetic the R9 test rests on

Nine statuses; eight are attemptable targets (`PLACED` is not: no method targets it). **9 × 8 = 72** attemptable pairs, **11** legal, **61** illegal. The test enumerates the 72 from a `dict[OrderStatus, Callable[[Order], None]]` of the nine methods, builds an order in each source state through `rehydrate` (the legal walk is R8's job), and for each of the 61 asserts: `IllegalOrderTransitionError` (or its subclass) raised, `status` unchanged, `len(domain_events)` unchanged, `updated_at` unchanged, totals and lines unchanged. The three counts are asserted as literals.

### 4.5 Terminality needs no code

`COMPLETED` and `CANCELLED` occur in `LEGAL_EDGES` only as targets, so `is_legal` is false for all 16 outbound pairs without an `if`. The transcription test is what guards it.

## 5. Totals (O3, R6)

### 5.1 State

`initial_amount`, `initial_discount`, `total_amount` are read-only `Money` properties; `currency` is a read-only `str` fixed at construction and validated by constructing `Money.zero(currency)` (refuses with `money.invalid_currency_code`).

### 5.2 The computation

```python
def compute_totals(lines: tuple[OrderLine, ...], currency: str) -> OrderTotals:
    initial_amount = Money.zero(currency)
    line_discounts = Money.zero(currency)
    for line in lines:
        initial_amount = initial_amount.add(line.unit_price.multiply(line.quantity))
        line_discounts = line_discounts.add(line.line_discount)
    order_discount = Money.zero(currency)  # R6's term; always zero (§5.4)
    initial_discount = line_discounts.add(order_discount)
    return OrderTotals(initial_amount, initial_discount, initial_amount.subtract(initial_discount))
```

Named methods only (L11). It does not check the sign: callers decide (a mutation and a load both refuse a negative total; §5.3, §8.2), which keeps the function total and lets the R6 test call it directly.

### 5.3 Candidate then commit

Every line mutator has one shape: (1) `_ensure_lines_mutable()`; (2) `require_utc(occurred_at)`; (3) argument checks in isolation (currency per field, line exists); (4) build the candidate `tuple` of lines; (5) `compute_totals` on the candidate (may raise `money.invalid_amount` on overflow, L9); (6) refuse an empty candidate (O1) or a negative candidate total (O3); (7) only now `_commit_lines(candidate, totals, occurred_at)` assigns `_lines`, the three totals and `_updated_at`. Any refusal in (1)–(6) leaves lines, totals, status, events and `updated_at` exactly as they were; the R6 and R7 tests assert every one of them.

### 5.4 The order-level discount is zero, inherited

#7 `order-totals.ts:25` (`const orderDiscount = Money.zero(currency)`) and #8 `Order.cs:534` write the term into the formula and never set it. #9 does the same: no field, no setter, nothing to persist. A non-zero `orderDiscount` arriving on the wire is refused by feature 15's place-order handler (#7 `place-order.handler.ts:67-68`), not dropped.

### 5.5 The negative-total message

`OrderTotalMustNotBeNegativeError` carries the candidate total as `candidate_total: Money` and renders its message with `format_money` (OP-1): `"The resulting total amount would be negative: -1.00 EUR."` (#8's wording, `OrderTotalMustNotBeNegativeError.cs:21`). #7's wording differs (`order-errors.ts:65`); message text is not a parity claim between #7 and #8 today, and #9 follows #8, the build its Gateway is ported from.

## 6. Lines

### 6.1 The mutating API

| Method | Purpose | R |
|---|---|---|
| `add_line(*, product_code, description, quantity, unit_price, line_discount, occurred_at) -> UniqueId` | append a line | R6, R7 |
| `remove_line(*, line_id, occurred_at)` | remove a line, refusing the last | R5, R6, R7 |
| `change_line(*, line_id, quantity, unit_price, line_discount, occurred_at)` | replace the three mutable fields of one line | R6, R7 |

`change_line` replaces all three at once (#8 `Order.cs:327-341`; #7 has only `changeLineQuantity`, `order.ts:344-356`, which #8 widened): one place for the freeze, the currency check and the recompute. `product_code` and `description` are snapshots, immutable on an existing line. `lines` returns the aggregate's `tuple` (L8). No live caller exists for these three methods until an amendment flow exists (none in the trilogy; ORDCHG is out of scope by O4); their tests are the only executors, the *double force* case of the fact-emission rule.

### 6.2 The freeze, and why it is first

`_ensure_lines_mutable()` raises `OrderLinesAreFrozenError` unless `status in LINES_MUTABLE_IN`, the literal `frozenset({PLACED, STOCK_RESERVED, CREDIT_APPROVED})` (#7's allow-list form, `order.ts:104`; #8 lists the six frozen states, `Order.cs:470`; equivalent today, and the allow-list freezes a status added later by default). It is the first statement of all three mutators, so removing the last line of a `confirmed` order raises `order.lines_are_frozen`, not `order.must_have_at_least_one_line`. The R7 test asserts the **code**, on a **one-line** order, so swapping the two checks fails it.

### 6.3 Single currency (O2)

`_require_line_currency(unit_price, line_discount)` compares each field's currency with the order's and raises `OrderLineCurrencyMismatchError` (`order.line_currency_mismatch`) naming the offending field's currency. It runs before the candidate is built, so the caller sees the order invariant, never the kernel's `money.cross_currency` one step later (#7 OA1, `order.ts:463-480`; #8 `Order.cs:478-490`). Each field is tested separately, on `place`, `add_line`, `change_line` and `rehydrate`.

## 7. Cancellation and the events

### 7.1 `cancel`

Order of checks, each before any mutation (#7 `order.ts:402-419` order): (1) `reason is None` → `CancellationReasonRequiredError`; (2) `type(reason) is not CancellationReason` → `UnknownCancellationReasonError`; (3) `require_utc(occurred_at)`; (4) `not is_legal(status, CANCELLED)` → `OrderNotCancellableError` (a subclass of `IllegalOrderTransitionError`, so the R9 matrix catches it through the base); (5) the pairing: `STOCK_REJECTED` only from `PLACED`, `CREDIT_REJECTED` only from `STOCK_RESERVED`, `OPERATOR_CANCELLED` from any of the four → `CancellationReasonNotApplicableError` (#7 `order.ts:414-419`, #8 `Order.cs:459-465`); (6) `steps = tuple(compensation_steps)`; (7) `_transition_to(CANCELLED, cancellation_reason=reason, build_event=...)`.

Immutability of the reason is structural: `CANCELLED` has no outbound edge, so a second `cancel` is refused by (4) before it could overwrite anything.

### 7.2 Events read the aggregate

Each event builder is a closure over `self` that reads **post-transition state**: `OrderCancelled.cancellation_reason = self._cancellation_reason`, `OrderConfirmed.total_amount = self._total_amount`, and so on. Consequence: if the reason assignment were moved out of `_transition_to`'s accepted branch to the line after it returns (#8's A2 shape), the event would carry `None` and the R10 test, which asserts the event's reason, fails. That makes A2 testable rather than a review observation.

### 7.3 The four events

| Class | `EVENT_TYPE` | Fields beyond the base |
|---|---|---|
| `OrderPlaced` | `order.placed.v1` | `order_reference: OrderNumber`, `retailer_code`, `company_code`, `buyer_gln: GLN`, `supplier_gln: GLN`, `currency`, `order_date`, `lines: tuple[OrderPlacedLine, ...]`, `initial_amount`, `initial_discount`, `total_amount` (`Money`), `notes: str \| None` |
| `OrderConfirmed` | `order.confirmed.v1` | `order_reference`, `retailer_code`, `company_code`, `currency`, `total_amount`, `confirmed_at` |
| `OrderCompleted` | `order.completed.v1` | `order_reference`, `retailer_code`, `company_code`, `currency`, `total_amount`, `completed_at` |
| `OrderCancelled` | `order.cancelled.v1` | `order_reference`, `retailer_code`, `company_code`, `cancellation_reason`, `cancelled_at`, `compensation_steps: tuple[CompensationStep, ...]`, `note: str \| None = None` (SA-2) |

Base (`OrderEventBase`): `event_id`, `aggregate_id`, `correlation_id`, `causation_id` (`UniqueId`), `occurred_at` (`datetime`). The field lists are the `required` lists of `asyncapi.yaml`'s four payload schemas plus the optional `notes` and `note`. `event_id = UniqueId.new()` and `aggregate_id = correlation_id = self.id` are set by the aggregate (`domain-model.md` §7.1: *"Always the order id"*); `causation_id` is a required parameter of `place`, `confirm`, `complete` and `cancel`, so the causal chain cannot be broken by omission. `confirmed_at`/`completed_at`/`cancelled_at` equal `occurred_at` by value (both from the same parameter), because the payloads require them.

**These are domain types.** The events carry `OrderNumber`, `GLN`, `Money`, `UniqueId`, `datetime`, never `otc_contracts` models. Mapping to the wire envelope is feature 14's. The guard is already in place: the money guard's import allow-list refuses `otc_contracts` in any domain file (`test_domain_and_shared_kernel_import_only_the_allowlist`); task 6.3 arms it with exactly that import, which is what #8 needed a new architecture rule for (#8 tasks 5.5).

**The note (SA-2).** `cancel(..., note=None)` carries an operator's free text onto `OrderCancelled.note`; absent when not supplied. The domain does not refuse a note with a saga-decided reason: #8 does not (`Order.cs:230`), and `asyncapi.yaml`'s description states what the flows do, not an invariant.

### 7.4 Which transitions raise an event — inherited from #7, verified

Seven T-1 rows raise an event (1, 4, 8, 9–12) and five do not (2, 3, 5, 6, 7). Evidence: #7 `order-transitions.ts:36,42,54,60,66` (`emits: null` on the five) and `order.ts:452` (the funnel gates on it); #8 `Order.cs:159-194` (`buildEvent: null` on the five); #7 `progress/history.md:760` (*"T-1 governs O8 so five internal edges emit nothing (OA2)"*). The shared documents corroborate it: the catalogue is closed at fourteen (`domain-model.md` §7.2) and T-1's *Fact* column is `—` on those rows. O8's testable half, *"A rejected transition appends none"*, is R9's. The suppression is guarded in the direction that matters (task 4.12 fails when an emission is **added**), and armed on an edge other than the one the implementation report uses (#8 history, notes for #9).

### 7.5 Instants

Every method that changes state takes `occurred_at: datetime`; `place` also takes `order_date`. No clock, no `datetime.now()` anywhere in the domain (#7 `TransitionContext`, `order.ts:42-47`; #8 parameters, #8 `design.md` §7.3). The clock port is feature 15's, in `application`. `require_utc` (L13) is called first in every such method, after the freeze and before any other check that could raise, so a refused instant also leaves the order unchanged.

### 7.6 Collection and drain

The kernel's `AggregateRoot` supplies `_raise_event`, `domain_events` and `pull_domain_events` (`entity.py:46-53`); this feature adds nothing to it. Contract for feature 14: events are appended in raise order only from `_transition_to`'s accepted branch and from `place`; the repository drains them with `pull_domain_events()` **after** the transaction commits, writing one `outbox` row per event in the same transaction as the aggregate rows (R13). An order confirmed in one saga step (`stock_reserved → credit_approved → confirmed`) holds exactly one event, `OrderConfirmed`. The aggregate publishes nothing.

## 8. Rehydration

### 8.1 The shape

`Order.rehydrate(snapshot: OrderSnapshot) -> Order`. `OrderSnapshot` fields: `id`, `order_reference`, `order_date`, `retailer_code`, `buyer_gln`, `company_code`, `supplier_gln`, `currency`, `status`, `cancellation_reason`, `notes`, `lines: tuple[OrderLineSnapshot, ...]`, `created_at`, `updated_at`; **no totals** (L16). `OrderLineSnapshot`: `id`, `product_code`, `description`, `quantity`, `unit_price`, `line_discount`. A snapshot (#7's shape, `order-snapshot.ts`) rather than #8's fourteen positional parameters: one value feature 15's mapper builds, keyword-constructed.

`rehydrate` restores a state the aggregate produced: it **bypasses the state machine** (the seed holds `completed` and `cancelled` orders no factory call can reach) and **raises no event** (they were published when they happened). Both get named tests.

### 8.2 What it validates, each check with its own test

| # | Check | Error | #7 / #8 |
|---|---|---|---|
| 1 | `type(status) is OrderStatus` | `InvalidOrderSnapshotError` (`order.snapshot_invalid`) | #7 `order.ts:182-187`; #8 `Order.cs:369-372` |
| 2 | `cancellation_reason is None or type(cancellation_reason) is CancellationReason` | `order.snapshot_invalid` | #7 `order.ts:192` (`isCancellationReason`); #8 type-enforced |
| 3 | O6: `CANCELLED` ⇒ reason present | `order.snapshot_invalid` | #7 `order.ts:191-197`; #8 `Order.cs:384-387` |
| 4 | O6: not `CANCELLED` ⇒ reason absent | `order.snapshot_invalid` | #7 `order.ts:198-203`; #8 `Order.cs:389-392` |
| 5 | O1: at least one line | `order.must_have_at_least_one_line` | #7 `order.ts:188-190`; #8 `Order.cs:374-377` |
| 6 | O2: each line's `unit_price` currency | `order.line_currency_mismatch` | #7 absent (its D3); #8 `Order.cs:379-382` |
| 7 | O2: each line's `line_discount` currency | `order.line_currency_mismatch` | as 6 |
| 8 | L13: `order_date`, `created_at`, `updated_at` are UTC | `order.instant_not_utc` | n/a in #7/#8 |
| 9 | O3: derived total not negative | `order.total_must_not_be_negative` | #7 via `computeOrderTotals` (`order-totals.ts:36-38`); #8 absent (`Order.cs:395`) — requirements.md §3 row 5 |

Load-time faults that are not invariants a live request could violate (1–4) raise `InvalidOrderSnapshotError`, distinct from every business code (#8's A3, closed in #8 by `InvalidOrderSnapshotError.cs:34-52`; #7 `order-errors.ts:133-142`). O1, O2 and O3 reuse the aggregate's own errors, as #7 and #8 both do. Each of the nine checks has one test that fails when that check **alone** is deleted (the #8 defect: two of four checks survived their own deletion). The fixture for each test corrupts exactly one thing, so no earlier check can catch it by accident; where a later step would also fail (deleting check 6 lets `Money.add` raise `money.cross_currency`), the test asserts the **code**, so the substitute error does not satisfy it.

### 8.3 Codes versus ids

The aggregate speaks business vocabulary (`retailer_code`, `company_code`, `product_code`, `buyer_gln`, `supplier_gln`, `currency`); the tables store local foreign keys (`retailer_id`, `company_id`, `currency_id`, `product_id`, `services/orders/src/otc_orders/infrastructure/persistence/models.py:119-145`). All four reference tables are in `otc_orders`, so feature 15's load joins them; no context boundary is crossed (#8 `design.md` §8.3).

### 8.4 Line order

`rehydrate` sorts lines by `line.id.value.int`. Line order is observable only on `order.placed.v1`, built from the in-memory aggregate inside the placing transaction, so the caller's order is what ships; the sort only makes reloads deterministic (L15).

## 9. Persistence contract for features 14 / 15 (not built here)

| Domain | Column (`models.py`) | Mapping |
|---|---|---|
| `id: UniqueId` | `orders.id uuid` | `.value` / `UniqueId(value)` |
| `order_reference: OrderNumber` | `order_reference varchar(20)` | `.value` / `OrderNumber.parse` |
| `order_date`, `created_at`, `updated_at` | `timestamptz(3)` | aware UTC `datetime` both ways; ms truncation is backlog 205 (feature 14) |
| `retailer_code`/`buyer_gln`, `company_code`/`supplier_gln`, `currency` | `retailer_id`, `company_id`, `currency_id` | resolved through the reference tables (§8.3) |
| `initial_amount`, `initial_discount`, `total_amount: Money` | `bigint` ×3 | `.amount` on write; **not read into the aggregate** (L16) |
| `status: OrderStatus` | `status varchar(20)` | `.value` / `parse_order_status` (raises `order.snapshot_invalid`) |
| `cancellation_reason` | `varchar(100) NULL` | `.value` / `parse_cancellation_reason`; `NULL` iff not cancelled |
| `notes: str \| None` | `notes text NULL` | direct |
| `OrderLine.id` | `order_items.id uuid` | direct |
| `OrderLine.product_code` | `product_id uuid` | resolved through `products` |
| `OrderLine.description: str \| None` | `description varchar(255) NOT NULL` | `or ""` on write (#8 `design.md` §8.1) |
| `unit_price`, `line_discount: Money` | `price`, `discount bigint` | `.amount` / `Money(value, currency)` |
| `quantity: Quantity` | `quantity integer` | `.value`; the range guard refuses > int32 at the write boundary (feature 15, backlog 204) |

No concurrency token: `orders` has no version column, so the aggregate invents none; feature 16 loads a saga step's order under `SELECT … FOR UPDATE` in its own transaction (#8 `design.md` §8.6).

## 10. Domain errors

Stable codes, `<subject>.<snake_case_reason>`, the convention #9's kernel inherited from #8 (`otc_shared_kernel/errors.py:1-10`). #7's codes are `UPPER_SNAKE` (`order-errors.ts:12-134`); they reach the wire only inside `RpcError.details.code`, and no production code and no API test of either build branches on a code value. Search (this spec pass): `grep -rlE` over every code literal of both builds, excluding each build's own `Orders/Domain` sources. #7 hits: `apps/orders/src/presentation/rpc-error-mapper.spec.ts` and `apps/gateway/src/presentation/problem-detail-money-text.spec.ts` (unit fixtures), `apps/orders/dist/**` and `apps/orders/coverage/**` (build output). #8 hits: six `tests/Orders.UnitTests/*Tests.cs` files and `tests/Gateway.UnitTests/ProblemDetailMoneyTextTests.cs` (unit tests only). #9 uses #8's codes.

| Class | `CODE` | Raised when | R |
|---|---|---|---|
| `OrderMustHaveAtLeastOneLineError` | `order.must_have_at_least_one_line` | `place` with no lines; `remove_line` on the last; load with none | R5 |
| `OrderTotalMustNotBeNegativeError` | `order.total_must_not_be_negative` | a candidate or loaded total is negative | R6 |
| `OrderLinesAreFrozenError` | `order.lines_are_frozen` | a line mutation outside `LINES_MUTABLE_IN` | R7 |
| `OrderLineNotFoundError` | `order.line_not_found` | `remove_line`/`change_line` with an unknown id | R6, R7 |
| `OrderLineCurrencyMismatchError` | `order.line_currency_mismatch` | a line field not in the order currency | R2 (O2) |
| `IllegalOrderTransitionError` | `order.illegal_transition` | `(from, to)` absent from T-1 | R8, R9 |
| `OrderNotCancellableError` (subclass of the above) | `order.not_cancellable` | `cancel` from a status with no cancel edge | R8, R9 |
| `CancellationReasonRequiredError` | `order.cancellation_reason_required` | `cancel(reason=None)`; parse of `None`/blank | R10 |
| `UnknownCancellationReasonError` | `order.cancellation_reason_unknown` | `cancel` with a non-member; parse of an unknown token | R10 |
| `CancellationReasonNotApplicableError` | `order.cancellation_reason_not_applicable` | the reason does not pair with the status (§7.1) | R10 |
| `InvalidOrderSnapshotError` | `order.snapshot_invalid` | load-time checks 1–4 of §8.2; `parse_order_status` of an unknown token | — (A3) |
| `InstantNotUtcError` | `order.instant_not_utc` | a naive or non-UTC instant (L13) | — (new in #9) |

Twelve. #8 shipped eleven against a table of ten (its A4); here the table is the population, and task 3.16 compares the real subclass set of `DomainError` defined in `otc_orders.domain` with this table as a literal of `(class name, code)` pairs. Messages carry specifics (the status pair, the line id, the currencies, the money text); `code` is what machines branch on. The RPC mapping of these codes (`VALIDATION_FAILED` with `details.code`, `ORDER_NOT_CANCELLABLE`) is features 15 and 41's, reproduced from #7/#8 there.

## 11. Test design

### 11.1 Placement and purity

`services/orders/tests/unit/domain/`, one file per matrix path plus the design-guard files listed in `tasks.md`. Builders are **pytest fixtures** in `services/orders/tests/unit/domain/conftest.py` (the repository runs `--import-mode=importlib`, so a test module cannot import a sibling helper module). Fixtures supply a placed EUR order with two lines (one-line variants where guard order must be observable), an `order_in(status)` factory built through `rehydrate`, and fixed aware-UTC instants. These tests touch no store, broker, clock or framework; task 6.4 makes that a guard (the import set of every file in the directory is a subset of a literal: `pytest`, the standard library, `otc_shared_kernel`, `otc_orders.domain`). The two checks that need `otc_contracts` (event types in the fact catalogue; tokens equal the generated enums) live one directory up, in `services/orders/tests/unit/test_order_domain_contract_parity.py`.

### 11.2 Transcription, not import

Every closed set the code holds is compared with a **literal transcribed from the specification**, never with the constant the code reads (#8 trap 3): the nine status tokens and the three reasons (`openapi.yaml`/`asyncapi.yaml` enums and `domain-model.md` §3.1), the two compensation kinds, the eleven edges plus row 1, the six frozen statuses (R7's list) and the four cancellable sources (R8's list). For T-1, the test additionally parses the table out of `specs/shared/domain-model.md` §3.3 at run time and asserts the parse equals the literal (12 rows; 11 with a source; 7 with a fact), so neither a typo in the literal nor a drift in the spec passes silently.

### 11.3 Fixtures that cannot satisfy a relation by accident

Equality assertions use distinct values (two lines with different prices, quantities and discounts; a non-round total so that a formula with the wrong term cannot coincide); currency-mismatch fixtures corrupt exactly one field; `causation_id` values differ from the order id; each event's `event_id` is asserted distinct from every other id in the test.

## 12. Arming

CLAUDE.md's protocol in full: back up by `cp`, introduce the one violation, run the **one** named test, record the failure verbatim (it must name the claim), restore from the backup, confirm with `cmp`, delete `__pycache__` under `services/orders/src` and `.mypy_cache`, re-run green. Every `[ARM]` task in `tasks.md` names its mutation; the rows are recorded in `progress/impl_orders_aggregate.md`. Defeat-list rows that apply to this feature: 1 (delete), 2 (corrupt a supplied field: wrong reason on the event, wrong causation), 3 (substitute a sibling: `STOCK_RESERVED` for `CREDIT_APPROVED` in an edge, `credit_rejected` for `stock_rejected` in the pairing), 7 (drop an optional element: the note), 9 (premise: the guard order test needs a one-line order), 11 (a form the instrument does not recognise: `setattr(self, "_status", ...)` and `object.__setattr__` against the single-writer test), 12 (a path the population never drives: a second status writer in a method no test calls is what the structural test exists for). Rows 4–6 and 10 concern syntax guards; they apply to the structural test (task 3.13) and are armed there.

## 13. Explicit non-goals

- No repository, port, mapper, ORM change, migration or seed change (OP-1 A touches the seed's import of `format_money` only).
- No outbox row, envelope, serialisation, Kafka, NATS, dispatcher, handler or composition-root registration.
- No `orders.create` validation, availability check, request-id dedup (R62) or order-discount refusal (feature 15).
- No `record_saga_failure` / `order.saga_failed.v1`: an `Order` fact without a status change that belongs to the dead-letter feature, as #7 (`order.ts:438-440`, added in a later phase) and #8 (`Order.cs:281-292`, likewise) placed it.
- No amendment, rewording or reinterpretation of anything under `specs/shared/`.
