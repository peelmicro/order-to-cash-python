# Implementation report — feature 33 `n8n_workflows` (phase 20, light, `sdd: false`)

Started 2026-11-14 11:22 UTC (12:22 CET). Finished 12:56 CET (11:56 UTC; the harness measured the first pass at 33 min 48 s). Leader correction: this line first said "12:55 UTC". One implementer, no reviewer.

## Summary

| Item | Result |
|---|---|
| 1. Four workflows fired for real | DONE, per workflow (below) |
| 2. Auto-import idempotent; activation claim tested | DONE. Counted claim armed. The header claim was **false** and was fixed in the script |
| 3. Removing n8n does not break the stack | DONE, with the `depends_on` enumeration |
| 4. README screenshots | **DONE after the leader's decision to use a throwaway n8n (see 'Item 4' at the end)**. First pass was stopped by the brief's rule: an owner already exists in the `n8n` database (`peelmicro@gmail.com`, `global:owner`) and no `N8N_OWNER_EMAIL` / `N8N_OWNER_PASSWORD` is in the environment (`env \| grep -i n8n` printed nothing). I did not reset it, did not write the capture script (an untested script is worse than none), and did not put image links in the README. The README n8n section is there without images |
| Scripts (import/export), dev-stack `--with-n8n`, crash-loop | DONE |

## Files changed

- `scripts/dev-stack.sh` — opt-in `up --with-n8n` (or `DEV_STACK_N8N=1`); `down` stops n8n before PostgreSQL; `status` lists n8n.
- `scripts/import-n8n-workflows.sh`, `scripts/export-n8n-workflows.sh` — new, ported from #8, headers rewritten, container `otcpy-n8n`, no `pnpm` references.
- `scripts/check-n8n-workflow-set.sh` — new: the counted claim of item 2 (expected set is a literal in the script).
- `infra/n8n/import-workflows-on-startup.sh` — keeps a workflow that was active, active (details in item 2); header rewritten.
- `docker-compose.infra.yml` — one comment only (the n8n-init header said "REUSED BYTE-IDENTICALLY", no longer true).
- `.env.example` — one comment line (`--with-n8n` sets `OTC_GATEWAY_URL`). No owner-credential lines: there is no capture script.
- `README.md` — new section "n8n demo workflows"; the dev-stack bullet now mentions `up [--with-n8n]`. The build-progress table is untouched.
- Not touched: `n8n/workflows/*.json` (`git status --short n8n/` empty, also after a round trip), `specs/shared/`, `services/`, `packages/`, `tests/`, `feature_list.json`, `progress/history.md`.
- `.arm/phase20/` holds backups with sha256 (git-ignored).

## Item 1 — all four fired for real

Method: no owner credentials, so activation went through the n8n CLI (`n8n publish:workflow --id=…` inside the container) then a recreate of `otcpy-n8n`; n8n's execution store was read with `psql` on the `n8n` database (`execution_entity`). Intervals shortened through the environment for this run only: `ORDER_GENERATOR_INTERVAL_SECONDS=20 PAYMENT_ROBOT_INTERVAL_SECONDS=20 STOCK_REPLENISH_INTERVAL_SECONDS=20 PAYMENT_AGE_MINUTES=0 PAYMENT_ROBOT_BATCH_SIZE=50 OTC_GATEWAY_URL=http://host.docker.internal:3001`. Burst used the default count (20). Stack was `scripts/dev-stack.sh up --with-n8n`.

Preconditions created through the Gateway first: `POST /orders` ALBIONFOODS / AldiDe / `PRD-0006` × 390 → `ORD-000123` (251550, stock `PRD-0006` fell to 16, below the threshold 20; the order reached `invoiced` → invoice `INV-000087`).

Baseline 12:34:01: orders total 123, issued invoices 26, paid invoices 61.

Execution store after the run (`select "workflowId",status,count(*) from execution_entity group by 1,2`):

```
 otcBurst              | error   |     2   (both from my own mis-configured probe before the env was set: EAI_AGAIN gateway)
 otcBurst              | success |     1
 otcOrderGenerator     | error   |     1
 otcOrderGenerator     | success |     6
 otcPaymentRobot       | error   |     1
 otcPaymentRobot       | success |     6
 otcStockReplenishment | error   |     1
 otcStockReplenishment | success |     6
```

The three schedule errors (execution ids 13-15, 11:35:40) are `POST /auth/login` answered `429 TOO_MANY_REQUESTS` by the Gateway (`logs/dev-stack/gateway.log`): three workflows logging in every 20 s plus the burst's login exceed the login limiter. It is caused by my shortened intervals; the defaults (45/120/300 s) are far below it. Recorded, not a defect.

Effect per workflow, read from the Gateway:

| Workflow | Success execution (n8n store) | Effect seen through the Gateway |
|---|---|---|
| 1 Order Generator | ids 5, 8, 11, 18 … (trigger, 11:34:40 onwards) | 5 orders not belonging to the burst appeared: `ORD-000124`, `125`, `143`, `144`, `145` (order dates 11:34:40.433, 11:35:00.412, 11:36:00.207, 11:36:20.146, 11:36:40.182), 4 `completed`, 1 `invoiced`. 6 success executions vs 5 orders: the 11:35:20 run succeeded with no order (concurrent with the burst), so a "success" does not by itself prove an effect, the orders do |
| 2 Payment Robot | ids 3, 6, 9, 17 … | `ORD-000123`'s invoice `INV-000087` went `issued` → `paid`, `paidAt` 11:34:40.314Z (the robot execution started 11:34:40.047); the order went `invoiced` → `completed`. Paid invoices 61 → 103 (the robot also paid 25 older issued invoices left by earlier phases; issued 26 → 1) |
| 3 Stock Replenishment | ids 4, 7, 10, 16 … | `ALBIONFOODS`/`PRD-0006` `units` 16 → 116 (+100 = `STOCK_REPLENISH_TOP_UP_UNITS` default), `belowThreshold=true` list empty afterwards |
| 4 Burst | id 12 (webhook, 11:35:20) | one `POST /webhook/otc-burst` returned `{"enabled":true,"requested":20,"placed":17,"refused":3,"orderReferences":[…17…]}` HTTP 200. All 17 references (17 distinct) exist in `GET /orders` (python check: found 17, missing []), 14 `completed`, 3 `cancelled` |

At the end all four were unpublished (`n8n unpublish:workflow`), n8n restarted, and `select id,active from workflow_entity` shows four `f`.

Side effect on the dev databases: stock `PRD-0006`/`ALBIONFOODS` was moved (the README says the e2e suite consumes this item); orders now 146 and invoices were paid. These are dev data; the e2e suite only needs stock to exist (116 minus the burst's use). Not rerun.

## Item 2 — auto-import, idempotent

Expected set (literal in `scripts/check-n8n-workflow-set.sh`): `otcBurst otcOrderGenerator otcPaymentRobot otcStockReplenishment`. Query: `select id from workflow_entity order by id` in `otcpy-postgres`, database `n8n`, role `otc_n8n`. The script also checks `n8n/workflows/*.json` ids against the literal.

Cold first import (I stopped n8n and n8n-init, ran `delete from workflow_entity` (4 rows), which is the only data I deleted; the `otcpy_n8n_data` volume was not touched):

```
$ scripts/check-n8n-workflow-set.sh          # after the delete
FAIL: workflow_entity ids differ from the expected set
  actual   (0 rows):                          rc=1
$ docker compose -p otcpy -f docker-compose.infra.yml --profile n8n up -d n8n n8n-init     # first up
init startedAt=2026-11-14T11:28:44.512190305Z
OK: workflow_entity holds exactly the 4 committed workflows: otcBurst otcOrderGenerator otcPaymentRobot otcStockReplenishment   rc=0
$ … up -d n8n n8n-init                       # second up, n8n-init re-runs
init startedAt=2026-11-14T11:28:51.182247536Z exited 0   ("Successfully imported 4 workflows.")
OK: … rc=0
```

Arm (one, light): backup `.arm/phase20/check-n8n-workflow-set.sh.orig` (sha256 recorded in `check.sha`). Violation: imported a fifth copy of `4-burst.json` with id `otcFifthCopy` into n8n by hand (`n8n import:workflow --input=/tmp/fifth.json`).

```
FAIL: workflow_entity ids differ from the expected set
  expected (4 rows): otcBurst otcOrderGenerator otcPaymentRobot otcStockReplenishment
  actual   (5 rows): otcBurst otcFifthCopy otcOrderGenerator otcPaymentRobot otcStockReplenishment
rc=1
```

Removed the row (`delete … where id='otcFifthCopy'`), re-ran: `OK … rc=0`; `cmp scripts/check-n8n-workflow-set.sh .arm/phase20/check-n8n-workflow-set.sh.orig` identical. Note: `workflow_entity.id` is the primary key, so a duplicate id is impossible by construction; the "no duplicate" half means "no second copy under another id", which is what the arm exercises.

**The inherited header claim was false.** `import-workflows-on-startup.sh` said a human activation "persists across restarts thereafter". Test: activated `otcBurst` (CLI publish; DB `active=t`), `docker compose … down n8n n8n-init`, `up -d n8n n8n-init`:

```
Deactivating workflow "4 - Burst (Order-To-Cash)".
Successfully imported 4 workflows.
otcBurst|f        (and all four f)
```

`n8n import:workflow` deactivates every workflow it overwrites, so every `up` switched off what a human had switched on. Disposition: **fixed in the script, comment and behaviour**. `n8n-init` now records `n8n list:workflow --active=true --onlyId` before the import and runs `n8n publish:workflow --id=…` for exactly those after it; content is still re-asserted from the JSON (idempotent, the count check still passes), only the activation flag is carried. Re-test: published `otcBurst`, `up -d n8n n8n-init` (log: `n8n-init: otcBurst was active before the import — publishing it again.`) → `otcBurst|t`; then `down n8n n8n-init` + `up` again → still `t`, and the webhook answered (500, the workflow ran; in that attempt `OTC_GATEWAY_URL` was the compose default `http://gateway:3001`, which does not resolve, `EAI_AGAIN gateway`). The header and a compose comment were rewritten accordingly. Not armed beyond that (light); the arm for the new publish step would be deleting the `for` loop and re-running the persistence test, which I did not run.

## Item 3 — removing n8n does not break the stack

`docker compose … --profile n8n down n8n n8n-init` removed both containers; `docker ps -a --filter name=n8n` printed nothing. Then, through the Gateway (stack up via dev-stack):

```
POST /orders (CarrefourEs / IBERFOODS / PRD-0002 × 2) → ORD-000146 status placed
GET /orders/{id}  → ORD-000146 invoiced   (invoice INV-000107, issued)
POST /invoices/{id}/payments source=operator → {"outcome":"accepted",…,"invoiceStatus":"paid"}
GET /orders/{id}  → ORD-000146 completed
```

`depends_on` search over the compose files. Files: `find . -name 'docker-compose*' -o -name 'compose*.y*ml'` (excluding node_modules/.venv/.git) → only `docker-compose.infra.yml` (no apps compose exists before phase 23). Command: `grep -n "depends_on" -A6 docker-compose*.yml | grep n8n`. One hit, `docker-compose.infra.yml:521`: `n8n-init` → `n8n: condition: service_healthy`. Classification: n8n-init depends on n8n, both behind the `n8n` profile; nothing outside the profile depends on either. `grep -rniE n8n services packages tests apps/web/src apps/web/e2e` hits only `services/billing/tests/unit/test_no_internal_payment_timer.py` (reads the workflow JSON as data; no runtime dependency).

## Answers to the three questions

1. **Does a newly activated burst webhook answer immediately or 404 until restart?** Measured with the CLI (`n8n publish:workflow`), because I had no owner login to activate through the UI/REST. Three trials on n8n 2.36.2: (a) first trial, 404 `"The requested webhook "POST otc-burst" is not registered"` until I restarted n8n; (b) after a clean `up`, publish then curl at once, at +10 s, +30 s, +60 s: always 500 (the workflow executed, Gateway unreachable; 404 would mean not registered); (c) import then publish on a running n8n, curl at once and +15 s: 500. After `unpublish:workflow` plus restart: 404. So 2 of 3 answered immediately and 1 needed a restart. Trial (a) came after I had deleted the workflow rows under a stopped n8n and re-imported them, which may be why, but I did not isolate it. The UI/REST activation path is **not measured**. README and script headers say what was measured; "restart if it does not fire" is the safe instruction.
2. **Cause of the `otcpy-n8n` crash-loop.** Reproduced: with n8n up and healthy, `docker compose … stop postgres` leaves n8n running (restart `unless-stopped`); n8n then logs repeated `getaddrinfo EAI_AGAIN postgres` (Docker's DNS stops resolving the name of a stopped container) and `Database connection recovery aborted after 5 attempt(s)`; a `docker restart otcpy-n8n` then retries `EAI_AGAIN postgres` with growing back-off and ends `Exited (1)`, which the restart policy turns into a loop. Cause in our tooling: `dev-stack.sh down` stopped PostgreSQL but never n8n, and the header told users to avoid the profile instead of fixing it. Fix: `dev-stack.sh down` stops `n8n n8n-init` **before** PostgreSQL when it started them (`logs/dev-stack/n8n-started`), and also when n8n is running but was started by hand while PostgreSQL is about to be stopped (prints a `[NOTE]`). Both paths run: normal (`up --with-n8n` then `down`: n8n `Exited (0)`) and the manual-n8n path (`up`, `compose up -d n8n`, `down`: `[NOTE] … stopping n8n with it`). Arm: backup `.arm/phase20/dev-stack.sh.new` (sha256 875329590c569c4bccef72f9416e5e6e18b0c593d3b4d4ee198dba2e9341e447), replaced the two stop conditions with `if false` (2 hits), `up --with-n8n` then `down`: down printed `stopped containers this script started: postgres mongodb kafka nats` with no n8n line and afterwards `otcpy-n8n Up About a minute (healthy)` next to `otcpy-postgres Exited (0)`, its log showing the DB errors. Restored by `cp`, `cmp` identical, sha256 equal, re-ran `up --with-n8n` + `down`: `stopped n8n (n8n n8n-init) before PostgreSQL`, n8n `Exited (0)`. Nothing in the compose file needed changing for this.
3. **Can n8n reach the host-process Gateway?** Yes. `docker exec otcpy-n8n wget -S -q -O - http://host.docker.internal:3001/health/ready` → `HTTP/1.1 200 OK … {"status":"up","checks":{"rpcTransport":{"status":"up"},"readModel":{"status":"up"},"streamSignals":{"status":"up"}}}`; the Gateway binds `0.0.0.0` and `extra_hosts: host.docker.internal:host-gateway` resolves it on this machine; no firewall blocked it. The real workflows' requests appear in the Gateway log from `172.19.0.2`.

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied it with | #9 supplies it by |
|---|---|---|---|
| Import CLI path | `scripts/import-n8n-workflows.sh` doing `docker exec otc-n8n n8n import:workflow` (`../order-to-cash-nestjs/scripts/import-n8n-workflows.sh`, and its `export` twin) | the same script with `otcnet-n8n` (`../order-to-cash-dotnet/scripts/import-n8n-workflows.sh:42,56`, `export-n8n-workflows.sh`) | the same two scripts with `otcpy-n8n`; the export round trip was run and leaves `git status --short n8n/` empty |
| Container-to-host bridge | gateway as a compose service (no bridge needed) | `extra_hosts: host.docker.internal:host-gateway` plus `OTC_GATEWAY_URL` override (`../order-to-cash-dotnet/docker-compose.infra.yml:445-448,495`) | the same compose lines, already present; `dev-stack.sh up --with-n8n` now sets the override from `GATEWAY_PORT`; reachability shown with `wget` (question 3) |
| n8n storage | SQLite in the `n8n_data` volume (`../order-to-cash-nestjs/docker-compose.infra.yml:372-376`) | SQLite (n8n has no MS-SQL support) | PostgreSQL, `n8n` database, role `otc_n8n`; workflow set counted in `workflow_entity` and executions read from `execution_entity` instead of a SQLite file, and a stopped database now takes n8n down (question 2), which neither SQLite stack could suffer |
| Activation / restart behaviour | CLI publish: webhook live without restart, scheduled need one (`../order-to-cash-nestjs/progress/review_n8n_workflows.md:118`, row at line 25, D8 at 369) | restart needed on its instance (leader note) | measured on 2.36.2: 2 of 3 webhook trials immediate, 1 needed a restart; activation across `n8n-init` re-import was **not** persistent until the script change (item 2) |
| Screenshot capture | by hand, two PNGs (`../order-to-cash-nestjs/README.md:56`) | none | not done in this run (owner credentials unavailable); a script would need `@playwright/test` 1.64.1 from `apps/web` through `createRequire` from `scripts/` |

## Findings and proposed dispositions

1. **Item 4 blocked: no owner credentials.** Re-open trigger: the maintainer supplies `N8N_OWNER_EMAIL` / `N8N_OWNER_PASSWORD` for the existing owner (or accepts resetting `otcpy_n8n_data`, which would NOT remove the owner because n8n's users live in PostgreSQL; a reset would need `n8n user-management:reset` or dropping the `n8n` database, which I will not do). Proposal: a follow-up dispatch with the credentials; the capture script is straightforward (log in through the REST API with the supplied credentials, open each workflow canvas by id, screenshot).
2. **The inherited "persists across restarts" claim was false** (fixed, item 2). The same claim is likely in #7's and #8's `import-workflows-on-startup.sh`; they are complete, so record it only.
3. **Login limiter versus short intervals**: three workflows at 20 s plus a burst trigger `429` on login and one failed run each. Not a defect at default intervals; documented in the README. Could become a backlog note if a demo wants shorter intervals.
4. **"Success" executions can do nothing** (the 11:35:20 generator run). Counting orders in the Gateway, not executions, is the right unit.
5. `scripts/dev-stack.sh`'s old header said n8n "crash-loops without the rest of the n8n stack"; that was a misdiagnosis, replaced.

## Manual how-to-test (each run by me)

```bash
cd /home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python
scripts/dev-stack.sh up --with-n8n            # prints "otcpy-n8n healthy" and "otcpy-n8n-init imported the workflows (inactive) and exited 0"
scripts/check-n8n-workflow-set.sh             # OK: workflow_entity holds exactly the 4 committed workflows
docker exec otcpy-n8n wget -q -O - http://host.docker.internal:3001/health/live    # {"status":"up"}
docker exec otcpy-n8n n8n publish:workflow --id=otcBurst && docker restart otcpy-n8n   # activate the burst workflow
until [ "$(docker inspect -f '{{.State.Health.Status}}' otcpy-n8n)" = healthy ]; do sleep 2; done   # leader, at the maintainer's test: without this wait the curl below hits a restarting n8n and -s hides the error
curl -sS -X POST http://localhost:5678/webhook/otc-burst -H 'content-type: application/json' -d '{"count":3}'   # placed/refused/orderReferences
docker exec otcpy-postgres psql -U otc_n8n -d n8n -c 'select "workflowId",status,count(*) from execution_entity group by 1,2'
scripts/export-n8n-workflows.sh && git status --short n8n/    # empty output: round trip changes nothing
scripts/dev-stack.sh down                     # "stopped n8n (n8n n8n-init) before PostgreSQL"
```

(`GATEWAY_OPERATOR_PASSWORD` is in `.env`; I did not print it.) `./init.sh` exits 0 after the changes. `./quality.sh` was not run (shell, compose comments and README only; no `services/`, `packages/`, `tests/` or `apps/web` change).

## State left behind

All `otcpy-*` containers stopped (n8n and postgres exited, none running), no host process of the stack, no `kb-poc-*` touched, four workflows inactive, `n8n/workflows/` clean in git, `otcpy_n8n_data` volume intact. The shortened-interval environment was only in the shell that recreated n8n for item 1; the later recreations used the defaults (checked with `docker inspect` on the stopped container).

## Item 4 — screenshots from a throwaway n8n (added after the leader's decision; finished 12:59 CET, 11:59 UTC; the PNGs are dated 12:58 CET)

Files added: `scripts/capture-n8n-screenshots.sh` (docker run `otcpy-n8n-capture`, `n8nio/n8n:2.36.2`, SQLite, `127.0.0.1:${N8N_CAPTURE_PORT:-5679}`, `n8n/workflows` mounted `:ro`, no volume of ours, not on `otcpy-net`; port-free check first; waits on `/healthz/readiness`; `n8n import:workflow --separate`; owner set up through `POST /rest/owner/setup` as `Demo Owner` / `demo@example.com` with a per-run random password held in memory; `trap` runs `docker rm -f -v` on every exit), `scripts/capture-n8n-screenshots.mjs` (resolves `@playwright/test` from `apps/web` with `createRequire`, so no package was added and nothing lives in `apps/web`; logs in via `/rest/login`, dismisses dialogs, presses `1` to fit the canvas), and `docs/screenshots/n8n-workflows.png`, `n8n-1-order-generator.png`, `n8n-2-payment-robot.png`, `n8n-3-stock-replenishment.png`, `n8n-4-burst.png`. README: the five images embedded in the n8n section with the regenerate command.

Evidence: ran `scripts/capture-n8n-screenshots.sh` (exit 0, five PNGs of 37-65 KB). Every PNG was opened with Read: the list shows exactly the four workflows (Burst, Stock Replenishment, Payment Robot, Order Generator); each canvas shows its own title (1, 2, 3, 4), a trigger node and a code node (a webhook with POST for Burst), fitted, no modal, no onboarding, and no identity anywhere (only "Personal"). No credential is written to disk. Not armed (light); the one failure path (port in use, readiness timeout) was not exercised.

Ledger row, screenshot capture: #7 captured two PNGs by hand against its real instance (`../order-to-cash-nestjs/README.md:56`); #8 none; in #9 a scripted throwaway instance plus Playwright from `apps/web`, so the images are reproducible and carry no real identity.

How to test: `./scripts/capture-n8n-screenshots.sh && git status --short docs/ n8n/` (new PNGs under `docs/screenshots/`, `n8n/` empty), then `docker ps -a | grep otcpy-n8n-capture` (empty).
