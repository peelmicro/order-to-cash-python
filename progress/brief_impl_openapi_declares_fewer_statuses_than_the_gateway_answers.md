# Brief — implementer, backlog 215 `openapi_declares_fewer_statuses_than_the_gateway_answers`, #9's code half of `SA-9` (phase 13, `sdd: false`, light)

**Task:** align #9's Gateway with the approved spec amendment **`SA-9`** (`specs/shared/openapi.yaml` as amended by the leader's `spec_author`; read the applied text and `progress/sa7_sa8_sa9_application.md`, not only `progress/proposal_sa9.md`). Backlog 215 is set `in_progress` by the leader at dispatch; its acceptance item 1 (the enumeration) is done (feature 26, `services/gateway/tests/unit/test_gateway_status_population.py`); item 2 is satisfied by `SA-9` plus this code half. Classification: **light** (as proposed at the gate: one mapping row, response declarations, test literals) — a Sonnet reviewer follows; say in your record if the change turns out larger, and stop if it touches anything beyond the Gateway's error mapping, its generated document and its tests.

## What changes (from `progress/proposal_sa9.md` "#9's code half", approved)

1. **An unreadable responder reply answers 503 `UPSTREAM_UNAVAILABLE`, as #7 and #8 do** (#8 `src/Gateway/Infrastructure/Messaging/NatsRpcClient.cs:82-85` + `Application/Ports/IRpcClient.cs:47-53`; #7 `apps/gateway/src/infrastructure/messaging/nats-rpc-client.adapter.ts:84-85` + `application/ports/rpc-client.port.ts:48-50`), replacing #9's `502 UPSTREAM_PROTOCOL_ERROR` (`services/gateway/src/otc_gateway/domain/rpc_error_classification.py`, `PROTOCOL_ERROR`). Decide, with a reason, whether the Problem `code` is `UPSTREAM_UNAVAILABLE` (parity) and whether the `detail` still says the reply was unreadable (it may — the amended `UpstreamUnavailable` text now covers "a reply the Gateway could not read"). Every test asserting 502 / `UPSTREAM_PROTOCOL_ERROR` is updated (enumerate them with a grep first, and the population test's literals).
2. **The Gateway's generated OpenAPI document declares the `default` response** on every route, so `services/gateway/tests/**/test_openapi_conformance.py` still compares like with like against the amended committed `openapi.yaml` — read first what that test compares (statuses or not) and keep it falsifiable both ways.
3. **`test_gateway_status_population.py`:** with `default` on every operation every observed pair is declared (by name or by `default`); restate what the test asserts so it still fails on something real — e.g. every operation in the committed contract carries `default`, the by-name declared set is unchanged, and the pairs answered only through `default` equal a literal (so a new undeclared-by-name status is still visible and named) — and update its docstring and the literals' citation of backlog 215 to the closed state.

## Arms (each a named test, the message names the claim)

- revert the mapping to 502 → a test fails naming the unreadable-reply case;
- drop `default` from one route of the Gateway's generated document → the conformance test fails;
- add a new by-name-undeclared status source → the population test still names the pair.

## Process

CLAUDE.md on disk is binding. Backups in `.arm/n215/` (`sha256`, `cp` + `cmp`, caches cleared, timeouts kill the process group). One `./quality.sh` at the end (developer stack down; exit code, pytest time and pass count, time per test; wait on the real PID). Write `progress/impl_openapi_declares_fewer_statuses_than_the_gateway_answers.md`.

## Bounds

May touch: `services/gateway/**` and the impl record; backlog 215's status line in `feature_list.json` (→ `in_review`). Nothing in `specs/`, `packages/`, other services. No git command that writes the index or working tree. Return only "result in `progress/impl_openapi_declares_fewer_statuses_than_the_gateway_answers.md`" plus at most 3 lines.
