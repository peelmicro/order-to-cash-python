# `billing_credit` (id 19, phase 10) — spec pass (assessment #9, Python)

**Author:** `spec_author` · **Date:** 2026-10-08 · **Brief:** `progress/brief_spec_billing_credit.md` (premise check `progress/premise_billing_credit_spec.md`)
**Deliverables:** `specs/billing_credit/{requirements,design,tasks}.md` (207 / 600 / 126 lines). `feature_list.json` not edited; the leader sets 19 to `spec_ready`. `specs/shared/` not edited (`git status --porcelain specs/shared` empty). **No `SA-6` proposed.**

**Normative range:** `R37` – `R41` (flipped by this feature; `R40` delivered uncalled for feature 21, `R41`'s `invoice_paid` half called by feature 22). `R42` – `R44` stay `TODO` for feature 20; this feature owns the port and `BC13` – `BC15`.
**Local ids:** #8's `BC1` – `BC17`, `BC20` – `BC22`, `BC24` – `BC28`, `BC30`, `BC32` reused (numbering unchanged, #9 notes where the mechanism differs); `BC18`, `BC19`, `BC23`, `BC29`, `BC31` not claimed, one reason each (`requirements.md` §2.2); **`BC33` – `BC39` new in #9**, `BC38` pending G1.
**Ported-idiom ledger:** `design.md` §3 — **30 enumerated boundaries, 37 rows**, the enumeration written before the rows.
**#8 backlog, Billing area:** `design.md` §17.1 — **37 entries, one row each** (17 Billing-area: 15 avoided with a named instrument, 1 assigned to feature 22 (id 57), 1 not applicable in Python (id 83); 20 not Billing-area, each with its owner). Population = #8 entries with `phase == 10` ∪ entries opened during #8's Phase 10 (history 1215 – 1410: 55, 56, 57) ∪ a full-text search of every entry ≥ 39 for `billing|credit|invoice|remittance|payment|phase 10` (31 hits, command below) ∪ a title read of 58 – 111 (added 87). It reproduces the brief's keyword list plus 87.
**Tasks:** 67, of which **51 carry `[ARM]`**; the 16 unflagged ones either make no countable claim or point at the task that arms theirs.

## Evidence produced by command in this session

| # | Command (abridged) | Result |
|---|---|---|
| M1 | `docker run --rm postgres:18.6` + `psql`: line locked `FOR UPDATE`, competitor inserts a 60 `hold` and commits after 3 s; second transaction locks then `SUM` at `READ COMMITTED` (A), `REPEATABLE READ` (B, B2 lock first statement), `SUM` before lock at `READ COMMITTED` (C) | A waited 2 099 ms, saw **60**; B / B2 waited 2 094 / 2 092 ms, saw **0** with **no error**; C waited 2 105 ms, saw **0** |
| M2 | Same container: an `INSERT INTO credit_items` taking no line lock while the line is held `FOR UPDATE` (D) / `FOR NO KEY UPDATE` (E) | D blocked 2 087 ms (FK `KEY SHARE` conflicts); E 109 ms |
| M3 | `SELECT SUM(amount) … FOR UPDATE`; `SELECT 'ORD-000001' = 'ord-000001'` | `ERROR: FOR UPDATE is not allowed with aggregate functions`; `f` |
| M4 | SQLAlchemy + asyncpg against `postgres:18.6`: `select(func.sum(<bigint expr>))`, `func.coalesce(func.sum(…), 0)`, `cast(…, BigInteger)`; `pg_typeof(SUM(bigint))` | `Decimal('50')`, `Decimal('50')`, `50` (`int`); `numeric` |
| M5 | `KAFKA_CLIENT_ID= FULFILLMENT_KAFKA_CLIENT_ID= uv run --no-sync python -I -c "…KafkaSettings().client_id…"` (Orders, Fulfillment) | `''` and `''`; unset → `'otc-orders'`, `'otc-fulfillment'` |
| M6 | `uv run --no-sync python -I -c "…AIOKafkaProducer(bootstrap_servers=…, client_id=cid).client._client_id"` for `''` and `None` (aiokafka 0.14.0) | `''` → `''`; `None` → `'aiokafka-producer-2'` (`producer.py:284-287`) |
| M7 | `grep -n "is_negative" services/orders/src/otc_orders/domain/order.py`; `grep -n "lineDiscount\|orderDiscount" specs/shared/asyncapi.yaml` | Orders refuses only a **negative** total (`:244, 340, 517, 530, 557`); `orders.create` accepts both discounts (`:3147-3152`) |
| M8 | `python3 -c "…json over ../order-to-cash-dotnet/feature_list.json, id ≥ 39, full text ~ billing|credit|invoice|remittance|payment|phase 10…"` | 31 hits: `31, 41, 50, 52, 55, 56, 57, 62, 63, 64, 66, 67, 68, 70, 71, 72, 74, 76, 77, 78, 79, 83, 84, 85, 86, 91, 92, 100, 102, 110, 111` |
| M9 | `grep -rln '__tablename__ = "outbox"' services/*/src` | three: billing, fulfillment, orders |

Every probe container was removed (`docker ps` showed none afterwards); the developer stack was not touched.

## Decided — #7 and #8 agree and Python forces no difference (adopted, cited)

| Decision | #7 | #8 | Where |
|---|---|---|---|
| Two-term exposure identity, not `domain-model.md` §5.1's literal formula | gate row 2, `credit-exposure.ts` | gate row 3 | `BC5`, `BC6`; design §5.3 |
| `already_held` on any recorded `hold` entry, whatever happened since | gate row 4, `buyer-credit.ts:150-155` | gate row 4, `BC7` | design §5.1 |
| A rejected hold is re-evaluated; no fourth entry type | `BC8` | gate row 5 | `BC8` |
| Port consulted only on `Fits`; it cannot say `over_limit`; one refusal path | gate row 6 | gate rows 6 – 7 | `BC13`, `BC14`; design §7.4 |
| Precedence `already_held` → `currency_mismatch` → `over_limit` | review N1 (real, unpinned) | gate row 12, `BC26` | `BC26` |
| `NOT_FOUND` for no line, `VALIDATION_FAILED` for currency, `PRECONDITION_FAILED` for underflow / no active hold, `DOMAIN_ERROR` otherwise | `rpc-error-mapper.ts:43-158` | `BillingErrorMapper.cs:37-157` | design §8.5 |
| `billing.credit.release` responder built now (the subject exists in the inherited contract) | added later (`credit-release.handler.ts`) | gate row 13, `BC25` | `BC25` |
| Billing consumes no fact; no idempotent-consumer copy | `billing-consumes-no-facts.spec.ts` | gate row 15, §9 | design §10.4 |
| `credit_items.updated_at` written equal to `created_at`, never updated | `buyer-credit.repository.ts:73` | `BuyerCreditRowMapper.cs:51-52` | design §1 |
| No `CR-` allocator: credit lines are seeded master data | seed `credits.data.ts` | seed `Credits` | design §1 |
| A release (`order_cancelled`) of a consumed hold releases its outstanding exposure; nothing about despatch is decided under Billing's lock (SA-4 is Fulfillment's lock) | `buyer-credit.ts:247-295` | `BuyerCredit.Release`; #8 id 79 is #7-Orders only | design §6.3 |
| One line row lock, no deadlock cycle; rule 6 met literally | `BC9` | gate rows 9 – 10 | `BC9`; design §6.2 |
| Business rejection is a reply, never an `RpcError`; reply returned only after commit | handler | §5.3 | design §7.3 |

**Decided by #9's own approved precedent** (feature 17's gate, 2026-10-08): exact, case-sensitive code matching (G2 → `BC28`'s note, L16 – L17); order reference routed as `str`, never kernel-parsed (L23 / FS28 → design §5.2); the responder, transactions, scope and settings shapes; the `BC33` edge check is FS28's twin.

**Forced by the engine and settled by measurement, not by the gate:** `READ COMMITTED` pinned (`BC35`; M1 — `REPEATABLE READ` is silently stale here, unlike feature 17's 40001); the committed-exposure scalar `CAST … AS bigint` with its unknown-token count and `22003` mapping (`BC37`, `BC30`; M3, M4 — both predecessors summed an unknown token as zero, which is closed here); plain `FOR UPDATE`, not `FOR NO KEY UPDATE` (M2); no in-process deadlock re-run (one row per transaction; neither predecessor re-ran in Billing); `decide` synchronous (narrower than #7's "sync or async" and #8's `ValueTask`, making "no I/O under the lock" structural).

**Answers to the brief's questions.**

- *Kafka client id* (M5, M6): empty today in both services, and aiokafka sends `''` verbatim. Billing's field and **Orders' and Fulfillment's** gain `pattern=r"^[A-Za-z0-9._-]+$"` in this feature (`BC34`, tasks G2 – G3), plus a cross-service distinctness test. A finding fixed in the phase that detects it.
- *Does Billing consume Kafka?* No, in #7, #8 or #9; feature 21's *"issued on order.despatched"* is the orchestrator's `invoice.issue` command. **No idempotent-consumer parity case goes live in 19 or 21** (case 3's literal `{"otc_orders"}` stays true; feature 22 dedups by `paymentReference`); they go live at feature 23.
- *Retryability sibling:* yes, `tests/architecture/test_billing_rpc_error_retryability.py`, with a `__subclasses__` walk so a new Billing error cannot skip the population.
- *Outbox parity:* the guard is extended to a `COPY_SERVICES` literal plus a glob census of services owning an `outbox` table (M9); existing sentinels re-pointed at Billing; eleven arms.
- *Live stack:* both parked rows (`ORD-000007`, `ORD-000008`) will be re-issued by the sweeper once Billing answers; `ORD-000008` is the park-and-resume proof to `despatched`; `ORD-000007` is expected to stop at `confirmed` (its Phase 9 out-of-band despatch), recorded, not a failure. The `credit.release` probe uses a throwaway order.

## Open for the gate — one point

**G1 — a zero-amount `credit.hold`** (`BC38`; `design.md` §16.1). *#7 and #8 disagree, and neither completes the cycle:* #7 approves a zero hold (`buyer-credit.ts:172-209`) then cannot consume it (`:305-309`, `activeHold <= 0` → `NoActiveHoldError`), so the order stops at `despatched`; #8 refuses it (`CreditLedgerEntry.cs:37-44`, `amount <= 0`; `DOMAIN_ERROR`, terminal), so the order stops at `stock_reserved`. *Reachable in #9* (M7): **O3** allows `totalAmount = 0`, Orders refuses only a negative total, and `orders.create` takes `lineDiscount` / `orderDiscount`.

**Recommendation: approve it, as `R38`'s text requires (`0 ≤ availableCredit`), and read `release` / `consume` by `BC11`'s own definition of outstanding (a `hold` entry and no `release` entry) and its `BC12` counterpart**, so a zero-total order is consumed at invoice issue, released with one `credit.released.v1` at payment, and the saga completes. Positive-amount behaviour is unchanged (the structural and amount predicates select the same orders on every positive ledger, asserted in task B9). Cost: the entry rule becomes "refuse negative", two predicates, one domain test and one integration case. No `SA-6`: `R38`, `R40` and `R41` are each satisfied literally.

*If overruled (adopt #8):* the entry rule refuses non-positive, a zero hold answers `DOMAIN_ERROR` (terminal), `BC38` is withdrawn, tasks B1, B9 and H5 drop their zero cases, and the divergence from `R38`'s literal text is recorded as accepted with a re-open trigger (any order placed with a zero total).

## Hand-over recorded for later features (`design.md` §15)

1. **Feature 20** — `infrastructure/credit/simulator.py`, a settings class, the composition default; nothing in `domain/`, `application/`, `presentation/`. `decide` is synchronous; the `% 100 == 99` fixture guard already exists in 19's harness.
2. **Feature 21** — `consume` ships uncalled; `CreditTransaction` gains `invoices` / `invoice_numbers`; the line row is locked before any invoice row; a zero-total order (if G1 as recommended) must consume.
3. **Feature 22** — `release` takes the caller's `CreditContext` (#8 id 57's causal edge); `release`'s `None` must not be discarded (#8 feature 22's N3); both facts through the per-row writer in emission order.
4. **Feature 41** — `saga.md` §2's missing `credit.release` row (an observation inherited from #8, `requirements.md` §1.2); the responder exists.

## Gate ruling (maintainer, 2026-10-08)

**Approved.** G1 adopted as recommended: a zero-amount `credit.hold` is approved (`R38`), and `release` / `consume` read outstanding by `BC11` / `BC12` (a `hold` entry and no `release` entry), so a zero-total order completes. `BC38` stands. The leader checked the evidence before the gate: `specs/shared/requirements.md:312` (R38), `domain-model.md` O3 (`totalAmount ≥ 0`) and B6 (invoice `totalAmount ≥ 0`), no B-invariant requiring a positive ledger amount (B1 – B5), #7 `buyer-credit.ts:305-309`, #8 `CreditLedgerEntry.cs:37-44`.
