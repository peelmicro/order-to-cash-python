# CHECKPOINTS — session-close criteria

> In multi-agent systems you do not evaluate the path, you evaluate the destination. These are objective checkpoints a judge — human or AI — can walk to decide whether the project is healthy. The `reviewer` agent walks C1–C7 and refuses to close a session while any box in an applicable section is empty.

## C1 — The harness is complete

- [ ] `AGENTS.md`, `CLAUDE.md`, `CHECKPOINTS.md`, `feature_list.json`, `init.sh` all exist.
- [ ] `progress/current.md` and `progress/history.md` exist.
- [ ] `.claude/agents/` holds leader, spec_author, implementer, reviewer, premise_checker, test_maintainer, suite_runner.
- [ ] **Every agent definition declares its model** — either `model:` in the frontmatter, or a description stating it deliberately inherits the session model.
- [ ] `./init.sh` exits 0.

## C2 — State is coherent

- [ ] At most **one** feature `in_progress` in `feature_list.json`.
- [ ] Every status is in `rules.valid_status`.
- [ ] Every `done` feature has passing tests associated with it.
- [ ] `progress/current.md` describes the active session or holds only the template — never leftovers from a previous session.
- [ ] Every `blocked` feature records *why* it is blocked.

## C3 — Architecture is respected

- [ ] No `sqlalchemy`, `asyncpg`, `aiokafka`, `nats`, `pymongo`, `fastapi`, `starlette` or `pydantic` import inside any `domain` package or `shared_kernel` — verified by running `lint-imports`, not by eye.
- [ ] No cross-service database access: no service reads another service's schema, and no foreign key crosses a service boundary. No service imports another service's package (import-linter's independence contract).
- [ ] No shared runtime code beyond `packages/shared_kernel`, `packages/contracts` and `packages/cqrs` (the third decided at the plan gate — #8 needed `src/Cqrs` for a DI package; #9's needs no dependency at all, but keeping it out of the kernel stops it widening what the domain may import).
- [ ] No `domain` package imports `otc_cqrs` — the dispatcher is an application-layer concern.
- [ ] `packages/shared_kernel` and `packages/cqrs` still declare `dependencies = []`.
- [ ] No `float`, `Decimal` or true division (`/`) in domain money arithmetic — `Money` is `int` minor units; `Decimal` only at presentation boundaries.
- [ ] Every inter-service interaction is classifiable as Kafka-fact or NATS-RPC per the decision matrix — no Kafka-as-request-bus, no RPC-for-facts.
- [ ] No stray debug logging, no context-free TODOs.

## C4 — Verification is real

- [ ] `./quality.sh` (ruff format + ruff check + mypy strict + import-linter + contracts drift check + pytest with coverage + web lint/test/build) passes.
- [ ] Domain tests are pure — no framework references, no DB, no broker.
- [ ] Integration tests use testcontainers-python against real Postgres / Kafka / NATS / MongoDB — not mocked brokers — and pass with the developer infrastructure down.
- [ ] Coverage thresholds met: **≥80% domain layer, ≥60% overall**.
- [ ] **No Jest, Karma or Jasmine anywhere.** pytest is the backend runner, Vitest the web one.

## C5 — The session closed cleanly

- [ ] No suspicious untracked files (`*.tmp`, build output outside `.gitignore`).
- [ ] `progress/history.md` has an entry for the feature just finished, **including its effort record** (sessions, wall-clock).
- [ ] `feature_list.json` reflects the true state of every feature touched.
- [ ] The human has been told **what was done** and **how to test it manually**.
- [ ] **Claude did not commit.** The commit is the human's, after testing.

## C6 — Spec-Driven Development

- [ ] Every `"sdd": true` feature in `spec_ready`, `in_progress`, `in_review` or `done` has `specs/<name>/` with all three of `requirements.md`, `design.md`, `tasks.md`.
- [ ] `requirements.md` uses strict EARS notation, every requirement carrying an `R<n>` id.
- [ ] Every `done` sdd feature has all its tasks ticked `[x]` in `tasks.md`.
- [ ] Every `R<n>` is covered by at least one concrete named test, recorded in `specs/shared/test-matrix.md`.
- [ ] The spec commit **precedes** the implementation commit in git history.

## C7 — Second-reuse fidelity and benchmark honesty (assessment #9 only)

#8 turned #7's C7 around, from *"is this reusable?"* to *"did it really reuse it?"*. #9 adds the question only a second reuse run can answer: *did the inherited review findings actually prevent anything, and is the three-way comparison honest?* These boxes are the evaluation criteria the Task names as specific to this assessment.

- [ ] **`specs/shared/` is still byte-identical to #8's and to #7's**, except `test-matrix.md`'s Status column, which records *this* assessment's realisation and is expected to name pytest/Vitest tests and Python paths. Verified with a real `cmp` against both checkouts (`init.sh` section 5d), not from memory.
- [ ] **Every deviation is a recorded `SA-n` amendment, in all three repositories.** No silent fork. Each amendment is its own commit in every repository, named in each README, and recorded in each `progress/history.md`.
- [ ] **The `R<n>` ids are #7's.** Where a requirement is claimed, the Python realisation genuinely satisfies the same requirement — a reused id is a claim about behaviour, not a convenient label.
- [ ] `n8n/workflows/*.json` are **unchanged** from #7/#8 apart from the base-URL environment variable, and **all four fire for real** against the Python Gateway — not one fired and three inferred.
- [ ] The black-box API script proves the **same** saga steps, the same facts and the same compensation as #7's and #8's.
- [ ] **Every inherited #8 finding is accounted for**: avoided (with its #8 backlog id cited in `progress/history.md`) or recorded as a recurrence. A reuse saving shows up as an absence, and an absence nobody writes down disappears from the comparison.
- [ ] `progress/history.md` effort records are complete and honest — **including the features that were not faster**, and, for every rejection, whether #7's or #8's review standard would have caught it. An all-green benchmark is not a result, it is a lack of measurement.
- [ ] The README's three-way benchmark section gives what the reused spec saved, what the reused harness saved, what the inherited findings saved, and what was not faster at all, in comparable detail — every figure re-read from the phase's own closing record in `progress/history.md`.

---

**How to use this file:** the `reviewer` agent walks each box, marks `[x]` or `[ ]`, and rejects the close if any applicable box is empty. Sections C3–C4 only apply once application code exists (phase 5 onwards); C6 only once a `sdd: true` feature has started (phase 8 onwards); C7's spec box from phase 3, the rest as their subjects come to exist.
