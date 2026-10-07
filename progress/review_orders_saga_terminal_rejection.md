# Review: feature 42 `orders_saga_terminal_rejection_classification` (round 1)

**Verdict: REJECTED.** The reason is documentation only. The code, the tests and the arming hold at every grain I probed: 15 reviewer mutations, every one killed, every one restored to its recorded sha256. But the design document of record still shows the very predicate this feature exists to remove. Under §9.6, `specs/order_saga_orchestrator/design.md:578` reads `park … WHERE id = :id AND status <> 'sent'`. The implementer's record says #8 note 5 (a stale doc) was "avoided". That is false: it partially recurred. The fix is a few lines of documentation. No source or test change is asked for, so a light re-review is enough (see "What must change").

Classification: full group (saga, persistence). Reviewer: Opus, round 1. One more round is allowed without asking the maintainer.

## What I ran (and what I did not)

- **No full `./quality.sh` re-run.** The claim under test is about this feature's files, not the suite. Instead I checked the implementer's artifacts. `.arm/f42_quality.exit` = `0`. `f42_q.end − f42_q.start` = 442 s. The log has `2387 passed in 409.07s`, `Contracts: 11 kept, 0 broken` and `quality.sh: all gates passed`. `find services packages tests apps/web/src -type f -newer .arm/f42_q.start` printed nothing, so no source or test file changed after the run started (the last source edit was `command_dispatcher.py` at 14:29:08; the run started at 14:39:11).
- **Targeted green run, developer stack down.** Before running I checked: `docker ps` showed only `otcpy-n8n`, none of 9092/4222/5432/27017 was listening, and no pytest was running. Run: `uv run pytest services/orders/tests/unit/saga …/integration/saga/{test_saga_command_rejected_ledger,test_saga_command_terminal_rejection,test_saga_command_ledger,test_saga_command_retry,test_nats_saga_commands_reply_decode}.py tests/architecture/test_write_path_population.py`. Result: **494 passed in 45.21s**.
- `uv run lint-imports`: `Contracts: 11 kept, 0 broken.` `uv run mypy`: `Success: no issues found in 387 source files`. `ruff check services/orders`: all passed. `ruff format --check services/orders`: 181 files already formatted. `./init.sh`: exit 0, warnings only for uncommitted changes and the reminders.
- **Reviewer mutations.** Driver `.arm/review42/rarm.py`. For each arm: a backup plus a recorded `sha256` in `.arm/review42/<id>/`, one mutation, whole test files run without `-x`, restore by copy, `cmp`, cache clear, and a green re-run. Every arm reported `restore cmp identical=True, sha256 equal=True` and a green restored run. A final sweep compared all 15 recorded sha256 files with the current files: `15 match`. No run hit the 600 s process-group timeout.

## Reviewer arming table (verbatim output in `.arm/review42/<id>/mutated.out`)

| Id | Mutation | Scope run | Result |
|---|---|---|---|
| R1 | drop `Code.not_found` from `TERMINAL_RPC_ERROR_CODES` | whole `unit/saga` (388) | exactly 2 fail: `…terminal_code_is_a_business_rejection…[NOT_FOUND]` and the partition test. The other 8 terminal and 3 transient cases stay green (#8 probe 1, at one-code grain and over a wider population than the implementer's single file) |
| R2 | dispatcher `ledger.reject` → `ledger.park` | `unit/saga` | the 2 feature-42 dispatcher tests fail at `[rejected] = r.ledger.rejected` (`ValueError: not enough values to unpack`). That is an earlier line than `parked == []`, so I armed the later claims separately (R2b, R2c) |
| R2b | reject **and** park | `unit/saga` | `AssertionError: reject is not park`, the same 2 tests. The "never parked" claim is live on its own (#8 note 1) |
| R2c | reject **and** mark_sent | `unit/saga` | `AssertionError: reject is not sent`, the same 2 tests |
| R5 | adapter passes `(message, code)` swapped (a corrupted field) | `unit/saga` | 9 fail, one per terminal code: `assert 'said VALIDATION_FAILED' == 'VALIDATION_FAILED'` |
| R6 | a code outside the twelve made terminal (`ValueError` → `SagaCommandBusinessRejectionError`) | `unit/saga` | exactly 1 fails: `test_so15_an_rpc_error_with_a_code_outside_the_twelve_fails_open_to_transport`, `AssertionError: an unknown code is not an RpcError` |
| R3 | `claim_due` **pending** branch admits `rejected` | e2e `test_saga_command_terminal_rejection.py` (real NATS, Postgres, Kafka) | the e2e fails: `AssertionError: the sweeper never re-issues it`, `assert 2 == 1` (see Q1) |
| R7 | `claim_due` **parked** branch admits `rejected` (a control row is present) | rejected-ledger file + feature 16's ledger file (20) | exactly 1 fails: `claim_due: exactly the pending control, never the rejected row` |
| R8 | `try_claim` admits `rejected` | the same 20 | exactly 1 fails: `try_claim: status, not the NULL next_attempt_at, keeps a rejected row out` |
| R4 | `reject` predicate `!= 'sent'` (re-rejects, but leaves sent rows alone): the second claim of a two-claim test | rejected-ledger file | exactly 1 fails: `assert ('rejected', 9, 'second') == ('rejected', 1, 'first')`. The implementer's L5 removed the whole predicate and died at the first (`sent`) assertion, so this claim had not been armed; it is live |
| R9 | `reject` stores `last_error=""` (field corruption on the persisted row) | rejected-ledger + e2e | 3 fail, including the e2e (`assert '' == 'CONFLICT: ee…'`) |
| R10 | `ensure_in_range` deleted from `reject` | rejected-ledger | exactly 1 fails: `…outside_int32_raises_the_range_guards_domain_error`. The failure is asyncpg's `DataError` (`value out of int32 range`), not the domain error. Not armed by the implementer |
| Q1 | no-responders raised as `SagaCommandTimeoutError` (feature 15/16 split) | `unit/saga` + reply-decode integration | 6 fail, `test_no_responders_is_a_transport_error_naming_its_subject[*]` |
| Q2 | an SO15 decode defect raised as a terminal rejection (the new risk feature 42 creates) | the same | 43 fail: all 36 SO15 unit cases, the unknown-code case and the 6 real-NATS reply-decode cases (`AssertionError: not UTF-8 … is SagaCommandTransportError`) |
| Q3 | SO4 in-line back-off removed | `unit/saga` + `test_saga_command_retry.py` | 3 fail, including `test_so4_retries_a_timed_out_command…` (`AssertionError: 500 ms then 1 000 ms, none after the last attempt`) |

Defeat-list rows I exercised: 1 (R2, R6), 2 (R5, R9), 3 (R1 and R4: a sibling code, and a sibling predicate set), 9 (R3 against the e2e, R4 against the stale closer half of a two-claim test), 12 (R3 drives the sweeper through the real lifespan). Rows 4–7 and 10 do not apply, because no syntax guard was added. For row 8: the expected code set is a literal tuple in the test, not read from the adapter.

## Rulings on the brief's questions

**Q1. E2 and the planted rows: the planted-state guard holds for `rejected`, for the same reason it held for `sent`.** I established reachability; I did not assume it. The writers of `next_attempt_at` on a `rejected` row are:

- `reject` sets it to NULL (`command_ledger.py:162`, armed by L7);
- `try_claim`, `claim_due`, `mark_sent` and `park` are all excluded by status, each armed (L1–L4, L8, R7, R8);
- `enqueue` is `ON CONFLICT DO NOTHING`.

So a `rejected` row with a non-NULL `next_attempt_at` cannot be reached, and E2 (the **parked** branch) is a genuinely equivalent mutant through the API. That matches feature 16 round 2's ruling for `sent` (`progress/review_order_saga_orchestrator.md:375-381`). The ruling's three tests are met here:

- **The reachable half is guarded through a reachable path.** R3 shows that the claim "the sweeper never re-issues a rejected row" fails the end-to-end test when the **pending** branch's status term admits `rejected`. A `rejected` row's NULL lease and old `created_at` satisfy every other conjunct of that branch, and `try_claim` (L3, R8) likewise needs no planted state.
- **The planted block cannot fail correct code.**
- **The planted block is labelled as planted** (`test_saga_command_rejected_ledger.py:174-175`).

The implementer's wording should be tightened: "the status claim rests on planted-row ledger tests" is true only of the parked branch.

**Q2. #8's probes, at my grain: all hold.**

- Probe 1: R1.
- Probe 2: R2 kills the test, though at an earlier line. R2b and R2c show the later "not park" and "not sent" claims are each live.
- Probe 3: R7 and R8, each with a control row present, each failing exactly one test. The negative assertion is never vacuous, because `[row.order_id for row in due] == [control.order_id]` is an equality, not a `not in`.

For note 1, I hunted the shape and found one more two-claim test whose second claim had not been armed (`test_reject_never_moves_a_sent_row_and_a_rejected_row_is_not_rejected_twice`). R4 shows that claim is live. No mutation survived.

**Q3. An unknown code is proven retryable, compositionally.**

- At the adapter, `test_so15_an_rpc_error_with_a_code_outside_the_twelve_fails_open_to_transport` asserts `type(...) is SagaCommandTransportError` and that there is no `code`. It is armed by R6.
- At the dispatcher, a plain `SagaCommandTransportError` is retried: `test_command_dispatcher.py:171` (`rig([SagaCommandTransportError("s", "no responder"), REPLY])`, sent after one pause).

No end-to-end test sends an unknown code. Given the two armed halves, I do not require one.

**Q4. Features 15 and 16 did not regress.** Feature 42 touched the adapter, the dispatcher, the ledger, the sweeper and two ports. Re-armed:

- the no-responders/timeout split (Q1, 6 killed);
- SO15 decode (Q2, 43 killed, and this also shows feature 42's new exception cannot swallow a decode defect);
- SO4 back-off (Q3);
- feature 16's ledger file, run in R7 and R8 (19 of its 20 tests green under each mutation, so its own predicates are unaffected).

SO9's files (`saga_facts_consumer.py`, `fact_handler.py`, `fact_consumption.py`) are not touched, so the SO9 arms do not apply. `composition.py` was last modified at 07:51, before feature 42's brief (13:37:47), so feature 15's P-arms do not apply. The stock-availability adapter `nats_stock_availability.py` (07:49) is untouched.

**Q5. The predecessor holes, verified with file and line.** This is evidence for the trilogy record only; #7 and #8 are not to be touched.

- **#7**, `apps/orders/src/infrastructure/saga/drizzle-saga-command-store.ts`:
  - `notAlreadySent()` = `status <> 'sent'` (`:190-191`) guards `markSent` (`:140`), `park` (`:155`) and `markRejected` (`:170`);
  - so `park` would re-park a `rejected` row, and `markRejected` re-rejects one;
  - the claim at `:124-125` names `pending`/`parked`, so a rejected row is not swept.
- **#8**, `src/Orders/Infrastructure/Saga/EfCoreSagaCommandStore.cs`:
  - `ParkAsync` uses `c.Status != "sent"` (`:217`);
  - `RejectAsync` has **no** status predicate (`:249`);
  - **and `MarkSentAsync` has no status predicate either (`:177`).** The implementer's ledger row omits that third hole: in #8 a late reply can move a `rejected` (or `parked`) row to `sent`;
  - the claim names `pending`/`parked` (`:87`).

In both predecessors these holes are reachable only through a dispatch that outlives its lease. That is improbable under a 60 s lease against a 16.5 s worst-case dispatch, but it is not structurally excluded. #9 closes all of them (`status IN CLAIMABLE` on every write, each armed).

## Defects

**D1 (blocking; doc of record contradicts the code; #8 note 5 recurred, claimed avoided).** In `specs/order_saga_orchestrator/design.md` §9.6:

- line 578 still gives `park`'s SQL as `WHERE id = :id AND status <> 'sent'`;
- line 554 says "All four statements", while there are now five, and `reject` has no SQL in the listing, although the section heading at line 552 says `reject` is feature 42's;
- line 583 says "`mark_sent` / `park` are conditional: a row another claimer already marked `sent` is never moved back to `parked`". It omits `rejected`, which is now the property that bullet must state.

The §9.5 amendment block (line 524) does say "`park` was `status <> 'sent'`", so the document contradicts itself one screen apart. Feature 42's whole acceptance item 4 is that change. The brief's question 6 assigned exactly this, and the record (`progress/impl_orders_saga_terminal_rejection.md`, "#8's probes and notes", Note 5) reports it "avoided".

**D2 (non-blocking, fix in the same pass; stale wording that omits `rejected`).**

- `design.md:522` and `command_dispatcher.py:5` list why a claim returns no row as "(absent, `sent`, or leased by someone else)". A `rejected` row is also a no-op claim.
- `application/ports/saga_command_store.py:21`: `ALREADY_OWED` is commented "pending, parked or sent".
- `command_ledger.py:1`: the module heading says "claim, mark sent, park".

**D3 (record accuracy).** Correct these in `progress/impl_orders_saga_terminal_rejection.md`:

- Note 5 is not "avoided" until D1 is fixed;
- the Q1 wording should say that only the parked-branch status term rests on planted state (R3 shows that the pending branch and `try_claim` are guarded through reachable state);
- the ledger row "Other ledger predicates" should add #8's predicate-free `MarkSentAsync` (`EfCoreSagaCommandStore.cs:177`).

## Traceability (acceptance item → test, verified by running and by mutation)

| Item | Tests | Armed by |
|---|---|---|
| 1. terminal `RpcError` classified terminal, not retried | `test_feature_42_a_terminal_code_is_a_business_rejection_not_a_transport_error[×9]`, `…partition_the_generated_code_enum`, `…every_command_method_classifies_a_terminal_code[×6]`, `…terminal_rejection_is_rejected_on_the_first_attempt_never_retried_parked_or_sent`, e2e `…terminal_rpc_error_resolves_the_row_to_rejected_on_the_first_attempt…` | R1, R2, R2b, R2c, R5; implementer A1–A4, D1–D5, E1 |
| 2. retryable transport failure still retried | `…transient_code_is_a_retryable_rpc_error_carrying_its_code[×3]`, `…transient_rpc_error_is_still_retried_and_parked_not_rejected`, e2e `…transient_rpc_error_is_still_retried_in_line_and_parked`, the SO4/SO15/no-responders tests, the unknown-code test | Q1, Q2, Q3, R6; implementer D6 |
| 3. a row receiving a terminal error reaches a resolved end state | `test_reject_resolves_a_claimed_row_to_rejected_clearing_the_lease…`, `test_reject_with_an_attempt_count_outside_int32…`, the e2e (status, attempts 1, last_error, NULL lease, order status unchanged) | R9, R10; implementer L6, L7 |
| 4. every status predicate, `park`'s included; the sweeper never re-claims | `test_park_never_re_parks_a_rejected_row…`, `test_mark_sent_never_moves_a_rejected_row…`, `test_try_claim_never_claims_a_rejected_row…`, `test_claim_due_never_returns_a_rejected_row…`, `test_reject_never_moves_a_sent_row_and_a_rejected_row_is_not_rejected_twice`, e2e "the sweeper never re-issues it" | R3, R4, R7, R8; implementer L1–L5, L8 |

There is no `R<n>` for this split, as #7 and #8 also found. `specs/shared/test-matrix.md` was last modified at 12:37, before feature 42 started (13:37). Correctly untouched.

## Ported-idiom ledger: claims checked

- **Terminal set:** #7 `nats-saga-commands.adapter.ts:79-93` and #8 `NatsSagaCommandsAdapter.cs:179-185` agree member for member with `TERMINAL_RPC_ERROR_CODES`. Confirmed by reading both.
- **Unknown code:** #8 falls to false (transient), matching its comment at `:170-178`. #9 relies on pydantic's `ValueError` for a value outside the enum, armed by R6.
- **Reject-before-retry:** #9's `SagaCommandBusinessRejectionError` is not a `SagaCommandTransportError` subclass. The test asserts `not isinstance(…, SagaCommandTransportError)`.
- **`rejected` write:** a single conditional statement, armed by L5 and R4.
- **Integer arithmetic:** `row.attempts + attempt`, range-guarded and armed by R10.

The ledger's "Other ledger predicates" row is incomplete (D3). Ported-guard table: consistent with #8's three probes.

## Deferred surfacing (routed, not narrated)

A `rejected` row leaves the order in an intermediate status, with only an ERROR log line: no `order.saga_failed.v1` and no dead letter. This is routed as an acceptance item on feature 27 (`feature_list.json`, id 27, the last acceptance entry, "carried from orders_saga_terminal_rejection_classification (id 42 …)"). That item requires deciding with evidence, and an `SA-n` proposal or a recorded decision if `specs/shared/` does not decide it. The artefact exists, so nothing further is owed here.

## CHECKPOINTS.md (applicable boxes)

C1:
- [x] the harness files exist
- [x] progress files exist
- [x] the agents are present
- [x] `./init.sh` exit 0 (this review)
- [ ] model declarations: not re-walked this round (unchanged by this feature)

C2:
- [x] at most one feature `in_progress` (42 was the only one active; now set back to `in_progress`)
- [x] every status is valid (init.sh)
- [x] `done` features have tests
- [x] `current.md` describes the active session
- [x] no `blocked` features to explain

C3:
- [x] `lint-imports`: 11 kept, 0 broken
- [x] no cross-service access; independence contract kept
- [x] no new shared runtime code
- [x] no `domain` imports `otc_cqrs`
- [x] `shared_kernel` and `cqrs` unchanged by this feature
- [x] no money arithmetic touched. The only `/` added is none: `timeout_ms / 1000` predates this feature, and it is not money
- [x] Kafka-fact / NATS-RPC classification unchanged (the saga commands are NATS RPC)
- [x] no debug logging or context-free TODOs in the six files

C4:
- [x] `./quality.sh` exit 0 (implementer's run; its artifacts checked as above)
- [x] no domain tests touched
- [x] integration tests on testcontainers with the developer stack down (R3, R7–R10 ran that way)
- [x] coverage: 98.70% total (log)
- [x] no Jest

C5:
- [ ] history entry: not written; the feature is not closed
- [x] `feature_list.json` reflects the true state (42 → `in_progress`)
- [x] no commit by Claude

C6: not applicable (`sdd: false`). `specs/order_saga_orchestrator/` is feature 16's spec, amended here; D1 is its defect.

C7:
- [x] `specs/shared/` byte-identical (init.sh 5d, exit 0)
- [ ] inherited #8 findings accounted for: #8 note 5 is recorded "avoided" but recurred partially (D1, D3)
- the rest: not applicable to this feature

## What must change before re-review

1. **`specs/order_saga_orchestrator/design.md` §9.6** (D1):
   - change `park`'s SQL at line 578 to `WHERE id = :id AND status IN ('pending', 'parked')`;
   - add `reject`'s statement to the listing (`SET status = 'rejected', attempts, last_error truncated, next_attempt_at = NULL, updated_at … WHERE id = :id AND status IN ('pending', 'parked')`);
   - change "All four statements" (line 554) to five;
   - rewrite the bullet at line 583 so that `mark_sent`, `park` and `reject` never move a `sent` **or `rejected`** row.

   Mark each change as feature 42's amendment. **Check:** `grep -n "<> 'sent'\|!= 'sent'\|All four" specs/order_saga_orchestrator/design.md` returns at most the historical mention inside the §9.5 amendment block ("`park` was `status <> 'sent'`"), classified as such in the record.
2. **D2:**
   - add `rejected` to the no-op-claim list at `design.md:522` and `command_dispatcher.py:5`;
   - change the `ALREADY_OWED` comment at `saga_command_store.py:21` to "pending, parked, sent or rejected";
   - add `reject` to `command_ledger.py:1`.

   Comment and docstring edits only. **Check:** `cmp` shows no code-statement change, and `uv run ruff format --check services/orders` and the targeted `unit/saga` run stay green.
3. **D3:** correct the record as listed under D3, and list the reviewer arms R4 and R10 as additional guards. No re-arming is needed: no executable line changes.
4. **No `./quality.sh` re-run is needed** if the diff is confined to the items above. The leader confirms that with `cmp` against the backups of the code files, or by a re-review that reads the diff. Because the remaining work is documentation, a light re-review (the leader reads the diff and runs the `grep` in item 1) is proportionate. That is the leader's call under CLAUDE.md's cost discipline.

## Effort (round 1, for the eventual history entry)

- Implementer: ≈63 min (13:44 → 14:47:51, per `progress/current.md` and file mtimes).
- Brief and premise check: 13:37:47 → 13:38:36.
- Review round 1: 14:48:49 → ≈15:15 (≈26 min), with 15 mutations, a 494-test targeted run, lint-imports, mypy and init.sh.
- Elapsed so far: ≈1 h 38 min, against #8's ≈1.1 h (1 pass, approved first time) and #7's ≈30–35 min (`../order-to-cash-dotnet/progress/history.md:874-876`).
- Rounds: 1 (rejected, documentation only).
