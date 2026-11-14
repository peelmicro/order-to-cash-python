# Implementation record: entry 218 `booted_predicate_fires_before_the_socket_listens` (LIGHT, test-only)

## Population

`grep -rn "booted\|startup complete" --include=*.py tests services packages` (src excluded) gave 8 `support.booted` waits in 7 files; each is followed by HTTP calls (connects afterwards). All 8 are fixed by the one change below:

- `test_{orders,billing,fulfillment,projector,notifications,gateway}_log_contract.py` (6 sites)
- `test_gateway_shutdown_with_open_streams.py:109` (or13)
- the remaining `startup complete` hits are the `LIFECYCLE_PREFIXES` entry (a filter for unit-id binding, unchanged) and the predicate itself. `test_orders_host_sigterm.py` has a local `booted` variable (a connect loop), not a wait on the line; `test_gateway_listens_on_gateway_port.py:141` reads "Uvicorn running on" from output.

## Change

In `tests/observability/log_contract_support.py` only (no consumer edited):

- `startup_complete(line)`: the old predicate (uvicorn's "Application startup complete.", logged before the bind).
- `booted(line)`: now matches uvicorn's "Uvicorn running on ..." line, logged by `_log_started_message` after `create_server` has bound the socket.
- The "Uvicorn running on" line reaches the JSON stderr: all 8 sites wait on it through `wait_for_event`, which fails on a non-JSON line or a timeout, and they pass (below). Nothing asserts the startup line apart from the unchanged `LIFECYCLE_PREFIXES`.

Guard: `tests/observability/test_booted_predicate.py::test_n218_booted_matches_only_once_the_socket_accepts_and_startup_complete_comes_first`. It starts a real uvicorn child (JSON log config), then asserts the lifespan line precedes the listening line, `booted` rejects the lifespan line and `startup_complete` rejects the listening line, and a connect succeeds after `booted`. Limit: the gap between the two lines is microseconds, so the race itself cannot be observed deterministically; the guard tests the predicate and the line order.

## Arm

Backup `.arm/n218/log_contract_support.py` (original) sha256 `86129b38b6ea54a1d27ae84e85991cdc0a19f6184a7de1ff013f7840f091eb27`; fixed copy `.arm/n218/fixed.py` sha256 `c5949a4c0c8e36608f79f089710839f7058e3310328fcf545d2399c50add7c5e`. Violation: `booted` returns `startup_complete(line)`. Failure verbatim:

`AssertionError: booted matches the lifespan line: it races the bind` / `where True = <function booted ...>({'logger': 'uvicorn.error', 'event': 'Application startup complete.'})`

Restored from the backup, `cmp` clean, `__pycache__` cleared, green.

## Verdicts

- or13 + the six log-contract tests + the guard, 3 consecutive runs (`setsid --wait`): 9 passed each (58.26 s, 50.59 s, 49.23 s), exit 0. Logs `.arm/n218/run{1,2,3}.log`.
- `./quality.sh` once: `all gates passed`, 5288 passed in 1452.18 s (0:24:12), web 687 passed. Log `.arm/n218/quality.log`.

Files touched: `tests/observability/log_contract_support.py`, new `tests/observability/test_booted_predicate.py`, `feature_list.json` (entry 218 status line only). Packages installed: none
