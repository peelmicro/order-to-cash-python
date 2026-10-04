# Shared Test Matrix — `R1`–`R63` → named tests

> **Fact-emission rule.** Every branch that emits — or deliberately suppresses — a domain fact must be covered by a test that **fails when that emission is deleted**. Structure and comments are not coverage. This applies with double force to branches that have no live caller yet, since integration harnesses bind the happy-path adapter and cannot reach them. Any assessment implementing this matrix should arm the deletion itself before claiming the row.

> **Scope.** The **stack-agnostic** traceability spine of the Order-To-Cash trilogy. Every EARS requirement of [`requirements.md`](./requirements.md) appears here exactly once, mapped to a test level and to a **named** test case that will prove it.
>
> **What is reused verbatim, and what is not.** Columns 1–4 of every table — the id, the requirement, the test level and the stack-neutral *Test file › case* sketch — together with this document's rules, conventions, amendment notes and summary structure, are the shared contract: assessments **#7**, **#8** and **#9** take them **unchanged**. Column 5 (**Status**) is **each assessment's own realisation record**: it names that assessment's real files and real case names, in that assessment's own language and test framework, and it starts at `TODO` for every row (rule 2 below) when an assessment begins. The Green/Scoped counts in the coverage summary are derived from column 5 and are per-assessment in the same way. An assessment starting from this file therefore **clears column 5 and those counts, and changes nothing else** — that, and not a byte-identical copy, is what "reused verbatim" means here. Concretely, starting a new assessment from this file is **four** mechanical steps and no judgement: (1) set every Status cell back to `TODO`; (2) reset the coverage summary's Green / Scoped / Not-yet-green counts to 0 / 0 / 63; (3) delete or replace **every paragraph explicitly labelled as a per-assessment aside** — each announces itself as one in its own opening words, and each exists so that the authoring assessment's own machinery never had to be smuggled into a shared rule; and (4) delete or rewrite the prose that **narrates one assessment's own realisation record** rather than stating a rule — it is derived from column 5 in exactly the way the counts are, and is per-assessment for the same reason. Two classes of it recur and are named here so they are not missed: any paragraph under the coverage table that recounts how the current counts came to be, and any amendment note that reasons from one assessment's own feature ordering or backlog rather than from a decision the trilogy shares. None of these are *stack* leaks, so keeping them would not breach `CHECKPOINTS.md` C7 — but they are the authoring assessment's history, they become false the moment they are inherited, and this recipe is a normative instruction, so it has to say so. This step was added in the Phase 25 closure pass, Round 4 (review finding N2); before that the recipe claimed three steps and *"everything else stays byte-for-byte"*, which was not true of this document. **Shared amendment SA-1** (raised in assessment #8, Phase 3; applied to #7 and #8 in the same session) reworded steps 3 and 4 from an *inventory of this copy* into a *description of the class*: the previous wording listed the specific paragraphs to delete, which made the recipe describe content that no longer existed the moment the recipe had been followed — correct when read, false immediately afterwards, and misleading to the next assessment inheriting the executed copy. A normative instruction that is invalidated by its own execution is a defect in the instruction, not in the reader. Everything that remains after those four steps — the rules, the Test levels table, the path convention, columns 1–4 of every row, the amendment notes that state a shared decision rather than one assessment's backlog, and the structure of every table including the summary — does stay byte-for-byte. Any stack term found outside those three places is a defect, and the fix is to move it into the Status cell it belongs to — never to soften the rule it leaked into.
>
> **Where stack-specific vocabulary is admissible.** In column 5 only, because it is a record of what that assessment actually built. Everywhere else — the rules, the level definitions, the path convention, the amendment notes — a stack-specific term would bind all three assessments to one stack and is a defect. A rule that has a stack-specific *mechanism* is written stack-neutrally, with the mechanism quarantined in a clearly-labelled per-assessment aside that the other two assessments may delete outright.
>
> Companion documents: [`domain-model.md`](./domain-model.md), [`saga.md`](./saga.md), [`asyncapi.yaml`](./asyncapi.yaml), [`openapi.yaml`](./openapi.yaml).

---

## The traceability rule

1. **Every requirement has at least one named test.** A requirement with no row
   here is a specification defect, not a testing gap.
2. **Status starts at `TODO` for every row.** The implementer flips a row to
   `DONE` only when the named test exists **and is green** — never when the
   production code merely looks finished.
3. **A feature cannot be marked `done` until every one of its rows is green — or scoped *and ratified*.** This is the gate: the backlog state machine may not advance a feature past implementation while any of its rows is still `TODO`. Partial coverage is visible as a partly-`TODO` group, never hidden behind a green build. A row whose named test is green but proves **less** than the requirement says is admissible only as a **ratified scoped** row, and ratification is a decision somebody takes, not a sentence somebody writes. Both conditions are required. (a) The cell states the shortfall as *which leg of the requirement is unproven*, in that requirement's own words, together with what closing it would take — "partially covered" states nothing a reader can act on and does not qualify. (b) The cell names the ratification: who accepted the deferral, and in which pass or record they accepted it. A shortfall disclosed only by whoever wrote the row is **not** ratified — that is the author marking their own homework — and such a row blocks this gate exactly as a `TODO` does, however well it reads. Be explicit about the pressure this class is under, because it is the one class in this document that can be abused without anybody lying: *scoped* is the most attractive word available here, it converts unfinished work into prose that reads finished, and it is written by the party with the strongest interest in the feature closing. The two conditions exist to make a scoped row cost more to write than the missing leg would have cost to finish: an honest one names its own gap and carries somebody else's name. Where either condition is absent the row is not scoped — it is unfinished, and the word for unfinished is `TODO`.
4. **Renaming a test means editing its row.** The test name in this table is the
   contract; a test whose name no longer matches has broken traceability even if
   it passes.
5. **Ids are stable.** `R<n>` is never renumbered, so #8 and #9 cite the same
   ids against their own test files.

## Test levels

| Level | What it may touch | What it must not touch |
|---|---|---|
| **domain unit** | Aggregates, value objects, state machines, invariants, compensation decisions | No store, no broker, no framework, no clock — time comes from a controllable clock port |
| **integration** | One service against **real** infrastructure: its write model, the fact stream, the RPC transport, the read model | Another service's internals |
| **API** | The composed stack **through the Gateway REST API only** (`openapi.yaml`) | No database, no broker, no service-internal call |
| **web component** | One UI component or composable with its inputs faked | No live backend |
| **e2e** | The whole composed stack driven through the user interface | Nothing is stubbed |
| **composed-stack integration** | The whole composed stack — every service running as its own real process against real infrastructure — driven **below** the user interface, through the API or through the transport | Nothing is stubbed here either, but the user interface is never exercised: nothing at this level evidences a claim about what a user sees, nor about anything that exists only on an inbound request arriving from the interface |

## Test path convention

Paths are written **stack-neutrally**, as `<area>/<layer>/<file>.spec` with no
language extension and no build-tool directory — for example
`orders/domain/order-state-machine.spec`. Each assessment maps them onto its own
conventions in its `design.md`:

| This matrix | Realised as |
|---|---|
| `orders/domain/order.spec` | the Orders service's domain test for the `Order` aggregate |
| `orders/integration/saga-happy-path.spec` | the Orders service's integration test for the happy path |
| `api/payment-idempotency.spec` | a black-box test through the Gateway |
| `web/components/order-timeline.spec` | a component test of the timeline |
| `observability/composed-stack/trace-continuity.spec` | a test that runs every service as its own real process and observes them together, below the user interface |
| `e2e/compensation-path.spec` | a browser-driven end-to-end test |

The `›` separator introduces the **test case name** inside the file.

**Verbatim vs. précis (H2, `progress/review_gateway_rest_auth.md` Round 3).** Every suite or case name quoted after a `›` — in backticks or in *italics* — is a **verbatim, character-exact quotation** of that string as it appears in the named test file, UNLESS it carries a leading `~` immediately before its opening backtick/asterisk (e.g. `` ~*a précis, not a quotation* ``), in which case it is a deliberate **précis**: a paraphrase, a summary of several cases, or a title with something dropped for brevity, and is exempt from the exact-match check. A citation that is genuinely a paraphrase must carry the `~`.

**Each assessment checks this mechanically, in its own language.** For every unmarked citation of the form *test-file path* › \[`suite name`\] › \*case name\* whose path names a real test file of that assessment, two things are asserted: the cited **path exists**, and the cited **string occurs literally inside it**. The comparison first normalises away differences that are purely cosmetic and cannot change what the string contains: (a) markdown escaping of characters that are markup in this document but plain text in the test's own title; (b) whatever escaping the implementation language applies to quote characters inside a string literal; (c) a title assembled at source level from several adjacent literals that the language joins into one runtime string; (d) typographic versus straight quotation marks. None of these loosen what counts as a match for a citation that has actually **drifted** — a renamed, deleted or summarised test still fails, because the underlying words differ, not their escaping. Unmarked and wrong is a defect the check must fail on; marked and wrong is a defect human review must still catch — the check trusts the marker, it does not police whether a précis is a *fair* précis.

## Coverage summary

Counted from the Status column as it actually stands, one row at a time, under three mutually exclusive classes that sum to the row count:

- **Green** — every half of the row names a test that exists and has been observed green, with no stated shortfall against the requirement's own wording.
- **Scoped** — the named test exists and is green, but proves **less** than the requirement says, with the shortfall stated explicitly in the cell. A scoped row is a *disclosed deferral, not coverage*, which is why it is counted in its own column: counting one as green is the failure mode this table exists to prevent. Rule 3 splits the class by **standing**, and the paragraph under the table says which rows hold which: a **ratified** scoped row has had its deferral consciously accepted, names who accepted it and what closing it would take, and may sit beneath a `done` feature; an **unratified** one is an open decision, not a finished row, and blocks the gate exactly as a `TODO` does — it is counted here rather than under *not yet green* only because what it is missing is a decision, not a test.
- **Not yet green** — at least one half has no test at all, or has a named test whose green run has not been observed.

| Feature | Requirements | Rows | Green | Scoped | Not yet green |
|---|---|---:|---:|---:|---:|
| 1. `orders_aggregate` | R1 – R10 | 10 | 0 | 0 | 10 |
| 2. `outbox_and_idempotency` | R11 – R18 | 8 | 0 | 0 | 8 |
| 3. `order_saga_orchestrator` | R19 – R29 | 11 | 0 | 0 | 11 |
| 4. `fulfillment_stock` | R30 – R36, R61 | 8 | 0 | 0 | 8 |
| 5. `billing_credit` | R37 – R44 | 8 | 0 | 0 | 8 |
| 6. `billing_invoicing` | R45 – R49 | 5 | 0 | 0 | 5 |
| 7. `projector_read_model` | R50 – R55 | 6 | 0 | 0 | 6 |
| 8. `observability_reliability` | R56 – R60, R62 | 6 | 0 | 0 | 6 |
| 8.1 gateway edge protection (per-assessment gateway feature) | R63 | 1 | 0 | 0 | 1 |
| **Total** | **R1 – R63** | **63** | **0** | **0** | **63** |

---

## 1. `orders_aggregate` — R1 – R10

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R1** | Every monetary amount is integer minor units plus an ISO 4217 code, everywhere | domain unit + API | `shared-kernel/domain/money.spec` › *represents 1 242,50 € as 124250 minor units and offers no decimal representation*<br>`api/money-representation.spec` › *every monetary field of every response is an integer accompanied by a currency code* | TODO |
| **R2** | Cross-currency arithmetic is a domain error, never an implicit conversion | domain unit | `shared-kernel/domain/money.spec` › *raises a domain error when EUR and GBP amounts are added, subtracted or compared* | TODO |
| **R3** | A quantity must be a strictly positive integer | domain unit | `shared-kernel/domain/quantity.spec` › *refuses zero, negative and fractional quantities and creates no value object* | TODO |
| **R4** | A GLN is 13 digits with a valid GS1 mod-10 check digit | domain unit | `shared-kernel/domain/gln.spec` › *accepts a valid GLN and refuses wrong length, non-digits and a bad check digit* | TODO |
| **R5** | An order always has at least one line (**O1**) | domain unit | `orders/domain/order.spec` › *refuses to create an order with no lines and to remove the last remaining line* | TODO |
| **R6** | Totals are recomputed on every line mutation and may not be negative (**O3**) | domain unit | `orders/domain/order-totals.spec` › *recomputes initialAmount, initialDiscount and totalAmount after each mutation and rejects a negative total* | TODO |
| **R7** | Lines are frozen from `confirmed` onwards (**O4**) | domain unit | `orders/domain/order.spec` › *refuses to add, remove or modify a line once the order is confirmed and leaves every field unchanged* | TODO |
| **R8** | Only edges of Table T-1; `completed` and `cancelled` terminal | domain unit | `orders/domain/order-state-machine.spec` › *walks every legal edge of Table T-1 and reaches cancelled only from placed, stock_reserved, credit_approved and confirmed* | TODO |
| **R9** | An illegal transition raises, changes nothing and appends no event | domain unit | `orders/domain/order-state-machine.spec` › *raises on every (from, to) pair absent from Table T-1 without mutating state or appending an event* | TODO |
| **R10** | Cancellation carries an immutable reason from the closed set (**O6**) | domain unit | `orders/domain/order-cancellation.spec` › *requires a reason from the closed set, records it immutably and carries it on order.cancelled.v1* | TODO |

## 2. `outbox_and_idempotency` — R11 – R18

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R11** | Complete envelope on every fact; `eventType` matches `<aggregate>.<fact>.v<n>` | domain unit | `shared-kernel/domain/event-envelope.spec` › *refuses an envelope with an absent, null or empty field and an eventType that does not match the pattern* | TODO |
| **R12** | `correlationId` = order id; `causationId` = the causing event or command | integration | `orders/integration/outbox-envelope.spec` › *stamps every fact of one order with the order id as correlationId and the causing event id as causationId* | TODO |
| **R13** | Aggregate state and outbox records commit in one transaction, or neither | integration | `orders/integration/outbox-atomicity.spec` › *persists neither the aggregate nor the outbox record and publishes nothing when the transaction fails* | TODO |
| **R14** | Only the relay publishes; unacknowledged records are republished | integration | `orders/integration/outbox-relay.spec` › *stamps a record only after the broker acknowledgement and republishes an unstamped record on the next poll* | TODO |
| **R15** | `correlationId` is the partition key, giving per-order ordering | integration | `orders/integration/fact-partitioning.spec` › *delivers all facts produced by one context about one order to consumers in emission order* | TODO |
| **R16** | Retry with backoff, then `<topic>.dlq` with consumer, attempts and error, then ack | integration | `orders/integration/fact-retry-dispatcher.spec` › *retries a fact whose processing throws up to the configured maximum, then publishes it to the topic's `.dlq` with `x-failed-consumer`, `x-attempts` and `x-error`, and acknowledges the original*<br>`orders/integration/saga-dead-letter.spec` › *a fact that fails for a reason the envelope guard cannot catch — a malformed `correlationId` — is retried, dead-lettered, and the consumer offset commits so the next, distinct fact on the same partition still processes* | TODO |
| **R17** | (`eventId`, consumer) recorded in the same transaction as the effects | integration | `orders/integration/idempotent-consumer.spec` › *records the eventId and consumer name in the same transaction as the state change and the outbox records* | TODO |
| **R18** | A redelivery is acknowledged with no mutation, no fact, no command | integration | `orders/integration/idempotent-consumer.spec` › *acknowledges a redelivered fact without mutating state, emitting a fact or issuing a command* | TODO |

## 3. `order_saga_orchestrator` — R19 – R29

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R19** | `order.placed.v1` + `placed` → issue `stock.reserve`, status unchanged | integration | `orders/integration/saga-happy-path.spec` › *issues stock.reserve for every line on order.placed.v1 and leaves the order in placed* | TODO |
| **R20** | `stock.reserved.v1` + `placed` → `stock_reserved`, issue `credit.hold` | integration | `orders/integration/saga-happy-path.spec` › *moves placed to stock_reserved and issues credit.hold for the order total* | TODO |
| **R21** | `credit.approved.v1` + `stock_reserved` → `credit_approved` → `confirmed`, one `order.confirmed.v1`, issue `despatch.create` | integration | `orders/integration/saga-happy-path.spec` › *moves stock_reserved through credit_approved to confirmed, emits exactly one order.confirmed.v1 and issues despatch.create* | TODO |
| **R22** | `order.despatched.v1` + `confirmed` → `despatched`, issue `invoice.issue` | integration | `orders/integration/saga-happy-path.spec` › *moves confirmed to despatched and issues invoice.issue* | TODO |
| **R23** | `invoice.issued.v1` + `despatched` → `invoiced`, no further command | integration | `orders/integration/saga-happy-path.spec` › *moves despatched to invoiced and issues no further command while awaiting a remittance* | TODO |
| **R24** | `payment.received.v1` → `paid`; `credit.released.v1` → `completed` + one `order.completed.v1`, with the completion triple (`payment.received.v1`, `credit.released.v1`, `order.completed.v1`) visible in the timeline in **causal order** (amendment A1, `projector_read_model` PR10/PR30–PR33) | integration + API | `orders/integration/saga-happy-path.spec` › *moves invoiced to paid then paid to completed and emits exactly one order.completed.v1*<br>`api/black-box-api.spec` › *scenario 1 — the completion triple is present, and the GENERAL causal-order invariant (`assertCausalOrder`: for every entry whose `causationId` names another entry's `eventId` in the same timeline, the cause precedes the effect) holds over the order's full `events[]`* | TODO |
| **R25** | A fact with an unmet precondition changes nothing and is recorded as ignored | integration | `orders/integration/saga-preconditions.spec` › *ignores a fact whose precondition status is unmet and records the observed and expected status* | TODO |
| **R26** | `stock.rejected.v1` + `placed` → cancel `stock_rejected`, **no** release command | integration | `orders/integration/saga-compensation-stock-rejected.spec` › *cancels with reason stock_rejected and issues no stock.release command* | TODO |
| **R27** | `credit.rejected.v1` + `stock_reserved` → issue `stock.release`, stay `stock_reserved` | integration | `orders/integration/saga-compensation-credit-rejected.spec` › *issues stock.release as the first compensation step and leaves the order in stock_reserved* | TODO |
| **R28** | `stock.released.v1` → cancel `credit_rejected`; both steps visible in causal order | integration + e2e | `orders/integration/saga-compensation-credit-rejected.spec` › *cancels with reason credit_rejected only after stock.released.v1 arrives*<br>`e2e/compensation-path.spec` › *a .99 order reaches cancelled with the stock release and the cancellation shown separately in causal order* | TODO |
| **R29** | RPC timeout → retry with backoff, status unchanged, idempotent commands, then DLQ + saga-failure entry | integration | `orders/integration/saga-command-retry.spec` › *retries a timed-out command with backoff without changing the order status and records the exhausted attempts durably*<br>`orders/integration/saga-command-dead-letter.spec` › *on a saga command's first transition into parked, publishes the triggering fact to the source topic's `.dlq` exactly once and appends an `order.saga_failed.v1` entry to the order timeline, while the sweeper's indefinite capped-backoff retry (SO5) continues unchanged* | TODO |

## 4. `fulfillment_stock` — R30 – R36, R61

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R30** | `reservedUnits ≤ units` always; a breaking operation is rejected in full (**F1**) | domain unit | `fulfillment/domain/stock-item.spec` › *rejects in full any operation that would push reservedUnits above units and changes no stock item* | TODO |
| **R31** | Availability check answers per line, mutates nothing, emits nothing | integration | `fulfillment/integration/stock-check.spec` › *answers per line without mutating a stock item and without emitting a fact* | TODO |
| **R32** | `stock.reserve` with every line satisfiable → one reservation per line, one `stock.reserved.v1` | domain unit | `fulfillment/domain/reservation.spec` › *creates one reservation per line, increases reservedUnits and emits exactly one stock.reserved.v1* | TODO |
| **R33** | Any short line → nothing reserved, `stock.rejected.v1` naming the shortages (**F3**) | domain unit | `fulfillment/domain/reservation.spec` › *creates no reservation at all and emits stock.rejected.v1 naming requested and available units when one line is short* | TODO |
| **R34** | `stock.release` releases once; an already-released order is a success no-op with no second fact (**F5**) | domain unit + integration | `fulfillment/domain/reservation-release.spec` › *releases the reservations, decreases reservedUnits and emits exactly one stock.released.v1*<br>`fulfillment/integration/stock-release-idempotency.spec` › *answers success and emits no second fact when every reservation is already released* | TODO |
| **R35** | A reservation moves only `reserved → released` or `reserved → consumed`; terminals are terminal (**F4**) | domain unit | `fulfillment/domain/reservation.spec` › *refuses every transition out of released and out of consumed and changes nothing* | TODO |
| **R36** | `despatch.create` consumes the reservations, creates one despatch advice, emits one fact; no reservation → nothing (**F6**, **F7**, **F8**) | domain unit + integration | `fulfillment/domain/order-despatch.spec` › *consumes every reserved reservation of the order across two items, moves them to consumed, and creates one DespatchAdvice with one fact*, *defensive: no_reservations when no item holds a reserved reservation of the order*<br>`fulfillment/domain/despatch-advice.spec` › *creates the aggregate and emits exactly one order.despatched.v1 whose payload traces each line to a despatched product/units pair*, *F6 — refuses an empty line list*<br>`fulfillment/integration/despatch-create.spec` › *happy path*, *F8 — a re-issued despatch.create...*, *R36 precondition — never reserved...*, *R36 precondition — every reservation already released...*, *concurrency against a simultaneous stock.release...* | TODO |
| **R61** | Replenishment adds on-hand `units` only — reservations, `reservedUnits` and every order untouched, no fact emitted | domain unit + API | `fulfillment/domain/stock-replenishment.spec` › *increases units by the requested quantity, leaves reservedUnits and every reservation unchanged and appends no domain event*<br>`api/stock-replenishment.spec` › *tops up a stock item without emitting a fact, without touching any reservation and without advancing any order* | TODO |

## 5. `billing_credit` — R37 – R44

Rows **R42**–**R44** cover the credit-check **simulator affordance**, not a
credit policy (`requirements.md` §5.1). They are non-negotiable across the
trilogy: they are what makes the compensation path reproducible on demand in the
demo, in the API tests and in the end-to-end tests.

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R37** | Holds + exposure ≤ limit; ledger is append-only (**B1**, **B2**) | domain unit | `billing/domain/buyer-credit.spec` › *keeps active holds plus open exposure within the credit limit and raises on any update or deletion of a ledger entry* | TODO |
| **R38** | Approved hold → one `hold` entry + one `credit.approved.v1` | domain unit | `billing/domain/credit-hold.spec` › *appends a hold entry and emits exactly one credit.approved.v1 carrying the held amount and the resulting available credit* | TODO |
| **R39** | Refused hold → no entry, unchanged credit, `credit.rejected.v1` with a reason (amended — the currency clause moved to `BC4`, a contract violation, per `requirements.md` §3 and the human-gate ruling) | domain unit | `billing/domain/credit-hold.spec` › *appends no ledger entry and emits credit.rejected.v1 with a machine-readable reason when the amount exceeds the available credit or the credit port refuses* | TODO |
| **R40** | Invoice issue converts the hold into exposure, leaving available credit unchanged | domain unit | `billing/domain/credit-ledger.spec` › *appends a consume entry at invoice issue that leaves available credit numerically unchanged and emits no fact* | TODO |
| **R41** | Payment and pre-invoice cancellation release credit with the right reason (**B5**) | domain unit | `billing/domain/credit-ledger.spec` › *releases with reason invoice_paid on payment and with reason order_cancelled on cancellation, restoring available credit without going below zero* | TODO |
| **R42** | Simulator: `totalAmount mod 100 = 99` → reject `simulated_cents_rule` regardless of credit | domain unit + integration | `billing/infrastructure/credit-simulator.spec` › *rejects a total whose minor units end in 99 with reason simulated_cents_rule even when the retailer has ample credit* | TODO |
| **R43** | `CREDIT_FAILURE_RATE` defaults to 0 and an out-of-range value fails startup | domain unit | `billing/infrastructure/credit-simulator.spec` › *defaults the failure rate to zero, rejects a configured proportion when set, and fails to start reporting the offending value when it is outside the closed interval zero to one* | TODO |
| **R44** | Simulated and genuine rejections are indistinguishable downstream except by `reason` | integration | `billing/integration/credit-rejection-parity.spec` › *produces the same fact type, payload shape and compensation path for a simulated and a genuine over-limit rejection, and keeps the over-limit rejection reachable with the simulator bound and the failure rate at zero* | TODO |

## 6. `billing_invoicing` — R45 – R49

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R45** | One invoice per order, lines mirror the despatch, repeat returns the existing reference (**B6**, **B7**) | domain unit | `billing/domain/invoice.spec` › *creates exactly one issued invoice mirroring the despatched lines with a non-negative total and returns the existing reference emitting no second fact on a repeat* | TODO |
| **R46** | Only `issued → paid`; `paidAt` set exactly then (**B8**, **B9**) | domain unit | `billing/domain/invoice.spec` › *allows only the transition from issued to paid, sets paidAt exactly then, and raises on every other transition changing and emitting nothing* | TODO |
| **R47** | Unseen `paymentReference` with matching amount → paid + `payment.received.v1` then `credit.released.v1` in one transaction | integration | `billing/integration/payment-intake.spec` › *records the payment, marks the invoice paid and emits payment.received.v1 followed by credit.released.v1 in that order and in one transaction* | TODO |
| **R48** | Repeated `paymentReference` → original outcome, one payment, no second fact (**B10**) | API | `api/payment-idempotency.spec` › *returns the original outcome and records exactly one payment and one fact when the same paymentReference is registered twice* | TODO |
| **R49** | Mismatched amount or currency, or a second reference against a paid invoice, is rejected with nothing changed | API | `api/payment-rejection.spec` › *rejects a mismatched amount, a mismatched currency and a different reference against an already-paid invoice with a machine-readable code, leaving the invoice and the credit ledger unchanged* | TODO |

## 7. `projector_read_model` — R50 – R55

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R50** | Every fact appends a timeline entry to the `correlationId` document, ordered by `occurredAt` | integration | `projector/integration/timeline-projection.spec` › *appends an entry carrying eventId, eventType, occurredAt and a summary and presents the timeline ordered by occurredAt rather than by arrival* | TODO |
| **R51** | A known `eventId` leaves the document unchanged on redelivery | integration | `projector/integration/timeline-projection.spec` › *leaves the read-model document unchanged when a fact with an already-present eventId is redelivered* | TODO |
| **R52** | An out-of-order fact appends but never regresses the status or overwrites newer references | integration | `projector/integration/out-of-order-facts.spec` › *appends the timeline entry without regressing the document status or overwriting newer references* | TODO |
| **R53** | A fact for an unknown order creates a placeholder, filled in when `order.placed.v1` arrives | integration | `projector/integration/placeholder-document.spec` › *creates a placeholder document keyed by correlationId and fills in the header fields when order.placed.v1 is consumed later* | TODO |
| **R54** | The projector is the only writer; list and detail queries are served from the read model only | integration | **projector half** — `projector/integration/sole-writer.spec` › *permits a read-model WRITE only in the projector and the allow-listed offline fixture loader, while permitting a read anywhere the requirement allows one, and declares no write-model dependency of its own*<br>**gateway half** — `gateway/integration/query-source.spec` › *answers order list and detail queries with every write model disconnected, proving no write-model read and no cross-context join* | TODO |
| **R55** | Update signal reaches subscribers; an unprojected order answers "projection pending", never not-found | integration + API + web component | **projector half** — `projector/integration/update-signal.spec` › *emits exactly one update signal per applied fact, on a per-order channel a single-order and a whole-stream subscriber both receive, and none at all for a suppressed redelivery*<br>**gateway half** — `api/projection-pending.spec` › *answers projection pending rather than not found for an order id just returned by place-order*<br>**web half** — `web/components/order-detail-pending.spec` › *renders the waiting state on a projection-pending answer and fills in from the update stream* | TODO |

## 8. `observability_reliability` — R56 – R60, R62

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R56** | One trace identifier spans the whole saga end to end | composed-stack integration + e2e | `observability/composed-stack/trace-continuity.spec` › *shows one trace identifier shared by every command, every write-model transaction and every fact publication of a single order across every service process of the composed stack*<br>`e2e/trace-continuity.spec` › *shows that same trace identifier beginning at the inbound request that placed the order and continuing through the consumption of every fact it caused* | TODO |
| **R57** | W3C trace context injected on publish and continued on consume, on both transports | integration | `orders/integration/trace-context-propagation.spec` › *injects `traceparent` into the outbound NATS request headers and into the outbox-relayed Kafka fact headers, and continues (does not restart) the trace when the corresponding fact is consumed* | TODO |
| **R58** | Every log line carries `correlationId` and the trace identifier | integration | `orders/integration/log-correlation.spec` › *emits structured records carrying correlationId and traceId on every line produced while handling a request, a command and a fact* | TODO |
| **R59** | Metrics for request latency, consumer latency, saga duration, outbox lag and DLQ depth | integration | `orders/integration/metrics-exposure.spec` › *records request latency, fact-processing latency per consumer, saga completion time, outbox lag and dead-letter depth as metric instruments with the documented names* | TODO |
| **R60** | Readiness fails on an unreachable dependency while liveness stays up | API | `api/health-probes.spec` › *reports not-ready on readiness while liveness remains unaffected when the write model, the fact stream or the RPC transport is unreachable* | TODO |
| **R62** | A repeated `requestId` on `orders.create` returns the original order, never a second one; a concurrent first-time race still yields exactly one order; an omitted `requestId` is unchanged | unit + integration | `orders/domain/place-order-idempotent-replay.spec` › *a repeated requestId returns the original order's reply and creates no second order*<br>`orders/integration/orders-create-idempotent-replay.spec` › *two concurrent first-time orders.create requests carrying the same requestId create exactly one order, and the loser's reply matches the winner's* | TODO |

---

## 8.1 gateway edge protection — R63

> **Whose feature this is.** R63 lives in `requirements.md` §8.1 for id-stability reasons explained there; the feature that closes it is each assessment's **gateway**, not its `observability_reliability` feature. The level is **API**: the requirement is entirely about what a client observes through `openapi.yaml`, so nothing below the gateway needs to be reachable to prove it.

| Id | Requirement (short) | Level | Test file › case | Status |
|---|---|---|---|---|
| **R63** | A rate limit exists on the unauthenticated login endpoint; tripping it yields `429` + `Problem` + `Retry-After` in seconds, issues no token, does not depend on whether the credentials were valid, and does not affect any other endpoint | API | `api/login-rate-limit.spec` › *exceeding the login rate limit answers 429 with an `application/problem+json` body matching `components.schemas.Problem` and a `Retry-After` header carrying a whole number of seconds, and issues no token*<br>`api/login-rate-limit.spec` › *the same 429 is returned for valid and for invalid credentials once the limit is exceeded, so the refusal reveals nothing about the credentials*<br>`api/login-rate-limit.spec` › *a client refused by the login limit continues to be served on every other endpoint — the limit is scoped to the login route, never global* | TODO |

---

## Verification

- **63 rows, ids `R1`–`R63`, contiguous and unique.** Verified by count against
  the eight feature groups above (plus §8.1) and against `requirements.md`.
  (`R61`, `R62` and `R63` are each the *next free id* at the time they were
  added, not a renumbering — see `requirements.md`'s own "Id ordering" notes at
  §4 and §8 and its §8.1 filing note — so "contiguous" means the union of ids,
  not each section's own run.)
- Every row names a **file** and a **case**; no row says "covered by the suite".
- The four cross-cutting demonstrations a reviewer will look for are reachable
  from this table alone:

  | Demonstration | Rows |
  |---|---|
  | Happy path end to end | R19 – R24 |
  | Compensation, both paths, with the stock visibly released | R26, R27, R28, R33, R34, R42 |
  | Effectively-once processing under at-least-once delivery | R16, R17, R18, R25, R29, R48, R51 |
  | One trace and honest health across both brokers | R56, R57, R58, R59, R60 |
  | Client-retry-safe order acceptance | R62 |
  | Abuse resistance at the published edge | R63 |
