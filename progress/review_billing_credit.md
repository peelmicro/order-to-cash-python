# Review — feature 19 `billing_credit` (phase 10, `sdd: true`, full group), round 1

**Verdict: REJECTED** — 3 blocking defects, **all guards** (test-only fixes; no production line needs to change), plus one `specs/shared/` gap that must be **routed** by the leader. Every production path behaved correctly under every probe; the live record (K1 – K5) is consistent with the code.

Reviewer: Opus, 2026-10-09, ≈07:28 → ≈08:10 local (≈42 min). Brief `progress/brief_review_billing_credit.md`, premise check `progress/premise_review_billing_credit.md` (the FALSE line count noted; `git diff --numstat` reads `180 58`). Developer stack never started (`docker ps`: `otcpy-n8n` only, before and after). All arm tooling, backups (with sha256) and verbatim logs: `.arm/review19/` (`arm.py`, `arm_multi.py`, `bak/<arm>/`, `logs/<arm>.log`). Every armed file restored by `cp`, confirmed by `cmp` and sha256 (a final sweep over every backup: 0 mismatches), `__pycache__` cleared after each restore, `.mypy_cache` removed after the mypy arms.

## 0. What I ran (and what I did not)

- **`./quality.sh` in full** (the claim under test is about the full suite): **exit 0, 349 s** (`.arm/review19/quality.log`), **3111 passed in 326.63 s**, overall coverage 97 %, domain coverage 99 %, `ruff format` 673 files clean, `ruff check` clean, `mypy --strict` 551 files clean, import-linter **11 kept, 0 broken** (incl. `otc_billing: presentation > infrastructure > application > domain` and the independence contract), web 1 test. 349 s against the maintainer's ~360 s reference and A2's 331 s.
- `./init.sh` exit 0 (section 5d: shared spec byte-identical to #8 and #7, 6 files; I re-ran `cmp` per file myself: all `same`).
- **58 arms of my own** (60 runs; `G6-f-g-plus-f-j` and `-v2` were invalid constructions of mine — `@dataclass(slots=True)` re-creates the class and re-fires `__init_subclass__` — and are discarded; `-v3` is the valid one), plus two scratch-tree probes of the parity instrument that touch no repository file.
- I did **not** re-run the implementer's 141 arms wholesale; I re-ran a random sample (§3.1) and every arm the brief named.

## 1. CHECKPOINTS.md

**C1** — [x] harness files exist · [x] `progress/current.md`, `history.md` · [x] seven agents · [x] every agent declares its model (`model:` or the explicit "inherits the session model" description: leader, spec_author, reviewer) · [x] `./init.sh` exit 0.

**C2** — [x] at most one `in_progress` (after this verdict: 19 only) · [x] statuses valid (`init.sh`) · [x] `done` features have tests · [x] `progress/current.md` is the active session's · [x] no `blocked` feature.

**C3** — [x] no framework import in `domain` / `shared_kernel` (`lint-imports`, run, not eyed) · [x] no cross-service DB access; independence contract kept; the only cross-service imports are in `tests/architecture/` (outside the contract by design) · [x] no new shared runtime code (`packages/` untouched) · [x] no `domain` imports `otc_cqrs` · [x] `shared_kernel` / `cqrs` `dependencies = []` unchanged · [x] no `float` / `Decimal` / `/` in Billing's domain (money guard green; grep of `services/billing/src/otc_billing/domain/*.py`: one hit, a docstring) · [x] interactions classified: three NATS RPC subjects (`billing.credit.hold/.release/.list`), three Kafka facts through the outbox; Billing consumes no fact (`test_kafka_client_confinement.py`) · [x] no stray debug logging or context-free TODO in `services/billing/src`.

**C4** — [x] `./quality.sh` passes · [x] domain tests pure (`test_domain_tests_are_pure.py`, import-linter) · [x] integration tests on testcontainers, green with the stack down · [x] coverage 99 % domain / 97 % overall · [x] no Jest/Karma/Jasmine.

**C5** — [x] no suspicious untracked files · [ ] history entry with effort — **not owed on a rejection** (written at approval) · [x] `feature_list.json` reflects the state (19 → `in_progress`, this one line) · [ ] human told what was done / how to test — the leader's, at close · [x] no commit.

**C6** — [x] `specs/billing_credit/` has all three files · [x] EARS with ids · [x] 67/67 tasks ticked — **but see D1–D3: three ticks (C4/H5 fixture rule, F6 row 11, F6's "any other difference") are not true** · [ ] every `R<n>` covered by a test that discriminates it — **R41's named test does not discriminate its "returns to its pre-hold value" clause (D1)** · [ ] spec commit precedes implementation commit — not yet committed (the human's).

**C7** — [x] `specs/shared/` byte-identical to #8 and #7 (except the test-matrix Status column; diff read: R37 – R41 cells and the two count rows only) · [x] no silent fork (no SA in this feature) · [x] R-ids are #7's and the realisation satisfies them (modulo D1 for R41's guard) · n/a n8n · n/a API script · [x] inherited #8 findings accounted for (impl §9; checked in §6 below) · [ ] effort record — at approval · n/a README benchmark (wrap-up).

## 2. Traceability (`R<n>` → test), verified

A script parsed every `path::test` / `› test` cell of `requirements.md` §3.2 (51 named tests) and the matrix rows R37 – R41 (21 named tests) and checked each `def test_…(` exists in its file: **0 missing**. Each was then read for what it asserts:

| Req | Test(s) verified | Discriminates? |
|---|---|---|
| R37 | `unit/domain/test_buyer_credit.py::test_r37_…`, `test_rehydrate_refuses_…`; `integration/test_credit_hold_race.py::test_bc9_…` (I1, three arms re-run, §3.2); `test_credit_repository.py::test_an_earlier_ledger_row_is_byte_equal_after_a_later_release`; `test_write_path_population.py` | yes |
| R38 | `unit/domain/test_credit_hold.py::test_r38_…`, `test_bc10_…`; `integration/test_credit_hold.py::test_r38_…` (every payload field vs seeded, distinct values; `availableCreditAfter = LIMIT − 4210`) | yes |
| R39 | `test_credit_hold.py::test_r39_…` (domain + integration, planted 3 000 so `availableCredit` 7 000 ≠ limit 10 000), `test_bc14_…` ×3 | yes (U7 killed) |
| R40 | `unit/domain/test_credit_ledger.py::test_r40_…`, `test_bc12_…` (domain only; caller is feature 21 — deviation 13 accepted) | yes |
| R41 | `unit/domain/test_credit_ledger.py::test_r41_…`, `test_bc11_…`; `integration/test_credit_release.py::test_bc25_…` | **no — D1**: every fixture releases the line's only exposure, so "pre-hold value" = credit limit; a release that reports the limit passes all of them |

`BC1` – `BC39`: all rows mapped; the ones I armed are in §3.

## 3. Arms

### 3.1 The random sample of `[ARM]` tasks (#8 D1's lesson)

Picked with `random.Random(19).sample(ids, 6)` over the 51 ids that `grep -oE '^- \[.\] [A-Z][0-9a-z]* \*\*\[ARM\]\*\*'` yields → **B5, C2, D4, G5, G6, I2**. Each run with **exactly** the mutation `tasks.md` prescribes; each failure matches impl §6:

| Arm | Result (verbatim) |
|---|---|
| B5 delete range check → test 1 / test 2 | both KILLED: `Failed: BC30: summarise returned a total outside int64 instead of raising: committed_exposure=9223372036854775810` |
| B5 check only per order → test 2 / control test 1 | test 2 KILLED (same message); test 1 green — exactly the prescription ("only the second fails") |
| C2 add `OVER_LIMIT` (pytest / mypy) | KILLED `AssertionError: BC14: the adapter's reason type has members ['over_limit', …]`; mypy `reasons.py:37: error: Argument 1 to "assert_never" has incompatible type "Literal[AdapterRejectionReason.OVER_LIMIT]"` |
| C2 `async def decide` (mypy) | `composition.py:295: error: Argument "credit_decision" to "BillingScope" has incompatible type …; expected "CreditDecisionPort"` |
| D4 delete the pin | KILLED `AssertionError: BC35: the transaction ran at 'repeatable read', not read committed` |
| G5 remove `register_command(ReleaseCreditCommand, …)` | KILLED `DispatcherValidationError: No command handler is registered for ReleaseCreditCommand. Exactly one is required.` |
| G6 F-g + F-j as one fixture (`__init_subclass__` self-registration drained by a helper loop) | KILLED `WIRE: 2 registrations share one statement (composition.py:111): ['…HoldCreditCommand', '…ReleaseCreditCommand']` (the intended clause; feature 43's carried item holds) |
| I2 read the order's entries before the lock | KILLED `AssertionError: B4: two holds for ONE order answered ['approved', 'approved']` |

### 3.2 The arms the brief named

- **Races (Q2), all constructed with a held `FOR UPDATE` and a `pg_stat_activity` wait — a change of kind; each failed, none hung (process group killed on timeout, never needed):** I1 drop `with_for_update` / pin `REPEATABLE READ` / read the scalar before the lock → all three KILLED `AssertionError: BC9: two holds for 6 000 against 10 000 of credit answered ['approved', 'approved']`; I3 serve inline → KILLED `Failed: BC21: a request on line B was not answered while line A's request waited` (19 s); I4 drop `with_for_update` → KILLED `expected 1 backend(s) waiting on a lock (query LIKE '%FROM credits%FOR UPDATE%'), saw 0 after 15.0 s`. `pool_size = bound + 1` is asserted through the real lifespan (`engine.pool.size() == 8` for a bound of 7), and U6 (responder bound + 1) is killed by `the responder's bound`.
- **Money boundaries (Q3):** drop the `CAST` → KILLED `InvalidBuyerCreditSnapshotError: … committed exposure Decimal('7000') is not an int.`; ignore the unknown count → KILLED `BC37: a line with an unknown type token answered HoldOutcomeKind.APPROVED`; drop the `22003` mapping → KILLED `Failed: BC30: the scalar's driver error escaped unmapped: Error` (`bigint out of range`); `summarise`'s int64 check → B5 above. **Mine, at the repository read:** the scalar also sums `consume` → KILLED `assert 9000 == ((5000 + 3000) - 1000)`; the unknown filter gains the sibling token `'Hold'` → KILLED (BC37 message).
- **RpcError codes (Q4):** a sibling code substituted at each of the 7 mapping sites (9 arms incl. → `CONFLICT` and → `TIMEOUT`): **9/9 KILLED**, each named by its row label in `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details[<row>]`. `test_billing_rpc_error_retryability.py` names only the saga-class breaks (→ `CONFLICT`: both its tests; terminal ↔ terminal swaps are the row test's), which is the right split.
- **BC34 (Q5):** pattern dropped per service → only that service's cases fail (Billing 5, Orders 4, Fulfillment 4; the other two services' cases and the arch test stay green); Billing default → `otc-orders` → KILLED `two services share a default client id: {…'billing': 'otc-orders'}`. The **real lifespan** (`otc_billing.main.lifespan`) with `BILLING_KAFKA_CLIENT_ID=""` and `" "` fails: `ValidationError | 1 validation error for KafkaSettings / BILLING_KAFKA_CLIENT_ID / String should match pattern '^[A-Za-z0-9._-]+$' [input_value='']` (and `' '`) — names the variable.
- **D6 / BC24 (Q8b):** mapper drops `tzinfo` → KILLED `BC24: wrote 2026-10-08 09:30:15.123000+00:00, read back 2026-10-08 09:30:15.123000`; shift to local then drop → KILLED `… read back 2026-10-08 11:30:15.123000`; **mine:** `astimezone()` keeping an aware CEST value (equality holds) → KILLED at `assert entry.entry_date.utcoffset() == timedelta(0)` (bare assert, see N2).
- **Parity guard (Q1), on the real tree:** Billing `relay.py` `DEADLOCK_ATTEMPTS = 3 → 4` → KILLED naming `infrastructure/outbox/relay.py`; census glob → sibling path `model.py` → KILLED (`AssertionError: []`); census token → `"outboxes"` → KILLED; Notifications' `__tablename__ = "processed_events"` → `"outbox"` (a fourth owner, no copies) → KILLED `services owning an \`outbox\` table without the relay family: ['notifications']`. **Two survivors → D2, D3.**

### 3.3 Unplanned mutations (Q9) — 14 sites

| Arm | Seam | Result |
|---|---|---|
| U1 swap correlation / request id in `decode_release` | responder → handler | KILLED (integration `test_bc25_…`, `test_bc3_release_…`; no unit test sees it — acceptable) |
| U2 `already_held` reports the re-issued amount | handler | KILLED `the RECORDED hold, not the re-issued amount` (unit + integration) |
| U3 port request `available_credit = credit_limit`; U3b retailer/company swapped | handler → port | both KILLED (`test_bc13_…` compares the whole `CreditDecisionRequest`) |
| U4 envelope `causation_id` from `correlation_id`; U4b released payload `credit_code` corrupted | fact → outbox row | both KILLED |
| U5 row `credit_date = created_at` | mapper ↔ snapshot | KILLED (`test_credit_mapper.py` and BC24) |
| U6 responder bound + 1 | settings → adapter (#8 id 56) | KILLED `the responder's bound` |
| U7 rejected reply `available_credit = credit_limit` | handler → reply | KILLED `assert 10000 == 7000` |
| **U8** `released: false` reply `available_credit_after = credit_limit` (`credit_release.py:47`) | handler → reply | **SURVIVED all 851 Billing + architecture tests → D1** |
| **U9** `released: true` reply `available_credit_after = credit_limit` (`credit_release.py:56`) | handler → reply | **SURVIVED all 851 → D1** |
| **U10** `CreditReleased.available_credit_after = credit_limit` (`buyer_credit.py:377`) | domain fact → outbox row | **SURVIVED all 851 → D1** (a payload corruption of a fact) |
| R9a delete only the per-order `Σ hold` check (`exposure.py:83`) | `summarise` | SURVIVED 257 unit tests → N1 |
| R9b delete only the per-order exposure check (`exposure.py:96`) | `summarise` | SURVIVED — an equivalent mutant (non-negative in-range per-type sums cannot leave the range by subtraction) |

## 4. Defects

### D1 (blocking) — the release path's available-credit fields are unguarded: the fixture satisfies the relation by accident

`credit.released.v1`'s `availableCreditAfter` (`services/billing/src/otc_billing/domain/buyer_credit.py:377`) and the reply's `availableCreditAfter` on both branches (`services/billing/src/otc_billing/application/credit_release.py:47`, `:56`) can each be replaced by the **credit limit** and the whole Billing suite plus `tests/architecture` stays green (U8, U9, U10: `851 passed`). Cause: every fixture that reaches a release releases the line's **only** exposure, so "available after the release" equals the limit — `unit/domain/test_credit_ledger.py` (R41's own named test, `:84`, `available_credit_after=1000` on limit 1000), `unit/test_credit_release_service.py:146, :167, :187` (1000 on limit 1000), `integration/test_credit_release.py:38, :57, :67` (`LIMIT`), `test_a_release_of_an_order_that_was_never_held_is_released_false` (`LIMIT`). CLAUDE.md: *"Fixtures must not satisfy the assertion's relation by accident: equality → distinct values"* and *"every branch that emits … a fact has a test that fails when … a field of it is corrupted"*; `design.md` §13.2 requires pairwise-distinct values. This is #7's W3/N5 and #8's D3 shape (a fact field whose corruption survives), on the one fact this feature emits on the saga's compensation path, and it leaves **R41's "returns to its pre-hold value" clause** un-discriminated (the production code is right: K4's live record shows 344 459, not 500 000).

### D2 (blocking) — the parity instrument does not compare the region before the docstring or the rest of the docstring's closing line, and its docstring says it does

`tests/architecture/test_outbox_copy_parity.py:79-90` (`split_docstring`) returns `lines[: first.end_lineno]` as "the docstring", and `violations()` (`:140-147`) only checks that region for the canonical's path. So everything **before** the docstring and everything **after the closing quotes on the same line** is uncompared — the region deviation 1 placed `# ruff: noqa: I001` in. Probe on the real tree (arm `Q1-code-on-docstring-line-plus-file-noqa`, restored, `cmp` equal): Billing's `infrastructure/outbox/relay.py` given `# ruff: noqa: E402 - …` as line 1 and `"""; HIDDEN = __import__("logging").disable()  # noqa: E702  # fmt: skip` as its closing docstring line — an executable statement that disables all logging process-wide at import — passes **the parity test (46 passed), `ruff check`, `ruff format --check` and `mypy`**. The instrument's own docstring (`:19-21`: "any other difference, a one-character change in code, in a comment or in a string, fails by file name") is false, and `requirements.md` `BC17` ("byte-identical … after banner and namespace normalisation") is claimed DONE on it. The brief asked exactly this (Q1); the answer is yes. Pre-existing since feature 17's version of `split_docstring`, but this feature rewrote the instrument, extended it to a new copy, and made the uncompared region load-bearing — CLAUDE.md: *"Changing an instrument swaps its premises. List the new instrument's assumptions and arm them in the same round."*

### D3 (blocking) — the census recognises one textual form; `tasks.md` mandates defeat row 11 armed there, and it was not

`outbox_owners()` (`test_outbox_copy_parity.py:173-180`) counts a service only when `services/*/src/otc_*/infrastructure/persistence/models.py` contains the literal `__tablename__ = "outbox"`. `tasks.md` (preamble): *"rows 4 – 6, 10 and 11 apply to the parity and census instruments (F6, …) and are armed there"*; impl §6's F6 rows arm the nine copies, the census with the recognised form, and the docstring — no row-11 arm. Scratch-tree probe (`table_census` on temporary trees, no repository file touched): a fourth service declaring its table as `__tablename__: str = "outbox"`, `__tablename__ = OUTBOX`, `Table("outbox", metadata)`, or in `persistence/outbox_models.py` → **`[]` (not detected)** in all four forms; only the literal form is caught. `BC17`'s "SHALL require the family from every service that owns a relational `outbox` table" is a behaviour, and CLAUDE.md row 11's remedy applies: *"when a syntax guard keeps losing, test the behaviour, or inspect what actually runs"*.

### Non-blocking (fix now with D1 – D3, same files open; or accept with evidence)

- **N1** — `summarise`'s per-order `Σ hold` check (`exposure.py:83`) is guarded only together with the exposure check: deleting it alone survives (R9a). Observable only on a corrupt ledger (two `hold` rows for one order summing above int64 with a small `release`, e.g. `2 × ((1 << 62) + 1)` and `3`: exposure lands on `INT64_MAX`, no raise). `design.md` §5.3 claims every per-order Σ is checked. Recommendation: one direct-drive case with that ledger. (Brief Q10 / deviation 9: the per-order checks are guarded **only together**; the exposure check alone is an equivalent mutant.)
- **N2** — `integration/test_credit_repository.py:279` `assert entry.entry_date.utcoffset() == timedelta(0)` carries no message naming BC24 (the aware-shift arm dies there anonymously). Add the message.
- **N3** — `UnknownCreditEntryTypeError(token)` is fed a sentence by the repository (`credit_repository.py:63-66`), so the message reads `'2 row(s) of credit line CR-… carry a type outside hold/consume/release' is not a credit ledger entry type.` (deviation 6). Cosmetic; give the error a count-shaped constructor or accept.

## 5. Deviations 2 – 13 (impl §5), ruled

1 (the `noqa` before the docstring) — acceptable **only** with D2's fix allow-listing exactly that directive. 2 accepted (a copy derived from the canonical through `expected_body` is the right lesson). 3 accepted (unreachable through the service; `approve` must refuse). 4 accepted: it makes `BC11`'s raise reachable and differs from #7/#8 only on a ledger that releases more than it held, which no writer here can produce. 5, 7, 8, 11 accepted. 6 accepted (N3). 9 ruled in N1. 10 accepted (the generated `^CR-` pattern guards `creditCode` at the writer; the payload-equality assertion remains). 12 accepted (the hard-coded URL still fails the reach test, slowly; message is a connection error, not the claim — not worth a round). 13 accepted: `R40`'s matrix level is *domain unit*, the cell names its caller (feature 21), and `consume` is armed (B9).

## 6. Ported-idiom ledger, inherited findings, BC32

- **Ledger (`design.md` §3.2, L1 – L37):** present, enumerated from a boundary list, both halves cited. Spot-checked `#8 EfCoreBuyerCreditRepository.cs:37, :53-55` and `#7 buyer-credit.repository.ts:45, :53-57, :63` — as cited. Probed the most-assumed rows: L8 / L30 (sum after lock at pinned READ COMMITTED: three I1 arms + D4), L9 (CAST), L10 (unknown count + sibling token), L11 (22003), L14 (mapper, three arms), L24 (C2 both halves), L26 (three services), L28 (I3, U6). All hold. L20's guard is the parity instrument → weakened by D2.
- **Inherited findings (`design.md` §17, impl §9):** #8 ids 49, 50, 51, 53/55, 54, 56/67/68, 63, 76/83, 85, 87/111, 102 and #7 D1, N1, #8 D1, D4, A1 — **avoided**, consistent with what I armed. **#7 W3/N5 and #8 D3 ("payload corruption survived") — RECURRED in this round as D1** (a fact field whose corruption survives the suite); the impl report's "None recurred" is not correct. #9 feature 17's class (surviving call-site mutations) — **recurred as U8/U9/U10**, at the release reply/fact sites that J1's enumeration covered for `release(` / `save(` calls but not for the result fields built after them.
- **BC32 (Q8c), re-derived independently, rooted at the call:** `grep -rnE "rpc\(|\.request\(|raw\(" services/billing/tests/{integration,unit}/*.py` → 39 `rpc(...)` call sites + 4 raw `json.loads(await raw(...))` sites. 37 of the 39 are consumed through `Decode.*` (discriminating field asserted before `from_wire_json`); 2 are discarded setup replies (`integration/test_credit_hold.py:234`, `:259`) whose effect is asserted later (no decode, so outside BC32's population); the 4 raw sites assert `outcome` / `released` / `page` / `code` first (`test_credit_wire.py:53, :61, :69, :83`). The race test's `r["outcome"]` (`test_credit_hold_race.py:60`) runs after `decode.hold` on both replies. **BC32 holds.**

## 7. A `specs/shared/` gap that must be routed (not narrated)

`requirements.md` §1.2 item 1: **`specs/shared/saga.md` §2's command table has no `credit.release` row** (confirmed: rows are `stock.check`, `stock.reserve`, `stock.release`, `despatch.create`, `credit.hold`, `invoice.issue`, `payment.register`), while `saga.md` §4.3 (lines 235, 241, 255) and §5 (lines 303 – 304) issue it and `asyncapi.yaml` `requestCreditRelease` names the orchestrator as caller. #8 narrated it with "owner feature 41"; #9 narrates it again; `feature_list.json` id 41's acceptance does not mention it (`grep` of `credit.release` across `feature_list.json`: only id 22's `credit.released.v1`). **The leader files backlog entry 213** (next free id; ids 200 – 212 are taken), **attached to feature 41** `orders_cancel_responder`: *"`specs/shared/saga.md` §2 lacks the `credit.release` row (caller Orchestrator, responder Billing, idempotency key `(orderReference, release)`, response `released` / `released: false`) although §4.3 and §5 issue the command; disposition at 41's gate: an `SA-6` proposal adding the row (byte-identical in #7 and #8), recommended, or accept with evidence and a re-open trigger."* Item 2 (headers not obliged) already has a gate disposition (feature 17, G3) and needs nothing.

## 8. What must change before re-review (round 2 of the one allowed without asking)

Test files only (`services/billing/tests/**`, `tests/architecture/test_outbox_copy_parity.py`); no production file should change. Each item names the arm that must then be seen red, with its message naming the claim, and green after restore.

1. **D1.** Give every release fixture a **second order's** active exposure on the same line, so available-after ≠ limit and ≠ pre-release value: `unit/domain/test_credit_ledger.py::test_r41_…` (both reasons) and `::test_bc11_…`; `unit/test_credit_release_service.py` (the released and the no-op cases); `integration/test_credit_release.py::test_bc25_…` and `::test_a_release_of_an_order_that_was_never_held_is_released_false` (plant another order's hold). Assert the fact's `availableCreditAfter` and both replies' `availableCreditAfter` against the hand value. **Arms:** U10 (`buyer_credit.py:377` → `self._credit_limit.amount`) red in `test_r41_…` **and** `test_bc25_…`; U9 (`credit_release.py:56` → `credit.credit_limit.amount`) red in the service test and `test_bc25_…`; U8 (`credit_release.py:47` → `credit.credit_limit.amount`) red in the no-op service case and the never-held integration case. Update `test-matrix.md` R41 only if a test name changes.
2. **D2.** Make the parity guard compare the whole file outside the docstring's own span: nothing may follow the closing quotes on the docstring's last line (use `end_col_offset`), and the lines before the docstring must equal an **allow-list literal** (today: empty, or exactly the one `# ruff: noqa: I001 - …` line on `wire.py` / `writer.py`, per file). Correct the instrument's docstring. **Sentinels (parametrised over both services) + arms:** (a) code after the closing quotes (the `Q1` mutation above) fails naming the file; (b) a non-allow-listed line before the docstring (`# ruff: noqa: E402`, `# type: ignore`) fails naming the file; (c) the pristine tree still passes. Re-run arm `Q1-code-on-docstring-line-plus-file-noqa` on the real tree: red.
3. **D3.** Replace the census's text match with behaviour, or with an instrument that recognises every form: e.g. import each `otc_*.infrastructure.persistence.models` found by glob and read its `metadata.tables` for `"outbox"`, or AST-scan every module under `persistence/` for an `Assign`/`AnnAssign` to `__tablename__` resolving to `"outbox"` and for `Table("outbox", …)`. State the new instrument's premises in its docstring. **Sentinels + arms:** the four forms of §4 D3 (annotated, constant, Core `Table`, another module) each fail the census naming the service; the existing `['notifications']` arm stays red; a pristine three-service tree passes; the literal `["billing", "fulfillment", "orders"]` population assertion stays.
4. **N1 – N3** (same round, no extra review weight): N1 one direct-drive case (arm R9a red); N2 the BC24 message (arm `D6-mine-mapper-aware-local` red naming BC24); N3 fix or accept in the impl report.
5. **Impl report:** correct §9 ("None recurred" → #7 W3/N5 / #8 D3 recurred as D1 in round 1, fixed in round 2), add the new arms to §6, and re-run `./quality.sh`.
6. **Leader (not the implementer):** file backlog entry 213 per §7.

## 9. Effort (for the leader's entry at approval)

Review round 1: ≈42 min (≈07:28 → ≈08:10, 2026-10-09), including one full `./quality.sh` (349 s), `./init.sh`, 58 valid arm runs (2 discarded constructions of mine) and two scratch-tree probes. Classification: full group.

---

# Round 2 — re-review after the fix round (`progress/impl_billing_credit.md` § Round 2)

**Verdict: APPROVED** — D1, D2 and D3 are closed. Each was re-armed by me on the real tree and failed with a message that names its claim. N1 and N2 are closed, and N3 is accepted, not fixed. Three new findings came out of attacking the new instruments' premises (R2-1 to R2-3). All three are test-only. None touches shipped behaviour. They are **not blocking, and the disposition is FIX NOW (light, test-only, before the feature's commit)**: §R2.6 gives the reason, and the leader owns the closing arms.

Reviewer: Opus, 2026-10-09, ≈09:21 → ≈10:06 local (≈45 min). Brief: `progress/brief_review_billing_credit_round2.md`. Premise check: `progress/premise_review_billing_credit_round2.md` (11 VERIFIED, 0 FALSE). I re-ran its two `find -newer` lines myself: no file under `services/*/src` or `packages/` changed in the fix round, and the six `.py` files listed are the only ones that did. I never started the developer stack (`docker ps`: `otcpy-n8n` only, before and after).

All tooling, specs, backups and verbatim logs are under `.arm/review19r2/`: `arm.py`, `arm_multi.py`, `arm_newfile.py`, `specs/`, `specs2/`, `bak/<arm>/` and `logs/<arm>.log`. Before the first arm, the sha256 of every file any arm edits was recorded in `pre_arm.sha256`, and afterwards `sha256sum -c` printed 8/8 `OK`. Every arm restored its files with `cp` and confirmed `cmp` plus sha256 equality inside the arm. Four arms created a new file, and each deleted that file and its new directories afterwards (checked: no leftovers). `git status --porcelain | sha256sum` gave the same hash before and after the arming (`5ed4108c…`). I cleared `__pycache__` after every restore and removed `.mypy_cache` at the end. After that the changed test files re-ran green: 111 passed.

## R2.0 What I ran (and what I did not)

- **`./quality.sh` once, developer stack down, before any arm.** Exit **0** in **353 s**, with **`3154 passed in 327.79s`**. The other gates: `ruff format` reported 678 files already formatted, `ruff check` was clean, `mypy --strict` was clean on 551 files, import-linter kept 11 contracts and broke 0, coverage was **97.42 % overall / 99 % domain**, and web passed 1 test. The log is `.arm/review19r2/quality.log`. This agrees with the implementer's figures (366 s, 3 154 passed). The +43 over round 1's 3 111 is 42 parity sentinel cases plus 1 `summarise` case.
- **30 arm runs** of **28 distinct mutations**: the review's U8, U9, U10 and Q1 re-run verbatim; 9 parity-premise attacks (D2b – D2j); 8 census arms (D3a – D3h); 5 instrument mutations (IM1 – IM5); and 2 release-computation mutations (M1, M2). Two of the runs (D2c2, Q1r) repeat D2c and Q1 with full output, because the first runs piped pytest through `tail` and could not show which test failed (logged as `run_all.out` and `run2.out`). There were also 18 scratch-tree probes plus 1 pristine control that touched no repository file (`scratchpad/r2/probe.py`, output `probe.out`).
- I did not re-run the implementer's round-2 arms wholesale. I re-ran every arm the round-1 §8 named, plus my own.

## R2.1 D1 — release fixtures (CLOSED)

The fixtures now plant a second order's exposure on the same line. I read every case:

| Case | limit | before | after (asserted) | after ≠ limit | after ≠ before |
|---|---|---|---|---|---|
| `test_credit_ledger.py::test_r41_…`, both reasons (`:70-95`) | 1 000 | 350 (asserted, `:71`) | 600, both on the fact and on `available_credit` | yes | yes |
| `::test_bc11_…` (`:139-151`) | 1 000 | 350 | 600, on the fact (`:151`) and on available credit | yes | yes |
| `test_credit_release_service.py`, released case (`:143-170`) | 1 000 | 350 | 600, on the reply and the whole fact | yes | yes |
| `…`, no-op cases ×2 (`:179-195`) | 1 000 | 600 | 600 on the reply | yes | n/a: nothing is released, so the correct value *is* the value before |
| `integration/test_credit_release.py::test_bc25_…` | 100 000 | 65 790 | 70 000, on the reply, the outbox payload and the repeat reply | yes | yes |
| `…::test_a_release_of_an_order_that_was_never_held_…` | 100 000 | 70 000 | 70 000 | yes | n/a (no-op) |

Every released case therefore separates the after value from both the limit and the before value. A no-op case can only separate it from the limit, and that is the mutation it owns (U8).

**Arms, exactly as round 1's §8 item 1 wrote them, all RED in the tests §8 named, and all green after restore:**

- **U10** (`buyer_credit.py:377` → `self._credit_limit.amount`): `test_r41_…` failed with `AssertionError: assert CreditRelease… == CreditRelease…` (`Differing attributes: ['available_credit_after']`). `test_bc25_…` failed with `AssertionError: a field of the credit.released.v1 payload is wrong` / `{'availableCreditAfter': 100000} != {'availableCreditAfter': 70000}`. Exit 1; after restore, 2 passed.
- **U9** (`credit_release.py:56` → `credit.credit_limit.amount`): the service's released case failed with `assert (250, 1000) == (250, 600)`, and `test_bc25_…` with `assert (4210, 100000) == (4210, 70000)`. After restore, 2 passed.
- **U8** (`credit_release.py:47` → `credit.credit_limit.amount`): the service's no-op case failed with `AssertionError: never held` / `assert 1000 == 600`, and the never-held integration case with `assert 100000 == 70000`. After restore, 2 passed.
- **Mine, M1** (the fact reports the *pre-release* value, `limit − self._committed_exposure`): KILLED in 4 tests (`test_r41_…`, `test_bc11_…` with `assert 350 == 600`, the service's released case with `a field of the credit.released.v1 fact is wrong`, and `test_bc25_…`). This arm attacks the other half of the relation that round 1 could not see.
- **Mine, M2** (the released reply reports `limit − released`): KILLED, with `assert (250, 750) == (250, 600)` in the unit test and `assert (4210, 95790) == (4210, 70000)` in the integration test.

R41's "returns to its pre-hold value" clause now discriminates. The test name is unchanged, and `test-matrix.md` needed no edit. A script checked R37–R41: 14 (path, test) pairs, 0 missing.

## R2.2 D2 — the parity instrument, with premises attacked (CLOSED on the copy operand; R2-1 is open on the canonical operand)

The round-1 **Q1** mutation, verbatim, on the real Billing `relay.py` (`# ruff: noqa: E402 …` as line 1, plus `"""; HIDDEN = __import__("logging").disable()  # noqa: E702  # fmt: skip`), went **RED**: `test_every_listed_module_is_a_faithful_copy_of_its_canonical[billing]` failed with `billing's outbox copies differ from Orders': ["infrastructure/outbox/relay.py: the lines before the docstring are '# ruff: noqa: E402 - the copy keeps the canonical layout\n', the allow-list holds ''", 'infrastructure/outbox/relay.py: text follows the docstring\'s closing quotes: \'; HIDDEN = __import__("logging").disable()  # noqa: E702  # fmt: skip\'']`. Green after restore.

**The new instrument's premises, and the attack on each:**

| Premise | Attack (real tree unless marked) | Result |
|---|---|---|
| **Preamble = allow-list literal** (`PREAMBLE_ALLOWED`, empty unless listed) | D2b: `# type: ignore` before Fulfillment's `writer.py` docstring | **RED**: `fulfillment's outbox copies differ from Orders': ["infrastructure/outbox/writer.py: the lines before the docstring are '# type: ignore\n', the allow-list holds ''"]` |
| **Tail empty** (`end_col_offset` on the closing line) | Q1 above, plus D2j: a comment-only tail `"""  # ruff: noqa` on Billing `relay.py` | **RED** both. D2j: `… text follows the docstring's closing quotes: '  # ruff: noqa'` |
| **P4, bytes and not characters** | D2c: `… never this copy. 日本""";0  # noqa: E703  # fmt: skip`. The two CJK characters shift a character slice by 4, and the tail starts with `;0` | **RED**: `… text follows the docstring's closing quotes: ';0  # noqa: E703  # fmt: skip'`. IM4 (my instrument mutation, slicing by characters) is **RED** in `test_sentinel_code_after_the_closing_quotes_is_seen_after_non_ascii_text_on_the_line[billing]` and `[fulfillment]` (`assert [] == ['infrastructure/outbox/relay.py']`). The sentinel can see the premise |
| **A docstring opened with `'''`** | D2f: `'''…'''; HIDDEN = 1  # noqa: E702  # fmt: skip` | **RED** (`text follows the docstring's closing quotes`) |
| **A prefixed docstring (`r"""`)** | D2d: `r"""…"""; HIDDEN = 1 …` | **RED** (same message) |
| | D2e: `r"""` alone | **green by design**: the docstring is the copy's own and is not compared. Accepted |
| P1 / P3 (first statement, column 0) | scratch: a parenthesised docstring passes; an f-string or bytes docstring is "no module docstring" | as designed |
| splitlines ≠ tokenizer lines (`\x0c`, U+2028 inside the docstring) | scratch: a form feed in the docstring plus code after the closing quotes; U+2028 alone | **caught, failing closed**: the shift puts the closing line into the body, so `differs from the canonical` (the message is misleading, but the tool fails) |
| **The canonical's own preamble and tail are empty** (an *unstated* premise) | **D2i**: round 1's Q1 mutation applied to **Orders' canonical** `relay.py` | **SURVIVED: R2-1** |

## R2.3 D3 — the census (CLOSED; R2-2 is open, an overclaim in the docstring)

Round 1's §4 forms, on the real tree:

| Arm | Result |
|---|---|
| D3a Notifications `__tablename__: str = "outbox"` | **RED**, both `test_every_service_owning_…` (`["services owning an \`outbox\` table without the relay family: ['notifications'] (listed: ['billing', 'fulfillment', 'orders'])"]`) and the cross-check |
| D3b `_OUTBOX_NAME = "outbox"` / `__tablename__ = _OUTBOX_NAME` | **RED**, same two tests, same message |
| D3c Core `Table("outbox", MetaData())` in a new `persistence/outbox_models.py` | **RED**, same two tests |
| D3d a second service's Core **mirror** (`otc_notifications/infrastructure/mirror_tables.py`) | **RED**: census `['notifications']`; cross-check `({'billing', 'fulfillment', 'orders'}, {'billing', 'fulfillment', 'notifications', 'orders'})` |
| D3e (**a form the scan does not list**) `__tablename__ = "out" + "box"` in `persistence/models.py` | **RED**, by the behaviour cross-check alone: `({'billing', 'fulfillment', 'notifications', 'orders'}, {'billing', 'fulfillment', 'orders'})` |
| D3h `Table("out" + "box", MetaData())` in `persistence/outbox_models.py` | **RED** by the cross-check |
| **D3g** the same `Table("out" + "box", …)` in `infrastructure/messaging/tables.py` | **SURVIVED: R2-2** |

**`MIRRORS_NOT_OWNERS = {"seed"}`, ruled:**

- **The seed is a mirror, not an owner.** It has no Alembic tree (migrations live in `services/{orders,fulfillment,billing,notifications}/alembic/`, none in `services/seed`). It writes *already-published* outbox rows into the three services' databases (`sagas.py:4`, `postgres.py:76`, `published_at=occurred_at` at `sagas.py:244`), so no relay is owed. `tables.py:1-13` says its Core tables are hand-written copies that `schema_check` checks against the migrated databases.
- **#7 and #8 do the same.** #8 writes the rows through Billing's own `BillingDbContext` (`src/Seed/Infrastructure/Persistence/BillingSeedWriter.cs:18, :137-152`), and #7 through Billing's own Drizzle `schema.outbox` (`apps/seed/src/writers/billing-db.writer.ts:6, :141-158`). #9 must mirror the table because the independence contract forbids importing a service. That is a forced difference, and the exclusion is its consequence.
- **The exclusion is a literal, with its reason beside it** (`test_outbox_copy_parity.py:109-113`).
- **It cannot go stale.** D3f (the seed's `_outbox` renamed to `"outbox_mirror"`) went **RED**: `assert set() == {'seed'}`. IM5 (`MIRRORS_NOT_OWNERS = {"seed", "billing"}`) went **RED** in both tests: `['fulfillment', 'orders'] == ['billing', …]`.
- **It cannot absorb a second mirror.** D3d went **RED**.

## R2.4 N1 – N3

- **N1, CLOSED.** `test_bc30_raises_ledger_overflow_when_the_hold_total_exceeds_int64_though_the_exposure_does_not` uses round 1's own ledger shape: `2 × (2**62 + 1)` held, then 3 released, landing on `INT64_MAX`. It asserts the message names the hold total. The implementer's arm R9a is recorded RED, with `committed_exposure=9223372036854775807`. I read the case and did not re-arm it.
- **N2, CLOSED.** `test_credit_repository.py:279-281` now carries the message `BC24: read back …, offset …, not UTC`. The implementer's arm is recorded RED with exactly that message.
- **N3, ACCEPTED, NOT FIXED.** It is cosmetic: the error's `code` and type are both guarded (round 1, Q3: the unknown-token arms were killed by type). The fix needs a production edit, which the fix round's bounds forbid. **Re-open trigger:** any edit to `services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:63-66` or to `UnknownCreditEntryTypeError`'s constructor, or any feature that shows this message to an operator (problem details, logs asserted by a test).

## R2.5 Unplanned mutations (mine), verbatim

| Arm | Site | Result |
|---|---|---|
| M1 | fact `available_credit_after = limit − committed before the release` | **KILLED**, 4 tests (above) |
| M2 | released reply `available_credit_after = limit − released` | **KILLED**, `assert (250, 750) == (250, 600)` and `assert (4210, 95790) == (4210, 70000)` |
| IM2 | census: same-module constants not resolved (`return False`) | **KILLED**, 6 sentinel cases (`…[models.py-constant-…]`, `…[models.py-annotated constant-…]`, ×3 modules) |
| IM3 | census glob `infrastructure/**/*.py` → `infrastructure/persistence/*.py` | **KILLED**: the cross-check gave `assert set() == {'seed'}`, and 6 `sub/tables.py` sentinel cases failed |
| IM4 | P4: tail sliced by characters | **KILLED**, 2 sentinel cases (above) |
| IM5 | mirror exclusion gains `billing` | **KILLED**, 2 tests |
| **IM1** | tail check ignores comments (`…decode("utf-8").split("#")[0]…`) | **SURVIVED all 88** (`88 passed in 28.61s`): **R2-3** |
| **D2i** | canonical-side Q1 | **SURVIVED: R2-1** |
| **D2h** | `# ruff: noqa: E402` before Orders' canonical docstring, alone | **SURVIVED** (part of R2-1) |
| **D3g** | unlisted form outside `persistence/` | **SURVIVED: R2-2** |

## R2.6 New findings (all test-only, all FIX NOW, light; none blocking)

**R2-1: the parity instrument does not check the canonical operand outside its docstring.** In `tests/architecture/test_outbox_copy_parity.py:174-180`, `expected_body` takes only `parts.body` of the canonical. Its `preamble` and `closing_tail` are never looked at, and `violations()` (`:183-222`) checks those two regions only on the copy.

Arm **D2i** applied round 1's Q1 mutation to `services/orders/src/otc_orders/infrastructure/outbox/relay.py`: `# ruff: noqa: E402 - …` as line 1, then `"""; HIDDEN = __import__("logging").disable()  # noqa: E702  # fmt: skip` as the closing docstring line. The result was **`88 passed in 28.35s`, `ruff check`: `All checks passed!`, `ruff format --check`: `1 file already formatted`, `mypy`: `Success: no issues found in 1 source file`**. Orders' relay then runs a statement at import that neither copy runs, yet the guard still reports the families byte-identical. That contradicts `BC17` ("byte-identical to the canonical copy after banner and namespace normalisation", claimed DONE) and the instrument's own docstring (`:8`: "the text AFTER the module docstring equals the Orders file's text after its docstring").

This is round-1 D2's class on the other operand: an unstated premise of the changed instrument. Why it does not block:

- All nine canonicals have an empty preamble and an empty tail today. I enumerated them: `docline 1 pre '' tail b'\n'` × 9.
- Neither this feature nor any earlier one placed anything there. Round-1 D2's region held deviation 1's directive.
- Orders' outbox files are untouched by feature 19 (`git status`: only Orders' `settings.py`), so the gap predates it.
- The fix is test-only, which CLAUDE.md sizes as light.

**Fix:** require the canonical's `preamble == ""` and `closing_tail.strip() == ""`, failing with a message that names `orders` and the module (for example in `expected_body`, or as one check per `rel` in `violations`). Add a sentinel parametrised over a tail and a preamble on the canonical. **Arm:** D2i must go RED naming `infrastructure/outbox/relay.py` and the canonical. D2h (the preamble alone) must go RED.

**R2-2: P6's claim is wider than the cross-check's population.** The docstring (`:47-50`) says the cross-check makes "a form the scan cannot read still fail on the real tree". But `test_the_scan_agrees_…` (`:357-370`) imports only `infrastructure/persistence/*.py`, while the scan's population (P5) is `infrastructure/**/*.py`. Arm **D3g** put `Table("out" + "box", MetaData())` in a new `otc_notifications/infrastructure/messaging/tables.py`, and the result was **`88 passed`**. The same form in `persistence/` is killed (D3h). The form is contrived, and the realistic forms (annotated, constant, Core, another module, BinOp in `persistence/`) are all caught. **Fix, either of:**

- (a) widen the cross-check's import population to the scan's (`infrastructure/**/*.py`, minus `__init__.py`). Arm: D3g RED.
- (b) correct the docstring to say the cross-check covers `persistence/*.py` only, and add that to P6. Arm: none owed for a wording fix.

(a) is recommended.

**R2-3: no sentinel arms the comment-only tail.** The real instrument catches `"""  # ruff: noqa` (D2j RED). But mutation IM1, which makes the tail check ignore comments, survives all 88 tests, so loosening that check would go unnoticed. A file-level `# ruff: noqa` on the closing line is a directive and not only a comment. **Fix:** add one sentinel, parametrised over both services: a comment-only tail (`"""  # ruff: noqa`) fails naming the file. **Arm:** IM1 must go RED.

**Disposition, and why the verdict is still APPROVED.** The feature's deliverables are correct and their guards are now armed. That covers every production path under every probe in both rounds, R37–R41, and round-1 D1–D3 as §8 specified them. R2-1 to R2-3 are guard extensions to a cross-service architecture test. CLAUDE.md's cost rules class a test-only fix as **light**: one implementer, the leader reads the diff, and one arm per fix. They are fixed now, in Phase 10, before feature 19's commit, by `test_maintainer` or `implementer` with the three arms above (D2i + D2h, D3g if (a) is chosen, and IM1) run by the leader and recorded in the effort entry. If the leader judges R2-1 to be blocking (the same class as round-1 D2), the three items above stand on their own as the "What must change" of a round 3.

No new `specs/shared/` root cause was found. Round 1's §7 gap is filed as backlog **213**, attached to feature 41 (`feature_list.json:849-859`, checked).

## R2.7 CHECKPOINTS.md (re-walked for round 2)

**C1**: [x] harness files present · [x] `./init.sh` (round 1, unchanged since: no harness file changed in the fix round).

**C2**: [x] at most one `in_progress` · [x] statuses valid · [x] after this verdict, 19 → `done`, one line.

**C3**:
- [x] domain / shared_kernel purity (import-linter, 11 kept, run)
- [x] no cross-service DB access; independence contract kept (the only cross-service imports are in `tests/architecture/`, by design)
- [x] no new shared runtime code (`packages/` untouched, `find -newer` empty)
- [x] no `float` / `Decimal` / `/` in Billing's domain (money guard green; no `src` file changed)
- [x] interactions classified (unchanged since round 1)

**C4**: [x] `./quality.sh` exit 0 (353 s, 3 154 passed) · [x] domain tests pure · [x] integration tests on testcontainers with the stack down (U8–U10 ran their integration halves against containers, with only `otcpy-n8n` up) · [x] coverage 99 % domain / 97.42 % overall · [x] no Jest, Karma or Jasmine.

**C5**: [x] no stray untracked files (all of `.arm/` is git-ignored; my new files were removed) · [x] history entry with effort (appended now) · [x] `feature_list.json` 19 → `done` · [ ] human told what was done and how to test (the leader's, at close) · [x] no commit.

**C6**:
- [x] `specs/billing_credit/` complete
- [x] 67/67 tasks ticked, and the three ticks round 1 disputed (C4/H5 fixture rule, F6 row 11, F6's "any other difference") are now true for the copy operand. F6's "any other difference" is false on the canonical operand: R2-1, fix now
- [x] every `R<n>` discriminated (R41 now)
- [ ] spec commit before implementation commit (the human's)

**C7**:
- [x] `specs/shared/` unchanged by the fix round
- [x] no silent fork
- [x] inherited findings accounted for, with impl §9 corrected (`:595`, `:617`)
- [x] effort record (now)

## R2.8 R → test (re-verified for what the fix round touched)

- R37, R38, R39 and R40 are unchanged since round 1, with names re-resolved: 0 missing.
- **R41**: `unit/domain/test_credit_ledger.py::test_r41_…` and `::test_bc11_…`, plus `integration/test_credit_release.py::test_bc25_…`. They now **discriminate** (U10, M1 RED at domain level; U9, U10, M2 RED at integration).
- BC17 is discriminating on the copy operand (Q1, D2b–D2f, D2j RED) and on ownership (D3a–D3f, D3h RED). The canonical operand is R2-1.
- BC24 has its message (N2), and BC30's hold-total check now stands on its own (N1).

## R2.9 Effort

Review round 2: ≈45 min (≈09:21 → ≈10:06, 2026-10-09). That covers one full `./quality.sh` (353 s), 30 arm runs, 18 scratch-tree probes, the seed / #7 / #8 ownership reading, and this record.
