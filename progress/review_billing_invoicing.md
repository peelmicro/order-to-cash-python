# Review — feature 21 `billing_invoicing` (phase 10, `sdd: true`, full group, round 1)

Reviewer: Opus, 2026-10-09 21:07 → 2026-10-10 05:42 (≈30 min active; the machine was in S3 suspend from ≈21:20 to 05:27:13, `journalctl`: "System returned from sleep operation 'suspend'"). Brief: `progress/brief_review_billing_invoicing.md`; premise check `progress/premise_review_billing_invoicing.md` (17 VERIFIED, 0 FALSE). Arming harness, backups (`sha256`), raw outputs: `.arm/review21/` (`arm.py`, `arms_def.py`, `arms_def2.py`, `arms.log`, `out/<id>.out`, `pre_sha.txt`).

## Verdict: **APPROVED** (round 1)

0 blocking defects. The code is right on every path I attacked: **54 reviewer arms, 52 red on a named assertion, 2 survivors, both explained** (Q2d is killed by feature 19's own guards once widened, Q3b-int is the residue survivor the spec's placement lesson predicts and the unit entry guard kills). Five non-blocking items are **FIX NOW (light, before feature 21's commit)** and one routing item is for the leader (§6).

**What I ran instead of re-reading** (scope discipline): `./quality.sh` once, stack down (only `otcpy-n8n`): **exit 0**, 21:08:41 → 21:14:55 (374 s), **3415 passed** in 354.54 s (matches the implementer's 3415 / +181 over A2's 3234), coverage 97.46 % overall, 98 % domain, import-linter **11 kept, 0 broken**, ruff / mypy clean, web gates green (`.arm/review21/quality.log`). I did not re-run the implementer's 158-row sweep; I ran my own 54 arms (below), then the 12 touched test files green (**526 passed**), then `sha256sum -c .arm/review21/pre_sha.txt` (17 of 17 files OK; their hashes equal the implementer's backup prefixes, so the tree I armed is the tree they armed). `./init.sh` exit 0, §5d shared spec byte-identical to #8 and #7 (6 files; `test-matrix.md` exempt).

## 1. CHECKPOINTS walked

**C1** [x] harness files exist · [x] `progress/current.md`, `history.md` · [x] seven agents · [x] every agent declares a model (4 `model:`; leader, reviewer, spec_author state they inherit) · [x] `./init.sh` exit 0.
**C2** [x] no feature `in_progress` (35 done, 20 pending, 1 in_review) · [x] every status valid · [x] every `done` feature has passing tests (quality.sh) · [x] `current.md` describes this session (its "Goal" paragraph still names feature 19's spec pass: leader's file, cosmetic) · [x] no `blocked` feature.
**C3** [x] `lint-imports` 11 kept, run not eyeballed · [x] no cross-service DB access; the Fulfillment change is inside Fulfillment · [x] shared runtime only the three packages (no `packages/` change) · [x] no `domain` imports `otc_cqrs` (contract kept) · [x] `dependencies = []` unchanged · [x] no `float` / `Decimal` / `/` in domain money (AST money guard green; my grep over `domain/invoice*.py` with a sentinel: four hits, all docstring section numbers) · [x] `billing.invoice.issue` / `.list` are NATS RPC rows (`saga.md` §2 line 49; asyncapi channels), `invoice.issued.v1` a Kafka fact through the outbox; Billing consumes nothing (BI1) · [x] no stray debug / TODO in the new files (grep, exit 1).
**C4** [x] `quality.sh` passes · [x] domain tests pure (`test_domain_tests_are_pure.py` green) · [x] integration on testcontainers with the developer stack down · [x] coverage 97.46 % / 98 % · [x] no Jest / Karma / Jasmine (`apps/web/package.json`: 0 hits).
**C5** [x] no suspicious untracked files outside `services/`, `specs/`, `progress/`, `tests/` · [x] history entry with effort record (appended by this review) · [x] `feature_list.json` (21 → `done`, this review, one line) · [ ] human told what was done and how to test — the leader's, at hand-over · [x] nothing committed (HEAD still `03b7725`).
**C6** [x] `specs/billing_invoicing/` has all three files · [x] EARS with ids · [x] 65 of 65 boxes ticked, nine reworded on the box (ruled in §5) · [x] `R45`, `R46` recorded in `test-matrix.md` with real names (re-derived: 63 rows, 41 DONE, 1 SCOPED, 21 other — equals the summary table) · [ ] spec commit precedes implementation commit — not yet committed; the wrap-up must commit the spec first.
**C7** [x] `specs/shared/` byte-identical to #8 and #7 (init.sh §5d, real `cmp`) · [x] no `SA-n` needed, none silently forked · [x] `R45`, `R46` are #7's ids and the Python behaviour satisfies them (arms below) · [x] n8n untouched by this feature · n/a black-box API script (feature 31) · [x] every inherited finding accounted for (§7) · [x] effort record honest, including that this feature was **not** faster (§ history) · n/a README benchmark (wrap-up).

## 2. `R<n>` → test, verified by arming (not by name)

| Id | Test | Arm that went red on it |
|---|---|---|
| **R45** (domain) | `unit/domain/test_invoice.py::test_r45_creates_exactly_one_issued_invoice_…` | Q1b `total = amount` → `Money(...) == Money(...)` |
| **R45** (host) | `integration/test_invoice_issue.py::test_r45_issues_one_invoice_through_the_real_host_with_a_non_zero_discount_…` | Q1a, Q1c, Q2a, Q2e, Q2f, Q3c, R-F4, X2, X5 (verbatim §3) |
| **R45** (repeat, B7) | `test_bi9_a_repeat_returns_the_existing_invoice_…`, `unit/test_invoice_issue_service.py::test_a_hit_on_the_fast_path_…` | F6-repro, L22-uuid |
| **R45** (race) | `integration/test_invoice_issue_race.py::test_bi8_two_concurrent_issues_…` | Q3a-race, Q3e |
| **R45** (atomic) | `integration/test_invoice_repository.py::test_bi7_commits_…` | X3-del |
| **R46** | `unit/domain/test_invoice.py::test_r46_allows_only_the_transition_from_issued_to_paid_…` (+ `test_bi14_…`) | R46-instant: `Paid(payment.value_date)` → `AssertionError: paid_at must be the context's instant` |

`R47` – `R49` stay `TODO` (feature 22), as `requirements.md` §1 says before a reviewer has to. `R40`'s live half: Q2f (consume treated as a release) → `AssertionError: R40: an issued invoice moved the available credit — assert 229979 == 221864`.

Local ids spot-checked by my arms: BI2/BI33 (via E-family, not re-armed), BI5 (Q3b-unit), BI8 (Q3a-unit, Q3e), BI9 (F6-repro, L22-uuid), BI12/BI29 (Q4a, Q4b), BI13 (R-B8a/b/c), BI15 (X6, Q1e), BI16/BI31 (R-E2a/b, X1), BI26 (Q6e), BI34 (R-C5a/b), BI35 (Q3d), BI37 (Q5a–Q5d), BI38 (Q1a–Q1f).

## 3. The arms (verbatim first failing line; every restore `cp` + `cmp` identical + caches cleared)

**Q1 — the discount zeroed at each site, one at a time (#8 D2).** Fixtures: gross 8465 derived from the lines `3×1999 + 2×1234` by `build_issue_fixture` (`conftest.py:570-628`, which computes `amount` and `total` and refuses equal / zero / substring-contained figures); discount 350; net 8115; list fixture discount `350 + n`.

| Arm | Site | Test | Result |
|---|---|---|---|
| Q1a | `invoice_wire.decode_issue` `discount=0` | host R45 | `assert ('EUR', 8465) == ('EUR', 8115)` |
| Q1b | `Invoice.issue` `total = amount` | unit R45 | `Money(...) == Money(...)` differing amount |
| Q1c | `invoice_mapper.new_invoice_row` `discount=0` | host R45 | `assert (8465, 0, 8115) == (8465, 350, 8115)` |
| Q1d | `payloads.issued_payload` `discount=0` | `test_outbox_payloads::test_invoice_issued_…` | `a field of the invoice.issued.v1 payload is not the supplied value` |
| Q1e | `invoice_mapper.invoice_view` `discount=0` (list) | `test_invoice_list::test_bi15_…` | `assert (8465, 0, 7510) == (8465, 955, 7510)` |
| Q1f | `invoice_wire._view` `discount=0` | `unit/test_invoice_wire.py` | `assert (8465, 0, 8115) == (8465, 350, 8115)` |

**Q2 — the most plausible wrong value at the production site (feature 19's D1).**

| Arm | Substitution | Result |
|---|---|---|
| Q2a | reply `totalAmount` = gross | `assert ('EUR', 8465) == ('EUR', 8115)` |
| Q2b | fact `totalAmount` = gross | `a field of the invoice.issued.v1 payload is not the supplied value` |
| Q2c | list view `totalAmount` = gross | `assert (8465, 955, 8465) == (8465, 955, 7510)` |
| Q2e | consume row amount + 1 (written to the store) | `assert (8116, UUID(…)) == (8115, UUID(…))` |
| Q2f | consume read as a release (available-after = limit-side value) | `R40: an issued invoice moved the available credit — 229979 == 221864` |
| Q2d | `open_exposure = 0` (the hold→exposure split, not availability) | **survived** the host R45 test (it asserts `availableCredit`, which this term does not move). Widened (Q2d-wide): killed by feature 19's `test_bc6_…[held + consumed]`, `test_r40_appends_a_consume_entry_…`, `test_the_structural_and_the_amount_readings_agree_…`, `integration/test_credit_list.py::test_bc6_every_listed_line_reconciles_…` (`assert (410, 0, 410) == (410, 410, 0)`). Not a feature-21 gap: the split is `summarise`'s, guarded where it lives. |

**Q3 — consume under the lock order.** None hung; each ≤ 11 s under a 600 s process-group timeout.

| Arm | Mutation | Result |
|---|---|---|
| Q3a-unit | counter allocated before `lock_for_order` | `BI8: the issue path's calls are not lock, re-read, allocate, save, save — 'next_reference' != 'lock_for_order'` |
| Q3a-race | same, through the race | `AssertionError: the counter advanced exactly once — assert 3 == 2` (the race **does** see this inversion: see N4) |
| Q3b-unit | `consume` after the allocator | `BI5: the counter was touched for an order with no active hold — assert 1 == 0` |
| Q3b-int | same, host BI5 test | **survived, as designed**: the allocation rolls back, so the residue is unchanged (#7 N10). The unit entry guard above is the placement proof; see N4 |
| Q3c | `consume` deleted | `expected exactly one consume row, got 0` (R45 and BI35 both red) |
| Q3d | `consume` skipped for a zero total (BC38) | `test_bi35_a_zero_hold_…`: `expected exactly one consume row — 0 == 1` |
| Q3e | `with_for_update()` dropped from `lock_for_order` | `BC32: expected an invoice-issue reply (created), got {'code': 'INTERNAL_ERROR', …}` |

**I1 is a held lock, a change of kind**: the test's own asyncpg connection holds `FOR UPDATE` on the line and the counter rows (`conftest.py:158-164`), waits until two backends are seen `wait_event_type = 'Lock'` in `pg_stat_activity` (`:166-191`, 20 ms pacing, 15 s bound naming the claim), then commits. Not a sleep.

**Q4 — `INV-` allocation.** Q4a (seed skipped) → `test_concurrent_allocations_…`: `sqlalchemy.exc.NoResultFound` (a named test, though the message is the driver's: accepted, it is the prescribed outcome of D6a). Q4b (`from_sequence(allocated + 1)`) → `test_seeding_over_a_non_empty_invoices_table_…`: `assert 'INV-000044' == 'INV-000043'`. `test_invoice_number_allocator.py` (6) and `test_billing_counter_seed.py` (5, backlog 211) green in the post-arm run.

**Q5 — G1 / BI37, each site separately.** Q5a (invoice clamp) and Q5b (`except OverflowError` → `ZeroDivisionError`) → `test_bi37_a_page_past_int64_and_an_age_before_year_one_…`: `BC32: expected an invoice list reply (a page), got {'code': 'INTERNAL_ERROR', …}`. Q5c → `test_credit_list.py::test_bi37_…`: `BC32: expected a list reply (a page), got {'code': 'INTERNAL_ERROR'…}`. Q5d → `fulfillment/…/test_stock_list.py::test_bi37_…`: `BI37: expected an empty page, got {'code': 'INTERNAL_ERROR'…}`. **`stock_reads.py`**: `git diff` shows the clamp line plus its `MAX_OFFSET` constant (2 lines, +2 −1 … `4 +-`), the same shape as the two Billing sites — this is "G1's offset clamp only" as `tasks.md` allows; `design.md` §18's "one line" is loose wording, accepted.

**Q6 — every `RpcError` code is a saga decision: a sibling code at each of the 8 mapping sites.** Every arm was killed by `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details[<row>]`, which names the row. `tests/architecture/test_billing_rpc_error_retryability.py` named the break at **one** site only (Q6e, `PRECONDITION_FAILED` → `DOMAIN_ERROR`: `test_bi26_…`). In particular **Q6f (every `DomainError`, including `InvoiceTotalOverflowError`, → `INTERNAL_ERROR`, i.e. terminal → transient: the saga would retry an overflow) is invisible to the retryability guard**; only the exact-code unit table sees it (13 rows red). See N3.

**Q8 — five-plus `[ARM]` tasks at random, the exact prescribed mutation.** Sample: `random.seed(20261009); random.sample(pool, 6)` over the 54 `[ARM]` tasks minus K2–K4 (live stack), A1, L2, L3 (searches / record) = 48 → **B8, C1, C5, E2, F4, G6**.

| Task | Prescribed mutation | Mine | Implementer's (`.arm/bc21/arms.md`) |
|---|---|---|---|
| B8a | swap `aggregate_id` / `correlation_id` | `aggregate_id must be the invoice's own id` | same |
| B8b | fact lines in canonical order | `InvoiceFactLine(product_code='PRD-AA'…) != …'PRD-ZZ'…` | same |
| B8c | `retailer_code` from `company_code` | `assert 'SUPPLY-CO' == 'RETAIL-77'` | same |
| C5a / C5b | `UniqueId.new` to `Invoice.issue` / `consume` | `the invoice's id is not from the scope's id port` / `the consume entry's id is not from the scope's id port` | same |
| C5c | return before the saves | `both saves must have happened before the commit` | same |
| E2a / E2b | sibling subject; drop the list route | `channel invoiceIssue: the subject Billing answers is not the spec's address` / set mismatch `'billing.invoice.list'` | same |
| F4 | delete `credits.save(credit)` | `expected exactly one consume row, got 0` | same |
| G6 | remove each sibling clamp | Q5c, Q5d above | same |
| C1 | (absence claim; no code arm) | `diff` of the three files against `.arm/bc21/c1/` copies: only imports, the two refusing properties, the refusing `NoInvoiceReads` class and the keyword; **no assertion changed** | same hunks as the impl report §2.3 |

**Unplanned call-site mutations (my own).**

| Id | Seam | Mutation | Result |
|---|---|---|---|
| X1 | responder → handler | `INVOICE_LIST_SUBJECT: _list` (the credit list route) | `assert 0 == 5` on `PageInfo(total=0)` in `test_bi15_…` (E2's set-equality guard is blind to a value swap; the host test is not) |
| X2 | handler → transaction | `InvoiceContext(causation_id=command.correlation_id)` | host R45: causation `'0d113adf…' == '48ee626f…'` |
| X3 | domain fact → outbox row (corrupt) | fact lines `reversed(...)` | `a field of the invoice.issued.v1 payload is not the supplied value` |
| X3-del | domain fact → outbox row (delete) | `outbox.write(session, [])` | `expected a whole-table outbox delta of exactly 1 — (0 - 0) == 1` |
| X4 | mapper ↔ snapshot | snapshot `invoice_date = row.created_at` | `test_a_row_maps_to_a_snapshot_field_by_field_…`: `10:15:37.123 == 10:15:30.123` |
| X5 | consume → credit store | consume written with type `hold` | `expected exactly one consume row, got 0` |
| X6 | handler → reads | `status=None` (filter dropped at the handler) | `test_invoice_list_handler` + `test_bi15_…` red |
| X7 | headers → command | correlation / request ids swapped in `decode_issue` | `test_bi2_billing_invoice_issue_dispatches_a_command_carrying_the_header_ids`: `'…00ca' == '…00c0'` |
| L22 | ledger L22 (most likely assumed: asyncpg's `UUID` subclass) | `_unique_id` returns the driver's value | `test_bi9_…`: `{'code': 'DOMAIN_ERROR', 'message': "UUID('…') is not a valid, non-nil UUID", 'details': {'code': 'unique_id.invalid'}}` — the ledger row's property is real and its named guard (F6/BI9) executes it |
| F6-repro | drop fast path **and** re-read | `BC32: expected an invoice-issue reply (created), got {'code': 'PRECONDITION_FAILED', … 'credit.no_active_hold'}` — confirms the implementer's finding, not the design's `INTERNAL_ERROR` |

Both mutation families on the live fact: deletion (X3-del; the implementer's F11: 12 named tests) **and** payload corruption on the wire (Q1d, Q2b, X3, X2, R-B8a–c).

## 4. Rulings on the brief's questions

1. **Discount**: every site fails a named test (Q1a–f); fixtures make gross ≠ discount ≠ net ≠ any line total (8465 / 350 / 8115 vs 5997, 2468), and the gross is **derived from the lines** by the fixture builder and by the domain (no `amount` on the wire). #8 D2 avoided.
2. **Accidental relations**: none found (Q2a–c, e, f red). Q2d is a different term (not availability) and is guarded by feature 19.
3. **Lock order**: line → (plain re-read) → consume → counter, verified by code (`invoice_issue.py:85-96`) and Q3a/b/c/e; BC38's zero hold is consumed (Q3d). **The F6 / I1 prose question: the code is right; the design text is wrong** in 2 of 3 I1 outcomes and in F6 (F6-repro reproduces `PRECONDITION_FAILED`; the implementer's I1 records give `PRECONDITION_FAILED`, `INTERNAL_ERROR` 23505, `UNAVAILABLE` 40001 — the `REPEATABLE READ` loser fails on the **counter** row the winner updated, which §6.2's "the line row is locked, not updated, so no 40001" did not consider). `design.md` must be corrected (N1).
4. **`INV-`**: Q4a, Q4b red; seed and allocator suites green.
5. **G1 / BI37**: three sites, three named tests, each red alone; the Fulfillment change is the clamp (constant + line) only.
6. **RpcError codes**: all 8 sites killed by the unit table; the architecture guard names only Q6e. N3 closes the terminal-direction gap.
7. **Deviation 1 (`@final` → `__init_subclass__`)**. Probe (`.arm/review21/b2probe/probe_subclass.py`: `class Voided(Issued): pass`): `mypy --strict` → `Success: no issues found`; importing it → `TypeError: Issued is final: InvoiceState is a closed pair`. So the **static** refusal of a subclass declaration is lost, the **runtime** refusal is gained (`typing.final` gives none: it only sets `__final__`), and the closure the design actually needs — a `match` over `Issued | Paid` ending in `assert_never` — does not depend on `final` (arm B2a: three `assert_never` sites fail under a third alias member). In addition, the retryability guard's `pkgutil.walk_packages` imports every `otc_billing` module, so a subclass anywhere in the service fails the suite at import. **Recommendation for the maintainer: accept as built; do not widen the census.** If the maintainer wants the static half too, add `final` to `ALLOWED_DECORATORS` with the reason "typing.final: closes a sum type for mypy; registers nothing", and keep the runtime refusal (they are complementary, not alternatives). Either way the design's text must follow the code (N2).
8. **#8's lessons**: §3, Q8 and X-rows, verbatim.
9. **Deviations 2 – 9 and the reworded boxes**: §5.

## 5. Deviations and reworded boxes — rulings

| Item | Ruling | Reason |
|---|---|---|
| Dev 1 / B2 | **accept** | §4.7 |
| Dev 2 `PaymentSource` in `invoice_events.py` | accept | the design's placement is an import cycle; re-exported from `invoice.py` |
| Dev 3 / C1 not "keyword only" | accept | `mypy --strict` checks the fakes against the extended Protocol; diffs verified, no assertion changed, the additions refuse (they make a stray call fail) |
| Dev 4 keyword `invoice_reference` | accept | BI10 requires the error to name the invoice |
| Dev 5 `rehydrate` refuses more | accept | stronger than §5.4, covered by `test_bi10_…` |
| Dev 6 extra helpers; one containment check | accept | I re-derived the builder's logic: with no flag a zero figure always equals another figure, so the containment check subsumes the removed branches (they were equivalent mutants) |
| Dev 7 / I1 holds the counter too | accept | needed for the no-line-lock arm to reach its assertion; side-effect: the race now sees a counter-first inversion (Q3a-race), so its header overclaims (N4) |
| Dev 8 F5 armed an outbox copy | accept | restored by `cp`/`cmp`; `test_outbox_copy_parity.py` green in my quality run |
| Dev 9 `rehydrate` uncalled | accept | feature 22's seam, as #7/#8 shipped `mark_paid` |
| A1 (population 3 → 5) | accept | expected growth, named |
| C6 (`git diff --stat services/orders` not empty) | accept | feature 20's two files; `command_payloads.py` sha `a3b14623…` equals the backup |
| D7 (docstrings reworded to meet the expected sets) | accept, with N5 | the hits were prose; but the D1 sentence it reworded is still incomplete |
| F1 (extended helpers) | accept | |
| F6, I1 (outcomes differ from the text) | accept the boxes; **the design must change** (N1) | |
| K2 (no Billing log line) | accept | request logging is feature 27; the database evidence is stronger |

Live walkthrough (K1–K5) reviewed as a record: figures reconcile (counter absent → 7 → 8; `CR-000001` available 344 459 before and after `ORD-000008`, 285 993 = 344 459 − 58 466 after `ORD-000010`'s new hold; `ORD-000010` 59 243 / 777 / 58 466 on the row and the fact; `causation_id` = the `invoice.issue` row's id `d44f20f5…`; `correlation_id` = `orders.id` `b7117514…`; the register extended).

## 6. Findings (none blocking) — FIX NOW, light, one batch before feature 21's commit

- **N1 (doc; `specs/billing_invoicing/design.md` §6.2 bullet "Why the line is locked first", §13.3, and `tasks.md` F6's parenthetical).** They state that all three race arms and the F6 arm end in `INTERNAL_ERROR` from the unique constraint, and that `REPEATABLE READ` cannot raise 40001. Observed: F6 → `PRECONDITION_FAILED` (consume precedes the insert); I1 → `PRECONDITION_FAILED` / `INTERNAL_ERROR` (23505) / `UNAVAILABLE` (40001 on the counter row the winner updated). Every outcome is safe (terminal on a consumed hold, or transient then the fast path), so the code stands; the spec must say what the code does. Leader's doc edit; no re-arm needed (F6-repro and the implementer's I1 rows are the evidence).
- **N2 (doc; `design.md` §5.2, ledger L41, §16.2; `requirements.md` BI23 #9 note).** Still say "`@final`". Replace with the runtime refusal (and the maintainer's decision on §4.7, if any).
- **N3 (test, light; `tests/architecture/test_billing_rpc_error_retryability.py`) — a ported guard partly dropped.** BI25 says the overflow maps to a code "the saga dispatcher classifies as terminal", and BI26's rule is to read that classification from Orders' own set. Today only `PRECONDITION_FAILED` is read from `TERMINAL_RPC_ERROR_CODES`. #8 read it for BI25 too: `../order-to-cash-dotnet/tests/Billing.UnitTests/BillingErrorMapperTests.cs:173-184` (`BI25_MapsInvoiceTotalOverflowErrorToDomainError`: `Assert.Contains(reply.Code, terminalSet)`) and `:55-60` (`CreditLedgerOverflowError`). `design.md` §4 classifies `BillingErrorMapperTests` as **Ported**; that assertion was not. The exact-code unit table still pins `DOMAIN_ERROR` (Q6f is red there), so behaviour is guarded; the lost half is the cross-service premise. Add an assertion that every `DOMAIN_ERRORS` input's mapped code is in `TERMINAL_RPC_ERROR_CODES` (it holds today: NOT_FOUND, VALIDATION_FAILED, PRECONDITION_FAILED, DOMAIN_ERROR). **Arm:** Q6f (`case DomainError()` → `Code.internal_error`) must then fail in the architecture file, naming the class.
- **N4 (test comments, nit).** (a) `integration/test_invoice_issue.py:389` `"the counter was touched"` is a residue assertion that cannot see a rolled-back allocation (Q3b-int survives); say so and name `unit/test_invoice_issue_service.py::test_bi5_…` as the placement guard. (b) `test_invoice_issue_race.py`'s header says the race "passes under an inversion"; with the counter held it fails a counter-first inversion on `the counter advanced exactly once` (Q3a-race). Say "cannot see an inversion in general; C4 is the guard".
- **N5 (docstring, nit; `credit_repository.py:19-21`).** "No `update(` … outside `invoice_number_allocator.py`'s counter statements" omits the outbox relay's `update(Outbox)` stamp (`outbox/relay.py:162`, D7's own expected set). D1's prescribed wording was incomplete.
- **Observation, no action:** the host R45 test asserts `availableCredit` only; the hold → exposure split (Q2d) is guarded by feature 19's `summarise` tests and `test_bc6_every_listed_line_reconciles_…`.

**Routing item (leader files it; I do not write `feature_list.json` beyond 21's status):**

- **R1.** `requirements.md` BI8's note "**Binding on feature 22**" (resolve the invoice unlocked, lock the `credits` row, re-read the invoice, then update it) and `design.md` §15.1's lock order exist only in feature 21's spec. Feature 22 is `sdd: false` and its `acceptance` list does not carry them (it carries #8 id 57 only). Add one acceptance item to **feature 22**: *"lock order credits row → invoices row (feature 21 BI8 binding, `specs/billing_invoicing/design.md` §15.1); the two outbox rows in one transaction, `payment.received.v1` first"*. Not rooted in `specs/shared/`; no `SA-n`.

Nothing is rooted in `specs/shared/`; no `SA-6`, no backlog entry.

## 7. Inherited findings (`design.md` §17), with my evidence

**Avoided:** #8 id 45 and 47 (Q4a/b; seed suite green) · id 49 (R-C5a/b; B6) · ids 53/55 (`Decode` asserts the discriminating field first: Q3e, Q5a–c fail on `BC32: expected …`) · id 54 (Q3e; the re-read is plain after the line lock) · id 57 seam (R46-instant; B9f) · id 65 (Q1f, Q2c) · id 72 / #8 D3 (matrix re-derived: 41 / 1 / 21) · id 85 (suite green with the stack down) · id 102 (BI36, implementer's E6d; not re-armed by me) · #8 **D1** (implementer's B9a–g, F9d–i; my payload corruptions on the issued fact) · #8 **D2** (Q1a–f) · #8 R2-N1 (`cp` + `cmp` + `sha256`) · #8 R2-N3 (G5 rooted at the decode) · #8 N6 (K5 register) · #7 N1 (65/65) · #7 N2 / N10 (Q3b-unit red on the entry) · #7 N3 (BI5 re-reads the ledger rows) · #7 N4 / N5 (Q3a-unit) · #7 N7 (X3-del, F10) · #7 N8 (H3).
**Recurred (this run's own):** (a) a design prescribing a mechanism a guard forbids (`@final` vs the decorator census) — caught by `quality.sh`, a spec defect; (b) a spec predicting failure outcomes it had not measured (F6 / I1 prose, defeat-list row 9's stale-premise class) — N1; (c) a residue assertion worded as an entry claim (#7 N10's class, in a message only) — N4a; (d) a guard classified **Ported** whose terminal-set assertion was not ported (`design.md` §4 row `BillingErrorMapperTests`; #8 `BillingErrorMapperTests.cs:173-184`) — N3, the "port the guards too" class.

#8's history is internally inconsistent on its blocking count ("two survived and became blocking defects" vs line 1366 "3/3 blocking defects closed"); I rely on **3** (D1, D2, D3: line 1366 and its findings table).
