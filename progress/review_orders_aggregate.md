# Review: `orders_aggregate` (feature 13, phase 8, full group: money domain)

**Verdict: REJECTED.** This is round 1 of at most one rejection round taken without asking the maintainer.

Every R5–R10 requirement is proven, all 37 re-armed guards on the specified paths were killed, and all six #8 findings stay closed as stated. The rejection is for one defect class, found by unrequested probes. **Ten field-level corruptions in the aggregate leave the whole domain suite green (127 passed):** four on the payloads of the domain events, four on `rehydrate`'s snapshot-to-aggregate mapping, and two on `place`'s read model. Two of them are money fields. CLAUDE.md line 128 is binding: *"Every branch that emits or suppresses a fact has a test that fails when the emission is deleted and when a field of it is corrupted."* The implementer armed deletion on every emission branch. Field corruption was armed only on `cancellation_reason`, `note`, `causation_id`, `correlation_id` and `event_id`. That is the same gap the reviewer brief warns about from #8 feature 17. The fix is test-only and bounded (section 6).

## 1. What I ran, and what I did not re-run

- **Per-file domain counts:** every file was run on its own (`uv run pytest -q -p no:cacheprovider <file>`). The figures are 2 + 24 + 1 + 8 + 4 + 18 + 17 + 7 + 19 + 7 + 14 = **121**. The parity file gave 6, the kernel's `test_money_text.py` 14, and the seed's `test_money_text.py` 15 (14 vectors plus the dataset test).
- **The implementer's five-path headline:** `packages/shared_kernel` 316, `services/seed/tests/unit` 148, `tests/architecture` 399. Combined with the two orders paths, one run gave **990 passed** (121 + 6 + 316 + 148 + 399 = 990). This reconciles.
- **`uv run lint-imports`:** `Contracts: 10 kept, 0 broken.`
- **`uv run mypy`:** `Success: no issues found in 241 source files`.
- **`uv run ruff format --check`:** `300 files already formatted`. **`uv run ruff check`:** `All checks passed!`.
- **`./init.sh`:** rc 0. Section 5d reported the shared spec byte-identical to `../order-to-cash-dotnet` and to `../order-to-cash-nestjs` across 6 files each.
- **Not re-run: `./quality.sh`.** No claim under test is about the full suite except the 1433 figure, and that one reconciles arithmetically (section 7). No integration suite was run either. This feature adds no integration test and touches no `infrastructure/`. The stack was neither started nor stopped.

## 2. CHECKPOINTS.md

**C1, the harness is complete**
- [x] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json` and `init.sh` exist.
- [x] `progress/current.md` and `progress/history.md` exist.
- [x] `.claude/agents/` holds all seven agents.
- [x] Every agent declares its model. Four have `model:`. leader, reviewer and spec_author state in their description that they inherit the session model.
- [x] `./init.sh` exits 0.

**C2, state is coherent**
- [x] At most one feature is `in_progress`. Before this verdict there were 0 (29 pending, 25 done, 1 in_review). After it there is 1, feature 13.
- [x] Every status is in `valid_status`.
- [x] Every `done` feature has passing tests (n/a to this change).
- [x] `progress/current.md` is the leader's live session note.
- [x] No feature is `blocked`.

**C3, architecture is respected**
- [x] `lint-imports` reports 10 kept, 0 broken.
- [x] No cross-service DB access or import. The domain imports only stdlib, `otc_shared_kernel` and `otc_orders.domain`. The census is in section 5, Q6.
- [x] No new shared runtime package. `format_money` went into `packages/shared_kernel` (the OP-1 gate ruling).
- [x] No domain module imports `otc_cqrs`.
- [x] `shared_kernel` and `cqrs` still have `dependencies = []` (line 6 of each `pyproject.toml`).
- [x] No float, Decimal, `/`, `round` or `pow` in the domain money arithmetic. The grep output is in section 5, Q6. The AST money guard is green.
- [x] Kafka/NATS classification: n/a, the domain does no I/O.
- [x] No stray debug output or context-free TODO: `grep -rnE "print\(|TODO|FIXME|XXX|breakpoint"` over the new files returned rc=1, no hits.

**C4, verification is real**
- [ ] `./quality.sh` passes. **Implementer-reported** (exit 0, 131 s, 1433 passed), not re-run by me. The count reconciles (section 7). It must be re-run after the rework.
- [x] Domain tests are pure. `test_domain_unit_tests_import_only_...` is green and was armed by the implementer (6.4).
- [x] Integration tests use testcontainers: n/a, this feature adds none.
- [x] Coverage thresholds: implementer-reported 98% domain and 98.41% total. Not recomputed.
- [x] No Jest, Karma or Jasmine.
- [ ] **The tests are not complete against CLAUDE.md line 128.** Ten field corruptions survive (section 4).

**C5, the session closed cleanly**
- [x] No suspicious untracked files. `git status --short --untracked-files=all` shows only the change set, the progress files, and the untracked `specs/orders_aggregate/`.
- [ ] A history entry with an effort record. Not owed on a rejection.
- [x] `feature_list.json` is true. I set feature 13 to `in_progress`, on that line only.
- [ ] The human has been told: that is for the leader.
- [x] Claude did not commit.

**C6, spec-driven development**
- [x] `specs/orders_aggregate/` holds all three files.
- [x] `requirements.md` reproduces R5–R10 verbatim in EARS form.
- [x] All 73 boxes of `tasks.md` are ticked. Ticked is not the same as sufficient, see section 4.
- [x] Every R5–R10 row of `test-matrix.md` names a real test. All 13 named node ids collect 29 cases, and all 29 pass.
- [ ] The spec commit precedes the implementation commit. Both are uncommitted; this is for the wrap-up.

**C7, second-reuse fidelity**
- [x] `specs/shared/` is byte-identical to #8 and #7 apart from `test-matrix.md` (init 5d, `cmp`).
- [x] No SA amendment is proposed, and none is needed.
- [x] The R ids are #7's, and the realisation matches them (section 3).
- [x] n8n, the API script, the README benchmark: n/a this feature.
- [x] Inherited #8 findings are accounted for, with evidence, in section 5, Q4.
- [ ] History effort record: not owed on a rejection.

## 3. R to test mapping (verified by running the named node ids)

| R | Named tests (all green, all exist) | Exercises the requirement? |
|---|---|---|
| R5 | `test_order.py::test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line` | Yes. It asserts the code on an empty `place` and on `remove_line` of the last line, and that the state is unchanged. Implementer arms 3.8 and 3.8b. |
| R6 | `test_order_totals.py::test_r6_order_recomputes_...`, `test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_...`, `test_r6_place_refuses_a_negative_total` | Yes. My M1 (`change_line` keeps the old quantity) was killed: `(10076, 258, 9818) == (13076, 258, 12818)`. My M2 (`_commit_lines` skips `_initial_discount`) was killed by the R6 test and the writer scan. |
| R7 | `test_order.py::test_r7_order_refuses_to_add_remove_or_modify_...` (six statuses, one-line order), `test_r7_lines_are_mutable_exactly_...` | Yes. Implementer arms 3.18a, 3.18b and 3.19. |
| R8 | `test_order_state_machine.py::test_r8_order_walks_every_legal_edge_of_table_t1`, `test_r8_..._reaches_cancelled_only_from_...`, `test_r8_..._treats_completed_and_cancelled_as_terminal` | Yes. See also the T-1 spec-parse arm in section 4.2. |
| R9 | `test_order_state_machine.py::test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_...` | Yes. The 72 / 11 / 61 counts are literals. Implementer arms 4.5a–c. |
| R10 | `test_order_cancellation.py::test_r10_order_requires_a_reason_...`, `test_r10_..._no_cancellation_reason_...`, `test_r10_..._does_not_pair_...` | Yes. Implementer arms 4.6a/b, 4.7/4.7b and 4.8a–c. The reason is assigned inside `_transition_to`'s accepted branch (`order.py:486-487`). |

The `test-matrix.md` edit (task 6.6) was checked line by line against `git show HEAD:` with the same line count:
- Only 8 lines differ.
- On rows R5–R10 only cell 5 (Status) changed.
- On the two summary rows only the Green and Not-yet-green cells changed.
- Recounting the Status cells gives 63 rows: 9 DONE, 1 SCOPED, 53 TODO. R1–R10 has 9 DONE and 1 SCOPED. This matches the edited summary counts.

## 4. Re-arming: my own probes (CLAUDE.md protocol)

Protocol for every probe:
1. Make a `cp` backup and apply a single-anchor mutation. The script refuses an anchor that matches 0 or more than 1 time.
2. Clear `__pycache__` and run the named target.
3. Restore from the backup and confirm with `cmp`. Every restore printed `identical`.
4. Clear `__pycache__` and `.mypy_cache`, then re-run green. Every re-run was green.

Target T is the whole domain suite plus the parity file (127 tests), unless named otherwise.

### 4.1 Survivors (the defect)

| # | File and anchor | Mutation | Family | Result |
|---|---|---|---|---|
| P1 | `order.py:273-274` (`OrderPlaced` builder) | `buyer_gln` ↔ `supplier_gln` swapped | corrupt field / sibling | **127 passed** |
| P2 | `order.py:423` (`OrderCompleted` builder) | `total_amount=self._initial_amount` | corrupt **money** field | **127 passed** |
| P3 | `order.py:276` (`OrderPlaced` builder) | `order_date=occurred_at` | corrupt field | **127 passed** |
| P4 | `order.py:282-283` (`OrderPlacedLine`) | `unit_price` ↔ `line_discount` swapped | corrupt **money** field | **127 passed** |
| R1 | `order.py:353` (`rehydrate`) | `notes=None` | drop an optional element | **127 passed** |
| R2 | `order.py:346-348` (`rehydrate`) | `retailer_code` ↔ `company_code` swapped | sibling | **127 passed** |
| R3 | `order.py:356` (`rehydrate`) | `created_at=snapshot.updated_at` | sibling | **127 passed** |
| R4 | `order.py:349` (`rehydrate`) | `supplier_gln=snapshot.buyer_gln` | sibling | **127 passed** |
| PL1 | `order.py:251-253` (`place`) | the order's `buyer_gln` ↔ `supplier_gln` swapped | sibling | **127 passed** |
| PL2 | `order.py:249` (`place`) | the order's `order_date=occurred_at` | corrupt field | **127 passed** |

Why these matter now and not at feature 14 or 15:
- Each of these values reaches a wire fact or a repository row from the aggregate alone.
- No test anywhere asserts `OrderPlaced.buyer_gln`, `.supplier_gln`, `.order_date`, `.currency`, `.retailer_code` or `.company_code`.
- No test asserts any `OrderPlacedLine.unit_price` or `.line_discount`.
- No test asserts `OrderCompleted.total_amount`, `.order_reference`, `.retailer_code`, `.company_code` or `.currency`, or `OrderCancelled.order_reference`, `.retailer_code` or `.company_code`.
- The enumerating grep over `services/orders/tests/unit` for `<event>.<field>` reads lists every payload read that exists. Those reads are confined to `test_order_events.py:277-290`, `test_order_cancellation.py:113-114,198,214` and `test_order_rehydration.py:63`.
- `test_place_keeps_the_order_reference_and_the_business_codes_it_was_given` (`test_order.py:262-270`) checks the reference, the notes and the retailer/company/currency, but not the two GLNs or `order_date`.
- No test reads `rehydrate`'s restored fields except status, reason, totals and line order.

The feature's own rule decides the disposition: findings are fixed in the phase that detects them, and the domain half is fully buildable now. #8 shipped the same shape (its domain tests had no field-level payload assertions either), which makes this a recurrence of #8's class, *a load-path or payload property no test reads, found by a probe nobody asked for*. It is not a new #9 regression of a specific #8 id.

### 4.2 Killed (guards that hold)

| # | Brief item | Mutation | Test(s) that failed (verbatim first line) |
|---|---|---|---|
| A1 | silent T-1 edge, **row 3** (`approve_credit`). The implementer used rows 6 and 7; #8 used rows 2 and 5. | `self._raise_event(object())` after the transition | `test_o8_..._five_silent_edges...`: `assert (<object obje...abea86ea470>,) == ()` |
| A2 | silent row 3, through the funnel (a valid `OrderConfirmed` passed as `build_event`) | a real event, not a sentinel object | same test: `AssertionError: assert (OrderConfirm...mezone.utc)),) == ()` |
| A3 | rehydrate check 6 **weakened** (not deleted) | `snapshot.lines[:1]`: only the first line checked | `test_rehydrate_refuses_a_line_whose_unit_price_...`: `assert 'money.cross_currency' == 'order.line_currency_mismatch'`. The fixture corrupts line 2, so a weakened loop is visible. |
| A4 | rehydrate check 3, sibling substitution | `CANCELLED` → `COMPLETED` in the O6 check | many failures: `InvalidOrderSnapshotError: ... a cancelled order has no cancellation reason` |
| M1 | money path, corrupt supplied field | `change_line` keeps `existing.quantity` | `test_r6_..._after_each_mutation`: `assert (10076, 258, 9818) == (13076, 258, 12818)` |
| M2 | money path, delete | `_commit_lines` drops `_initial_discount` | writer scan, and the R6 recompute test (2 failed) |
| F1 | kernel `format_money`, CLDR-style separator | `" "` → `" "` | 11 failed. Kernel: `assert '1\xa0234\xa0567.89 EUR' == '1 234 567.89 EUR'`. The orders 3.10 and seed tests also failed. |
| F2 | `format_money`, sign on zero | `< 0` → `<= 0` | `assert '-0.00 USD' == '0.00 USD'` |
| F3 | `format_money`, fraction not zero-padded | `f".{fraction_part}"` | 6 failed: `assert '0.5 EUR' == '0.05 EUR'` |
| X1 | unrequested: token table sibling | `"paid": OrderStatus.COMPLETED` in `_BY_TOKEN` | `test_parse_accepts_each_real_token_and_returns_its_member` |
| X2 | unrequested: reason table sibling | `"stock_rejected": CREDIT_REJECTED` | same test |
| X3 | unrequested: `require_utc` weakened (accepts any aware offset) | `utcoffset() is None` | 4 failed: `Failed: DID NOT RAISE InstantNotUtcError` (plus-one-hour cases) |
| L7 | ledger: `assert_never` exhaustiveness (mypy half of a two-party engine claim) | `case OPERATOR_CANCELLED` deleted | `uv run mypy .../domain`: `order.py:75: error: Argument 1 to "assert_never" has incompatible type "Literal[CancellationReason.OPERATOR_CANCELLED]"` |
| L1 | ledger: `strict_equality` flags `status == "placed"` | `if self._status == "placed": return` in `mark_paid` | mypy: `Non-overlapping equality check (left operand type: "OrderStatus", right operand type: "Literal['placed']")` |
| T1 | T-1 **spec-parse half** (the implementer could not arm it, report section 6 item 8) | On an **out-of-tree copy** of `domain-model.md` at `<scratchpad>/armT1/specs/shared/`, with the test file copied beside it. `specs/shared/` was never touched (`git diff --stat` empty). (a) Row 3 target changed to `confirmed`. (b) Row 5 fact changed to `order.despatched.v1`. | (a) `At index 2 diff: (3, 'stock_reserved', 'confirmed', None) != (3, 'stock_reserved', 'credit_approved', None)`. (b) `At index 4 diff: (5, 'confirmed', 'despatched', 'order.despatched.v1') != (5, ..., None)`. The copy was restored, `cmp` against the real spec matched, and the test went green. |
| D11 | defeat row 11 against the writer scan | `getattr(type(self), "_cancellation_reason").__set__(self, OPERATOR_CANCELLED)` in `add_line` | **The structural scan is blind to it** (no `setattr`, no attribute target). It was **caught behaviourally**: 2 failed (`test_r6_..._negative...[add_line]`, `test_an_overflowing_total...`), `At index 1 diff: <CancellationReason.OPERATOR_CANCELLED> != None`. |

Defeat-list rows that apply to my probes:
- Row 1 (delete): M2, plus the implementer's full set.
- Row 2 (corrupt a supplied field): P2, P3, M1, PL2.
- Row 3 (substitute a sibling): P1, P4, R2, R3, R4, PL1, A4, X1, X2, T1a.
- Row 7 (drop an optional element): R1.
- Row 9 (premise): A3's fixture corrupts line 2, which is why the weakened loop is seen.
- Row 11 (a form the instrument does not recognise): D11.
- Row 12 (a path the population never drives): A1 and A2 on row 3.
- Rows 4–6 and 10 concern the syntax instruments. The implementer armed them with sentinels (`test_the_writer_scan_*`), and I re-read none of them.

## 5. The brief's questions

**Q1, re-arm.** See section 4. I used guards the implementer had not armed that way: a different silent edge (row 3); rehydrate weakened and substituted rather than deleted; the money path by a corrupt supplied quantity; `format_money` by its separator, sign and padding; and the T-1 spec half. The unrequested probes are X1–X3, D11, P1–P4, R1–R4 and PL1–PL2. The last ten survived.

**Q2, the spec texts the implementer flagged.**

Task 3.12 (the arm "cannot bite"): the finding is **sound**.
- `place` binds `requested = tuple(lines)` (`order.py:223`) and only iterates it.
- New `OrderLine`s are built into `order_lines`, so the caller's sequence is never stored anywhere.
- Replacing `tuple(lines)` with `lines` changes nothing observable.
- The substitute arms (lines held as a `list`, 3.12; the caller's list kept as `compensation_steps`, 4.13a) attack the two real aliasing sites, so no property is left unguarded.

Task 4.16 ("exactly the four `order.*` facts other than `saga_failed`" is false): the finding is **sound**.
- `FACT_MODELS` holds 14 keys, 6 of them `order.*`: cancelled, completed, confirmed, **despatched**, placed, saga_failed (`uv run python -c ...`).
- The test (`test_order_domain_contract_parity.py:63`) subtracts both named keys and asserts equality with the four, so "exactly" is still enforced.

Disposition for both: **fix the wording now (leader, docs).** Amend `specs/orders_aggregate/tasks.md` 3.12's arm text to *"hold the aggregate's lines as the internal `list` (`placed_lines = order_lines`)"*, and 4.16's to *"other than `order.saga_failed.v1` and Fulfillment's `order.despatched.v1`"*. This is a feature-spec edit, not a `specs/shared/` amendment.

**Q3, the ledger (design.md section 2).** Every row's guard executes the code the row is about. I checked both halves of the rows a reviewer is most likely to assume:
- L1: the `strict_equality` claim was armed (mypy error).
- L7: `assert_never` was armed (mypy error). The report's "narrower" note is accurate: one `match` exists, and the freeze table is guarded behaviourally by 3.18 and 3.19.
- L4 and L5: the structural scan reads `order.py`. Its blind spot (D11) is backed by behaviour on the probed path.
- L6: both halves were armed (the implementer did the transcription half, I did the spec half, T1).
- L13: X3.
- L17: A3 and A4.
- L9: the implementer's arm 3.11 drives `compute_totals` inside `add_line`.

**The ledger has no row for the field mapping of events and snapshots.** That is not an idiom ported from #7 or #8, so the absence is not a ledger defect. It is the coverage gap of section 4.1.

**Q4, #8's findings.**

| #8 id | Verdict | Evidence |
|---|---|---|
| defect (Rehydrate checks survive deletion) | **avoided** as stated | The implementer deleted each of the nine checks alone; each is killed by its own test. My A3 (weakened) and A4 (substituted) were killed too. **The class recurred in a different place:** R1–R4 (rehydrate's field mapping) survive, found the way #8's defect was found, by an unrequested probe. |
| A1 (report figures do not reconcile) | **avoided** | Per-file 121. Five-path 990 = 121 + 6 + 316 + 148 + 399, re-run by me. 1433 = 1290 + 143 (section 7). |
| A2 (reason assigned outside the accepted branch) | **avoided** | `order.py:485-487`. The event reads `self._cancellation_reason` (`order.py:452`). Arms 3.13b and 4.6a. |
| A3 (corrupt snapshot raises a business code) | **avoided** | `InvalidOrderSnapshotError` / `order.snapshot_invalid` for checks 1–4 (`order.py:303-313`). |
| A4 (more error classes than the table) | **avoided** | 12 classes in `errors.py` = design section 10. `test_the_orders_domain_error_population_is_the_literal_table` walks the package (arm 3.16). |
| A5 (brief vs tasks conflict handled ad hoc) | **avoided** | No conflict arose. The two spec-text imprecisions were reported, not silently resolved. |

**Q5, `test-matrix.md`.** Columns 1–4 and every other row are byte-identical. Column-5 names exist and pass (section 3).

**Q6, purity and money.** `grep -nE "float|Decimal|round\(|pow\(|[^/]/[^/]|\*\*|__import__|setattr|datetime\.now|async def|..."` over `services/orders/src/otc_orders/domain` and the kernel's `money_text.py` returned 6 hits. Each one is classified:
- `errors.py:1`: a path in the docstring.
- `order.py:1`: a path in the docstring.
- `order.py:3`: the docstring text "no `async def`".
- `money_text.py:3`: a path in the docstring.
- `money_text.py:5`: the docstring text "never `/`".
- `money_text.py:14`: a comment about `10 ** exponent`.

None is code.

The `enum` allow-list edit is backed by a census: an AST walk of the 46 files (`find ... -name '*.py' | wc -l` gives 46) finds `enum` imported in 3 files (`order_status`, `cancellation_reason`, `compensation_step`). The full root set is collections, dataclasses, datetime, enum, hashlib, types, typing, uuid, plus first-party. This matches the docstring and `ALLOWED_ROOTS`.

`Money` is the kernel's int64-bounded `int`. The overflow refusal is armed (3.11).

The seed produces identical text. `diff <(git show HEAD:services/seed/src/otc_seed/domain/money_text.py) packages/shared_kernel/src/otc_shared_kernel/money_text.py` differs only on line 8, the import (`otc_shared_kernel` → `otc_shared_kernel.currency_exponent`, which avoids an import cycle inside the kernel). The function body is byte-identical. The seed's unit suite passed 148, including `test_every_credit_summary_of_the_dataset_renders_the_amount_as_money`.

**Q7, timing.** The count is fully explained by this feature: 1290 + 121 (domain) + 6 (parity) + 14 (kernel `format_money`) + 2 (`test_kernel_surface` parametrised `[money_text]` ×2, found by `--collect-only`) = **1433**.

The time is **not** explained by this feature. Its 143 tests run in about 1.2 s (domain 0.7 s, parity 0.25 s, kernel 0.03 s, measured). The remaining roughly 27 s over Phase 7's 103.24 s was measured with the `otcpy` stack up, while the threshold of about 125 s is defined with the stack stopped. The two runs are not comparable. **Report only:** the leader should re-time `quality.sh` with the stack stopped at the post-rework run.

On the integration suites, this feature changes nothing under `infrastructure/` and adds no integration test. Their independence from the developer stack is untouched by it, and I did not re-demonstrate it.

## 6. Defects and dispositions

| # | Finding | Where | Disposition |
|---|---|---|---|
| **D1** | Event payload fields not guarded against corruption. P1–P4 survive, and two of the fields are money. | `order.py:263-292` (`OrderPlaced`, `OrderPlacedLine`), `:412-425` (`OrderCompleted`), `:376-389` (`OrderConfirmed.order_reference`), `:455-468` (`OrderCancelled` business codes). Tests: `test_order_events.py:270-290` assert only a subset. | **Fix (reject).** |
| **D2** | `rehydrate` field mapping not guarded. R1–R4 survive. | `order.py:342-358`. Fixture `conftest.py:177` has `notes=None`, so a dropped note is invisible. | **Fix (reject).** |
| **D3** | `place` read-model mapping not guarded for the GLNs and `order_date`. PL1 and PL2 survive. | `order.py:246-262`. Test `test_order.py:262-270`. | **Fix (reject).** |
| F4 | ruff 0.16 formats ```` ```python ```` blocks in `specs/**/*.md`. This rewrote `specs/orders_aggregate/design.md` during the run. It would rewrite `specs/shared/` (read-only, byte-identical to #7/#8) the moment a Python block appears there. Today: `ruff format --check specs/` reports `8 files already formatted`, and `specs/shared/` has no Python block (premise check). | root `pyproject.toml` `[tool.ruff]` | **Fix this phase, leader** (root config is the leader's to edit). Exclude `specs/` at the source (`extend-exclude`). Arm it with a throwaway ```` ```python ```` block in a scratch `.md` under `specs/`, which must then be reported as not checked. Not the implementer's defect, and it does not block this verdict. |
| F5 | `tasks.md` 3.12 and 4.16 wording | `specs/orders_aggregate/tasks.md:54, 82` | **Fix this phase, leader (docs).** The text is in section 5, Q2. |
| F6 | The writer scan cannot see a slot-descriptor write via `getattr(...).__set__` (D11). | `test_order_structure.py` instrument | **Accept with evidence.** On the probed path the behaviour tests caught it (2 failed). Writing it requires deliberate obfuscation that `mypy --strict` types as `Any`. **Re-open if** any `__set__` or `getattr(` appears under `otc_orders/domain`. |
| F7 | `Order.__init__` is public, so a caller could construct an `Order` without `place` or `rehydrate` validation. | `order.py:100` | **Accept with evidence.** `grep -rnE "\bOrder\(\|cls\(" services/orders/src` returned 4 hits: `order.py:80` (class def), `:246` (`place`), `:342` (`rehydrate`) and `models.py:112` (the ORM class, a different class). There is no outside caller. **Re-open if** feature 15's mapper or any module outside `order.py` calls `Order(`. Leader: attach that as an acceptance item on feature 15. |

`# pragma: no cover` at `order.py:453` is accepted as disclosed (report section 6 item 5). It narrows a type for mypy and is reachable only under arm 4.6a.

## 7. What must change before re-review (implementer, test-only, no production edit expected)

1. **Event payload, every field.** Add a test, named for its claim, that asserts every payload field of each of the four events against fixture-supplied literals with pairwise-distinct values:
   - `OrderPlaced`: `order_reference`, `retailer_code`, `company_code`, `buyer_gln`, `supplier_gln`, `currency`, `order_date`, `notes`, the three totals, and each `OrderPlacedLine`'s five fields for **both** lines.
   - `OrderConfirmed` and `OrderCompleted`: `order_reference`, `retailer_code`, `company_code`, `currency`, `total_amount`.
   - `OrderCancelled`: `order_reference`, `retailer_code`, `company_code`.
   - The fixtures need distinct values. The fixture GLNs, `order_date` vs `occurred_at`, and price vs discount are already distinct. `retailer_code` and `company_code` are already distinct.
   - Arm it with P1, P2, P3 and P4 exactly as in section 4.1, plus one corruption on `OrderConfirmed` (for example `order_reference`) and one on `OrderCancelled` (`retailer_code` ↔ `company_code`). Each must fail naming the field.
2. **`rehydrate` restores every field.** One test asserting each read-model property equals its snapshot field: `id`, `order_reference`, `order_date`, `retailer_code`, `buyer_gln`, `company_code`, `supplier_gln`, `currency`, `notes` (**non-None** in that test), `created_at`, `updated_at`, and each line's `product_code`, `description`, `quantity`, `unit_price`, `line_discount`. Arm it with R1–R4.
3. **`place` keeps every field.** Extend `test_place_keeps_...` (or add a sibling test) to cover `buyer_gln`, `supplier_gln`, `order_date`, `created_at` and `updated_at`. Arm it with PL1 and PL2.
4. Add one row per arm to `progress/impl_orders_aggregate.md` under the same protocol. Update the per-file counts so they still sum to the headline. Re-run `./quality.sh` once.
5. Leader, before re-dispatch: add these as tasks (for example 4.17, 5.12 and 3.22) to `specs/orders_aggregate/tasks.md` so the brief does not outrank the spec. Also apply F4 and F5. On re-review, the effort entry should name this rejection, and whether #8's review standard would have caught it. Probably not: #8's six probes were deletion and guard order, and its domain tests had the same gap.

---

## Round 2 (re-review of the D1–D3 rework): **APPROVED**

**Inputs:**
- the "Review round 1 rework" section of `progress/impl_orders_aggregate.md`;
- tasks 3.22, 4.17 and 5.12 in `specs/orders_aggregate/tasks.md` (0 unticked: `grep -c "^- \[ \]"` gives 0);
- the leader's fixes F4, F5 and F7.

**Not re-run:** `quality.sh`. Per the leader, the stack is up and the leader times it with the stack stopped at wrap-up. Instead I ran:
- `uv run ruff check`: `All checks passed!`
- `uv run mypy`: `Success: no issues found in 241 source files`
- `uv run lint-imports`: `Contracts: 10 kept, 0 broken.`
- `./init.sh`: rc 0
- per-file counts, each file run alone: 2 + 24 + 1 + 9 + 4 + 19 + 18 + 7 + 19 + 7 + 14 = **124**, plus parity 6. The implementer's 1436 = 1433 + 3 reconciles.

### R2.1 Is the production code the code I reviewed?

`order.py`'s mtime (09:40:55) is newer than my round-1 review. No byte copy was held from round 1, so this is verification by content, not by `cmp`:
- `wc -l` is still **592**.
- Every one of my 10 round-1 survivor anchors and the U-probe anchors matched **exactly once**. The script refuses an anchor that matches 0 or more than 1 time.
- A re-read of the logic regions matches my round-1 read line for line: `_sources_for` at lines 67–77, `rehydrate`'s nine checks and sort at 303–341, the `cancel` check order at 440–449, `_transition_to` at 483–490, and the three line mutators with `_commit_lines` and `_require_currency` at 504–584.
- The only file under `services/orders/src` newer than my review is `order.py` (`find services/orders/src -newer progress/review_orders_aggregate.md`). The 09:32 mtimes on `instants.py`, `order_status.py` and `cancellation_reason.py` are my own round-1 `cp` restores (X1–X3).

Conclusion: no production change. The mtime is the implementer's `cp` restore.

### R2.2 My round-1 survivors, re-run against the whole domain suite plus parity (130 tests)

| Probe | Result | Test killed it | Failure (verbatim `E` line) |
|---|---|---|---|
| P1 `OrderPlaced` GLNs swapped | **killed**, 1 failed / 129 passed | `test_every_payload_field_of_each_of_the_four_events_...` | `assert GLN(value='5412345000006') == GLN(value='4012345000009')` |
| P2 `OrderCompleted.total_amount=_initial_amount` | **killed** | same | `At index 4 diff: Money(amount=8465, currency='EUR') != Money(amount=8115, currency='EUR')` |
| P3 `OrderPlaced.order_date=occurred_at` | **killed** | same | `... = OrderPlaced(...).order_date` (9:00 vs 8:00) |
| P4 `OrderPlacedLine` price ↔ discount | **killed** | same | `At index 0 diff: ('SKU-A', 'Alpha pallet', Quantity(value=3), Money(amount=250...), Money(amount=1999...)) != (...)` |
| R1 `rehydrate` `notes=None` | **killed** | `test_rehydrate_restores_every_field_of_the_snapshot_with_a_non_none_note` | `assert None == 'leave at dock 4'` / `where None = <...Order...>.notes` |
| R2 `rehydrate` retailer ↔ company | **killed** | same | `assert 'CMP-01' == 'RET-01'` |
| R3 `rehydrate` `created_at=updated_at` | **killed** | same | `where ... 9:05 = <...Order...>.created_at` |
| R4 `rehydrate` `supplier_gln=buyer_gln` | **killed** | same | `assert GLN(value='4012345000009') == GLN(value='5412345000006')` |
| PL1 `place` GLNs swapped | **killed** | `test_place_keeps_both_glns_the_order_date_and_the_two_creation_instants_it_was_given` | `assert GLN(value='5412345000006') == GLN(value='4012345000009')` |
| PL2 `place` `order_date=occurred_at` | **killed** | same | `where ... 9:07 = <...Order...>.order_date` |

Every restore printed `identical`, and every re-run after clearing the caches was `130 passed`.

**Do the failures name the field?** Six of the ten do so in the `E` line itself (`.order_date`, `.notes`, `.created_at`, or the two codes). P1, R4 and PL1 compare one attribute per `assert` statement, so the failing statement (pytest's `>` line) names the field; the GLN values also say which side is wrong. P2 and P4 compare a tuple and report an index into a literal tuple written beside it in the test. That is unambiguous, but positional. I accept it as naming the field. It is not a defect.

### R2.3 Fixtures pairwise distinct for every asserted field

**Events (4.17):**
- `buyer_gln` `4012345000009` ≠ `supplier_gln` `5412345000006`.
- `retailer_code` `RET-01` ≠ `company_code` `CMP-01`.
- `order_date` `at(-60)` ≠ `occurred_at` `at(0)`.
- On each line: price ≠ discount (1999/250, 1234/100). Across lines: quantities 3 ≠ 2, `description` `"Alpha pallet"` ≠ `None`, `product_code` `SKU-A` ≠ `SKU-B`.
- `initial_amount` 8465 ≠ `initial_discount` 350 ≠ `total_amount` 8115.
- The cancelled order is `ORD-000010`, not the first order's `ORD-000009`, so a cross-order mix-up is visible.
- `currency` has only EUR, but no sibling currency field exists to swap with.

**`rehydrate` (5.12):**
- `notes="leave at dock 4"` (non-None, as required).
- `order_date` `at(-60)`, `created_at` `at(0)` and `updated_at` `at(5)` are pairwise distinct.
- GLNs are distinct, and `buyer_gln != supplier_gln` is asserted explicitly.
- Lines are compared by id, so a field swapped across lines is visible.

**`place` (3.22):** `created_at` and `updated_at` are both `at(7)`. That is **by design**: both come from `occurred_at` (`order.py:260-261`), so no distinct value exists. Both are distinct from `order_date` `at(-60)`. Accepted.

### R2.4 Fresh unrequested probes on field-mapping paths not probed before

| Probe | Mutation | Result |
|---|---|---|
| U4 | `rehydrate` builds each `OrderLine` with `description=None` | **killed** by the 5.12 test: `At index 1 diff: None != 'Alpha pallet'` |
| U1 | `add_line` builds the new line with `description=None` | **survived**: 130 passed |
| U2 | `add_line` builds the new line with `product_code=str(description)` | **survived**: 130 passed |
| U3 | `change_line`'s replacement takes `description=None` | **survived**: 130 passed |

**F8. The non-money fields of the line mutators (`add_line`, `change_line`) are not asserted.** Disposition: **ACCEPTED, NOT FIXED**, on this evidence:
1. The money fields of those mutators are guarded: M1 (round 1) and the R6 recompute test kill a wrong quantity, price or discount.
2. Neither method emits a fact (`order.py:494-559`: no `_raise_event`). A corrupted `product_code` or `description` there reaches no wire payload.
3. `design.md` §6.1 records that **no live caller exists, or is planned anywhere in the trilogy**, for the three line mutators (ORDCHG is out of scope by O4). In round 1, `rehydrate`, `place` and the events were different: each has a real caller in features 14 and 15.

**Re-open if** any production module calls `add_line` or `change_line`, or an amendment flow (ORDCHG) enters scope. Fixing it then takes two asserts in `test_r6_order_recomputes_...`, armed with U1–U3. *Self-criticism, recorded for the benchmark:* my round-1 §7 asked for event, `rehydrate` and `place` coverage, but not the line mutators, so round 1's probe set was itself a sample of the field-mapping population. The population is now enumerated: every constructor call of `OrderLine` (`order.py:233` place, `:326` rehydrate, `:507` add_line, `:547` change_line) and of each event class (`:264`, `:377`, `:413`, `:455`). Each has been probed at least once.

### R2.5 The leader's fixes

**F4: applied and holds.** `pyproject.toml` `[tool.ruff]` has `extend-exclude = ["specs"]` with a reason comment. I re-armed it myself with a throwaway `specs/_review_probe.md` containing `x=[1,2 ,3]` in a Python block:
- the repo-wide `uv run ruff format --check` (exactly `quality.sh` step 1, line 17) reported `295 files already formatted`, so the probe was not seen;
- the same file with `--isolated` (no project config) reported `1 file would be reformatted`, so the probe was valid;
- I deleted the probe (`ls specs/` gives `orders_aggregate shared`) and the re-run was clean.

**F5: applied.** Task 3.12's arm now reads *"hold the aggregate's lines as the internal `list` (`placed_lines = order_lines`)"*. Task 4.16 now reads *"other than `order.saga_failed.v1` and Fulfillment's `order.despatched.v1`"*. Each carries an *"Amended after review round 1, F5"* note.

**F7: applied.** The acceptance item is appended to feature **15 `orders_acceptance`** (status `pending`) in `feature_list.json`. It names the search, the hit-by-hit classification and the arm. That is the right owner: the mapper is the feature-15 code it guards.

### R2.6 CHECKPOINTS delta from round 1

- C4 "tests complete against CLAUDE.md line 128" is now **[x]**. All four emission branches (`place`, `confirm`, `complete`, `cancel`) have a test that fails on deletion (implementer arms 4.11a–d) and on field corruption (P1–P4, plus the implementer's CONF and CANC arms).
- C4 `quality.sh` is still implementer-reported (exit 0, 1436 passed, stack up). The count reconciles; the leader times it at wrap-up.
- C5: history entry with effort record **[x]** (appended now).
- C6: the spec commit preceding the implementation commit is still for the wrap-up. Both are uncommitted, `specs/orders_aggregate/` is untracked, and the order is the leader's to keep.

All other boxes are unchanged from round 1.

### Verdict

**APPROVED.** D1–D3 are closed: the ten survivors are killed, each failure locates its field, and the fixtures are pairwise distinct where distinctness is possible. F4, F5 and F7 are applied and checked. F6, F7 and F8 are dispositioned with re-open triggers. Feature 13 is set to `done`, and the history entry is appended.
