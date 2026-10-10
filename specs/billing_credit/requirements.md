# Requirements — `billing_credit` (feature 19, phase 10, `sdd: true`)

> **This is a pointer document.** `specs/shared/` was copied verbatim from #8 (with `SA-1` – `SA-5` applied) and is **read-only**. The shared requirements this feature realises are cited by id and **not restated**: `specs/shared/requirements.md` §5 (`R37` – `R41`, including the boxed amendment under `R39` that moved the currency and unknown-pair clauses to contract violations) is their single authority, elaborated by `specs/shared/domain-model.md` §5.1 (`BuyerCredit`, `CreditLedgerEntry`, the derived quantities, invariants **B1** – **B5**), `specs/shared/saga.md` §2 (command vocabulary and idempotency keys), §3.1 steps 2, 3, 6 and 7, §4.2 – §4.3 (the credit-rejection compensation, why nothing is released on it, the SA-4 operator-cancel ordering and the late-approval paragraph), §5 (Billing consumes no fact) and §6 (the redelivery table), and `specs/shared/asyncapi.yaml` (channels `creditHold` / `creditRelease` / `creditList` at lines 419 – 471, operations `requestCreditHold` / `requestCreditRelease` / `requestCreditList` at lines 1019 – 1088, `RpcHeaders`, `RpcError` and its closed twelve-value `code` enum, the `CreditApproved` / `CreditRejected` / `CreditReleased` payloads and the `billingFacts` topic). Nothing below amends, rewords or reinterprets them. The stack-specific value of this feature is in [`design.md`](./design.md).
>
> **Local ids.** This file reuses #8's local ids (`../order-to-cash-dotnet/specs/billing_credit/requirements.md` §1) **`BC1` – `BC17`, `BC20` – `BC22`, `BC24` – `BC28`, `BC30` and `BC32`**, numbering unchanged (`BC1` – `BC17` and `BC20` are #7's, `BC21` – `BC32` #8's). Reusing an id is a claim that the Python / PostgreSQL / nats-py realisation owes the same obligation; each was checked against `design.md` before it was written down, and where the mechanism differs a *#9 note* says how. **Not claimed, each with its reason (§2.2):** `BC18`, `BC19` (for #8's reasons), `BC23` (its premise, hand-retyped key lists, does not exist here), `BC29` (its mechanism is a compile error; #9's realisation is `BC34`), `BC31` (an Orders property, already realised by feature 16). **`BC33` – `BC39` are new in #9**, each tied to an acceptance item of `feature_list.json` id 19, to a measurement made for this spec, or to a #8 backlog finding, and each says why #7 and #8 did not carry it. `BC38` depends on gate point **G1** (`design.md` §16.1).

## 1. Shared requirements realised

| Shared id | One-line reminder (authority: `specs/shared/requirements.md` §5) | Realised in #9 by | `design.md` |
|---|---|---|---|
| **R37** | Holds + exposure ≤ limit (**B1**); the ledger is append-only (**B2**) | `BuyerCredit.evaluate_hold` decides, `approve` refuses anything but `Fits`, `rehydrate` refuses a snapshot already over its limit; `CreditLedgerEntry` is a frozen value with no mutator; the repository only ever inserts `credit_items` rows (the write-path population test makes any `UPDATE` / `DELETE` an unclassified hit) | §5.1 – §5.3, §9.2 |
| **R38** | Fitting, currency-matching, port-approved hold → one `hold` entry + exactly one `credit.approved.v1` | `approve` appends one entry and raises one `CreditApproved` whose `available_credit_after` is recomputed with the entry; the repository writes the row and the outbox record in one transaction | §5.1, §6.2 |
| **R39** | Over-limit or port-refused hold → no entry, credit unchanged, `credit.rejected.v1` with a reason (currency and unknown pair are contract violations: no fact, an error reply) | `refuse` raises one `CreditRejected` through one builder for every refusal; the credit-decision port is consulted only on `Fits` and cannot say `over_limit`; currency mismatch and unknown pair raise application errors before any fact | §5.1, §7.4, §8.5 |
| **R40** | Invoice issue converts the hold into exposure, available credit numerically unchanged | `consume` appends one `consume` entry and raises nothing; `consume` appears in neither term of `available_credit`, so neutrality is a property of `summarise`, not a rule | §5.3 |
| **R41** | Payment releases with `invoice_paid`, pre-invoice cancellation with `order_cancelled`; credit returns to its pre-hold value, never below zero (**B5**) | `release(order_reference, reason, …)` appends one `release` entry for the order's outstanding exposure and raises one `CreditReleased`; the `billing.credit.release` responder drives the `order_cancelled` half (`BC25`); the `invoice_paid` half's caller is feature 22 | §5.1, §6.3 |

**What feature 19 proves, and what it leaves.** The matrix rows `R37` – `R41` are domain-unit rows (`specs/shared/test-matrix.md` §5) and are flipped by this feature's named tests. `R40` is **delivered but not driven**: `consume` ships with its domain tests and no caller, exactly as #7 and #8 shipped it (#8 `requirements.md` header; #7 `requirements.md` header); its caller is feature **21** `billing_invoicing` (seam: `design.md` §15.2). `R41`'s `invoice_paid` half has no caller here; its caller is feature **22** `billing_remittance_intake`, which calls the same `release` with `reason = invoice_paid` and its own `CreditContext` (seam: `design.md` §15.3). `R42` – `R44` are feature **20** `billing_credit_simulator`'s and stay `TODO`: this feature owns only the **port** they sit behind and the structural guarantee `R44` needs (`BC13` – `BC15`), so feature 20 is a binding change (seam: `design.md` §15.1). The live walkthrough of this feature also places one genuine over-limit order with no simulator bound, which is `R44`'s last clause observed before feature 20 exists (#8 `tasks.md` I3 did the same).

### 1.1 Related shared requirements this feature composes with but does not own

`R12` (`correlationId` / `causationId` chains — `BC1`), `R13` – `R15` (outbox, relay, partition key — Billing's copies are proven against them through the parity guard, `BC17`; the rows stay feature 14's), `R17` / `R18` (the idempotent consumer — **not** copied into Billing, `design.md` §10.4), `R26` – `R28` (the compensation `credit.rejected.v1` triggers — feature 16's, already green), `R29` (the orchestrator's retry and its `(orderReference, operation)` responder contract — Billing's half is `BC7`).

### 1.2 Shared-contract observations inherited, not fixed here

1. `saga.md` §2's command table still has **no row for `credit.release`**, while `asyncapi.yaml`'s `requestCreditRelease` names *"Caller — orders.saga"*. #8 recorded this with **owner feature 41** (`../order-to-cash-dotnet/specs/billing_credit/requirements.md` §3 item 1). Unchanged in #9; this feature builds the responder that row would point at. Not an `SA-6`: the subject and both payload schemas exist; only a table row is missing, and its owner has not run.
2. No shared requirement obliges the `x-correlation-id` / `x-request-id` request headers, yet `R12` is unsatisfiable for Billing-emitted facts without them. Inherited from #7 (promotion candidate 2) and #8 (§3 item 2); feature 17's gate closed #8's promotion candidates without an `SA-6` (G3, `specs/fulfillment_stock/design.md` §16.1), and the same reasoning applies.

## 2. Local requirements

### 2.1 Reused from #7 and #8

Texts are #8's, verbatim except where a *#9 note* is attached; line-unwrapped only.

**BC1.** WHEN Billing emits a fact in response to a `billing.credit.hold` or `billing.credit.release` command, THE SYSTEM SHALL set the fact's `correlationId` from the request's `x-correlation-id` header and its `causationId` from the request's `x-request-id` header (`R12`); IF either header is absent or is not a well-formed `UniqueId`, THEN THE SYSTEM SHALL reply `RpcError` `VALIDATION_FAILED`, SHALL append no ledger entry and SHALL emit no fact. `billing.credit.list` SHALL require neither header.

> *#9 note.* The premise holds: Orders sends both headers on every saga command attempt (`services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:143`, guarded by SO14). The malformed-`x-request-id`-only case is a case of its own (#8 review D4: the theory malformed only `x-correlation-id`).

**BC2.** THE SYSTEM SHALL accept `billing.credit.hold`, `billing.credit.release` and `billing.credit.list` as **bare JSON** payloads matching their AsyncAPI request schemas — no framework packet envelope around them — and SHALL reply with a bare JSON success payload or a bare JSON `RpcError`, serialised through the one shared serializer; a responder SHALL never reply with anything else and SHALL never leave a request unanswered on any path it can reach.

> *#9 note.* The one serializer is `otc_contracts.to_wire_json`; requests are parsed by `from_wire_json` into the generated models. "Never unanswered" excludes a message with no reply subject, which is logged and dropped exactly as Fulfillment's responder does (`stock_responder.py:209-211`).

**BC3.** IF a `billing.credit.hold` or `billing.credit.release` command names a `(retailerCode, companyCode)` pair for which **no** credit line exists, THEN THE SYSTEM SHALL reply `RpcError` `NOT_FOUND` naming the pair, SHALL append no ledger entry and SHALL emit **no** fact, and SHALL NOT create a credit line on demand — a credit line is master data, and a fact with no aggregate has no `aggregateId` to carry (`domain-model.md` §7.1).

**BC4.** IF a `billing.credit.hold` command names a currency other than the resolved credit line's currency, THEN THE SYSTEM SHALL reply `RpcError` `VALIDATION_FAILED` carrying the expected and received codes, SHALL append no ledger entry and SHALL emit **no** fact — an order is single-currency by **M2**/**O1** and a credit line's currency is its retailer's, so a mismatch is a defective message, not a statement about the buyer's credit, and the three `reason` values of `credit.rejected.v1` stay closed (`R44`).

**BC5.** THE SYSTEM SHALL derive a credit line's available credit **only** from its `credits` row and its append-only ledger, as `committedExposure(line) = Σ amount WHERE type = 'hold' − Σ amount WHERE type = 'release'` and `availableCredit(line) = creditLimit − committedExposure(line)`, and SHALL persist **no** materialised, cached or derived available-credit, active-hold or open-exposure column anywhere. A `consume` entry appears in neither term, which is *why* invoice issue is numerically neutral (`R40`).

**BC6.** THE SYSTEM SHALL derive the per-order split reported by `billing.credit.list` as `exposure(order) = Σ hold(order) − Σ release(order)`, `openExposure(order) = min(Σ consume(order), exposure(order))`, `activeHold(order) = exposure(order) − openExposure(order)`, and SHALL satisfy, for every credit line and at every instant, `Σ activeHold(order) + Σ openExposure(order) = creditLimit − availableCredit`.

> *#9 note.* `domain-model.md` §5.1's literal formula is not used, for #7's and #8's reason (its *"applied to holds"* qualifier is not computable, and its naive reading yields a negative `openExposure` for an order cancelled before invoicing); `domain-model.md` is not edited (#8 gate record row 3).

**BC7.** WHILE a `hold` ledger entry already exists for the request's `orderReference` on the resolved credit line — **whatever its net exposure is now**, including an order whose hold has since been released — THE SYSTEM SHALL reply to `billing.credit.hold` with `outcome: already_held` carrying the amount of that recorded `hold` entry as `heldAmount` and the line's **current** `availableCredit`, SHALL append no ledger entry, SHALL consult the credit-decision port not at all, and SHALL emit no fact (invariant **B4**, `saga.md` §6 layer 3, `R29`'s responder half). The idempotency key is `(orderReference, hold)`; `x-request-id` is **not** the key.

**BC8.** IF a `billing.credit.hold` command is re-issued for an order whose previous hold was **rejected**, THEN THE SYSTEM SHALL re-evaluate the request from scratch — a rejection records nothing (**B1**), so there is nothing for `BC7` to recognise — and MAY therefore emit a second `credit.rejected.v1` with a distinct `eventId`; THE SYSTEM SHALL rely for safety on the orchestrator's three idempotency layers and on its `(order_id, command)`-idempotent enqueue, and SHALL NOT invent a fourth ledger entry type to record refusals.

> *#9 note.* The enqueue idempotency is #9's feature 16 (`specs/order_saga_orchestrator/design.md` L10); this feature changes nothing in Orders.

**BC9.** WHEN executing `billing.credit.hold` or `billing.credit.release`, THE SYSTEM SHALL acquire an exclusive row lock on the resolved `credits` row **before** reading any `credit_items` row and before evaluating anything, and SHALL perform every read and every write of that line's ledger inside that same transaction, so that IF two commands for different orders compete against one credit line concurrently, THEN their combined recorded holds never exceed `creditLimit` and neither transaction deadlocks (exactly one row is ever locked, so no lock-ordering cycle can form).

> *#9 note.* This is #7's text. #8 added *"SHALL make every `credit_items` read of that transaction a locking read"* because under `READ_COMMITTED_SNAPSHOT` an unhinted read is a row version taken before the lock. That clause is **not** claimed: PostgreSQL refuses `FOR UPDATE` with an aggregate (measured, `design.md` header), so the committed-exposure read cannot lock. The property the clause served — every ledger read is current, never older than the lock — is `BC35`'s, and is supplied by reading only after the line lock is granted, at `READ COMMITTED` pinned per transaction.

**BC10.** WHEN a `credit.hold` is approved, THE SYSTEM SHALL append exactly one `hold` entry and exactly one `credit.approved.v1` **in the same transaction** (`R38`, `R13`), and the fact's `availableCreditAfter` SHALL equal `availableCredit` recomputed from the ledger *including* the entry just appended — never the pre-hold value, never a value carried from the request.

**BC11.** WHEN `release` is invoked for an order, THE SYSTEM SHALL append exactly one `release` entry for that order's **outstanding exposure** and emit exactly one `credit.released.v1` carrying that amount and the caller-supplied reason (`invoice_paid` | `order_cancelled`); WHILE the order has no outstanding exposure — never held, or already released — THE SYSTEM SHALL append nothing, emit nothing and report the no-op; and THE SYSTEM SHALL never append a `release` that would drive `exposure(order)` below zero (**B5**), raising a domain error instead.

> *#9 note.* "Outstanding" is read by the definition the requirement itself gives: an order has outstanding exposure exactly when it has a `hold` entry and no `release` entry. For every ledger the system can write with positive amounts this is the same set as `exposure(order) > 0` (#7 `buyer-credit.ts:252-262`, #8 `BuyerCredit.Release`); it differs only for a zero-amount hold, which is gate point **G1** (`BC38`).

**BC12.** WHEN `consume` is invoked for an order holding an active hold, THE SYSTEM SHALL append exactly one `consume` entry of the same amount, SHALL emit **no** fact, and SHALL leave `availableCredit` numerically unchanged (`R40`); IF it is invoked for an order with no active hold, THEN THE SYSTEM SHALL raise a domain error and append nothing.

> *#9 note.* "Holding an active hold" is read structurally, as in `BC11`: a `hold` entry, and neither a `consume` nor a `release` entry. Same set as #7's and #8's `activeHold(order) > 0` for positive amounts; differs only for a zero-amount hold (**G1**).

**BC13.** THE SYSTEM SHALL consult the credit-decision port **only after** the aggregate has determined, from `BC5`, that the requested amount fits within the available credit, so that a bound adapter can turn an otherwise-approvable hold into a refusal but can **never** turn an over-limit hold into an approval — `R44`'s *"SHALL NOT allow the simulator to bypass `R37`"*, enforced by evaluation order rather than by discipline.

**BC14.** THE SYSTEM SHALL forbid the credit-decision port from returning the reason `over_limit` — `over_limit` is the aggregate's word and only the aggregate may say it — and SHALL build `credit.rejected.v1`, the outbox record and the RPC reply through **one** code path for every refusal, so that a genuine over-limit refusal and an adapter refusal differ in exactly one field (`reason`) and in nothing else (`R44`). WHEN the port refuses a hold the aggregate found fitting, THE SYSTEM SHALL record exactly one `credit.rejected.v1` on the aggregate it persists, carrying the port's reason, the requested amount and the unchanged available credit.

> *#9 note.* The port's reason type is a two-member `enum.Enum` (`AdapterRejectionReason`) with one total mapping to the fact's reason, exhaustive under `mypy --strict` through `assert_never` (#7's `Exclude<…>`, #8's separate enum; ledger L24).

**BC15.** WHERE no credit-check simulator is bound, THE SYSTEM SHALL bind an adapter that approves every request it is asked about, and THE SYSTEM SHALL make substituting feature 20's simulator a change to **composition wiring only** — no change to any file under `domain/`, `application/` or `presentation/`.

> *#9 note.* #8's text said *"DI registration only"*; the #9 equivalent is the composition root's binding (`composition.py`), plus the new adapter module and its settings class under `infrastructure/`.

**BC16.** THE SYSTEM SHALL write `credit.approved.v1`, `credit.rejected.v1` and `credit.released.v1` as outbox records in the **same transaction** as the ledger entries they describe (`R13`), and SHALL publish them to `otc.billing.facts.v1` **only** through Billing's own outbox relay, keyed by `correlationId` (`R14`, `R15`) — no responder, handler or aggregate publishes directly.

**BC17.** THE SYSTEM SHALL hold every write model's copy of the outbox-relay family byte-identical to the canonical copy after banner and namespace normalisation, SHALL keep the canonical copy free of any service name outside those normalised regions, and SHALL require the family from every service that owns a relational `outbox` table.

> *#9 note.* The #9 family is the nine modules `tests/architecture/test_outbox_copy_parity.py` already guards for Fulfillment (`application/ports/clock.py`, `infrastructure/clock.py`, `infrastructure/outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py`); "namespace normalisation" is its literal token map plus the formatter's reflow. The guard is extended to Billing and gains the census clause (`design.md` §10.2). #8's "no `using` outside a portable whitelist" clause has no Python counterpart worth claiming: the copies' imports are compared byte for byte after the token map.

**BC20.** WHEN the Billing responders first start against a compose stack whose `otc_orders.saga_commands` holds `parked` `credit.hold` rows, THE SYSTEM SHALL answer the sweeper's next re-issue of each row so that, **without operator action**, each such order gains exactly one `hold` ledger entry, exactly one `credit.approved.v1` in `otc_billing.outbox` stamped published, and advances in Orders through `credit_approved` → `confirmed` → `despatched`, parking at `invoice.issue` for which this feature registers no responder.

> *#9 note.* The developer stack holds two such rows (`progress/current.md`): `ORD-000008` and `ORD-000007`. `ORD-000007` was despatched in Fulfillment out of band during Phase 9 while Orders held it at `stock_reserved`, so its later `despatch.create` answers `created: false` with no fact (F8) and it stops at `confirmed`. That stop is the corrupted fixture's, not Billing's: Billing's part (one entry, one fact) is asserted for both orders, the "advances to `despatched`" clause for `ORD-000008` only (`design.md` §14).

**BC21.** THE SYSTEM SHALL handle `billing.credit.*` requests **concurrently** with a bounded degree, building a **distinct scope (unit of work) per request** and never one per responder, so that a request blocked on a `credits` row lock does not delay an unrelated request on another line.

**BC22.** WHEN the host shuts down while a `billing.credit.*` request is in flight, THE SYSTEM SHALL wait for **every** in-flight request to complete and SHALL NOT propagate the failure of any one of them out of the shutdown, so a single faulted reply cannot abort the host's shutdown sequence or mask the completion of its healthy siblings; the failure SHALL be logged.

**BC24.** WHEN a `credit_items` row's `credit_date` is read back into the domain, THE SYSTEM SHALL yield the same instant that was written, independently of the host's and the database session's time zone.

> *#9 note.* `timestamptz(3)` plus asyncpg's binary decode returns an aware UTC `datetime`; the instants written come from the clock port, already truncated to whole milliseconds (`wire_instant`), so `timestamptz(3)`'s rounding cannot move them. The guard reads through the production mapper (#8 review D1), under a non-UTC session `TimeZone`.

**BC25.** THE SYSTEM SHALL answer `billing.credit.release` by appending exactly one `release` ledger entry for the order's outstanding exposure with reason `order_cancelled` and emitting exactly one `credit.released.v1`, replying `released: true` with the released amount and the resulting available credit; WHILE the order has no outstanding exposure, THE SYSTEM SHALL append nothing, emit nothing, and reply `released: false` — success, not an error (`asyncapi.yaml` `requestCreditRelease`). `reason` is not a caller-supplied field on this subject.

**BC26.** WHEN a `billing.credit.hold` request would satisfy more than one of `BC7`'s `already_held`, `BC4`'s currency mismatch and `R39`'s over-limit, THE SYSTEM SHALL apply them in the fixed order **`already_held` → `currency_mismatch` → `over_limit`**.

**BC27.** THE SYSTEM SHALL map every transient store failure of a `billing.credit.*` command to an `RpcError` code the orchestrator treats as **retryable**, and SHALL never produce `CONFLICT` from this feature's subjects.

> *#9 note.* Orders' terminal set is `TERMINAL_RPC_ERROR_CODES` (`nats_saga_commands.py:65-75`, nine codes, #8's). Feature 22 will add `CONFLICT` for `billing.payment.register` (#7 `rpc-error-mapper.ts:138-145`, #8 `BillingErrorMapper.cs:145`), a Gateway-called subject the saga never sends; the clause is scoped to this feature's three subjects so feature 22 does not falsify it.

**BC28.** THE SYSTEM SHALL group a credit line's ledger entries by `orderReference` using a comparison that agrees with the database's own matching of that column, and SHALL derive the `retailerCode`, `companyCode`, `creditCode` and `currency` of every emitted fact and every reply from the **resolved credit line row**, never from the request's echoed strings.

> *#9 note.* PostgreSQL's deterministic collation is case-sensitive (measured: `'ORD-000001' = 'ord-000001'` is false), so exact `==` grouping agrees with the database without normalising — feature 17's G2 ruling, adopted for this service (`design.md` §16.2). Because the line is resolved by exact equality, the request's codes equal the row's whenever a line is found; the obligation is therefore guarded as a payload-corruption check per fact (#8 review D3), not by a differently-cased request.

**BC30.** WHEN any summation over a credit line's ledger — the per-order exposure, the committed exposure, the open exposure, or the available credit derived from them — would exceed the range of a 64-bit signed integer, THE SYSTEM SHALL **raise** a domain error carrying a stable code and SHALL NOT return a wrapped value; and THE SYSTEM SHALL make that behaviour reachable from a unit test that drives the summation function directly, with no aggregate state and no persisted ledger.

> *#9 note.* Python `int` never wraps, so "not wrapped" comes free; the raise does not: an exact out-of-range total would reach `Money` (which refuses it with a non-domain-specific code) or a `bigint` column. `summarise` checks the range explicitly and raises `CreditLedgerOverflowError`; the SQL scalar's `CAST(… AS bigint)` raises SQLSTATE `22003` on the same condition, which is mapped to the same error (`BC37`).

**BC32.** THE SYSTEM SHALL make every integration test that decodes an RPC reply assert that reply's own discriminating field **before** it touches any collection, so a wrong-shaped or error-shaped reply fails on a named assertion.

> *#9 note.* `from_wire_json(<reply model>, body)` raises on an `RpcError` body (required fields missing), so the silent all-defaults case #8 had cannot occur; the rule still holds for tests that read `json.loads(body)` directly. The population is enumerated from every reply decode in Billing's tests (#8 id 55's lesson: root the search at the decode, not at a member name).

### 2.2 Not claimed

| #8 id | Why not |
|---|---|
| `BC18` | #8's reason: #7's instrument compared migration **text**; #9's reliability-table parity reads the live catalogs of all four databases (`services/billing/src/otc_billing/infrastructure/persistence/models.py:11-12`, feature 11), so a comment cannot enter the comparison |
| `BC19` | #8's reason: no seed re-run is part of this feature's procedure, so no verifier runs against a long-lived database here |
| `BC23` | Its premise — hand-retyped key lists in payload tests — does not exist in #9: every request and reply is a generated model, drift-tested against `asyncapi.yaml` (`packages/contracts/tests/test_generation_drift.py`; `specs/fulfillment_stock/design.md` §4 row "`StockRpcPayloadTests`") |
| `BC29` | Its mechanism is a C# `required` member and a compile error, which Python cannot render; the obligation it carried is `BC34`, realised at boot |
| `BC31` | An Orders adapter property (a fresh header collection per saga command), already realised by feature 16 (`nats_saga_commands.py:143`, L19 of its design); this feature changes nothing in Orders' adapter |

### 2.3 New in #9 (`BC33` – `BC39`)

**BC33.** IF a `billing.credit.hold` or `billing.credit.release` request carries an `orderReference` longer than 20 characters, or a `billing.credit.hold` request carries a negative `amount.amount`, THEN THE SYSTEM SHALL reply `RpcError` `VALIDATION_FAILED` naming the field, SHALL append no ledger entry and SHALL emit no fact.

> *Why new.* The wire pattern `^ORD-[0-9]{6,}$` has no maximum while `credit_items.order_reference` is `varchar(20)`; #7 (MySQL strict mode → `INTERNAL_ERROR`, retried) and #8 (`nvarchar(20)` overflow → `UNAVAILABLE`, retried) both answered it as transient, which a saga retries forever. The shared `Money` schema admits a negative amount, which would *increase* available credit; #8 refused it (`CreditRequestValidator.cs:110-115`), #7 did not (its DTO is `@IsInt()` only, `credit.dto.ts:16`), so #8's refusal is adopted. Feature 17's `FS28` is the same edge check for Fulfillment.

**BC34.** THE SYSTEM SHALL give each service's outbox-relay Kafka producer its own client id; IF a service's client-id variable (`KAFKA_CLIENT_ID` for Orders, `FULFILLMENT_KAFKA_CLIENT_ID`, `BILLING_KAFKA_CLIENT_ID`) is set to an empty or blank value or to anything outside `^[A-Za-z0-9._-]+$`, THEN that service SHALL fail to start, naming the variable; and the three services' default client ids SHALL be pairwise distinct.

> *Why new.* `feature_list.json` id 19's fourth acceptance item. aiokafka substitutes a default only for `None`; an empty string is sent as the client id verbatim (measured, `design.md` header), and today both Orders and Fulfillment accept `""` (measured). #8's `BC29` made omission a compile error, but its review found the empty-string variable still produced an empty id at runtime (#8 `progress/review_billing_credit.md` §2 A1). Applied to all three services in this feature (a finding is fixed in the phase that detects it).

**BC35.** THE SYSTEM SHALL run every Billing write transaction at `READ COMMITTED`, set explicitly on the transaction before its first statement, and SHALL issue every `credit_items` read of a `billing.credit.hold` or `billing.credit.release` transaction only after the line's `credits` row lock has been granted.

> *Why new.* #8 id 54's warning, measured for this service: with the line row locked first and the sum read second, a competing hold's committed entry is seen at `READ COMMITTED` and **silently missed** at `REPEATABLE READ` (no serialization error, because the `credits` row is locked but never updated); reading the sum before the lock misses it at either level (`design.md` header, runs A, B, B2, C). #7 got currency from `FOR UPDATE` under InnoDB; #8 from `UPDLOCK` hints under RCSI.

**BC36.** THE SYSTEM SHALL take the id of every ledger entry it appends and the `eventId` of every fact it raises from the id port passed into the domain operation, at every such site, so that a test can supply each identifier and assert it by equality.

> *Why new.* #8 id 49 and its follow-on (one of four sites guarded) recurred in #9 feature 17 round 1 (`specs/fulfillment_stock/design.md` L15). Billing has six sites (hold entry, approved fact, rejected fact, release entry, released fact, consume entry).

**BC37.** THE SYSTEM SHALL compute a credit line's committed exposure as an exact integer: the stored sum SHALL reach the domain as `int` (never `Decimal`), an out-of-range sum SHALL raise `CreditLedgerOverflowError` (`BC30`), and IF any `credit_items` row of the line carries a `type` outside `hold` / `consume` / `release`, THEN the hold or release SHALL be refused with a domain error rather than computed with that row counted as zero.

> *Why new.* PostgreSQL's `SUM(bigint)` is `numeric`, which asyncpg decodes as `Decimal` even through SQLAlchemy's `func.sum` over a `BigInteger` column (measured, `design.md` header); #7 converted with `Number(...)` (`buyer-credit.repository.ts:53, 65`), #8 got `long` from `SqlQueryRaw<long>` over SQL Server's `bigint` sum (`EfCoreBuyerCreditRepository.cs:53-54`). And both #7's and #8's scalar summed an unknown `type` as `ELSE 0` (`buyer-credit.repository.ts:53`; `EfCoreBuyerCreditRepository.cs:54`), silently, while their row parse was loud (#8 ledger L12) — the gap is closed here.

**BC38.** *(Pending gate point **G1**; text as recommended.)* WHEN a `billing.credit.hold` command carries an amount of zero for an order with no `hold` entry on the line, THE SYSTEM SHALL approve it as `R38` requires — one `hold` entry of zero and one `credit.approved.v1` with `heldAmount: 0` — and `consume` and `release` SHALL treat that order by `BC11`'s and `BC12`'s structural reading (a zero `consume` entry at invoice issue; a zero `release` entry and one `credit.released.v1` when it is released).

> *Why new.* `domain-model.md` **O3** allows `totalAmount = 0` and #9's Orders accepts it (`services/orders/src/otc_orders/domain/order.py:244` refuses only a negative total), so a zero hold is reachable. #7 approves it but cannot consume it (`consumeHold` throws `NoActiveHoldError` on `activeHold <= 0`, `buyer-credit.ts:305-309`: the order stops at `despatched`); #8 refuses it (`CreditLedgerEntry.Create` throws on `<= 0`, `CreditLedgerEntry.cs:37-44`, mapped `DOMAIN_ERROR`, terminal: the order stops at `stock_reserved`). The two disagree, and neither completes the cycle.

**BC39.** THE SYSTEM SHALL render every amount named in the human-readable `message` of a Billing domain or application error with the shared ISO 4217 money-text formatter (`otc_shared_kernel.money_text.format_money`, SA-5), never as raw minor units; machine-readable fields (`code`, `details`) SHALL stay integer minor units.

> *Why new.* #8 id 102 (problem-document money in raw minor units), fixed in #7 and #8 in their Phase 16 (#7 `buyer-credit.ts:80-90`). An inherited finding is an acceptance criterion here, at the first Billing error that names an amount.

## 3. Traceability

### 3.1 Shared rows flipped by this feature

`specs/shared/test-matrix.md` §5, column 5 only: `R37`, `R38`, `R39`, `R40`, `R41`, each to `DONE — <path> › <test>` once green. `R42` – `R44` stay `TODO` (feature 20). Matrix path mapping: `design.md` §13.4.

### 3.2 Local rows

| Id | Level | Test (`services/billing/tests/…` unless stated) | Status |
|---|---|---|---|
| BC1 | unit + integration | `unit/test_credit_responder.py::test_bc1_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`; `integration/test_credit_hold.py::test_bc1_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_credit_approved_fact` | DONE |
| BC2 | integration | `integration/test_credit_wire.py::test_bc2_answers_a_bare_json_request_with_a_bare_json_reply_on_all_three_subjects`, `::test_bc2_answers_a_bare_json_rpc_error_on_a_validation_failure` | DONE |
| BC3 | integration | `integration/test_credit_hold.py::test_bc3_replies_not_found_naming_the_pair_writing_no_ledger_entry_and_emitting_no_fact`; `integration/test_credit_release.py::test_bc3_release_replies_not_found_for_an_unknown_pair` | DONE |
| BC4 | integration | `integration/test_credit_hold.py::test_bc4_replies_validation_failed_writing_no_ledger_entry_and_emitting_no_fact_when_the_currency_differs` | DONE |
| BC5 | domain unit | `unit/domain/test_buyer_credit.py::test_bc5_derives_available_credit_as_the_limit_minus_holds_plus_releases_so_a_consume_entry_moves_it_by_nothing` | DONE |
| BC6 | domain unit + integration | `unit/domain/test_credit_exposure.py::test_bc6_active_holds_plus_open_exposure_equal_the_limit_minus_available_credit_on_every_ledger_shape`; `integration/test_credit_list.py::test_bc6_every_listed_line_reconciles_to_its_credit_limit` | DONE |
| BC7 | unit + integration | `unit/test_credit_hold_service.py::test_bc7_already_held_on_a_released_hold_calls_no_port_and_writes_nothing`; `integration/test_credit_hold.py::test_bc7_a_reissued_hold_answers_already_held_with_the_recorded_amount_and_the_current_credit_and_writes_nothing` | DONE |
| BC8 | integration | `integration/test_credit_hold.py::test_bc8_a_previously_rejected_hold_is_re_evaluated_and_writes_no_ledger_entry_either_time` | DONE |
| BC9 | integration | `integration/test_credit_hold_race.py::test_bc9_two_concurrent_holds_against_one_nearly_exhausted_line_yield_one_approval_and_one_rejection` | DONE |
| BC10 | domain unit + integration | `unit/domain/test_credit_hold.py::test_bc10_available_credit_after_is_recomputed_with_the_appended_hold`; `integration/test_credit_repository.py::test_bc10_a_forced_rollback_leaves_neither_the_hold_row_nor_the_outbox_row` | DONE |
| BC11 | domain unit | `unit/domain/test_credit_ledger.py::test_bc11_releases_the_outstanding_exposure_once_and_reports_a_no_op_on_a_second_release` | DONE |
| BC12 | domain unit | `unit/domain/test_credit_ledger.py::test_bc12_consume_leaves_available_credit_unchanged_emits_no_fact_and_refuses_an_order_with_no_active_hold` | DONE |
| BC13 | unit | `unit/test_credit_hold_service.py::test_bc13_the_port_is_consulted_only_for_a_fitting_hold_and_never_for_an_over_limit_one` | DONE |
| BC14 | domain unit + unit | `unit/domain/test_credit_hold.py::test_bc14_an_adapter_refusal_differs_from_an_over_limit_refusal_only_in_reason`; `unit/test_credit_decision_port.py::test_bc14_the_adapter_reason_type_has_exactly_the_two_simulator_members_and_a_total_mapping`; `unit/test_credit_hold_service.py::test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate`; `integration/test_credit_hold.py::test_bc14_a_refusing_port_puts_one_credit_rejected_fact_with_its_reason_in_the_outbox` | DONE |
| BC15 | unit | `unit/test_always_approve.py::test_bc15_approves_every_request` | DONE |
| BC16 | integration | `integration/test_billing_outbox_relay.py::test_bc16_publishes_the_hold_facts_to_the_billing_topic_keyed_by_correlation_id_and_stamps_published_at_after_the_ack` | DONE |
| BC17 | architecture | `tests/architecture/test_outbox_copy_parity.py` (every case, parametrised over Fulfillment and Billing) and `::test_every_service_owning_an_outbox_table_holds_the_family` | DONE |
| BC20 | live verification | `progress/impl_billing_credit.md` § Live boot | DONE |
| BC21 | unit + integration | `unit/test_credit_responder.py::test_bc21_builds_a_distinct_scope_per_request`; `integration/test_credit_responder_concurrency.py::test_bc21_answers_a_second_request_while_an_earlier_one_waits_on_a_credit_row_lock` | DONE |
| BC22 | unit | `unit/test_credit_responder.py::test_bc22_shutdown_waits_for_every_in_flight_request_when_one_faults_and_one_succeeds` | DONE |
| BC24 | integration | `integration/test_credit_repository.py::test_bc24_a_ledger_entry_instant_reads_back_unchanged_through_the_mapper_under_a_non_utc_session_time_zone` | DONE |
| BC25 | integration | `integration/test_credit_release.py::test_bc25_one_release_entry_and_one_released_fact_then_released_false_writing_nothing_on_a_repeat` | DONE |
| BC26 | domain unit | `unit/domain/test_credit_hold.py::test_bc26_already_held_ranks_above_currency_mismatch_and_currency_mismatch_above_over_limit` | DONE |
| BC27 | architecture | `tests/architecture/test_billing_rpc_error_retryability.py::test_bc27_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries`, `::test_bc27_no_input_produces_conflict` | DONE |
| BC28 | unit + integration | `unit/domain/test_credit_exposure.py::test_bc28_groups_by_exact_order_reference`; `integration/test_credit_hold.py`, `test_credit_release.py`: the approved, rejected and released facts' five identity fields asserted against the seeded row | DONE |
| BC30 | domain unit + integration | `unit/domain/test_credit_exposure.py::test_bc30_raises_ledger_overflow_when_one_orders_hold_total_exceeds_int64`, `::test_bc30_raises_ledger_overflow_when_the_committed_exposure_across_orders_exceeds_int64`; `integration/test_credit_repository.py::test_bc30_an_out_of_range_line_sum_is_refused_as_ledger_overflow` | DONE |
| BC32 | integration | the enumeration of `tasks.md` H8 (every reply decode in Billing's tests) | DONE |
| BC33 | unit | `unit/test_credit_requests.py::test_bc33_an_order_reference_over_twenty_characters_is_validation_failed`, `::test_bc33_a_negative_hold_amount_is_validation_failed` | DONE |
| BC34 | unit + architecture | `unit/test_billing_settings_env.py::test_bc34_an_empty_or_blank_client_id_fails_naming_the_variable` (and its Orders and Fulfillment siblings); `tests/architecture/test_kafka_client_ids.py::test_bc34_the_three_default_client_ids_are_non_empty_and_pairwise_distinct` | DONE |
| BC35 | integration | `integration/test_credit_hold_race.py` (the race, armed by the isolation pin and by the read order); `integration/test_credit_repository.py::test_bc35_the_transaction_runs_at_read_committed` | DONE |
| BC36 | domain unit + unit | `unit/domain/test_credit_ids.py::test_bc36_every_entry_id_and_event_id_is_the_one_the_id_source_supplied`; `unit/test_credit_hold_service.py::test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`, `unit/test_credit_release_service.py::test_bc36_the_release_hands_the_scope_id_port_to_the_domain` | DONE |
| BC37 | integration | `integration/test_credit_repository.py::test_bc37_the_committed_exposure_reaches_the_domain_as_an_exact_int`, `::test_bc37_an_unknown_type_token_on_the_line_refuses_the_hold` | DONE |
| BC38 | domain unit + integration | `unit/domain/test_credit_ledger.py::test_bc38_a_zero_hold_is_approved_consumed_and_released_with_one_fact_each_where_owed`; `integration/test_credit_hold.py::test_bc38_a_zero_amount_hold_is_approved` | DONE (G1 decided as recommended) |
| BC39 | unit | `unit/test_credit_rpc_errors.py::test_bc39_every_error_message_naming_an_amount_renders_it_with_the_money_text_formatter` | DONE |

## 4. Spec amendment

**None proposed.** `BC38` resolves the zero-total case within `R38`, `R40` and `R41`'s existing text (each is satisfied literally by the structural reading), so no shared wording is wrong; if the gate rules G1 against the recommendation, `design.md` §16.1 states what changes and that it still needs no `SA-6`.
