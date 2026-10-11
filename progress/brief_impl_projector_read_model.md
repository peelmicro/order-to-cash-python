# Brief — implementer, feature 24 `projector_read_model` (phase 12)

**Task:** implement feature 24 from its approved spec, `specs/projector_read_model/{requirements,design,tasks}.md`, ticking every box of `tasks.md` (or rewording it, argued on the box). Write your report to `progress/impl_projector_read_model.md` as you go — not at the end — and return a summary of at most 15 lines naming that file. When every task is done, set feature 24's `status` line in `feature_list.json` from `in_progress` to `in_review` (edit that one line only, then read `git diff feature_list.json`). Read `CLAUDE.md` on disk before starting.

## The gate (2026-10-11, maintainer: "Approved")

The ruling is appended at the end of `progress/spec_projector_read_model.md` ("Gate ruling"). In short: **G1 = option (b)** (task O3 takes the (b) branch); **R1 ratified** (task O2); no other change to the spec.

## State of the working tree when you start (not yours; do not revert, do not "fix")

- **`SA-6` is applied but uncommitted**: `specs/shared/openapi.yaml` (the `TimelineEntry.causationId` description), and the two regenerated header lines of `packages/contracts/src/otc_contracts/generated/{openapi,nullable}.py`; plus `README.md`, `CLAUDE.md`, `AGENTS.md`, `progress/history.md`, `progress/current.md`. Record: `progress/sa6_application.md`. Task O3's note that the SA-6 text is not this feature's is satisfied.
- **Task A3 is done by the leader:** `.env.example` has the Projector block (`PROJECTOR_KAFKA_CLIENT_ID=otc-projector`, `PROJECTOR_CONSUMER_GROUP=projector`). Verify it with `grep` and record it in the report; do not edit `.env.example`.
- **`feature_list.json`** has a new pending entry, id **214** (unbounded `nats.connect` in Orders/Fulfillment/Billing). It is **not** this feature's work — leave those three `composition.py` files alone; it runs after you.

## Bounds

`tasks.md`'s "Files this feature may touch" and "Must not touch" lists are binding; this brief adds nothing to them. If anything in this brief conflicts with `tasks.md`, `tasks.md` wins: stop and report the conflict. No git command that writes the index or working tree (`stash`, `reset`, `restore`, `clean`, `checkout`); use `git show HEAD:<path>` to read committed content. Arming follows `CLAUDE.md`'s protocol (backups in the repo-local `.arm/`, sha256, `cmp` on restore, process-group kill on timeout).

## The live walkthrough (task N2 and its neighbours)

Start the developer stack with `docker compose -p otcpy -f docker-compose.infra.yml start` only when you reach those tasks, and stop it again (`... stop`, leaving `otcpy-n8n` running) when you finish them. Read `progress/current.md` "Live dev data" first: the altered fixtures, `ORD-000007` stalled at `confirmed`, and the **16 duplicate fact records** on the three fact topics — record the topic contents before the replay. Never run a test suite while the stack is up and another run is using it.

## Lessons from Phase 11 (already in `tasks.md`; repeated because they cost time)

- Bound every wait with `asyncio.timeout(...)` and a message naming the claim: this project's pytest has no timeout plugin, and a missing `task.cancel()` hung a test indefinitely (N1).
- Name the restart every test performs (in-process rebuild vs new group vs process restart) (N2).
- Ledger rows: file:line on both halves, "none owed" too (N3).
- Do not set `in_review` with open TODOs in the report. If you hit a blocker, write it into the report and return; do not leave a half-set status.
- Write the report incrementally: if you are interrupted, the file must show where you were.
