# messaging_topology (id 5, phase 4) — implementation record

**Process:** light (infra config). Closed by the leader; no reviewer.

## What was built

Nothing new. `infra/kafka/create-topics.sh` and its Dockerfile are #8's, `cmp`-identical to #8's and #7's; the script parses the topic list from `specs/shared/asyncapi.yaml` at run time and fails unless the broker's non-internal topic set is exactly the spec's, with the configured partition count and replication factor. NATS runs core-only with #8's command line.

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Guard (armed) |
|---|---|---|---|---|
| Topics derived from the spec, exact set | `kafka-init` + `create-topics.sh` (`order-to-cash-nestjs/docker-compose.infra.yml:154`) | the same script, `cmp`-identical | the same script, `cmp`-identical (`docker-compose.infra.yml:203`) | planted `otc.orders.facts.v2` → rc=1, `FATAL: the broker's topic set does not match the spec exactly.` with expected/actual lists; deleted → rc=0 |
| NATS core-only | `command: ["-p", "4222", "-m", "8222"]` (`nestjs/docker-compose.infra.yml:240`) | same (`dotnet/docker-compose.infra.yml:274`) | same (`docker-compose.infra.yml:278`) | `nats stream add` → `no responders available`; armed against a throwaway `nats:2.14.5-alpine -js` → `Stream PROBE was created` |

Python-port questions: **not applicable** — no Python code.

## Verification (2026-10-04)

- **Channels, all 36 classified by each channel's `servers` reference** (not by `bindings`: only the 6 Kafka channels carry bindings, and a first classifier that keyed on bindings put all 30 NATS channels in an unclassified bucket — the instrument did not recognise the form): `kafka`/addressed 6, `nats`/addressed 15, `nats`/`address: null` 15. No channel outside those three classes.
- **Kafka:** spec 6 = broker 6 = Redpanda Console API 6 (`/api/topics`, non-internal) — `otc.{orders,fulfillment,billing}.facts.v1` and their `.dlq`; each 6 partitions, RF 1. `kafka-init` re-run is idempotent (rc=0, "no others").
- **NATS requests:** 15 in the spec vs the plan's 15-subject list as a literal — spec − plan = ∅, plan − spec = ∅. Every request channel has its `<name>Reply` channel and every reply has its request.
- **NATS core works:** `nats reply` / `nats request` round trip on the stack's server → `pong-from-core`, rc=0 (the control for the refusal above).

## Inherited #8 findings

- `/varz | grep jetstream` offered as proof of core-only, which matches with JetStream on and off (#8 phase 4, caught at the human gate) → **avoided**: verified by asking for the refused operation, and the check was itself armed against a JetStream-enabled server.
- The plan's NATS table missing `billing.credit.release` (#8 phase 4) → **avoided**: 15/15 by set difference against the spec.
