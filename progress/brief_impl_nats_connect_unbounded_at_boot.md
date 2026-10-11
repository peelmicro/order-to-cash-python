# Brief — implementer, backlog 214 `nats_connect_unbounded_at_boot` (phase 12, `sdd: false`, **light**)

**Task:** satisfy the two acceptance items of `feature_list.json` id 214 (read them, and its `note`). Write `progress/impl_nats_connect_unbounded_at_boot.md` (what changed, the three arms with their verbatim failures, the green runs) and return a summary of at most 8 lines. **Do not edit `feature_list.json`** — this is a light change; the leader reads the diff, runs the tests and closes it. Read `CLAUDE.md` on disk first.

## Verified by the leader this session

- `services/orders/src/otc_orders/composition.py:333`, `services/fulfillment/src/otc_fulfillment/composition.py:282`, `services/billing/src/otc_billing/composition.py:290` each call `await nats.connect(settings.nats.url)` with nats-py's defaults (`DEFAULT_MAX_RECONNECT_ATTEMPTS = 60`, `DEFAULT_RECONNECT_TIME_WAIT = 2`, `DEFAULT_CONNECT_TIMEOUT = 2`, read from `nats.aio.client` this session).
- The pattern to copy is feature 24's, just approved: `services/projector/src/otc_projector/composition.py` — `NATS_CONNECT_SECONDS = 10.0` (`:67`), `connect_nats` (`:136-158`: the caller owns the `NatsClient` and closes it on any `BaseException`, so a bound that cancels the connect leaves no task — `progress/impl_projector_read_model.md` §4.2 finding 7), and the bounded call in `start_runtime` (`:320-330`: `asyncio.timeout`, re-raised as `RuntimeError` naming `NATS_URL` and the bound). Its tests: `services/projector/tests/unit/test_composition.py:261` and `services/projector/tests/integration/test_projector_lifespan.py:51`.

## Bounds

- Edit only the three `composition.py` files and add/extend tests under each of those three services' `tests/`. No shared helper (CLAUDE.md: no shared runtime code outside `packages/`); each service carries its own copy, matching the projector's shape. Runtime reconnect behaviour stays as the defaults (only the boot connect is bounded). Keep each service's existing NATS callbacks/arguments if it passes any.
- If a service's lifespan has a keyword override seam for bounds (Notifications/Projector shape), use it so the test can use a short bound; otherwise add one in the same shape. Each test waits under its own `asyncio.timeout(...)` with a message naming the claim, and asserts the error names `NATS_URL` and that no task is left (as `test_pr45_…` does). A closed port must be Docker-held or provably closed, never picked free and released.
- Arms (one per service): remove the bound; the service's new test must fail, fast, naming the claim. Arming protocol: `.arm/n214/`, sha256, `cp` + `cmp` restore, clear `__pycache__`/`.mypy_cache`, process-group kill on timeout.
- Verification: the three services' test suites, `tests/architecture` (the composition env-read guard), `ruff`, `mypy --strict` over the workspace. Do **not** run `quality.sh`; the leader runs it. No git command that writes the index or working tree.
