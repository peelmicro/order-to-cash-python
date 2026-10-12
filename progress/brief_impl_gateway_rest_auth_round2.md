# Brief — implementer, feature 25 `gateway_rest_auth`, fix round (round 2)

**Task:** fix the two blocking findings of `progress/review_gateway_rest_auth.md` (round 1, REJECTED) and the record items of its §8 — nothing else. Feature 25 is `in_progress`. Read, in order: the review's §1 (B1, B2) and §8 (items 1 – 3; item 4 is the leader's and is done: backlog 215), then the relevant sections of `progress/impl_gateway_rest_auth.md` (§1's routes table, §4's E1 line, §7's arming table, §12 (b) on the `WrapValidator`). CLAUDE.md on disk is binding.

## B1 — non-JSON or absent `Content-Type` on a body route answers 500

`services/gateway/src/otc_gateway/presentation/wire.py:24-28` calls `json.dumps(value)` on what FastAPI 0.142.2 hands over as **bytes** when the media type is not JSON. Required:

- Every operation with a request body answers **400 `VALIDATION_FAILED`** as `application/problem+json` for `text/plain`, `application/x-www-form-urlencoded` and **no** `Content-Type`, and logs **no ERROR line**. Choose the remedy (refuse in the validator, or refuse non-JSON media types before the body is read) and say why, citing what #7 (Nest body parser → `{}` → 400) and #8 (ASP.NET → 415) do; #9 answers 400 because `openapi.yaml` declares 400 on these operations and no 415 — check that for each of the five.
- **Guard:** one test whose population is **derived from the app** (every operation with a `requestBody`, read from the served routes — never a hand list; n = 5 today), each driven with the three media cases, asserting status, `Content-Type`, the Problem `code`, and that no ERROR record was logged (`caplog`). Add a census sentinel: the derived population equals a literal expected set, so a body route that escapes the derivation fails.
- **Arms:** (a) revert the fix → fails naming the route and the media type; (b) the population: a sixth body route added to a scratch app (or the derivation narrowed) must be seen by the guard.

## B2 — the read-model adapter's totals are guarded only by accident

Every seeded saga has `initialDiscount = 0`, so `initialAmount == totalAmount` in every document `services/gateway/tests/integration/test_order_read_model.py` reads, and the whole file (21 tests) stays green with the totals transposed in `infrastructure/mongo_order_read_model.py:143-146`.

- Add at least one read-model document whose **three totals are pairwise distinct** (e.g. project the facts of an order with line discounts, as `test_gateway_over_real_responders.py::test_a_placed_order_is_pending_until_the_projector_has_written_it` does with 8525 / 165 / 8360 — or write the document the way the file's fixture already writes documents, if it does not depend on the seed), and assert the three totals of **both** the list summary and the detail on it.
- Fix test `:174` (`test_the_three_totals_of_the_seed_are_three_different_numbers_so_a_swap_is_seen`) so it asserts what its name claims, or rename it to what it asserts.
- **Arms**, each must fail **inside `test_order_read_model.py`**: `initialAmount ↔ totalAmount` and `initialDiscount ↔ totalAmount` in the adapter's parse (the review's I-r2c).
- Check for the same accident at every other money field the Gateway reads or forwards (list the sites with a command: e.g. `grep -n "amount\|Amount\|discount\|Discount\|price\|Price" services/gateway/src -r`), and state per site which test would fail on a transposition with its neighbour. Fix any further accident you find (same class, same phase).

## Record items

- §1's `POST /orders` row lists the undeclared 404 (backlog 215 now owns the contract side).
- §4's E1 line names the adapter site and the B2 fix.
- Append a "Round 2" section: what changed (file:line), the new arms (mutation, test, verbatim message, `sha256`, `cmp`), and one `./quality.sh` run (developer stack down; exit code, pytest time and pass count, time per test). Wait on the real PID; read the verdict from the log.

## Bounds

May touch: `services/gateway/**` (source and tests), `progress/impl_gateway_rest_auth.md`, feature 25's status line in `feature_list.json` (set `in_review` at the end). Nothing else. No git command that writes the index or working tree. Arming per CLAUDE.md: backups in `.arm/n25r2/` with `sha256`, restore by `cp` + `cmp`, clear caches, a timeout kills the whole process group.

Return only "result in `progress/impl_gateway_rest_auth.md` (Round 2)" plus at most 4 lines.
