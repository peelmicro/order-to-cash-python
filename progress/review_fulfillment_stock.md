# Review — feature 17 `fulfillment_stock` (phase 9, full group, round 1)

**Verdict: REJECTED** (round 1 of the two allowed without asking the maintainer). Feature 17 is set back to `in_progress` (`feature_list.json` line 327, that line only).

The code is correct on every path I drove, and the implementer's arming record holds up where I re-ran it. The rejection is about **guards that do not see the clause they are named for**: three of my own mutations survived the whole Fulfillment and architecture suites (809 tests each). One of them is #7's rejection shape exactly. It is an unplanned sub-clause mutation of a stated requirement (FS25's *"before reading the order's reservations"*), on the very method (`lock_order_items`, the SA-4 lock) that feature 18 is told to reuse. All fixes are test-only, plus three record and spec-text corrections and one routing action for the leader.

Reviewer: Opus, one session, 2026-10-08 ≈05:20 – 07:00 UTC (**≈1 h 40 min** wall-clock, including a full `quality.sh` and 34 arm runs).

## 0. What I ran (verification, not assumption)

| Claim | Command / instrument | Result |
|---|---|---|
| `quality.sh` exit 0 (a full-suite claim, so re-run in full, developer stack down; `docker ps` = `otcpy-n8n` only) | `./quality.sh` → `.arm/review17/quality.log` | **exit 0, 300 s, 2686 passed**; coverage overall 98 %, domain 99 % (`TOTAL … 99%` of the domain report); `quality.sh: all gates passed`. Matches the implementer's 2686 / 309–315 s |
| `lint-imports` 11 contracts kept | step 4 of the same run | `Contracts: 11 kept, 0 broken`; `otc_fulfillment` in domain-purity, fact-producer-confinement, `otc_fulfillment: presentation > infrastructure > application > domain`, service independence |
| `init.sh` coherent; shared spec byte-identical to #8 and #7 | `./init.sh` → `.arm/review17/init.out` | exit 0; 5d: byte-identical to both checkouts across 6 files (test-matrix exempt) |
| Every test name cited in `test-matrix.md` (diff) and `requirements.md` §3 exists | loop over every `` `test_…` `` token, `grep -rl "def <name>\b" services tests` | 0 missing |
| Arms | `.arm/review17/rarm.py` (backup into `.arm/review17/bak/` with sha256, one mutation set, named tests in their own process group killed whole on timeout, restore by `cp`, `cmp`, `__pycache__` + `.mypy_cache` cleared, re-run green); records in `.arm/review17/log.md`, outputs in `.arm/review17/logs/` | 34 arm runs: **30 RED, 4 survived** (§4). Every backup `cmp`-identical after restore (re-checked over all of `.arm/review17/bak/` at the end: 0 differences); every re-run green |

I did **not** re-run the implementer's 119 arm runs; I re-ran the ones the brief names (Q3, Q5, Q6) and added my own.

## 1. Questions of the brief — rulings

**Q1 — Deviation 1 (the parity guard compares against `ruff format` of the mapped canonical): ACCEPTED.** The new instrument's premises, listed and probed:
1. *The formatter is applied to the expected side only; the copy is compared un-normalised, byte for byte* (`tests/architecture/test_outbox_copy_parity.py:98-134`). Armed twice with formatter-only differences in the **copy**: `Q1a` (a string in the relay copy re-quoted with single quotes) → RED, `relay.py: differs from the canonical after the docstring: … "+ 'outbox relay cycle was a deadlock victim; retrying',"`; `Q1b` (the reflowed call in `kafka_publisher.py` re-joined onto one line, i.e. the canonical's own layout) → RED, `kafka_publisher.py: differs … '-  FULFILLMENT_FACTS_TOPIC,', '- value=fact.value,'`. So nothing the formatter normalises is forgiven in the copy.
2. *Formatting is deterministic and semantics-preserving*: `ruff format` is AST-preserving by contract (quote style, trailing commas, parenthesisation, reflow); the run uses the venv's locked ruff (`sys.executable -m ruff`) and the root `pyproject.toml` (`--config`). A difference the formatter erases can only exist on the expected side, which is the mapped canonical; it cannot hide a behavioural difference because the copy must equal the formatter's output exactly.
3. *The premise of step 2 is still real*: `test_the_reflow_the_longer_topic_name_forces_is_real_and_is_what_the_copy_holds` fails if the reflow ever becomes unnecessary. Sentinels for defeat rows 4–6 exist and pass.

**Q2 — Unarmed claims: both ACCEPTED, as argued.**
- C6's *"`published_at` set only after the broker acknowledgement"*: armed `Q2` — the relay **copy** stamps after a failed publish (`raise _CycleAborted(...)` → `pass`). Result: C3's parity test RED (`relay.py: … '+ pass  # rolls back'`), **C6 GREEN** (`1 failed, 1 passed`). So C6 alone does not see the ordering, exactly as the report says; the property is bound to the copy by C3 and proven on the canonical by `services/orders/tests/integration/test_outbox_relay.py:85` (`test_r14_stamps_a_record_only_after_the_broker_acknowledgement…`) and `:163` (`test_oi8_…`). An edit to the copy cannot survive C3; an identical edit to both cannot survive Orders' test.
- H10a: a genuine equivalent mutant at integration level (the raise rolls the whole transaction back; nothing observable differs). The ordering claim is a unit-level claim and E5 holds it. Accepted.

**Q3 — Concurrency claims: the reserve side is constructed as a change of kind and every arm fails, none hangs. The release side has a hole (D1).** Re-run arms (each against its one named test):
- `Q3-I3` lock in request order → RED: `no transaction was a deadlock victim: ['stock transaction was a deadlock victim (SQLSTATE 40P01); re-running it from the start']`.
- `Q3-I1` drop `with_for_update()` → RED: `exactly one wins the last units: … assert ['accepted', 'accepted'] == ['accepted', 'rejected']`.
- `Q3-D5a` swap steps 1 and 2 of §6.2 in `lock_for_reserve` → RED: `the reservation committed while the lock waited is seen  assert [] == [UUID('d42b01…')]`.
- `Q3-I4` remove the re-run (`if state == DEADLOCK_DETECTED and attempt < DEADLOCK_ATTEMPTS:` → `if False:`) → RED: `assert 0 == 1  where 0 = len([])` (the WARNING count).
- `Q3-I5` drop the stock-row `FOR UPDATE` used by `lock_order_items` → RED, but only as `asyncio.exceptions.CancelledError / TimeoutError` from `conftest.py` `wait_for_lock_waiters` (23.8 s): the failure does not name the claim (D6).
- FS18: `pool_size = bound + 1`, `max_overflow = 0` asserted by G4 (`engine.pool.size() == 8`, recorded kwargs `(8, 0)`); H9 constructed on a held lock. Pacing of FS23 is a recorded-sleep change of kind (D4d). Not re-armed by me beyond the above.
- **Not guarded: the order of the two reads in `lock_order_items`** — see D1. My mutation `R1` survives everything.

**Q4 — Every `RpcError` code is a saga decision: CONFIRMED.** A sibling code substituted at each of the seven sites of `presentation/stock_rpc_errors.py:268-286` (`Q4a`–`Q4g`) is RED every time, each naming its row: e.g. `Q4b` `AssertionError: no carrier  assert PRECONDITION_FAILED is NOT_FOUND`; `Q4f` `store unavailable … INTERNAL_ERROR is UNAVAILABLE` and `concurrent reservation change …`; `Q4d` (`CONFLICT` for a consumed reservation) is caught three times, including `test_fs21_no_input_produces_conflict` (which imports `TERMINAL_RPC_ERROR_CODES` from `services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:65-75`, never retyped). Terminal↔terminal and transient↔transient substitutions are caught by the unit table (`services/fulfillment/tests/unit/test_stock_rpc_errors.py`), not by the retryability test, which is correct division of labour.

**Q5 — #8 ids 49, 50, 95: the domain guards hold.** `Q5-B7a…d` (one site each of `domain/order_stock_reservation.py`) RED at their own assertions: *a reservation id was not the supplied one*; *the rejected fact's event id …*; *the reserved fact's event id …*; *the released fact's event id …*. `Q5-F7` (`gather` without `return_exceptions`) RED: *one request finishing (badly) must not end the drain early*. `Q5-F8` (flush deleted) RED: `assert ('subscribe',…) == ('flush',)`. **But the id source's seam into the domain is unguarded** (D2: `Q7-M1` survived).

**Q6 — Feature 43's carried item: the guard holds; the implementer's arm record mis-describes its F-j half.** I built a genuine F-j + F-g pipeline on this root (`Q6-G8-Fj-plus-Fg`): the three command handlers self-register through an `__init_subclass__` hook into a `HANDLERS` dict in `application/handlers.py`, and `register_handlers` drains it through a helper `_one(...)`. RED by the WIRE clause: `WIRE: 3 registrations share one statement (composition.py:112): ['…ReserveStockCommand', …ReleaseStockCommand', …ReplenishStockCommand']`. The implementer's own `G8` arm (`.arm/impl17/arm_g.py:8`) put the `__init_subclass__` hook on `ReserveStockCommand`, which nothing subclasses, and drained a literal tuple, so its F-j half was inert; it failed by F-g alone (D7). Zero/two handlers failing the boot: `test_a_command_or_query_with_no_registered_handler_fails_the_boot_before_connecting` and `test_a_command_with_two_registered_handlers_fails_the_boot` exist and ran green in the full run.

**Q7 — Own mutations** (each run against `services/fulfillment` + `tests/architecture`, 809 tests): see §4. Eleven sites across responder → handler, handler → transaction, domain fact → outbox row, mapper ↔ snapshot, settings → adapter (#8 id 56), plus `R1`. Three non-equivalent survivors (R1, M1, M9), one equivalent-in-practice survivor (M5).

**Q8 — The `[ARM]` population: 52, reconciled.** Literal list from `tasks.md` (task lines carrying `**[ARM]**`): B2 B4 B6 B7 B8 B9 C3 C4 C5 C6 D4 D5 D6 D7 D8 D9 E3 E4 E5 F1 F2 F3 F4 F6 F7 F8 F9 G3 G4 G5 G6 G7 G8 H1 H2 H3 H4 H5 H6 H7 H8 H9 H10 H11 H12 I1 I2 I3 I4 I5 J1 K3 = **52**. `grep -n "\[ARM\]" tasks.md` gives 55 lines = these 52 + header line 5 + L1 (138) + L4 (141). Matching each id against the arm headings of `impl_fulfillment_stock.md` §16: every one has at least one arm record except **K3**, whose arm is the live control query recorded in §10 (accepted: no mutation on a live database). The spec_author's "54" has no basis in the file. No `[ARM]` task lacks an arm.

**Q9 — Deviations 2–10 and the stale citations.**
- 2 (`ReservationSnapshot.product_code`): accepted, needed for FS5's refs on products outside the request (D6) and for `rehydrate`'s foreign-product refusal.
- 3 (module placement), 4 (`FulfillmentRuntime.engine` / `.responder`), 7 (no module-level `app` in `presentation/app.py`; no Dockerfile/compose/script references it, `grep` over the repository outside `.arm/.venv/progress/specs`), 8 (FS17 cell → group K), 10 (`already_released` with `released: []` for R34): accepted.
- 5 (`host_environment` depends on `kafka_server`): accepted, the reason is measured (`asyncio.run` inside a running loop) and the relay-off boot points Kafka at `127.0.0.1:1`.
- 6 (`NatsServerShape` in Orders' conftest): **confirmed forced.** `pyproject.toml:106` runs pytest with `--import-mode=importlib`, under which a conftest is not importable, so the three annotations that named the moved `NatsServer` class could only become a structural `Protocol`; `KafkaServerShape` (HEAD line 279) is the precedent. The moved fixture's docstring sentence was reworded because it would be false in the root file; the body is otherwise identical (diff read). The `tasks.md` line-15 bound was written without knowing the annotation dependency; the deviation is disclosed, not silent.
- 9 (H10a equivalent): accepted (Q2).
- §2 stale citations: the substance holds (I spot-checked `nats_saga_commands.py:65-75`, #7 `stock-item.repository.ts:44-61`, #8 `EfCoreStockItemRepository.cs:51,68`, `OrderStockReservation.cs:161,181,185,234`, `EfCoreUnitOfWork.cs:40`, all as the ledger says), but the wrong line numbers are still **in the spec files** feature 18 will read (D5).

## 2. `CHECKPOINTS.md`

**C1 — harness**: [x] five root files exist · [x] `progress/current.md`, `progress/history.md` · [x] seven agents in `.claude/agents/` · [x] each declares a model or deliberate inheritance (`model:` in four; leader, reviewer, spec_author state inheritance in `description`) · [x] `./init.sh` exit 0.

**C2 — state**: [x] at most one `in_progress` (17 after this verdict; `init.sh` saw none) · [x] statuses valid · [x] every `done` feature's tests pass (full run green) · [x] `progress/current.md` is the leader's active session (not touched by me) · [x] no `blocked` feature.

**C3 — architecture**: [x] no framework in `domain` / `shared_kernel` (`lint-imports` run, 11 kept) · [x] no cross-service DB access, no service imports another (independence contract kept; `test_fulfillment_rpc_error_retryability.py` imports both services from `tests/`, outside `root_packages`, by design) · [x] no new shared runtime package (the relay guard is a copy, `composition.py:127-175`) · [x] no `domain` imports `otc_cqrs` · [x] kernel and cqrs `dependencies = []` (untouched) · [x] no `float` / `Decimal` / `/` in Fulfillment's domain arithmetic: `grep -rnE "\bfloat\b|Decimal| / " services/fulfillment/src/otc_fulfillment/domain` → 4 hits, all in docstring prose (`R32 / R33`, `reserve / reject`, `created_at / updated_at`, `R30 / R35 / FS10`); money guard green · [x] every interaction classified: five NATS RPCs (`fulfillment.stock.*`, commands and queries), three Kafka facts via the outbox on `otc.fulfillment.facts.v1` · [x] no stray debug output or context-free TODO (`grep -rnE "print\(|TODO|FIXME|breakpoint\(|pdb"` over the new sources → exit 1, no hit).

**C4 — verification**: [x] `quality.sh` passes (run by me) · [x] domain tests pure (B9 `test_domain_tests_are_pure.py`, green) · [x] integration tests on testcontainers, developer stack down during my run · [x] coverage 99 % domain / 98 % overall · [x] no Jest/Karma/Jasmine (`grep` on `apps/web/package.json`, exit 1).

**C5 — session close**: [x] no suspicious untracked files (all untracked paths classified in impl §12; my artefacts are under the git-ignored `.arm/review17/`) · [ ] history entry with effort record — **not applicable on rejection** (written on approval) · [x] `feature_list.json` reflects the state (17 → `in_progress`) · [ ] human told what was done / how to test — leader's, at close · [x] Claude did not commit (`git status`: 76 uncommitted paths, no new commit).

**C6 — SDD**: [x] `specs/fulfillment_stock/` has all three files · [x] EARS with ids (shared `R<n>` cited, local `FS2`–`FS28`) · [x] 82/82 tasks ticked — but see D1/D2/D3: three ticked tasks claim a guard that does not see its clause · [x] every `R30`–`R35`, `R61` (domain) has a named test in `test-matrix.md` · [ ] spec commit precedes implementation commit — not yet committed (wrap-up).

**C7 — second-reuse fidelity**: [x] `specs/shared/` byte-identical to #8 and #7 except the matrix Status column (`init.sh` 5d) · [x] no silent fork, no `SA-6` needed (G3 closed at the gate) · [x] the `R` ids are #7's and the realisation satisfies them on the paths I drove · [ ] n8n / black-box API script — not applicable until features 25/31 · [ ] inherited findings accounted for — see §5: the report's dispositions for #8 id 49 and id 79 overstate (D1, D2) · [ ] effort records — on approval · [ ] README benchmark — wrap-up.

## 3. `R<n>` → test, as verified

| Id | Test (exists, green in the full run) | Armed by (seen red by me, or by the implementer only) |
|---|---|---|
| R30 | `unit/domain/test_stock_item.py::test_r30_rejects_in_full_…`; race half `integration/test_stock_reserve_race.py::test_fs6_…` | B4a/B4e2 (impl); `Q3-I1` (me) on the race half |
| R31 | `integration/test_stock_check.py::test_r31_answers_per_line_…`, `test_a_check_is_answered_while_a_test_transaction_holds_the_row_for_update` | H1a/H1b2/H2 (impl); `Q7-M6` (me: `<=` → `<` is red on `test_r31_…`) |
| R32 | `unit/domain/test_reservation.py::test_r32_…`; `integration/test_stock_reserve.py::test_r32_the_accepted_path_…` | B6/H3 (impl); `Q7-M2` (me) shows the outbox write is observed on the rejected path |
| R33 | `unit/domain/test_reservation.py::test_r33_…`; `integration/test_stock_reserve.py::test_h4_the_rejected_path_…` | B6a/B6d/H4 (impl); `Q7-M2` RED on `test_h4_…` ×2, `test_a_code_differing_only_in_letter_case…`, `test_fs6_…` (me) |
| R34 | `unit/domain/test_reservation_release.py::test_r34_…`; `integration/test_stock_release_idempotency.py::test_r34_answers_success_and_emits_no_second_fact_…` | B8/H7 (impl); `Q7-M3` and `Q7-M8` RED on `test_the_release_releases_every_reservation_…` (me) |
| R35 | `unit/domain/test_reservation.py::test_r35_refuses_every_transition_…` | B2a–d (impl) |
| R61 (domain) | `unit/domain/test_stock_replenishment.py::test_r61_…`; host: `integration/test_stock_replenish.py::test_r61_replenish_raises_units_by_the_sums_…` | B8b (impl); `Q7-M10` RED on both (me) |

The FS rows of `requirements.md` §3 map to existing tests; FS25's row is marked DONE but its test does not see its distinguishing clause (D1), and FS24's chain is guarded inside the domain only (D2).

## 4. My own mutations (Q7 and R1)

| Id | Site (boundary) | Mutation | Result |
|---|---|---|---|
| **R1** | `infrastructure/persistence/stock_repository.py:101-102` (`lock_order_items`, the SA-4 lock) | read the order's reservations **before** locking the stock rows | **SURVIVED**: `809 passed in 46.53s` (whole `services/fulfillment` + `tests/architecture`) |
| **M1** | `application/stock_reservation.py:115` (handler → transaction / domain) | `new_id=scope.ids.new` → `new_id=UniqueId.new` | **SURVIVED**: `809 passed` |
| M2 | `stock_repository.py` `save()` (domain fact → outbox row) | extend the outbox events only when the item's counters changed | RED: 4 failed (`test_h4_the_rejected_path_…`, `test_h4_an_unstocked_product_…`, `test_a_code_differing_only_in_letter_case_…`, `test_fs6_…`) |
| M3 | `stock_mapper.py` `reservation_snapshot` (mapper ↔ snapshot) | `retailer_code=row.company_code` | RED: `test_the_release_releases_every_reservation_lowers_the_counters_and_writes_exactly_one_released_fact` |
| M4 | `composition.py` (settings → adapter, #8 id 56) | `web_concurrency=1` instead of `settings.server.web_concurrency` | RED: `test_more_than_one_worker_with_the_relay_enabled_refuses_to_boot_before_connecting` |
| M5 | `presentation/stock_wire.py:74` (responder → handler) | default `page_size` 25 → 20 | survived — **equivalent in practice**: the generated `StockListRequestPayload.page_size` already defaults to 25 (`asyncapi.py:654/736/768`), so the branch runs only for an explicit `"pageSize": null`; the default itself is asserted by `test_stock_list.py:28`. Not a finding |
| M6 | `stock_reads.py` availability | `requested <= available` → `<` | RED: `test_r31_…` |
| M7 | `stock_reads.py` list | `count()` ignores the filters | RED: `test_fs15_…` |
| M8 | `domain/order_stock_reservation.py` release fact (payload field on the wire) | `company_code=retailer_code` | RED: `test_the_release_releases_every_reservation_…`, `test_r34_releases_…` |
| **M9** | `stock_repository.py:104-105` (`lock_order_items`' defensive check) | `if False and any(...)`: never raise `ConcurrentReservationChangeError` | **SURVIVED**: `809 passed` |
| M10 | `application/stock_replenishment.py` | repeated replenish lines not summed | RED: `test_r61_replenish_raises_units_by_the_sums_…`, `test_every_line_known_replenishes_all_sums_repeated_lines_and_saves_once` |
| M11 | `stock_wire.py` FS28 boundary | `len > 20` → `len >= 20` | RED: `test_f2_the_boundary_values_the_schema_allows_are_accepted` |

Both mutation families were probed on the facts: deletion-shaped (M2 suppresses the rejected fact's row) and payload corruption on the wire (M3 `retailerCode`, M8 `companyCode` of `stock.released.v1`). Both are seen.

## 5. Inherited findings (`design.md` §17) — the report's dispositions, checked

| Finding | Report says | Ruling |
|---|---|---|
| #8 id 49 + follow-on | avoided (4 sites) | **Avoided at the four domain sites** (re-armed). **Open at the seam**: the two application sites that hand the id port to the domain (`stock_reservation.py:115`, `:170`) are unguarded (M1). The follow-on's lesson was "one of four sites guarded"; here it is four of six (D2) |
| #8 id 50 | avoided | Avoided (re-armed F7) |
| #8 id 51 | avoided | Avoided (generated models; Orders' set imported) |
| #8 id 54 | avoided | Avoided for the guard it names (D5 isolation case, implementer's D5b/D5c) |
| #8 id 79 (release half) | built and guarded | **Built; only half-guarded**: the lock's existence is guarded (I5), its order relative to the reservation read is not (R1, D1) |
| #8 id 95 | avoided | Avoided (re-armed F8) |
| #8 id 101 | assigned to feature 29 | Confirmed: feature 29's acceptance item names id 101 |
| #8 D1 / D2, A6, #7 FS5 rejection, #8 G6, #8 id 56 | avoided | Confirmed by the implementer's arms and my M2/M3/M4/M8 and Q3-I3 |

**Recurred, in its general form:** #7's feature-17 rejection, *an unplanned sub-clause mutation survived the full suite*, recurred as R1 (FS25's "before reading the order's reservations").

## 6. Defects

**D1 (blocking) — FS25's distinguishing clause and the SA-4 lock order are unguarded.** `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py:101-102`. FS25 requires the release to *"wait for that transaction to end **before reading the order's reservations**"*. `design.md` §6.3 states the SA-4 lock as stock rows first, then the order's reservations, and tells feature 18 to reuse this method. Swapping the two reads (R1) leaves all 809 tests green. `test_fs25_…` (`test_stock_release_idempotency.py:163`) only observes that *some* `SELECT … FROM stock … FOR UPDATE` waits, and that still happens after a reservation read taken first. D5, the protocol test that does see the order, exercises `lock_for_reserve` only (`test_stock_repository.py:74`). So ledger row L1's guard does not execute the code the release half is about. This matters for the same reason D5 matters for reserve: PostgreSQL has no key-range lock (measured in the design header), so a reservation read taken before the stock lock misses rows committed while the lock waited. It is also the method feature 18's despatch half will call.

**D2 (blocking) — FS24's identifier chain is unguarded at the application → domain seam.** `services/fulfillment/src/otc_fulfillment/application/stock_reservation.py:115` (reserve) and `:170` (release). Replacing `scope.ids.new` with `UniqueId.new` (M1) leaves 809 tests green. Worse, `test_fs5_…` (`tests/unit/test_stock_reservation_service.py:184`) uses `rig.ids.minted == 0` as its observable for "no domain function ran". Under M1 that instrument is blind (defeat row 9: the premise "the handler mints through the port" is unchecked). FS24's text ends *"so that a caller supplying known identifiers observes exactly those identifiers on the reservations and the facts"*, and in the running service that caller is the `IdSource` port.

**D3 (should fix now) — the `ConcurrentReservationChangeError` branch has no test.** `stock_repository.py:104-105`. `tasks.md` D2 names it, `design.md` §6.3 step 2 specifies it, and §8.5 maps it to `UNAVAILABLE`. Only the mapping row is unit-tested. Removing the check (M9) leaves 809 tests green.

**D4 (routing, leader action, not the implementer's) — the carried half of SA-4 is not on feature 18.** `feature_list.json` feature 18 has two acceptance items and none of what `design.md` §15 / §17 and impl §9 say "remains for 18": `despatch.create` taking exactly `StockReads.stock_keys_of_order` + `StockRepository.lock_order_items`; the release-versus-despatch race in both outcomes; the despatch half of FS25's lock test (#8 id 79); the in-lock re-read under the pinned `READ COMMITTED` (#8 id 54). By CLAUDE.md, *"only the half of a fix that depends on code not yet built is carried, as an acceptance item on the feature that builds it"*. Today it is carried only as prose in feature 17's design, the "the next feature must close it" shape. Feature 18 is `sdd: false`, so nothing else will make its implementer read 17's §15. **The leader must add the acceptance item to feature 18** (I may not edit `feature_list.json` beyond 17's status). It is not rooted in `specs/shared/`, so no `SA-n`.

**D5 (minor, spec text) — stale line citations remain in the approved spec.** The implementer corrected them only in the report (§2): `design.md:31` (`QUANTITY_COLUMNS` "148 – 158" → 151–157), `:26` (`models.py` "60 – 138" → 59–150), `:40` and `:395` (`composition.py:134-499`, `213-261` in a 464-line file), `:103`, `:353` and `requirements.md:91` (`nats_saga_commands.py:197-209` → 65–75), `requirements.md:39` (`276-279` → 143–146), `:63` (`:202`), `design.md:104` (`writer.py:243-258` in a 72-line file → 57, 72). Feature 18 reads these files.

**D6 (minor, guard quality) — the FS25 test's failure under its own arm does not name the claim.** Under I5 the test dies as `asyncio.exceptions.CancelledError / TimeoutError` inside `conftest.py` `wait_for_lock_waiters` (`test_stock_release_idempotency.py:173`). CLAUDE.md's arming protocol requires the message to name the claim.

**D7 (minor, record accuracy) — `progress/impl_fulfillment_stock.md`.** (a) §8.1 is an empty heading; the arm list is §16. (b) The G8 arm (`.arm/impl17/arm_g.py:8`) is described as "feature 43's carried F-g + F-j fixture", but its `__init_subclass__` hook sits on `ReserveStockCommand`, which nothing subclasses, and the root drains a literal tuple. The F-j half was inert and the arm failed by F-g alone. The guard itself holds (my `Q6` arm with a real F-j pipeline is red by the WIRE clause). (c) §7's id 49 and id 79 dispositions must be restated once D1/D2 are closed.

## 7. What must change before re-review

Each item names the test and the arm that will prove it. Arms follow CLAUDE.md's protocol (backup in `.arm/`, sha256, one mutation, named test only, restore by `cp` + `cmp`, caches cleared, re-run green, verbatim failure recorded).

1. **D1** — add an integration test of `lock_order_items`' read order, D5's construction applied to the SA-4 lock. Either at repository level in `services/fulfillment/tests/integration/test_stock_repository.py` (suggested name `test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_sees_a_reservation_committed_while_it_waited`) or through the host in `test_stock_release_idempotency.py`. The construction: the test's connection follows the protocol (locks a stock row the order already holds a reservation on, inserts a further `reserved` reservation of the order on that row, raises the counter, holds); `lock_order_items` (or `stock.release`) is seen ungranted; the test commits; the returned `reservations_of_order` contains the new row (or the release releases it and the counter returns to the pre-reserve value). **Arm: `R1`** (swap lines 101–102 of `stock_repository.py`); it must fail naming the missing reservation. Keep FS25's existing test. Update ledger row L1 (and §17's id 79 line) to name this guard. Record the arm.
2. **D2** — in `services/fulfillment/tests/unit/test_stock_reservation_service.py`, assert on the accepted reserve that every reservation id in the result and the reserved fact's `event_id` equal the `FakeIds` values in minting order, and on a release that the released fact's `event_id` equals the supplied one. **Arms: `M1` on `stock_reservation.py:115` and the same substitution on `:170`, two arms**, each failing at its own assertion. Also give `test_fs5_…` an observable for "no domain function ran" that does not depend on the port being used, or state why `stocked.to_snapshot() == before` and `domain_events == ()` already carry it.
3. **D3** — a test that `lock_order_items` raises `ConcurrentReservationChangeError` when the order holds a reservation on a stock row outside the keys it was given (repository level, real PostgreSQL). Optionally add the host-level `UNAVAILABLE` reply. **Arm: `M9`**.
4. **D6** — make the FS25 test's lock wait fail with a message naming the claim (e.g. *"the release never waited on the held stock row"*). Re-run arm `I5` and record the new failure text.
5. **D5** — correct the stale line citations listed in D5 in `specs/fulfillment_stock/design.md` and `requirements.md` (substance unchanged; this is a spec-text edit inside the feature's own spec, not `specs/shared/`).
6. **D7** — fix §8.1, re-describe the G8 arm truthfully (or re-arm it with a real F-j pipeline, e.g. my `Q6` fixture in `.arm/review17/log.md`), and restate the id 49 / id 79 dispositions.
7. **Leader (D4)** — add to feature 18's `acceptance` in `feature_list.json` the carried SA-4 item: *"`despatch.create` takes the SA-4 lock through `StockReads.stock_keys_of_order` + `StockRepository.lock_order_items` exactly as `stock.release` does; the release-versus-despatch race is integration-tested in both outcomes; the despatch half of FS25's lock test (#8 id 79); the in-lock re-read relies on the pinned READ COMMITTED (#8 id 54)"*. This must be done before feature 18 starts, whatever the outcome of round 2.
8. Re-run `./quality.sh` once after the last edit (developer stack down) and report count and duration. Re-run every arm whose path the new tests touch (I5, D5a, and the new R1/M1/M9 arms).

Not required: the code itself. Every behaviour I drove is correct; the changes are guards, records and spec text.

## 8. For the record (not findings)

- `quality.sh` took 300 s on my run (268 s at A2 before the feature; the maintainer's Phase 7 reference was ~125 s). Reported, not ruled on.
- The live walkthrough (K1–K5) was reviewed as a record and not re-run, as briefed. The causal chain K3 claims (`correlation_id` = order id, `causation_id` = `saga_commands.id`) is consistent with FS3's integration guard, which I saw protecting the same mapping (H3b, impl). The developer databases are left changed (`ORD-000007` `stock_reserved`, `ORD-000008` created), as the report discloses.
- Arm artefacts: `.arm/review17/rarm.py`, `a_r1.py`, `a_q3.py`, `a_q1245.py`, `a_q56.py`, `a_q7.py`; records `.arm/review17/log.md`; outputs `.arm/review17/logs/*.red.txt|*.green.txt`; backups with sha256 in `.arm/review17/bak/`.

---

## Round 2 — 2026-10-08 ≈07:10 – 07:30 UTC (≈20 min wall-clock)

**Verdict: APPROVED.** Feature 17 is set to `done` (`feature_list.json` line 327, that line only). The effort entry is appended to `progress/history.md`.

Every round-1 blocking item (D1, D2, D3) is closed by a test that fails, naming its claim, when the code is reverted. I re-ran those arms myself. D4 is on feature 18. D5, D6 and D7 are corrected and were checked against the files. Five new mutations of my own in the code the fix round guards: four RED, and one survivor that is equivalent under the lock protocol (§R2.4). One non-blocking record finding (**N-1**) remains: two ledger/traceability cells were not updated to name the new guards. Its disposition is to fix it now, as a light docs-only edit, before the spec commit (§R2.6).

### R2.0 What I ran (verification, not assumption)

| Claim | Command / instrument | Result |
|---|---|---|
| The fix round changed tests only | `find services packages tests -newer progress/review_fulfillment_stock.md -type f` (excluding `__pycache__`) | 3 files: `integration/test_stock_release_idempotency.py`, `integration/test_stock_repository.py`, `unit/test_stock_reservation_service.py`. Every round-1 `src` backup in `.arm/review17/bak/` (36 files over 14 sources) `cmp`-identical to the live source. Every `.arm/fix17/bak/` file `cmp`-identical too |
| `quality.sh` exit 0 (full-suite claim, re-run in full; `docker ps` = `otcpy-n8n` only, no other pytest process) | `./quality.sh` → `.arm/review17r2/quality.log` | **exit 0, 324 s script, `2690 passed in 282.64s`**. ruff clean, `mypy` clean on 458 source files, `Contracts: 11 kept, 0 broken`, coverage 98 % overall / 99 % domain, Vitest green, `quality.sh: all gates passed`. Matches the implementer's 2690 (2686 + 4 new tests) |
| `init.sh` coherent | `./init.sh` → `.arm/review17r2/init.out` | exit 0, "environment and state are coherent" |
| Arms | `.arm/review17r2/rarm.py` (round 1's helper re-pointed: backup with sha256 into `.arm/review17r2/bak/`, one mutation, named test(s) in their own process group killed whole on timeout, restore by `cp`, `cmp`, `__pycache__` + `.mypy_cache` cleared, green re-run); script `.arm/review17r2/arms.py`; records `.arm/review17r2/log.md`; outputs `.arm/review17r2/logs/` | 10 arm runs: **9 RED, 1 survived (N3, equivalent, §R2.4)**. All 10 backups `cmp`-identical after restore; final sha256 of `stock_repository.py` `1088a62c…dddc9` and of `stock_reservation.py` `feead357…df23d3d` equal the pre-arm values; every re-run green |

I did not re-run the fix round's D5a arm: its target (`lock_for_reserve`) and its test are untouched by the fix round (round-1 backup `cmp`-identical), and I saw it RED myself in round 1 (`Q3-D5a`).

### R2.1 The five arms of the fix round, re-run (brief step 1)

| Arm | Mutation | Named test | Red, verbatim | Answer to "what fails if I revert this?" |
|---|---|---|---|---|
| R1 | `stock_repository.py:101-102`: the two reads of `lock_order_items` swapped | `test_stock_repository.py::test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_sees_a_reservation_committed_while_it_waited` | `AssertionError: the lock read the order's reservations BEFORE the stock lock was granted: the reservation committed while it waited is missing` / `Extra items in the right set: UUID('90a98f2c-…')` (the late id) | The construction is right. The existing reservation is committed beforehand. The late one is inserted by a protocol-following holder, so it is uncommitted while the release reads, and a reservations-first read takes a snapshot without it. The `FOR UPDATE` on reservations does not wait for an uncommitted insert (no key-range lock, as measured in the design header). The assertion is **set equality** with both ids, not containment of one |
| M1a | `stock_reservation.py:115`: `new_id=scope.ids.new` → `UniqueId.new` | `test_stock_reservation_service.py::test_fs24_the_reserve_uses_the_id_port_…` | `At index 0 diff: UniqueId(value=UUID('a0b706e3-…')) != UniqueId(value=UUID('00000000-0000-0000-0000-000000009001'))` | Equality with `[uid(0x9001), uid(0x9002)]` in minting order, then the fact `event_id == uid(0x9003)` and `minted == 3`. This is **equality with the supplied ids in minting order**, not inequality or type (brief step 2). The first assertion has no message string, but the diff names the supplied id against a random one |
| M1b | `:170` the same substitution (release) | `…::test_fs24_the_release_uses_the_id_port_for_the_released_facts_event_id` | `AssertionError: the released fact's event id comes from the id port` / `UUID('da8a6071-…') != UUID('00000000-…-000000009001')` | Equality with `uid(0x9001)` |
| M9 | `:104` `if False and any(...)` | `test_stock_repository.py::test_the_release_lock_raises_concurrent_reservation_change_…` | `Failed: DID NOT RAISE ConcurrentReservationChangeError` | Real PostgreSQL. The keys name PRD-A1 only and the order also holds a reservation on PRD-B2. The control half (both keys → accepted, two reservations) proves that the raise comes from the check and not from the data |
| I5 (D6) | drop `.with_for_update()` in `_lock_stock_rows` | `test_stock_release_idempotency.py::test_fs25_a_release_waits_for_…` | `Failed: the release never waited on the held stock row: no locking SELECT on stock was seen ungranted, so the release does not take the stock lock (FS25)` (chained after the `CancelledError`/`TimeoutError` of the bounded wait) | The failure now names the claim. The bounded wait went from 23.8 s in round 1 to `deadline_seconds=10`, and the whole test takes 18.8 s red. `conftest.py` is untouched (`asyncio.timeout` raises the built-in `TimeoutError` the test catches) |

**`test_fs5_…`'s observable (brief step 2).** It no longer reads `rig.ids.minted`. It asserts `stocked.to_snapshot() == before`, `stocked.reservations == ()` and `stocked.domain_events == ()`, with the reason in a comment. All three are properties of the item, independent of the id port: a domain call on the satisfiable fixture would add a reservation and record a fact whichever id source it used. The defeat-row-9 premise is gone.

### R2.2 D5 citations and D7 record fixes, checked against the files (brief step 3)

- `design.md:26` `models.py` 59 – 144: `class Stock` at 59, `ProcessedEvent`'s last column at 144. Correct. `:31` `QUANTITY_COLUMNS` 151 – 157: correct. `:40` and `:395` Orders `composition.py:100-464` (file is 464 lines; `OrdersSettings` at 100) and single-relay guard 181 – 230 (`MultipleOutboxRelaysError` 181 … `_claim_relay_slot` ends before `OrdersRuntime` at 232): correct. `:103`, `:353`, `requirements.md:91` `nats_saga_commands.py:65-75`: the frozenset opens at 65 and its nine members end at 75 (closing `}`/`)` at 76 – 77), so the range is correct for the set. `requirements.md:39` 143 – 146, the header dict: correct. `:63` `:174`, the `if error.code in TERMINAL_RPC_ERROR_CODES`: correct. `design.md:104` `writer.py:57, 72` (`session.add(`, `await session.flush()`): correct.
- D7a: §8.1 now points at §16 and the Round 2 section. True.
- D7b: G8's arm record (impl line 516) now says that F-g fired alone and the F-j hook was inert, and it names my `Q6` as the real F-j pipeline. True. Feature 17's carried acceptance item (feature 43, "armed with F-g + F-j … as one fixture") is therefore discharged by **`Q6-G8-Fj-plus-Fg`** (round 1, RED by the WIRE clause), not by the implementer's G8. That is recorded here so the history entry does not credit the wrong arm.
- D7c: impl §7's id 49 and id 79 rows and `design.md` §17's id 49 and id 79 lines name the new tests and arms. True. Ledger row L1 (`design.md:96`) names `test_fs25_the_release_lock_reads_…` and arm R1. True. **But see N-1.**
- D4 (leader): feature 18's third acceptance item names `stock_keys_of_order` + `lock_order_items` "exactly as stock.release does", the race in both outcomes with each outcome stated, the despatch half of FS25's lock test (#8 id 79), and the pinned READ COMMITTED with its ledger row (#8 id 54). It covers all four parts of my D4.

### R2.3 Rulings on what was not done

- **D3's optional host-level `UNAVAILABLE` reply: ACCEPTED, not owed.** The raise is guarded on real PostgreSQL (M9). The mapping row is unit-tested (`test_stock_rpc_errors.py:66`). The host path between them is the generic error path that FS10's host test already drives. My own arm N2 also showed it end to end: with the lock narrowed to the first key, the host replied `{'code': 'UNAVAILABLE', 'message': 'order ORD-000042 gained a reservation on a stock item that was not locked', …}` (`.arm/review17r2/logs/N2-lock-first-key-only.red.txt`).
- **`specs/shared/test-matrix.md` unchanged: ACCEPTED.** The new tests prove local rows (FS24, FS25, §6.3 step 2). No shared `R<n>` changes status, and the R30 – R35 and R61 rows already name tests I verified in round 1.

### R2.4 My own mutations in the code the fix round guards (brief step 5)

Each was run against `services/fulfillment` + `tests/architecture` (813 tests).

| Id | Site | Mutation | Result |
|---|---|---|---|
| N1 | `stock_repository.py:104` | `any(` → `all(` in the concurrent-change check | RED: `test_the_release_lock_raises_concurrent_reservation_change_…` (1 failed, 812 passed) |
| N2 | `:101` | lock only `keys[:1]` | RED: 7 failed (the release host tests, FS25 host, the M9 control half, FS12) |
| N3 | `_lock_reservations_of` | drop `.with_for_update()` on the order's reservations | **SURVIVED** (813 passed). **Equivalent under the protocol, not a finding.** Every writer of a `reservations` row takes the `stock` row lock of that reservation's item first: reserve on the requested rows, release on every row of the order through `lock_order_items`, which refuses a reservation on an unlocked row (N1/M9); replenish writes no reservation. So no reachable interleaving reaches the reservation row lock contended. The one case it could matter in, two concurrent reserves of one order naming disjoint products, is gate point G1's accepted residual, and there a row lock cannot help (no key-range lock). The row lock is defence in depth. **Note for feature 18:** the despatch must not rely on it, because no test would notice its loss |
| N4 | `lock_order_items` | keep only `status == 'reserved'` reservations (hide terminal rows from the release) | RED: `test_fs10_replies_precondition_failed_…` |
| N5 | `lock_order_items` | keep only the first reservation (`reservations[:1]`), the payload-shaped variant of R1 | RED: 5 failed, including the new R1 test (`the lock read the order's reservations BEFORE …`), the release host test (`'units': 3` ≠ `5`) and the M9 test |

Two mutation families were probed on the release lock: deletion (M9, N3) and corruption of what the lock returns (N4, N5). Substitution was probed on the id seam (M1a/M1b: a valid sibling id source).

### R2.5 `CHECKPOINTS.md` (re-walked; changes from round 1 only)

**C2**: [x] 17 → `done`, no `in_progress` feature left · [x] every `done` feature's tests pass (full run, 2690). **C5**: [x] history entry with effort record (appended) · [x] `feature_list.json` reflects the state · [ ] human told what was done / how to test: the leader's, at close · [x] Claude did not commit. **C6**: [x] the three spec files complete; [x] every shared R row has a named test; [ ] spec commit before implementation commit: at wrap-up. **C7**: [x] inherited findings accounted for (id 49 six of six sites, id 79 release half fully guarded); [x] effort record; [ ] README benchmark: at wrap-up. All other boxes are as marked in round 1, re-confirmed by this round's `quality.sh` (C3, C4: 11 contracts kept, money guard and domain purity green) and `init.sh` (C1, C7 byte-identity).

### R2.6 Findings

**N-1 (non-blocking; disposition: FIX now, light, docs-only, before the spec commit at wrap-up).** Two traceability cells still name only the round-1 guards, so a reader following them to the guard lands on a test that does not execute the clause:
- `specs/fulfillment_stock/design.md:110`, ledger row L15. Its "#9 supplied by" half says *"the handler passes `scope.ids.new`"*, but its guard cell names only B7 (domain) and the four domain arms. Add `test_fs24_the_reserve_uses_the_id_port_…` and `test_fs24_the_release_uses_the_id_port_…`, arms M1a and M1b (CLAUDE.md line 67: *"does the named guard execute the code the row is about?"*).
- `specs/fulfillment_stock/requirements.md:160-161`, the §3 rows for FS24 and FS25. FS24 names only the domain unit test. FS25 names only the host test, which does not see the *"before reading the order's reservations"* clause (that was round-1 D1). Add the two FS24 unit tests, and `test_stock_repository.py::test_fs25_the_release_lock_reads_…`.
This is a light docs edit to the feature's own spec, not `specs/shared/`, so no `SA-n`. It is not blocking, because the guards exist, are armed and are named in `design.md` §3 L1 and §17. Feature 18's implementer reads §3 and §15, so fix it in this phase. **Re-open trigger:** the spec commit lands with either cell still naming only the round-1 test.

No finding is rooted in `specs/shared/`, so no `SA-n` is proposed.
