# Brief — reviewer, feature 24 `projector_read_model` (phase 12, `sdd: true`, full group)

**Task:** adversarial review of feature 24 against its approved spec `specs/projector_read_model/{requirements,design,tasks}.md`, the gate ruling at the end of `progress/spec_projector_read_model.md` (G1 = (b), R1 ratified), its eight acceptance items (`feature_list.json` id 24), `specs/shared/` R50 – R55, and `CHECKPOINTS.md`. The implementation record is `progress/impl_projector_read_model.md` (6394 lines; sections 0 – 11; §10 is the verbatim arm ledger, 133 blocks); arming artefacts are under `.arm/p24/`. Feature 24 is `in_review`. Round 1. Read `CLAUDE.md` on disk first.

## Verified by the leader this session (do not re-derive; do re-check anything your verdict rests on)

- `feature_list.json`: 24 is `in_review`, 214 is `pending` (214 was added by the leader at the gate; it is not this feature's work).
- `git diff specs/shared/test-matrix.md` changes the §7 summary row (`6 | 4 | 0 | 2`), the total row (`46 | 1 | 16`) and rows R50 – R55; check that only column 5 of those rows changed.
- The working tree also carries **`SA-6`** (uncommitted, not this feature's: `specs/shared/openapi.yaml`, two regenerated header lines in `packages/contracts/.../generated/{openapi,nullable}.py`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `progress/history.md`; record `progress/sa6_application.md`) and the leader's task A3 (`.env.example`). Do not review those as part of 24, except that SA-6's text must agree with what 24 does with `causationId`.
- The record claims `quality.sh` green twice (exit 0; 541 s and 491 s; `4075 passed`; logs `.arm/p24/quality1.log`, `quality2.log`; baseline 428 s, 3782 passed). Only `otcpy-n8n` is running.

## Questions the review must answer (each with a command or a mutation, not by reading the record)

1. **Causal ordering (acceptance 1, PR10, PR30 – PR35):** run your own fixture where arrival order, `occurredAt` order and the causal edge all differ, including a tie group with a chain of three and a fallback pair; does the stored order match the shared rule in `openapi.yaml`'s `TimelineEntry` description, and does a test fail when the edge is ignored?
2. **Out-of-order and replay (acceptance 2, R52, PR38):** does replaying a topic through Kafka (not an in-process call) reproduce a byte-identical document, and which restart does each test perform? Does the status never regress and a newer reference never get overwritten?
3. **Idempotency and the parity guard (PR23 – PR26, PR48, F1 – F3):** the record says the Orders parity guard now takes a literal registry cross-checked with `asyncapi.yaml` consumers. Is the population fixed by that literal and not by the thing under test? Remove the projector from the registry, delete its conformance file, drop the `$ne` dedup filter (E5): which tests fail, and does any stay green that should not?
4. **Indexes (acceptance 3, PR22, PR52):** are they created at boot and compared against the server's stored specification? Substitute a sibling (a plain unique index already present, a different partial filter): does boot fail with a message naming the index?
5. **Update signal (acceptance 4, R55 projector half, PR17 – PR19, PR42, PR45):** exactly one signal per applied fact, none for a suppressed redelivery; the NATS connection established in `start_runtime` within the bound; an unreachable NATS fails the boot fast.
6. **SA-2 (acceptance 5, PR46/PR47):** the note reaches the cancellation entry on every compensation branch; a `$`-prefixed note is stored verbatim (the latent #7/#8 defect).
7. **Constants pin (acceptance 6, PR40):** bump the projector's version alone, then its status-rank table, then its prefix: does each fail a named test reading `tests/fixtures/read_model_constants.json`?
8. **Registration guard (acceptance 8, PR27, PR49):** the `projector` rows in `tests/architecture/test_registration_behaviour.py` and the F-g + F-j fixture, armed against this service's composition root.
9. **The three accepted survivors** (record §4.2 findings 1 – 3: the unreachable `DuplicateKeyError` retry, the never-binding `$min` cap, the redundant `$sortArray`): is each truly equivalent or unreachable, or is a test missing? Each disposition must carry a re-open trigger.
10. **Record §4.2 finding 4 (live data):** `ORD-000007` is `confirmed` in Orders' write model (`progress/current.md`), yet it projects `despatched` because an `order.despatched.v1` for it is on the topic. Establish by command which is true of the facts on the topic and whether the projection is correct per R52; if the write model and the topic disagree, say which feature owns that and classify it.
11. **Record §4.2 finding 5 (test isolation):** the session-wide test Kafka carries every service's facts, and the projector's runtime tests now use private topics. Do any other suites (Orders', Notifications') have the same exposure today, and is it a defect now or only when feature 27 lands? Give it a disposition.
12. **Ported-idiom ledger (design §10, record §3):** spot-check at least eight rows across the Python questions (loop affinity, cancellation, `Any` leakage, timestamp format, integer widths): does the named guard execute the code the row is about?
13. **Avoided / recurred** for every #7 / #8 finding the spec lists (design §13, the 27-hit #8 backlog table; #7's and #8's review classes in the gate record §6 note 5).

## Rules

Read-only: never edit source, tests or `feature_list.json` except feature 24's status line (`done` on approval; `in_progress` on rejection). Mutations follow CLAUDE.md's arming protocol: backups in `.arm/p24-review/` with `sha256`, restore by `cp` + `cmp`, clear `__pycache__` / `.mypy_cache`, never `git checkout`; never two test runs against the same containers at once; a timeout kills the process group. The developer stack stays stopped (start it only for question 10 if a command needs it, and stop it after, leaving `otcpy-n8n`). Every finding gets a disposition (fix / accept with evidence and a re-open trigger / SA-n proposal) and names its unit. No git command that writes the index or working tree. Bound every wait you write with `asyncio.timeout(...)`.

## Output

`progress/review_projector_read_model.md`: verdict (APPROVED / REJECTED), blocking and non-blocking findings with the mutation or command that proves each, the answers to questions 1 – 13. Write it incrementally. Return only "result in `progress/review_projector_read_model.md`" plus the verdict and the count of blocking findings.
