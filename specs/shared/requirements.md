# Shared Requirements — EARS Notation

> **Scope.** The **stack-agnostic** requirements of the Order-To-Cash trilogy,
> reused **verbatim** by assessments **#7**, **#8** and **#9**. Every requirement
> here is a statement about the *system*, never about a framework, a library, a
> database engine or a language. Stack realisation belongs in each assessment's
> per-feature `design.md`.
>
> Companion documents: [`domain-model.md`](./domain-model.md) and
> [`saga.md`](./saga.md). Invariant ids (`M1`, `O4`, `F3`, `B7`…) referenced
> below are defined in `domain-model.md`.

## Notation

Strict EARS. Every requirement uses exactly one of five patterns:

| Pattern | Template |
|---|---|
| **Ubiquitous** | *THE SYSTEM SHALL &lt;response&gt;.* |
| **Event-driven** | *WHEN &lt;trigger&gt;, THE SYSTEM SHALL &lt;response&gt;.* |
| **State-driven** | *WHILE &lt;state&gt;, THE SYSTEM SHALL &lt;response&gt;.* |
| **Unwanted** | *IF &lt;condition&gt;, THEN THE SYSTEM SHALL &lt;response&gt;.* |
| **Optional** | *WHERE &lt;feature is included&gt;, THE SYSTEM SHALL &lt;response&gt;.* |

Rules of this document:

- Every requirement has a stable id `R<n>`. Ids are **never renumbered**; a
  withdrawn requirement is struck through, not removed, so that #8 and #9 can
  cite the same id as #7.
- Every requirement is **testable** — there exists an observation that can make
  it fail. "The system shall be performant" is not a requirement and does not
  appear here.
- Every `R<n>` maps to at least one named test in `test-matrix.md` (Pass B).

## Vocabulary

| Term | Meaning |
|---|---|
| **write model** | The authoritative store of one bounded context. |
| **read model** | The denormalised, projected query store. |
| **fact stream** | The durable, replayable, many-consumer log carrying domain facts (Kafka). |
| **RPC transport** | The request-reply bus carrying commands and synchronous queries (NATS core). |
| **fact** | A published domain event with the envelope of `domain-model.md` §7.1. |
| **command** | An RPC request; never a fact. |
| **consumer** | A named fact-stream subscriber: `orders.saga`, `projector`, `notifications`. |
| **minor units** | Integer count of the smallest denomination of a currency. |
| **domain error** | A refusal raised inside the domain layer carrying a stable code; it changes no state and emits no fact. |

## Requirement index

| Feature | Requirements | Count |
|---|---|---:|
| `orders_aggregate` | R1 – R10 | 10 |
| `outbox_and_idempotency` | R11 – R18 | 8 |
| `order_saga_orchestrator` | R19 – R29 | 11 |
| `fulfillment_stock` | R30 – R36, R61 | 8 |
| `billing_credit` (incl. simulator affordance R42 – R44) | R37 – R44 | 8 |
| `billing_invoicing` | R45 – R49 | 5 |
| `projector_read_model` | R50 – R55 | 6 |
| `observability_reliability` | R56 – R60, R62 | 6 |
| gateway edge protection (§8.1, per-assessment gateway feature) | R63 | 1 |
| **Total** | | **63** |

---

## 1. `orders_aggregate`

Value objects, the `Order` aggregate, its invariants and its state machine.
All of these are provable by **pure domain tests** — no store, no broker, no
framework.

**R1.** THE SYSTEM SHALL represent every monetary amount as an integer count of
**minor units** together with an ISO 4217 alpha-3 currency code, in the write
model, in every fact payload, in the read model and in every API response.

**R2.** IF an addition, subtraction or comparison is attempted between two
monetary amounts whose currency codes differ, THEN THE SYSTEM SHALL raise a
domain error and SHALL NOT perform any implicit currency conversion.

**R3.** IF a quantity is constructed from a value that is not a strictly
positive integer, THEN THE SYSTEM SHALL raise a domain error and SHALL NOT create
the value object.

**R4.** IF a Global Location Number is constructed from a value that is not
exactly 13 decimal digits, or whose final digit is not the correct GS1 mod-10
check digit over the preceding twelve, THEN THE SYSTEM SHALL raise a domain error
and SHALL NOT create the value object.

**R5.** IF an order is created with no lines, or its last remaining line is
removed, THEN THE SYSTEM SHALL raise a domain error and SHALL NOT persist the
order (invariant **O1**).

**R6.** WHEN any line of an order is added, removed or modified, THE SYSTEM SHALL
recompute the order's initial amount as the sum over lines of `unitPrice ×
quantity`, its initial discount as the sum of line discounts plus any order-level
discount, and its total amount as `initialAmount − initialDiscount`; and IF the
resulting total amount is negative, THEN THE SYSTEM SHALL raise a domain error
and leave the order unchanged (invariant **O3**).

**R7.** IF a line addition, removal or modification is attempted while the order
status is `confirmed`, `despatched`, `invoiced`, `paid`, `completed` or
`cancelled`, THEN THE SYSTEM SHALL raise a domain error and SHALL leave every
field of the order unchanged (invariant **O4**).

**R8.** THE SYSTEM SHALL permit an order status change only along an edge listed
in Table T-1 of `domain-model.md` §3.3, SHALL treat `completed` and `cancelled`
as terminal, and SHALL allow `cancelled` to be reached from `placed`,
`stock_reserved`, `credit_approved` and `confirmed` only.

**R9.** IF an order status change is attempted along a `(from, to)` pair absent
from Table T-1, THEN THE SYSTEM SHALL raise a domain error, SHALL leave the
status and every other field unchanged, and SHALL append no domain event to the
aggregate.

**R10.** WHEN an order transitions to `cancelled`, THE SYSTEM SHALL require a
cancellation reason drawn from `{stock_rejected, credit_rejected,
operator_cancelled}`, SHALL record it immutably on the order, and SHALL emit
`order.cancelled.v1` carrying it; and IF no reason is supplied, THEN THE SYSTEM
SHALL raise a domain error and SHALL NOT change the status (invariant **O6**).

---

## 2. `outbox_and_idempotency`

The envelope contract, transactional publication without dual-write, and
effectively-once consumption under at-least-once delivery.

**R11.** THE SYSTEM SHALL publish every fact with a complete envelope containing
`eventId`, `eventType`, `aggregateId`, `correlationId`, `causationId`,
`occurredAt` and `payload`, with no field absent, null or empty, and with
`eventType` matching the pattern `<aggregate>.<fact>.v<n>`.

**R12.** THE SYSTEM SHALL set the `correlationId` of every fact belonging to one
order's saga to that order's identifier, and SHALL set `causationId` to the
`eventId` of the fact — or the identifier of the command — that caused the fact,
so that the causal chain of an order is reconstructible from the facts alone.

**R13.** WHEN an aggregate carrying uncommitted domain events is persisted, THE
SYSTEM SHALL write the aggregate state and the corresponding outbox records in a
**single transaction of one write model**; and IF that transaction fails, THEN
THE SYSTEM SHALL persist neither the aggregate state nor the outbox records and
SHALL place no fact on the fact stream.

**R14.** THE SYSTEM SHALL publish facts to the fact stream **only** from the
outbox relay, SHALL stamp an outbox record as published only after the broker has
acknowledged it, and SHALL leave the record unstamped and republish it on a later
poll IF the acknowledgement is not received — accepting at-least-once delivery as
the contract. No command handler, aggregate or domain service publishes directly.

**R15.** THE SYSTEM SHALL use the `correlationId` as the fact-stream partition
key, so that all facts produced by one context about one order are delivered to
consumers in the order in which they were emitted.

**R16.** IF the processing of a fact by a consumer fails, THEN THE SYSTEM SHALL
retry it with backoff up to a configured maximum number of attempts, and on
exhausting them SHALL publish the fact to the corresponding `<topic>.dlq`
dead-letter topic annotated with the failing consumer name, the attempt count and
the error, and SHALL acknowledge the original fact so that the partition is not
blocked.

**R17.** WHEN a consumer processes a fact, THE SYSTEM SHALL record the pair
(`eventId`, consumer name) in the **same transaction** as every state change and
every outbox record that the processing produced.

**R18.** WHILE the pair (`eventId`, consumer name) has already been recorded for
a given consumer, THE SYSTEM SHALL acknowledge the redelivery without mutating
any aggregate state, without emitting any fact and without issuing any command.

---

## 3. `order_saga_orchestrator`

The orchestrated saga. In every requirement below, the trigger is a **fact**
observed on the fact stream and the action is a **command** issued over the RPC
transport; a command's response never advances the saga.

**R19.** WHEN `order.placed.v1` is received for an order in status `placed`, THE
SYSTEM SHALL issue a `stock.reserve` command over the RPC transport for every
line of the order, and SHALL leave the order status unchanged until the resulting
fact arrives.

**R20.** WHEN `stock.reserved.v1` is received for an order in status `placed`,
THE SYSTEM SHALL set the order to `stock_reserved` and SHALL issue a
`credit.hold` command for the order's total amount.

**R21.** WHEN `credit.approved.v1` is received for an order in status
`stock_reserved`, THE SYSTEM SHALL set the order to `credit_approved` and then to
`confirmed`, SHALL emit exactly one `order.confirmed.v1`, and SHALL issue a
`despatch.create` command.

**R22.** WHEN `order.despatched.v1` is received for an order in status
`confirmed`, THE SYSTEM SHALL set the order to `despatched` and SHALL issue an
`invoice.issue` command.

**R23.** WHEN `invoice.issued.v1` is received for an order in status
`despatched`, THE SYSTEM SHALL set the order to `invoiced` and SHALL issue no
further command, awaiting a remittance from outside the system.

**R24.** WHEN `payment.received.v1` is received for an order in status
`invoiced`, THE SYSTEM SHALL set the order to `paid`; and WHEN
`credit.released.v1` is subsequently received for an order in status `paid`, THE
SYSTEM SHALL set the order to `completed` and SHALL emit exactly one
`order.completed.v1`, closing the saga.

**R25.** IF a fact is received for an order whose current status is not the
precondition status stated in R19–R24, R26, R27 or R28, THEN THE SYSTEM SHALL
change no aggregate state, SHALL issue no command, SHALL emit no fact, and SHALL
record the fact as ignored together with the observed and expected status.

**R26.** WHEN `stock.rejected.v1` is received for an order in status `placed`,
THE SYSTEM SHALL set the order to `cancelled` with reason `stock_rejected` and
SHALL NOT issue a `stock.release` command, because reservation is all-or-nothing
and no stock was held (invariant **F3**).

**R27.** WHEN `credit.rejected.v1` is received for an order in status
`stock_reserved`, THE SYSTEM SHALL issue a `stock.release` command for that order
as the first compensation step, and SHALL leave the order in status
`stock_reserved` until the release is confirmed by a fact.

**R28.** WHEN `stock.released.v1` is received for an order in status
`stock_reserved` whose pending compensation is a credit rejection, THE SYSTEM
SHALL set the order to `cancelled` with reason `credit_rejected`, and SHALL make
both compensation steps — the stock release and the cancellation — separately
visible in the order timeline in causal order. THE SYSTEM SHALL NOT set the order
to `cancelled` before the corresponding `stock.released.v1` has been received.

**R29.** IF a command issued over the RPC transport times out or returns a
transport error, THEN THE SYSTEM SHALL retry it with backoff up to a configured
maximum number of attempts while leaving the order status unchanged; THE SYSTEM
SHALL make every command idempotent by (`orderReference`, operation) so that a
retried command produces no duplicate effect; and on exhausting the attempts THE
SYSTEM SHALL route the triggering fact to the dead-letter topic and record a
saga-failure entry in the order timeline.

---

## 4. `fulfillment_stock`

The `StockItem` aggregate, the reservation lifecycle — the compensable resource —
and the despatch advice.

> **Id ordering.** This section reads R30 – R36 followed by **R61**. R61 was
> added after R60 existed and ids are **never renumbered** (see *Notation*), so
> it keeps the next free id while sitting with the feature it belongs to.

**R30.** THE SYSTEM SHALL maintain, for every stock item, the invariant
`reservedUnits ≤ units`, and IF an operation would break it, THEN THE SYSTEM
SHALL reject that operation in full and change no stock item (invariant **F1**).

**R31.** WHEN a stock availability check is requested for a set of lines, THE
SYSTEM SHALL answer per line whether the requested units are currently available,
SHALL mutate no stock item and SHALL emit no fact — the check is a non-locking
read and is explicitly not a reservation.

**R32.** WHEN a `stock.reserve` command is received for an order whose every line
satisfies `units − reservedUnits ≥ requested`, THE SYSTEM SHALL create one
reservation per line in status `reserved`, SHALL increase `reservedUnits` by the
reserved amounts, and SHALL emit exactly one `stock.reserved.v1` for the order.

**R33.** IF a `stock.reserve` command is received for an order in which **any**
single line cannot be satisfied, THEN THE SYSTEM SHALL create no reservation at
all, SHALL leave every `reservedUnits` unchanged, and SHALL emit
`stock.rejected.v1` naming the short lines with requested and available units
(invariant **F3**).

**R34.** WHEN a `stock.release` command is received for an order holding
reservations in status `reserved`, THE SYSTEM SHALL set those reservations to
`released`, SHALL decrease `reservedUnits` by their amounts and SHALL emit exactly
one `stock.released.v1`; WHILE every reservation of that order is already
`released`, THE SYSTEM SHALL respond with success without changing any counter
and without emitting a second fact (invariant **F5**).

**R35.** THE SYSTEM SHALL allow a reservation to move only from `reserved` to
`released` or from `reserved` to `consumed`, SHALL treat `released` and
`consumed` as terminal, and IF a transition out of a terminal reservation state
is attempted, THEN THE SYSTEM SHALL raise a domain error and change nothing
(invariant **F4**).

**R36.** WHEN a `despatch.create` command is received for an order holding
reservations in status `reserved`, THE SYSTEM SHALL set those reservations to
`consumed`, SHALL create exactly one despatch advice with at least one line, each
line tracing to a consumed reservation of the same order and despatching exactly
the reserved units, and SHALL emit exactly one `order.despatched.v1`; and IF the
order holds no reservation in status `reserved`, THEN THE SYSTEM SHALL create no
despatch advice and emit no fact (invariants **F6**, **F7**, **F8**).

**R61.** WHEN a stock replenishment command is received for a known stock item
carrying a strictly positive integer quantity of units, THE SYSTEM SHALL increase
that stock item's on-hand `units` by exactly that quantity and SHALL leave
`reservedUnits`, every existing reservation and every reservation status
unchanged; the only observable effects SHALL be the increased `units` value and
the command's reply — no fact SHALL appear on the fact stream, no entry SHALL
appear in any order timeline and no order status SHALL change, because
replenishment is stock master-data maintenance performed by an operator or by
the stock-replenishment demo workflow and is **not** a step of the order-to-cash
saga. THE SYSTEM SHALL continue to satisfy invariant **F1** (`reservedUnits ≤
units`) after every replenishment, replenishment being the only stock operation
that can never move a stock item closer to breaking it.

---

## 5. `billing_credit`

The `BuyerCredit` aggregate and its append-only hold / consume / release ledger.

**R37.** THE SYSTEM SHALL maintain, for every credit line, the invariant
`Σ(active holds) + Σ(open invoice exposure) ≤ creditLimit`, and SHALL treat the
credit ledger as **append-only** — IF an update or deletion of an existing ledger
entry is attempted, THEN THE SYSTEM SHALL raise a domain error and change nothing
(invariants **B1**, **B2**).

**R38.** WHEN a `credit.hold` command is received for an order whose total amount
is less than or equal to the retailer's available credit, is expressed in the
credit line's currency, and is approved by the credit port, THE SYSTEM SHALL
append a `hold` ledger entry for the order and SHALL emit exactly one
`credit.approved.v1` carrying the held amount and the resulting available credit.

**R39.** IF a `credit.hold` command is received whose amount exceeds the
retailer's available credit, or which the credit port rejects, THEN THE SYSTEM
SHALL append **no** ledger entry, SHALL leave the available credit unchanged, and
SHALL emit `credit.rejected.v1` carrying the requested amount, the available
credit and a machine-readable reason.

> **Currency and identity are contract violations, not credit decisions.** IF a
> `credit.hold` command names a currency other than the credit line's, or names a
> `(retailerCode, companyCode)` pair for which no credit line exists, THEN THE
> SYSTEM SHALL append no ledger entry, SHALL emit **no** fact, and SHALL answer
> the command with an error reply. An order is single-currency by **M2**/**O1**
> and a credit line is master data, so neither case is a statement about the
> buyer's credit and neither may cause an order to be cancelled; and a fact whose
> aggregate does not exist has no `aggregateId` to carry (§7.1 of
> `domain-model.md`). This keeps the three `reason` values of
> `credit.rejected.v1` closed, as **R44** requires.

**R40.** WHEN an invoice is issued for an order holding an active credit hold,
THE SYSTEM SHALL append a `consume` ledger entry that converts the hold into open
invoice exposure of the same amount, leaving the retailer's available credit
numerically unchanged.

**R41.** WHEN a payment is registered against an issued invoice, THE SYSTEM SHALL
append a `release` ledger entry for that order's open exposure and SHALL emit
`credit.released.v1` with reason `invoice_paid`; and WHEN an order that holds an
active credit hold is cancelled before invoicing, THE SYSTEM SHALL append a
`release` entry for the hold and SHALL emit `credit.released.v1` with reason
`order_cancelled`. In both cases the retailer's available credit SHALL return to
its value before the hold was placed, and SHALL never be driven below zero
exposure (invariant **B5**).

### 5.1 Simulator affordance — NOT a credit policy

> **⚠ These three requirements describe a DEMO DETERMINISM DEVICE, not a business
> rule.**
>
> The `.99` rule and `CREDIT_FAILURE_RATE` exist for exactly one purpose: to make
> the **compensation path reproducible on demand**, in a demo, in an API test and
> in an end-to-end test, without having to construct a retailer whose credit limit
> is nearly exhausted. No real credit department rejects orders because the cents
> of the total happen to be 99.
>
> They live **behind the credit port**, in the credit-check *simulator adapter*
> that is bound in place of a real credit-assessment integration. Swapping the
> adapter removes them entirely, and nothing in the domain layer, the saga, the
> facts or the read model changes.
>
> **Trilogy obligation.** Assessments **#8** and **#9** MUST reproduce R42 and
> R43 **identically** — same predicate, same default, same rejection reasons —
> because the demo script, the API tests and the end-to-end tests of all three
> assessments place an order whose total ends in `.99` and assert that the order
> reaches `cancelled` with the stock visibly released. If an assessment changes
> or drops this affordance, compensation stops being demoable and the shared
> test matrix stops being portable.

**R42.** WHERE the credit-check **simulator** is the adapter bound to the credit
port, WHEN a `credit.hold` command is received whose order total amount satisfies
`totalAmount mod 100 = 99` in minor units, THE SYSTEM SHALL reject the hold with
reason `simulated_cents_rule` **regardless of the retailer's available credit**,
SHALL append no ledger entry, and SHALL emit `credit.rejected.v1`.

**R43.** WHERE the credit-check **simulator** is the adapter bound to the credit
port, THE SYSTEM SHALL additionally reject a pseudo-random proportion of hold
requests equal to the configured `CREDIT_FAILURE_RATE` with reason
`simulated_failure_rate`; THE SYSTEM SHALL default `CREDIT_FAILURE_RATE` to `0`
so that behaviour is deterministic unless a demo explicitly asks for noise; and
IF the configured value is not a number in the closed interval `[0, 1]`, THEN THE
SYSTEM SHALL fail to start and report the offending value.

**R44.** THE SYSTEM SHALL make a simulated rejection indistinguishable downstream
from a genuine over-limit rejection — same `credit.rejected.v1` fact type, same
payload shape, same compensation path — differing only in the `reason` field; and
THE SYSTEM SHALL NOT allow the simulator to bypass R37, so that a genuine
over-limit rejection remains reachable with the simulator bound and
`CREDIT_FAILURE_RATE = 0`.

---

## 6. `billing_invoicing`

The `Invoice` aggregate, its state machine, and the remittance intake.

**R45.** WHEN an `invoice.issue` command is received for an order in status
`despatched` that has no invoice, THE SYSTEM SHALL create exactly one invoice in
status `issued` whose lines mirror the despatched lines, whose amount is the sum
of `unitPrice × units`, whose total amount is `amount − discount` and is not
negative, and SHALL emit exactly one `invoice.issued.v1`; and IF an invoice
already exists for that order, THEN THE SYSTEM SHALL return the existing invoice
reference and emit no second fact (invariants **B6**, **B7**).

**R46.** THE SYSTEM SHALL allow an invoice to move only from `issued` to `paid`,
SHALL set `paidAt` exactly when the status becomes `paid` and SHALL leave it
unset while the invoice is `issued`; and IF any other invoice transition is
attempted, THEN THE SYSTEM SHALL raise a domain error, change nothing and emit
nothing (invariants **B8**, **B9**).

**R47.** WHEN a remittance is registered with a previously unseen
`paymentReference` against an invoice in status `issued`, whose amount and
currency equal the invoice's total amount and currency, THE SYSTEM SHALL record
the payment, SHALL set the invoice to `paid`, and SHALL emit
`payment.received.v1` followed by `credit.released.v1` in that order and in the
same transaction.

**R48.** WHILE a `paymentReference` has already been recorded, THE SYSTEM SHALL
respond to a repeated remittance with the original outcome, SHALL record no
second payment and SHALL emit no second `payment.received.v1` — the remittance
intake is idempotent by `paymentReference` (invariant **B10**).

**R49.** IF a remittance is registered whose amount differs from the invoice's
total amount, or whose currency differs from the invoice's currency, or which
targets an invoice already in status `paid` under a different
`paymentReference`, THEN THE SYSTEM SHALL reject it with a machine-readable
reason, SHALL leave the invoice and the credit ledger unchanged, and SHALL emit
no fact.

---

## 7. `projector_read_model`

The denormalised order timeline: the "what happened to order X and when" view.

**R50.** WHEN any fact is consumed by the projector, THE SYSTEM SHALL append an
entry carrying at least `eventId`, `eventType`, `occurredAt` and a
human-readable summary to the timeline of the order identified by the fact's
`correlationId`, and SHALL present the timeline ordered by `occurredAt` rather
than by arrival order.

**R51.** WHILE an `eventId` is already present in an order's timeline, THE SYSTEM
SHALL leave the read-model document unchanged on redelivery of that fact —
producing no duplicate timeline entry and no duplicate state update.

**R52.** IF a fact is consumed whose implied order status precedes the status
already recorded on the read-model document, THEN THE SYSTEM SHALL still append
the timeline entry but SHALL NOT regress the document's status field or overwrite
newer references, so that out-of-order delivery degrades ordering only, never
correctness.

**R53.** IF a fact is consumed for an order that has no read-model document yet,
THEN THE SYSTEM SHALL create a placeholder document keyed by the fact's
`correlationId`, SHALL record the fact in its timeline, and SHALL fill in the
order header fields when `order.placed.v1` is subsequently consumed.

**R54.** THE SYSTEM SHALL make the projector the **only** writer of the read
model, and SHALL serve every order list and order detail query from the read
model only — never by reading a write model and never by joining across bounded
contexts.

**R55.** WHEN a read-model document is created or updated, THE SYSTEM SHALL emit
an update signal that the real-time push channel delivers to subscribed clients;
and WHILE no read-model document yet exists for an order identifier that the
caller has just been given, THE SYSTEM SHALL respond with an explicit
"projection pending" indication rather than a not-found error, so that eventual
consistency is surfaced honestly instead of being hidden.

---

## 8. `observability_reliability`

One trace per order across both brokers, correlated logs, meaningful metrics, and
honest health.

**R56.** THE SYSTEM SHALL place every unit of work performed on behalf of one
order — the inbound HTTP request, every RPC command and response, every write-
model transaction, every fact publication and every fact consumption in every
service — under a **single trace identifier**, so that one distributed trace
shows the whole saga end to end.

**R57.** WHEN a message is published on either the fact stream or the RPC
transport, THE SYSTEM SHALL inject the W3C trace context into the message
headers; and WHEN a message is consumed from either, THE SYSTEM SHALL extract
that context and continue the trace from it rather than starting a new one.

**R58.** THE SYSTEM SHALL emit structured log records that carry the
`correlationId` and the trace identifier on **every** line produced while
handling a request, a command or a fact.

**R59.** THE SYSTEM SHALL expose metrics for at least: request latency per
endpoint, fact-processing latency per consumer, saga completion time from
`order.placed.v1` to `order.completed.v1` or `order.cancelled.v1`, outbox lag
measured as the age of the oldest unpublished outbox record, and dead-letter
depth per topic.

**R60.** THE SYSTEM SHALL expose a liveness and a readiness check per service,
and IF the service's write model, the fact stream or the RPC transport is
unreachable, THEN the readiness check SHALL report not-ready while the liveness
check SHALL remain unaffected, so that an unready service is withdrawn from
traffic without being restarted.

> **Id ordering / provenance.** This section reads R56 – R60 followed by
> **R62**. R62 was added after R61 already existed and ids are **never
> renumbered** (see *Notation*), so it takes the next free id. R62 is not,
> conceptually, an observability or reliability requirement — it is
> `orders.create`'s idempotent-replay contract. `asyncapi.yaml`'s
> `OrdersCreateRequestPayload.requestId` has stated it normatively ("a repeat
> with the same value returns the original order instead of placing a second
> one") since Pass B, but it was never given a shared `R<n>` at the time, and
> `orders_acceptance` (feature 15, `sdd: false`) shipped the field
> unenforced — accepted, validated, seeded only into `causationId`. The gap
> was opened by `progress/review_orders_acceptance.md`'s finding D3, tracked
> as its own dormant feature (`orders_idempotent_replay`, id 39) from Phase 8,
> and folded into this feature (`observability_reliability`, id 27) by
> explicit human decision on 2026-08-26. R62 sits in **this** section because
> feature 27 is the feature that closes it, exactly as R61 sits with
> `fulfillment_stock` for the same reason — not because request-id dedup is
> conceptually about tracing, logs, metrics or health.

**R62.** WHEN `orders.create` is received carrying a `requestId` that matches
a previously accepted request, THE SYSTEM SHALL create no new order and SHALL
return the reply of the **original** order — the same `orderId`,
`orderReference`, `currency` and monetary fields — as if this request had
placed it; WHERE two requests carrying the same, not-yet-seen `requestId`
arrive concurrently, THE SYSTEM SHALL ensure that exactly one order is
created for that `requestId` and SHALL resolve the other request to that same
order's reply, never to a second order or to an error; and WHERE `requestId`
is omitted, THE SYSTEM SHALL place a normal order with no deduplication
performed.


### 8.1 Edge protection of the unauthenticated login endpoint — R63

> **Filing note.** R63 is **not**, conceptually, an observability or reliability requirement, and the per-assessment feature that closes it is each assessment's **gateway**, not its `observability_reliability` feature. It is filed as a subsection of §8 for the same reason R61 and R62 carry the ids they do: ids are **never renumbered**, and section numbers are not renumbered either, because §9 and §10 are cited by id from `test-matrix.md` and from per-assessment specs. §8 is the last normative section, so a new normative subsection goes here. The subsection form itself follows §5.1's precedent.
>
> **Why a shared requirement at all, given §10's "auth, seeding and gateway endpoints are product-level concerns".** Because the refusal is already in the shared contract. `openapi.yaml` has declared `POST /auth/login` → `'429': TooManyRequests` since Pass B, and that file is inherited **verbatim** by #7, #8 and #9 — so every assessment already promises its clients a response that, without this requirement, nothing obliges it to be able to produce. #7 was in exactly that state until the `auth_rate_limit` pass, and the gap was invisible precisely because no `R<n>` and no `test-matrix.md` row existed to be `TODO`. §10 leaves open **which** auth endpoints exist and **how** credentials are checked; it does not license a documented response with no requirement above it. §10's own server-sent-events bullet already records the same judgement in the same words: where the shared contract publishes a surface, the shared requirements close the hole rather than leave it open.
>
> **What is required, and what is not.** R63 requires the **existence** of a limit on the unauthenticated login endpoint and the **observable consequences** of tripping it. It fixes no number: the attempt count and the window length are per-assessment configuration, exactly as §10's "concrete numbers deliberately left configurable" bullet already rules for the retry count, the poll interval and the RPC timeout. It also fixes no tracking key — per client address, per submitted identity, or per credential pair are all conforming, because the trilogy's own deployments differ (a browser client reaching the gateway through a server-side backend-for-frontend presents one address for every user, so mandating a per-address key here would mandate a policy that is wrong in at least one of the three).

**R63.** THE SYSTEM SHALL enforce a rate limit on the unauthenticated login endpoint published in `openapi.yaml`; IF a client exceeds that limit, THEN THE SYSTEM SHALL refuse the attempt with HTTP `429` carrying a `Problem` body and a `Retry-After` header stating, as a whole number of seconds, how long the client must wait, SHALL issue no token, and SHALL make the refusal independent of whether the submitted credentials were valid; and WHILE a client is being refused by that limit, THE SYSTEM SHALL continue to serve that client's requests to every other endpoint — the limit is scoped to the login endpoint and is never applied to the API as a whole.

---

## 9. Coverage notes

What these 63 requirements deliberately cover, so a reviewer can check the
spec rather than the code:

| Concern | Covered by |
|---|---|
| Every **legal** order transition | R8 (table), R19–R24 (each edge exercised by the saga), R26, R28 |
| Every **illegal** order transition | R9 (the rule), R7 (frozen lines), R25 (precondition guard) |
| Every **invoice** transition, legal and illegal | R45, R46 |
| **Reservation** lifecycle, legal and illegal | R32, R33, R34, R35, R36 |
| **Stock master-data maintenance**, outside the saga | R61 (replenishment adds on-hand units, emits no fact, advances no order) |
| Every **aggregate invariant** in `domain-model.md` | O1→R5, O3→R6, O4→R7, O5/O7→R8/R9, O6→R10, F1→R30, F3→R33, F4→R35, F5→R34, F6/F7/F8→R36, B1/B2→R37, B4→R29, B5→R41, B6/B7→R45, B8/B9→R46, B10→R48, M1→R1, M2→R2 |
| **Both** compensation paths | R26 (`StockRejected`, no release), R27+R28 (`CreditRejected`, release then cancel, ordering explicit) |
| **Outbox atomicity / no dual-write** | R13, R14 |
| **Consumer idempotency under redelivery** | R17, R18, plus R25 (state guard) and R29 (command idempotency) |
| **DLQ after N attempts** | R16 (consumers), R29 (saga commands) |
| **Read-model projection idempotency** | R51 |
| **Out-of-order tolerance in the read model** | R50 (ordering key), R52 (no status regression), R53 (placeholder) |
| **Trace propagation across both brokers** | R56, R57 |
| **Client-retry-safe order acceptance** | R62 (`orders.create`'s `requestId`; the concurrent-first-request race resolves to one order, never two, never an error) |
| **Money as integer minor units, always** | R1, reinforced by R2 |
| **The `.99` affordance, labelled as an affordance** | R42, R43, R44 and the boxed warning in §5.1 |
| **Abuse resistance at the edge** | R63 (a rate limit exists on the unauthenticated login endpoint; its observable refusal is a `429` with a `Problem` body and a `Retry-After` in seconds, scoped to that endpoint alone) |

---

## 10. Left to Pass B and to per-assessment specs

Recorded so #8 and #9 know where to look, and so nothing here is mistaken for an
omission:

- **`asyncapi.yaml`** — fact topic names, DLQ topics, RPC subject names, and the
  JSON schema of the envelope and of all thirteen payloads. Pass B.
- **`openapi.yaml`** — the gateway REST contract that the demo workflows depend
  on. Pass B.
- **`test-matrix.md`** — the `R<n>` → named-test mapping, initially all `TODO`.
  Pass B. Every id above must appear there at least once.
- **`n8n-workflows.md`** — the functional specification of the four demo
  workflows (order generator, payment robot, stock replenishment, burst). Pass B.
- **Concrete numbers** deliberately left configurable rather than fixed here:
  the consumer retry count and backoff schedule, the outbox poll interval, the
  RPC timeout, and the sequence-number width of business references. Each
  assessment fixes them in its `design.md`; only their *existence* and their
  observable consequences are required here (R16, R29, R59).
- **Auth, seeding and gateway endpoints** are product-level concerns specified
  per assessment; R54 and R55 constrain only where query answers may come from
  and how eventual consistency is surfaced. **One exception, added with R63:**
  where `openapi.yaml` publishes a response the outside world may observe, the
  shared requirements own that response. R63 therefore requires the login rate
  limit to exist and fixes what a client sees when it trips, while leaving the
  attempt count, the window length and the tracking key to each assessment.
  This exception is about the *published surface*, not about auth: an auth
  behaviour with no counterpart in `openapi.yaml` stays per-assessment.
- **The real-time transport is fixed, not left open.** Server-sent events are
  the trilogy's chosen realisation of R55's push channel and are published in
  `openapi.yaml` (`GET /orders/stream`, `text/event-stream`), which #7, #8 and #9
  reuse verbatim so the shared contract has no hole. WebSocket remains the
  documented alternative and may be substituted by a single assessment if a
  reason ever arises, but such a substitution is that assessment's deviation from
  the shared contract, not an option the contract leaves open.
