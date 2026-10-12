# Proposal `SA-9` — every Gateway status is declared, and `UpstreamUnavailable` stops promising "not applied" (backlog 215)

**Status:** proposed by the leader, Phase 13 (2026-10-12), for the maintainer's gate. Not applied.

## The population (backlog 215 acceptance 1, done)

Enumerated by feature 26's implementer and checked by its reviewer: `services/gateway/tests/unit/test_gateway_status_population.py` derives every `(operation, HTTP status ≥ 400)` pair the #9 Gateway can answer through four doors (the error classifier, every handler `raise` site by AST walk, the request-validation handler, the cold app without a lifespan) and sets it against what `specs/shared/openapi.yaml` declares (record `progress/impl_gateway_sse_push.md` §9 and its Round 2; output `.arm/n26r2/status_population.out`):

| | pairs |
|---|---|
| observed (status ≥ 400) | **100** |
| declared | 41 (none declared-but-unreachable) |
| **undeclared** | **59** |
| — responder codes passed through the shared `RpcError` table (e.g. `POST /orders` 404 for unknown reference data, `GET /stock` 409 / 422) | 25 |
| — Gateway-originated: malformed query / path parameter 400, the fallthrough 500, read-model outage 503 on `GET /orders` and `GET /orders/{id}` | 20 |
| — Gateway-originated, **#9-only**: `502 UPSTREAM_PROTOCOL_ERROR` on the ten RPC-backed operations (a responder reply that does not decode) | 10 |
| — reachable only without a lifespan (`GET /auth/me`, `GET /docs`, `POST /auth/login`, `GET /orders/stream` → 503; uvicorn never serves before startup completes) | 4 |

**#7 and #8 answer the same 45 non-#9-only pairs** (the same twelve-row `RpcError` table: #7 `apps/gateway/src/domain/problem/rpc-error-mapping.ts:37-71`, #8 `src/Gateway/Domain/Problem/RpcErrorClassification.cs`). For a reply that does not decode they answer **503 `UPSTREAM_UNAVAILABLE`** through their transport error (#8 `Infrastructure/Messaging/NatsRpcClient.cs:82-85` with `Application/Ports/IRpcClient.cs:47-53` `Code => "UNAVAILABLE"`; #7 `infrastructure/messaging/nats-rpc-client.adapter.ts:84-85` with `application/ports/rpc-client.port.ts:48-50`). The gap is the contract's, inherited by all three builds; only the 502 is #9's.

## A second defect the enumeration exposed — the 503 promise

`components/responses/UpstreamUnavailable` says: *"The owning context did not answer within the deadline, or the RPC transport is unreachable. The command was **not** applied; the client may retry."* That holds for "no responder" (nothing received the request) but **not after a timeout**, where the responder may have applied the command and answered late — nor for a reply that does not decode, where the responder ran. It matters: `POST /stock/replenish` is *"deliberately **not** idempotent"* (`openapi.yaml`, the operation's description) and declares this 503, so a client following the contract retries a top-up that may already have happened and adds the stock twice. Leader-verified in the YAML.

## The change (`openapi.yaml`, three parts)

**A. One `default` response on every operation**, referencing a new shared response:

```yaml
    UnlistedProblem:
      description: |
        Any status this operation does not list. The body is always a
        `Problem`. A 4xx is a request the Gateway or the owning context refused
        (an unknown reference, a malformed parameter, a domain rule); a 5xx is
        a failure in the Gateway or upstream. The listed statuses are the ones
        a client is expected to handle by name; this one exists so that no
        status the system can answer is outside the contract.
      content:
        application/problem+json:
          schema:
            $ref: '#/components/schemas/Problem'
```

Why `default` rather than listing the 59 pairs: the 25 pass-through pairs are each responder's choice through one shared table, so listing them per operation would couple the REST contract to every context's error choices and go stale with the next one; `default` is OpenAPI's own construct for "anything else", declares every pair honestly, and needs **no code change in #7 or #8**.

**B. `UpstreamUnavailable`'s description corrected:**

```yaml
      description: |
        The owning context could not be reached, did not answer within the
        deadline, or answered with a reply the Gateway could not read. When no
        responder was reachable the command was not applied; after a timeout
        or an unreadable reply it may have been. A client may retry an
        idempotent operation (one with an `Idempotency-Key` or a natural key
        such as `paymentReference`); before retrying any other it should
        re-read the resource.
```

**C. `/stock/replenish`'s description** gains one sentence: *"A `503` after a timeout does not mean the top-up was not applied: re-read `GET /stock` before retrying."*

## #9's code half (backlog 215, in this phase, light)

- **Restore parity for the unreadable reply: 503 `UPSTREAM_UNAVAILABLE`**, as #7 and #8 answer — part B makes that status's text true for it, so the #9-only 502 no longer buys honesty and only costs comparability. (The alternative — keep 502 and declare it by name — would put a status in the shared contract that two of three builds never answer.)
- The Gateway's generated document declares `default` per route so `test_openapi_conformance.py` still compares like with like; `test_gateway_status_population.py`'s undeclared literals become empty (every pair is then declared, by name or by `default`), armed by planting a pair outside both.
- Implementer + Sonnet reviewer (light: one mapping row, response declarations, test literals); or, if you rule the Gateway's contract work full group, Opus.

## Recommendation

Approve `SA-9` (parts A – C) byte-identically in #7, #8 and #9, committed on its own in each, with a registry row and a history entry in each. #7's and #8's code needs **no** change for A – C. #9's code half as above, in this phase.
