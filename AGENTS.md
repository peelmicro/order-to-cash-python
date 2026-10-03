# AGENTS.md — Navigation map for AI agents

> This file is the **entry point** for any agent working in this repository. It is not a rulebook — it is a **map**. Read only what you need, when you need it (progressive disclosure).

---

## 1. Before you start (mandatory)

1. Run `./init.sh` and check it exits 0. If it fails, **stop** and fix the environment before touching anything.
2. Read `progress/current.md` to see where the last session left off.
3. Read `feature_list.json`. Any feature with `"sdd": true` goes through **Spec-Driven Development** — see §4.
4. Read `CLAUDE.md` for the project conventions before writing code.

## 2. Repository map

| File / folder | What it holds | When to read it |
|---|---|---|
| `feature_list.json` | Backlog with state machine (`pending` / `spec_ready` / `in_progress` / `in_review` / `done` / `blocked`) | Always, at the start |
| `progress/current.md` | State of the active session | Always, at the start |
| `progress/history.md` | Append-only log of finished features, **with effort records** | For historical context |
| `progress/impl_<feature>.md` | Implementer's report for one feature | When reviewing |
| `progress/review_<feature>.md` | Reviewer's verdict for one feature | When closing a feature |
| `specs/shared/` | The stack-agnostic spec, **copied verbatim from #8** (identical to #7's through `SA-1`…`SA-5`) — read it, never rewrite it | Before designing anything |
| `specs/<feature>/` | Triple-doc (`requirements.md` EARS + `design.md` + `tasks.md`) | Before implementing any `"sdd": true` feature |
| `CLAUDE.md` | Leader role + project conventions (cost discipline, layering, naming, money, testing, commits) — kept short | Before writing code |
| `docs/lessons.md` | **#8's** incident record and reasoning behind the inherited `CLAUDE.md` rules (archive, copied unchanged) | Only when you need the *why* of a rule |
| `CHECKPOINTS.md` | Objective "is this session closeable" criteria | To self-assess before closing |
| `docs/PROCESS.md` | The full process guide: harness + SDD concepts, the cast, the loop, EARS, the artifact registry, current status | To understand or replicate the process; **updated at the end of every phase** |
| `.claude/agents/` | Subagent definitions (leader, spec_author, implementer, reviewer, premise_checker, test_maintainer, suite_runner) | When orchestrating work |
| `http/` | REST Client `.http` files for manual probing of a running stack | When testing by hand |
| `pyproject.toml`, `uv.lock` | The `uv` workspace root: members, dev dependencies, ruff, mypy, pytest, coverage and **import-linter contracts** (from Phase 5) | Before adding a dependency or a layer |
| `services/` | The 6 services + `seed`, each `src/otc_<name>/{domain,application,infrastructure,presentation}` with its own tests and Alembic history | To implement |
| `packages/` | `shared_kernel` (dependency-free), `contracts` (generated Pydantic models), `cqrs` (the in-process dispatcher, application layer only, dependency-free) | To implement |
| `tests/` | Cross-cutting suites: architecture guards, black-box API tests, the end-to-end saga | To implement |
| `apps/web/` | The Analog (Angular) app and its Nitro BFF, with its own `package.json` and lockfile | To implement |
| `infra/`, `docker-compose*.yml` | Infrastructure | For environment work |

## 3. Hard rules (non-negotiable)

- **One feature at a time.** At most one `in_progress` in `feature_list.json`.
- **Never mark a feature `done` without green tests.** Tests are written *inside* the feature loop, not at the end of the project.
- **Never skip the spec phase.** Any feature with `"sdd": true` goes through `spec_author` and human approval before code is written.
- **Never edit `specs/shared/`.** It is copied verbatim from #8 (and identical to #7's). A change there is a **spec amendment** (`SA-n`): explicit, human-gated, and applied to all three repositories in the same session — never a silent fork.
- **Never skip the human approval gate** between `spec_ready` and `in_progress`.
- **Never run `git commit` or `git push`.** Report what was done and how to test it; the human commits. See `CLAUDE.md` § Commit discipline.
- **The domain layer imports nothing.** No SQLAlchemy, asyncpg, aiokafka, nats, PyMongo, FastAPI or Pydantic inside any `domain` package — enforced by import-linter, which fails the build, not by good manners.
- **Document as you go** in `progress/current.md`, not at the end.
- **If you do not know something, read `specs/` or `CLAUDE.md`** before inventing it.
- **Never quote a convention from the copy of `CLAUDE.md` injected into your context — `grep` the file on disk.** An injected snapshot is a cache taken when your session started. This repository amends its own conventions at human gates *mid-project, by design* — #8's wire-shape rule changed in its Phase 5 and its arming protocol gained two clauses in Phases 5 and 6. So the cache is **expected** to go stale, and enforcing a rule from it is a guard firing on something that is no longer true — the guard-that-does-not-guard, inverted. It cost #8 one spurious advisory in its Phase 7; on a rule with teeth it would have cost a spurious rejection. This applies to the leader as much as to any subagent.

## 4. Workflow (SDD)

```
pending → [spec_author] → spec_ready → ⏸ HUMAN APPROVES → in_progress
        → [implementer] → in_review → [reviewer] → done
                                          │
                                          └─ rejected → back to in_progress
```

1. The leader picks the first non-`done`, non-`blocked` feature.
2. If `"sdd": true` and status is `pending` → launch `spec_author`, which writes `specs/<name>/{requirements,design,tasks}.md` and sets `spec_ready`.
3. **Pause.** The human reads the spec and approves or requests changes.
4. On approval → status `in_progress`, launch `implementer`, which works from the spec (not from the original `acceptance` list).
5. Implementer finishes → status `in_review`, launch `reviewer`.
6. Reviewer verifies `R<n>` ↔ test traceability and that `tasks.md` is complete, then approves (→ `done`) or rejects (→ back to `in_progress`).
7. On `done`: append the summary **and the effort record** to `progress/history.md`.

Features with `"sdd": false` skip steps 2–3 but still traverse the state machine.

## 5. Closing a session

1. Run `./init.sh` — all green.
2. Update `feature_list.json` to the true status.
3. Move the `progress/current.md` summary to the end of `progress/history.md`, including the **effort record** (sessions, wall-clock).
4. Reset `progress/current.md` to the empty template.
5. No temp files, no debug logging, no context-free TODOs.
6. Meet every box in `CHECKPOINTS.md`.
7. Report to the human what was done and how to test it — **do not commit**.

## 6. If you get stuck

- Re-read the relevant part of `specs/` or `CLAUDE.md`.
- If a tool does not behave as expected, **do not invent a workaround**: record the blocker in `progress/current.md`, set the feature to `blocked` with a reason, and stop the session.
