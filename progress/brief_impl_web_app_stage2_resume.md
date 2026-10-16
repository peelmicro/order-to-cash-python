# Addendum — implementer, feature 29 `web_app`, stage 2 **resume** (phase 16, session 2)

Read `progress/brief_impl_web_app_stage2.md` first: it is the brief of record (items 1–12, *Must hold*, bounds, output). This addendum changes only how you start.

**Resume, don't restart.** A previous implementer pass on this brief was stopped at the maintainer's request after about 55 minutes (VS Code restart), not because of a failure. Its work is on disk, uncommitted, under `apps/web/**`. Do not rebuild what exists.

## What the leader verified on disk this session (with a command)

- `git status`: tracked changes outside `apps/web/**` are only the leader's own (`.env.example`, `feature_list.json`, `init.sh`, `progress/*`, `quality.sh`). Stay inside your bounds.
- `.arm/web29s2/results.jsonl` has 45 rows: M01–M13, M01b, P01–P26, R01–R03, N1_line_deleted, N1_prod (list them with `python3 -c "import json;[print(json.loads(l)['id']) for l in open('.arm/web29s2/results.jsonl')]"`). Not every row has a `cmp` key. The previous session's leader recorded every arm there as restored (`DIFFERENT` count 0) and the Python-side table arms J1–J3 as `real python table file unchanged` (`.arm/web29s2/arm_py.out`). Pre-edit copies are in `.arm/web29s2/backup/`; helper scripts `arm.py`, `defs_money.py`, `defs_pages.py`, `gates.sh`, `ids100_102*.py`, live script `live/live.mjs`. Earlier outputs (`gates.summary`, `cldr.out`, `ids100_102_all.out`, `sweep_full.log`) predate the interruption: treat them as possibly stale.
- There is **no "Stage 2" section in `progress/impl_web_app.md` yet.**
- Nothing listens on 3010; only `otcpy-n8n` is running (it restart-loops because the stack's Postgres is stopped — environment, not code).

## What you do

1. **Inventory by test, not by reading.** Run the web gates (`quality.sh` section 7's commands) and map each brief item (1–12) and each *Must hold* bullet to the named test(s) that prove it. Mark each built / partial / missing.
2. **Verify the arm log is still current.** For every row in `results.jsonl`, check whether the file it mutated has changed since the arm ran (compare against the arm's recorded `sha256` of the original, or the file's mtime against the row). Re-run any arm whose path changed; an arm whose path is unchanged may be cited as is. Rows written before the interruption are not trusted for the restore: confirm each target with `cmp` against its backup or with the current gates green.
3. **Finish what is missing**, with arms for every new guard (protocol as in the brief, backups in `.arm/web29s2/`).
4. **Re-run** the CLDR measurement script and the ids 100/102 search (the outputs on disk may be stale), then the live check (the developer stack is stopped: start it per `progress/current.md` *Notes* and README *Running the services*; record `docker ps` and `ss -ltnp` before and after; stop what you started, leaving `otcpy-n8n` as found).
5. **Write the "Stage 2" section** of `progress/impl_web_app.md` as the brief's *Output* lists, with the arming table from `results.jsonl` (plus re-runs) and the Vitest count reconciled with stage 1's final 18 files / 253 tests.

If anything blocks you (a defect in `services/**`, a premise in the brief that is false), write it in the record and return; do not widen your bounds.

Return only "result in `progress/impl_web_app.md`" plus at most 5 lines.
