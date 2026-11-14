# Brief — reviewer, feature 31 `api_tests` (phase 18, full group)

**Task:** approve or reject feature 31 (`in_review`) against its **seven** acceptance items (`feature_list.json` id 31; item 7, R61's API half, was added at dispatch, see `progress/current.md`). Check them against the implementer's brief `progress/brief_impl_api_tests.md` and `CLAUDE.md` on disk (testing conventions, arming protocol, defeat list). The implementer's record is `progress/impl_api_tests.md`. Do not take its claims as given: re-derive the countable ones.

## What is in the tree (verified by the leader this session)

- **Feature 31:**
  - `tests/api/{conftest.py,api_support.py,test_api_instruments.py,test_black_box_api.py,test_money_representation.py,test_stock_replenishment.py}` (1 785 lines);
  - `tests/saga_e2e/conftest.py` (+`Fleet.gateway`);
  - `tests/architecture/test_no_reload_servers.py` (`EXPECTED_POPULATION` 13 → 15);
  - `specs/shared/test-matrix.md`: R1, R24, R48, R49 and R61 moved to DONE, plus the summary. No `services/**`, `packages/**` or `apps/web/**` file differs from HEAD (`git status --short`).
- **Two light test-support fixes, closed by the leader, found while getting `quality.sh` green. Not under review here, but they are in the same tree:**
  - entry **217**: Mongo containers are now ready only after an authenticated ping through the host port (`tests/observability/health_support.py`, `conftest.py`, `test_gateway_degraded.py`);
  - entry **218**: `log_contract_support.booted` now matches "Uvicorn running on", not the lifespan line.
  - Records: `progress/impl_{mongo_container_ready_before_its_real_server,booted_predicate_fires_before_the_socket_listens}.md`.
- **The last full `./quality.sh`:** `.arm/n218/quality.log`, 18:32, "all gates passed", 5 288 passed in 1 452 s, web 687. No file under `tests/`, `services/`, `packages/`, `specs/` or `conftest.py` is newer than that log (`find -newer`, empty). Do not re-run the whole gate unless you change the tree or doubt that log. Run `tests/api/` once with the developer infrastructure down. Only `otcpy-n8n` and another project's `kb-poc-*` containers are up; the machine is loaded by an `ollama` `llama-server`, so leave it running.

## Probe these (each a question, not a conclusion)

1. **R61's fixture deviation** (record §9.1): the open reservation is made over NATS for an order reference Orders has never seen.
   - Is that reservation a real one, made by the same code path as an order's?
   - Does "advances no order" assert anything in this fixture, or is it vacuous because no real order exists? Is there an order in the fixture whose state could move?
   - A12 "passes and is not an arm", because `lock_for_replenish` loads no reservation rows. Is the reservation claim then guarded only by forging the evidence (A15-RES)? Is that enough under `CLAUDE.md`'s mutation families?
2. **R48 armed only by forging the evidence** (§10: four Billing layers). Do the forged-evidence arms show that the counts read the right rows, topic and invoice, including substituting a sibling identifier (another invoice's payment)?
3. **I9 and I10 are caught by a 40 s process-group kill, not by a message** (§10). `CLAUDE.md` requires the failure message to name the claim, and pacing to be proven by a change of kind. Is the pacing of `api_support.poll` proven? Is a hang an acceptable detection here, or is a bounded, message-bearing guard owed?
4. **R1's sweep:**
   - `minimum_for` lowers the minimum to 0 for a `headerComplete: false` projection (§10). Can that exemption make the sweep vacuous on a response kind that should carry money?
   - The population of operations is derived from the contract YAML, because `app.openapi()` inlines `MinorUnits`. Is the expected set a literal with coverage by subtraction?
   - Are Problem bodies, the timeline and list pages in it, as #8's and #7's sweeps had them?
   - Try your own arm of a different family from the implementer's: for example a float that is integral (`100.0`), `true` in an amount field, or a currency on a sibling object that should not cover the field.
5. **R24 and #8 id 105:** how is the required number of edges per path derived? Reverse the projector's causal tiebreak (`services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py`, as #8's reviewer did) and confirm the failure names the claim.
6. **R49:** is "nothing changed" checked on every table Billing writes on that path (derive the list from Billing's schema yourself)? Do the three refusals really go through three distinct checks? #8's F1 was a false "identical code path" sentence.
7. **Black-box:** a real uvicorn socket over `fleet.gateway` with `lifespan="off"`. Is httpx the only driver of the system under test, and does the fleet's lifespan own the Gateway runtime?
8. **The matrix:** recount column 5 by script. Read every new sentence in the five rows as a claim and check it (F1), and confirm the scoped-rows paragraph is consistent with R1 = DONE.
9. **`tests/architecture/test_no_reload_servers.py`:** the brief did not list this file. Is the population edit correct, and are both new sites real uvicorn servers without reload?
10. **The ledger, the guard-port table, the inventory of #7's assertions (§2) and the #8 backlog classification:** spot-check the citations against `../order-to-cash-dotnet` and `../order-to-cash-nestjs`, and check every inherited finding is named as avoided or recurred.

## Arming

Run your own arms, of a mutation family the implementer did not use, following `CLAUDE.md`'s protocol:
- backups in `.arm/r31/` with `sha256`;
- one named test per arm under `setsid --wait`, with a timeout that kills the process group;
- restore with `cp` + `cmp`, clear `__pycache__`, re-run green.
Re-run arms; do not re-read them. State which defeat-list rows apply.

## Output and bounds

Read-only, apart from `.arm/r31/` (temporary arms, restored) and your outputs:
- Write `progress/review_api_tests.md`: verdict, findings (each with a disposition: blocking, condition of approval, or non-blocking with a re-open trigger), your arms verbatim, the counts you re-derived, and the effort (start and end times).
- Set feature 31 to `done` (approved) or `in_progress` (rejected); that line only. You are the only writer of `feature_list.json` while you run.
- No git command that writes the index or the working tree.

Return only "result in `progress/review_api_tests.md`" plus a one-line verdict.
