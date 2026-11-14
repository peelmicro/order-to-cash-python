# Implementation record: entry 217 `mongo_container_ready_before_its_real_server` (LIGHT, test-only)

## Population (re-derived)

`grep -rn "MongoDbContainer(" tests services packages conftest.py --include=*.py`:

- `conftest.py:244` (session `mongo_server`): fixed
- `tests/observability/health_support.py:156` (`private_mongo`): fixed
- `services/gateway/tests/integration/test_gateway_degraded.py:280`: fixed
- `tests/observability/test_mongo_readiness.py:40`: the new guard, which waits through the helper itself

3 production sites, same as at filing.

## Change

- One helper, `wait_until_mongo_answers(container, username, password, budget_seconds=60)` in `tests/observability/health_support.py`. It opens a sync `pymongo.MongoClient` on the host's mapped port with the test's credentials, runs `admin.command("ping")` with `serverSelectionTimeoutMS=500`, and sleeps `POLL_INTERVAL_SECONDS` (0.25 s) between attempts. Past the budget it raises `TimeoutError` carrying the last error. `private_mongo()` calls it.
- Reached by `importlib` from a path, as the support modules already are: `test_gateway_degraded.py` already had `health_support()`, and `conftest.py` got a small `_health_support()` loader (`Path(__file__).parent / "tests/observability/health_support.py"`).
- Guard: `tests/observability/test_mongo_readiness.py`.
  - `test_n217_the_first_authenticated_ping_through_the_mapped_port_succeeds_at_once`: real container, helper, then an immediate ping with a 300 ms selection timeout.
  - `test_n217_the_wait_is_paced_and_bounded_when_every_ping_fails_in_microseconds`: a client that fails in microseconds (change of kind from the real 500 ms timeout) shows the 0.25 s gaps, the attempt count and the budget bound.
- Lint fixes along the way: `conftest.py` raises instead of `assert` (S101); line length; `itertools.pairwise`.

## Arm

Backup `.arm/n217/health_support.py`, sha256 `d79d92f7702d65be0918c42ed1d39fe52d18f1a47ecadf659159a5923a9097a9`. Violation: a `return` at the top of the helper body (equivalent to the library-only wait). The first test, run 3 times, failed 3 of 3:

`pymongo.errors.ServerSelectionTimeoutError: localhost:34017: [Errno 104] Connection reset by peer ... Timeout: 0.3s` (ports 34017, 34019, 34022).

The ratio is 3/3, so the 5 s window does not make the arm unreliable. Restored from the backup, `cmp` clean, `__pycache__` cleared, green (2 passed).

The pacing test was not armed separately (not the claim of the arm requested); its assertions fail if the sleep is removed (gaps and attempt count).

## Verdicts

- `test_gateway_health_probes.py`, 3 consecutive runs (`setsid --wait`): 2 passed each (10.35 s, 10.42 s, 10.52 s), exit 0. Logs: `.arm/n217/gw{1,2,3}.log`. It failed 3 of 3 before the fix, per the brief. The load was the leader's measured `llama-server`, left running.
- `./quality.sh`, developer stack down (only an unrelated `kb-poc-*` project's containers were up):
  - Run 1: red. 1 failed, 5286 passed (24:01) on `test_gateway_shutdown_with_open_streams.py::test_or13...`, an `httpx.ConnectError` from the test to its spawned Gateway child on fixed `PORT`, after "startup complete". It is not a Mongo path (`mongo_server` had already pinged); it passed alone twice (18.18 s, 17.99 s). Log: `.arm/n217/quality_run1.log`.
  - Run 2: `quality.sh: all gates passed`, 5287 passed in 1863.49 s (0:31:03), web 687 tests in 35 files passed, coverage 96.42%. Log: `.arm/n217/quality.log`.
  - Open observation: the `or13` test looks flaky under load. Not investigated or touched (out of bounds); the leader may want an entry.

## Questions

- Sync `MongoClient` in a sync fixture: acceptable. `CLAUDE.md` forbids a sync driver in a service runtime; this is test support, and the helper is not imported by any `services/*/src`. In the async `test_gateway_degraded` test it blocks the loop only for the few seconds before any task of the test exists.
- `mongo_server` loop-scope note: no change needed. The fixture is sync (no loop), and the helper creates and closes its clients inside the call.

Files touched: `conftest.py`, `tests/observability/health_support.py`, `services/gateway/tests/integration/test_gateway_degraded.py`, new `tests/observability/test_mongo_readiness.py`, `feature_list.json` (line 921 only: `in_review`). `specs/shared/test-matrix.md` unchanged (entry 217 has no `R<n>`).

Packages installed: none
