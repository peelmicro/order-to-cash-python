# Brief — implementer, feature 27 `observability_reliability`, review round 1 fixes

**Classification: full group** (a wire-contract header and a migration). Rules: everything in `progress/brief_impl_observability_reliability.md` still binds (`setsid --wait`; arming restores single files by `cp`, never deletes or moves a tracked path; every command from the repository root; no git writes; no `feature_list.json`, `.env*`, compose, `infra/`, `apps/web/`; `specs/shared/` only the Status cells and coverage table this feature owns).

**Input:** `progress/review_observability_reliability.md` — read §4 (Q4, B1's analysis and proposed fix), §18 (findings) and §19 ("What must change before re-review"). The leader verified B1 on disk this session: `asyncapi.yaml:2227-2230` (SA-3: "`x-first-failed-at` … equals `x-failed-at` only when a single attempt was made"), `services/orders/src/otc_orders/infrastructure/saga/first_park.py:77-78` (`first_failed_at=now, failed_at=now`; the review cites 80-81, which are the closing parentheses), `services/orders/tests/integration/saga/test_saga_first_park_dead_letter.py:211` (asserts the equality).

## Leader dispositions — build all of these

1. **B1 — fix.** Record the first failed attempt's instant of a saga command durably and send it as `x-first-failed-at`; the park instant stays `x-failed-at`. Migration `0003` is uncommitted: add the column there (a nullable `timestamptz(3)`, e.g. `saga_commands.first_failed_at`, set with `COALESCE(first_failed_at, :now)` wherever the ledger records a failed attempt — find every such site with a command and list them in the record), extend `models.py` and the models-match / migration tests, return it from `claim_first_park`, and use it in `first_park.py`. State what is sent for a row with no recorded first failure, and why that case can or cannot arise (the review's reasoning about pre-`0003` rows; verify it). Replace the `:211` assertion with one against the instant the test itself observed for the first failure, with fixture instants pairwise distinct, and **arm** it (both instants = the claim's → red, with a message naming SA-3). Also arm the `COALESCE` (overwrite on every failure → the first instant is lost → red). Update design §5.6, the ledger (§11), §13's #8 id 75 row ("recurred on the first-park path, found in review round 1") and §14 D6.
2. **N1** — `specs/observability_reliability/requirements.md` §4: reword the two undelivered names to the delivered ones and write the Status cells.
3. **N2** — the three trace-hop failures must name the hop (presence asserted with a message before unpacking); re-arm the review's mutations 1a and 1b and record the new failure texts.
4. **N3** — one integration case: `claim_first_park` on a `rejected` and on a `sent` row returns `None` and leaves `dead_lettered_at` NULL; arm by removing the `status = 'parked'` predicate.
5. **N4** — reword RI2 in `requirements.md` as the review proposes (the valid-request condition; cite #7 `place-order.handler.ts:68-77` and #8's divergence `PlaceOrderCommandHandler.cs:39-50`), and add the unit case "known `requestId` + non-zero `orderDiscount` → refused, no replay"; arm it (move the fast path before the refusal → red).
6. **N5** — the no-reload census counts `shell=True` calls, `os.system`, `os.popen` and `create_subprocess_shell` as opaque spawns in the population literal, and searches string constants for a `--reload` / `--watch` **token**; add the review's probe 9a forms as sentinels; arm.
7. **N6** — the S8c SMTP ported-idiom row goes into `design.md` §11 as L42, with its guard names.

N7 is the leader's (history entry at close).

## Gate

Run what §19 item 3 lists, then `./quality.sh` with the developer infrastructure down (the change touches a migration); record total, failures, time and time per test from its artifacts, reconciled against 5 216 / 0.1588 s. Append a "Review round 1 fixes" section to `progress/impl_observability_reliability.md`: each item, its files, each arm (backup, `sha256`, verbatim failure, `cmp`, green re-run). Return at most 10 lines.
