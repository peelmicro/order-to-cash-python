# Brief — implementer, entry 217 `mongo_container_ready_before_its_real_server` (phase 18, LIGHT, test-only)

**Task:** entry 217 in `feature_list.json`: three acceptance items. Read the entry's `note`: it holds the mechanism, measured by the leader this session.

## What the leader measured (commands run this session)

- `services/gateway/tests/integration/test_gateway_health_probes.py` failed 3 of 3 runs at about 16:40 on 2026-10-18, in both cases (`[rpcTransport]` and `[readModel]`). The error was `pymongo.errors.ServerSelectionTimeoutError: localhost:<port>: [Errno 104] Connection reset by peer ... Timeout: 1.0s`. It is raised at the Gateway's boot ping (`services/gateway/src/otc_gateway/composition.py:289`, reached through `test_gateway_health_probes.py:82`), before any pause.
- `docker run -e MONGO_INITDB_ROOT_USERNAME=u -e MONGO_INITDB_ROOT_PASSWORD=p mongo:8.3.8` logs "Waiting for connections" twice:
  - first from the init `mongod`, on `127.0.0.1:27017` only;
  - then, 5.2 s later, from the real one on `0.0.0.0:27017`.
- `testcontainers.community.mongodb.MongoDbContainer` waits for the first line (`LogMessageWaitStrategy`, `.venv/lib/python3.14/site-packages/testcontainers/community/mongodb/__init__.py:62`).
- At filing, the population is three sites: `conftest.py:228` (session `mongo_server`), `tests/observability/health_support.py:111` (`private_mongo`) and `services/gateway/tests/integration/test_gateway_degraded.py:280`.
- The machine is loaded by another project's `llama-server` (about 7 of 16 cores). Do not stop it. The fix must hold under that load.

## Must hold

1. Re-derive the population with a command (`MongoDbContainer(` over `tests/`, `services/`, `packages/` and `conftest.py`, excluding `.venv` at the source). Every site must yield only after an authenticated `ping` succeeds through the **host's** mapped port, with the same credentials the tests use. The wait is bounded and paced, and the pacing is proven by a change of kind (`CLAUDE.md`: retry loops). One helper, not three copies, if the import mechanics allow it; the support modules are loaded by `importlib` from paths, so say how the helper is reached.
2. A guard test, fast and with no fleet, that fails when the fix is removed. It starts a container through the readiness helper, then pings at once with a short server-selection timeout. Arm it once by restoring the library-only wait (arming protocol in `CLAUDE.md`, backups in `.arm/n217/`). If the 5 s window makes the arm fire unreliably, say so and show the ratio.
3. Run `test_gateway_health_probes.py` three consecutive times (`setsid --wait`, wait on the PID), then `./quality.sh` once (developer stack down). Report both verdicts from the logs.

Questions to answer in the record: is a sync `pymongo.MongoClient` acceptable in a sync fixture (`CLAUDE.md` forbids a sync driver in a *service runtime*)? Does the session `mongo_server` fixture's loop-scope note need a change?

## Bounds

You may touch the three sites, one new helper (if needed) and one new guard test file, `progress/impl_mongo_container_ready_before_its_real_server.md`, and entry 217's `status` line in `feature_list.json` (set it to `in_review`). Nothing else:
- no edit under `services/*/src/**`, `packages/**` or `tests/api/**`;
- no change to feature 31's lines;
- no git command that writes the index or the working tree.

## Output

Write `progress/impl_mongo_container_ready_before_its_real_server.md` with:
- the population command and its output;
- the change;
- the arm (verbatim failure, `sha256`, `cmp`);
- the three runs and the `quality.sh` verdict (counts, wall time);
- `Packages installed:`.

Return only the file reference plus at most 3 lines.
