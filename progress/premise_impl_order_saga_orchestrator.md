# Premise check — progress/brief_impl_order_saga_orchestrator.md (2026-10-07)

FALSE  "Feature 16 is `in_progress` (set by the leader)" — `grep '"id": 16' -A12 feature_list.json` shows `"status": "spec_ready"` (HEAD: `pending`). Not yet set.
VERIFIED  design.md §17.1 first paragraph is the gate outcome, 2026-10-06, G1/G2/G3 as recommended — `sed -n 723,727p design.md`.
VERIFIED  A2' in design.md §1 (table row A2, line 31) and §2 (line 82), and tasks.md line 14 file list — grep.
VERIFIED  feature 15 `done` — feature_list.json id 15 status "done".
VERIFIED  history.md orders_acceptance entry (line 814) incl. light round 3 closure by the leader and review rounds 1-2.
VERIFIED  start_runtime stops and awaits tasks on BaseException — composition.py:306-308 `except BaseException: await _stop_tasks(...)`; _stop_tasks gathers all (220-227).
VERIFIED  HandlerRegistry.registered_factories covers commands, queries, events — dispatcher.py:93-101; used by composition.py:88,240,261; test_cqrs_dispatcher.py:543.
VERIFIED  lifespan is in otc_orders/main.py; contract `fact-producer-confinement` exists — pyproject.toml:244; review_orders_acceptance.md Q1 line 72.
VERIFIED  #8 history lines 821-871 = order_saga_orchestrator entry, four review rounds — `grep -n '^## '` gives 821 and next heading 872; rounds 1-4 listed.
VERIFIED  tasks.md 0.1 (A1-A7), 0.2 (baseline), 14.x close-out, header arming protocol / defeat list / may and must-not-touch lists exist.
VERIFIED  "ten fact commands and five events" — design.md lines 15, 59-60, 396.
VERIFIED  no brief/tasks conflict — brief's bans (feature_list beyond 16's status, CLAUDE.md, current.md, specs beyond tasks.md) match tasks.md "Must not touch" and 14.8.
UNVERIFIABLE  "A session break lost a reviewer's /tmp backups" — history.md orders_acceptance "Process incident" says so; accepted as recorded.

Counts: VERIFIED 11, FALSE 1, UNVERIFIABLE 1.
