# Brief — implementer, feature 14 `outbox_and_idempotency` (phase 8, full group)

**Task:** implement `specs/outbox_and_idempotency/` (approved at the human gate on 2026-10-06, with G1 and G2 decided as recommended — `design.md` §12.1) by working through `specs/outbox_and_idempotency/tasks.md` in order, ticking each box as it is done. The spec is the authority: where this brief and the approved `tasks.md` disagree, the spec wins — stop and report the conflict rather than picking a side. Feature 14 is `in_progress` (set by the leader).

## Inputs

- `specs/outbox_and_idempotency/{requirements,design,tasks}.md`. The `tasks.md` preamble lists the files this feature may and must not touch; that list is the bound (it includes adding `aiokafka` to `services/orders/pyproject.toml` and `uv.lock`, and the named architecture-test and `pyproject.toml` edits).
- Feature 13's aggregate and events (`services/orders/src/otc_orders/domain/`) and feature 43's `otc_cqrs` are done and must not be edited (they are on the "must not touch" list).

## Process (full group: persistence, wire contract)

- Every `[ARM]` task under the CLAUDE.md arming protocol (cp backup, mutation, ONE named test, verbatim failure naming the claim, restore, `cmp`, clear caches, re-run green). Never `git checkout`/`restore`/`stash`. Record each arm in a table in the report.
- Arm field corruption on **every** constructor call that maps values into a fact, an envelope, a row or an aggregate (feature 13's review lesson: ten single-field corruptions survived there). Enumerate those call sites first and list them in the report.
- The skip-versus-block measurement (tasks.md) is a measurement: record the numbers, with the guard armed the other way.
- Integration tests use testcontainers with Docker-assigned ports. The leader **stopped** the developer stack `otcpy` for this feature (`docker compose -p otcpy -f docker-compose.infra.yml stop`); only `otcpy-n8n` remains, on 5678, and no Kafka/Postgres/NATS/Mongo port is listening (`ss -ltn`). That is the state task 2.1 needs (#8 id 104: a developer Kafka on 9092 hid a dependency). Do not start the stack. Task 2.1's run with the stack down and its arm (bootstrap pointed at `localhost:9092` must fail) are yours, as `tasks.md` says; no fixed host port anywhere in a fixture.
- Run the defeat list against your guards and state which rows apply.
- Before finishing: `./quality.sh` once (exit, duration, pass count, and that the stack was down), per-file counts summing to the headline. Every package added goes in the report's "Packages installed" list.

## Output

- `progress/impl_outbox_and_idempotency.md`: what was built, every file touched, the ported-idiom ledger rows whose guard changed from `design.md`, the arming table, the constructor-call census, the skip-versus-block numbers, defeat-list rows, figures with commands, packages installed, and every divergence from the spec with its reason.
- Set feature 14 to `in_review` (that line only). No git writes, no commit.
- Return only "result in `progress/impl_outbox_and_idempotency.md`" plus at most 5 lines.
