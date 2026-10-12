# Brief — reviewer, feature 40 `orders_catalog_responder` (phase 13, full group, round 1)

**Task:** approve or reject feature 40 (`in_review`). Inputs: `progress/impl_orders_catalog_responder.md`, its brief `progress/brief_impl_orders_catalog_responder.md` (Must-hold list = your checklist, with `feature_list.json` id 40's two acceptance items), the premise check `progress/premise_impl_orders_catalog_responder.md`, and the working tree (nothing committed; feature 25's uncommitted Gateway is in the same tree and is `done` — review only feature 40's change: `services/orders/**`, the two architecture literals the record names, and the leader's Gateway test edit below). CLAUDE.md on disk is binding.

## Already settled by the leader

- **`place_order` still accepts disabled reference rows** (record): not a finding — #7 (`apps/orders/src/infrastructure/persistence/order-reference-data.repository.ts`, the disabled filter only in `listProducts` / `listParties`) and #8 (`EfCoreOrderReferenceCatalog.cs:53-55, 76-78, 93`, the filter only in the `List*` methods) both resolve placement without it, and no shared-spec text requires a refusal.
- **The Gateway test that asserted the catalog 503 "until feature 40"** was deleted by `test_maintainer` at the leader's request (`services/gateway/tests/integration/test_gateway_over_real_responders.py`; its docstring now points at `services/orders/tests/integration/test_catalog_through_gateway.py`). The no-responder mapping stays guarded at `services/gateway/tests/integration/test_nats_rpc_client.py:112`. Confirm the deletion left no hole: is "a no-responder on a Gateway route answers 503 `UPSTREAM_UNAVAILABLE`" still asserted at the HTTP level by some test (the cancel route's `..._until_feature_41` test does, for now)?
- **No `test-matrix.md` row** names this feature (record): verify with a grep.

## Where to push hardest (#8's round-1 failures on this feature, `../order-to-cash-dotnet/progress/history.md:1684-1706`)

1. **D1 `includeDisabled`** end to end: Gateway query parameter → wire → query → SQL, with a fixture that has a disabled row of each kind; substitute the flag with a constant at each hop.
2. **D2 history halves**: open #7's and #8's cited lines for at least the "same instance place-order uses" and the task / queue-group rows; the two-party claim probed both ways.
3. **A5 ordering** for every list, with a fixture whose insertion order differs from code order and from its reverse; delete each `ORDER BY` in turn.
4. **The seam** (`docs/lessons.md:123`): `test_catalog_through_gateway.py` drives the real Gateway against the real responder — corrupt a key in the reply builder and a field in the Gateway's mapping; both must fail there.
5. Reply validated against `CatalogReferenceListReplyPayload` from the contract (key sets both ways, never retyped); money as integer minor units + currency.
6. Responder lifecycle: started and awaited by the lifespan, never leaves a request unanswered, own `AsyncSession` per request, read-only.
7. The registration guard's new Orders row and `test_write_path_population.py`'s count change (3 → 6): does the instrument still fail on what it claims?

## Process

Arm on copies in `.arm/r40/` (backup + `sha256`, `cmp` restore, clear caches; timeout kills the process group). Read-only: no source or test edit, no index-writing git command. Run `./quality.sh` once at the end (developer stack down): exit code, pytest time and pass count (implementer: one failure, the deleted Gateway test; 4 501 passed otherwise).

## Output

`progress/review_orders_catalog_responder.md`: verdict; blocking findings (surviving mutation + remedy); non-blocking with a disposition; your arming table; #8 D1, D2, A4, A5 avoided / recurred. APPROVED → feature 40 `done`; REJECTED → `in_progress` (that line only). Return only "result in `progress/review_orders_catalog_responder.md`" plus the verdict and at most 4 lines.
