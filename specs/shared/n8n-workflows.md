# Demo Automation Workflows — Functional Specification

> **Scope.** The **stack-agnostic** functional specification of the four demo
> workflows, reused **verbatim** by assessments **#7**, **#8** and **#9**. The
> workflows are authored in **n8n** and committed as JSON; this document
> specifies *what they do*, not how a node is wired.
>
> Companion documents: [`openapi.yaml`](./openapi.yaml) (the only interface they
> use), [`saga.md`](./saga.md) and [`requirements.md`](./requirements.md).

---

## 1. The one rule that makes these portable

> ### The workflows call **ONLY the Gateway public REST API**.
>
> **Never** a database. **Never** the fact stream. **Never** the RPC transport.
> **Never** a service-internal endpoint. They hold no database credential and no
> broker credential, because they have nothing to connect to. Every action they
> take is an HTTP call described in [`openapi.yaml`](./openapi.yaml), and every
> effect they cause happens because the system's own saga reacted to it.

Three things follow, and they are the whole reason the rule is stated this
strongly:

1. **The same JSON files serve all three assessments.** Porting to #8 or #9 is a
   change of **one value — the Gateway base URL**. Nothing else in a workflow
   references anything stack-specific, because there is nothing stack-specific
   in a REST call.
2. **They are honest demand, not a rigged demo.** Payments and replenishment
   arrive **from outside the system**, exactly as they would in reality. There
   is no hidden in-service timer paying its own invoices; `saga.md` is explicit
   that a saga waiting at `invoiced` waits indefinitely by design, and these
   workflows are the outside world that ends that wait.
3. **They are a live contract test.** A workflow that breaks after a refactor
   has found a breaking change in the public API — which is the point of having
   an external client that only knows the contract.

**Corollary — the workflows are demo-only.** No service depends on them, no test
requires them, and no requirement `R1`–`R60` is satisfied by them. They make the
system *visibly alive*; they are not part of it. See §7.

---

## 2. Common behaviour

Everything in this section applies to all four workflows.

### 2.1 Authentication

Each workflow begins by obtaining a bearer token from `POST /auth/login` using
credentials supplied **from the environment**, never hard-coded in the JSON, and
sends it on every subsequent call. A `401` at any point causes a single re-login
and one retry; a second `401` fails the run loudly rather than silently looping.

### 2.2 Money

Every amount a workflow sends or reads is **integer minor units plus a currency
code** (R1). A workflow never divides, never rounds, and never converts to a
decimal for display — the `.99` engineering of §3.1 is arithmetic on integers
precisely because that is the only representation this system has.

### 2.3 Idempotency and retries

| Situation | Behaviour |
|---|---|
| Network error or `5xx` | Retry up to 3 times with exponential backoff, then skip the item and continue the batch. One bad item never aborts a run. |
| `409` or `422` | **Never retried.** These are deliberate answers — an unavailable stock line, an already-paid invoice, a mismatched amount. The item is skipped and counted. |
| Payment replay after an ambiguous failure | Safe by construction: the workflow derives a **deterministic** `paymentReference` from the invoice reference, so a retry after a dropped connection returns `200` with `outcome: duplicate` instead of paying twice (R48). |
| Two runs overlapping | Each run re-reads current state before acting; nothing is cached between runs. |

### 2.4 What a workflow must never assume

- **Not that a placed order is immediately queryable.** `POST /orders` returns
  before the projection exists; `GET /orders/{id}` may answer *projection
  pending* (R55). A workflow that needs an order's state waits and re-reads, or
  simply does not look — the generator does not look.
- **Not that an order will complete.** Roughly one in six is engineered to be
  refused credit and to end `cancelled`. That is the desired outcome, not a
  failure, and the workflow counts it as a success.
- **Not that stock is infinite.** Genuine `409 STOCK_UNAVAILABLE` answers are
  expected and are what makes the replenishment workflow worth watching.

### 2.5 Configuration

Every knob is an environment variable read by the workflow, so a demo is tuned
without editing JSON. Defaults are chosen so that `docker compose up` produces a
watchable but not overwhelming stream of activity.

| Variable | Default | Applies to | Meaning |
|---|---|---|---|
| `N8N_WORKFLOWS_ENABLED` | `true` | all | Master switch. When false, nothing is imported or activated. |
| `OTC_GATEWAY_URL` | `http://gateway:3000` | all | **The single value that changes when porting to #8 or #9.** |
| `OTC_OPERATOR_USERNAME` | — | all | Login for the demo operator. |
| `OTC_OPERATOR_PASSWORD` | — | all | Supplied from the environment; never committed. |
| `OTC_REQUEST_TIMEOUT_MS` | `10000` | all | Per-call timeout. |

---

## 3. Workflow 1 — Order generator

| Property | Value |
|---|---|
| **Purpose** | Keep a steady stream of realistic orders flowing so the live feed, the traces and the dashboards are never empty. |
| **Trigger** | Cron / interval. |
| **Schedule** | Every `ORDER_GENERATOR_INTERVAL_SECONDS`, default **45 s**. |
| **Gateway endpoints** | `POST /auth/login`, `GET /catalog/products`, `GET /catalog/retailers`, `GET /catalog/companies`, `POST /orders` |
| **Writes** | One order per run (optionally a small batch). |

### 3.1 What it does

1. Reads the catalogue (products, retailers, companies) — cached for
   `ORDER_GENERATOR_CATALOG_TTL_SECONDS` so the demo does not hammer it.
2. Picks a retailer and a company at random, restricted to
   `ORDER_GENERATOR_RETAILERS` / `ORDER_GENERATOR_COMPANIES` when set, and picks
   1 – `ORDER_GENERATOR_MAX_LINES` products **that share the retailer's
   currency** — mixing currencies inside an order is a domain error (R2), and
   the generator must produce valid orders, not test the validator.
3. Chooses a quantity per line between 1 and `ORDER_GENERATOR_MAX_UNITS`.
4. **Decides the fate of this order.** With probability
   `ORDER_GENERATOR_COMPENSATION_RATIO` (default **0.15**, i.e. ~15 %) it
   engineers the total to end in `.99`; otherwise it leaves catalogue prices
   untouched.
5. `POST /orders`, records the returned `orderId` and `orderReference` in the
   run log, and stops. **It does not follow the order** — the saga is the
   system's job, and watching it is the reviewer's.

### 3.2 The `.99` engineering — how, and why it is legitimate

The credit-check **simulator** refuses any hold whose amount satisfies
`totalAmount mod 100 = 99` in minor units (R42). To make roughly 15 % of orders
take the compensation path, the generator adjusts **one line's `unitPrice`** —
the request body permits an explicit price, which is snapshotted onto the line:

```
total   = Σ (unitPrice × quantity) − Σ lineDiscount      (all integers, minor units)
delta   = (99 − (total mod 100) + 100) mod 100
lastLine.unitPrice += ceil(delta / lastLine.quantity)     # then re-derive and
                                                          # correct the remainder
```

The adjustment is at most 99 minor units spread over one line, so prices stay
realistic, quantities stay whole, and the arithmetic never leaves the integer
domain. The generator then **asserts locally** that its computed total ends in
`99` before sending; if it cannot achieve it (a single-unit line whose price
would go negative — impossible with the seeded catalogue, but checked anyway) it
sends an ordinary order instead and counts a miss.

Two honesty notes that belong with this workflow, not buried in a README:

- The `.99` rule is a **simulator affordance, not a credit policy**
  (`requirements.md` §5.1). The generator exploits it deliberately to make
  compensation appear in a live feed **unprompted**, which is far more
  convincing than a reviewer clicking a "make it fail" button.
- Genuine over-limit rejections **also** happen, because the seeded credit
  limits are modest and the generator keeps placing orders. Those are real
  domain refusals reaching the same compensation path (R44), and they are not
  engineered by anyone.

### 3.3 Expected effects

| Observation | Where |
|---|---|
| A new order every ~45 s, reaching `completed` after its invoice is paid | Order list, live feed |
| ~15 % reaching `cancelled` with reason `credit_rejected`, the stock release and the cancellation visible as separate timeline steps | Order detail timeline (R28) |
| Occasional `409 STOCK_UNAVAILABLE` at acceptance, and occasional `stock.rejected.v1` cancellations when the reserve loses the race the check won | Order list, workflow run log |
| Facts flowing on all three topics, traces spanning both brokers | Broker console, tracing UI |

### 3.4 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ORDER_GENERATOR_ENABLED` | `true` | Per-workflow switch. |
| `ORDER_GENERATOR_INTERVAL_SECONDS` | `45` | Cron period. |
| `ORDER_GENERATOR_ORDERS_PER_RUN` | `1` | Orders placed per tick. |
| `ORDER_GENERATOR_COMPENSATION_RATIO` | `0.15` | Proportion engineered to total `.99`. `0` disables the compensation demo entirely. |
| `ORDER_GENERATOR_MAX_LINES` | `4` | Maximum lines per order. |
| `ORDER_GENERATOR_MAX_UNITS` | `10` | Maximum units per line. |
| `ORDER_GENERATOR_RETAILERS` | *(empty)* | Comma-separated retailer codes to restrict to. |
| `ORDER_GENERATOR_COMPANIES` | *(empty)* | Comma-separated company codes to restrict to. |
| `ORDER_GENERATOR_CATALOG_TTL_SECONDS` | `600` | Catalogue cache lifetime. |

---

## 4. Workflow 2 — Payment robot (the bank)

| Property | Value |
|---|---|
| **Purpose** | Play "the retailer paying within terms". It is the **outside world** that moves invoices from `issued` to `paid` and lets sagas close. |
| **Trigger** | Cron / interval. |
| **Schedule** | Every `PAYMENT_ROBOT_INTERVAL_SECONDS`, default **120 s**. |
| **Gateway endpoints** | `POST /auth/login`, `GET /invoices`, `POST /invoices/{id}/payments` |
| **Writes** | One remittance per selected invoice. |

### 4.1 What it does

1. `GET /invoices?status=issued&issuedBeforeMinutes={PAYMENT_AGE_MINUTES}&pageSize={PAYMENT_ROBOT_BATCH_SIZE}`
   — only invoices **older than the configured age** are eligible, so a
   reviewer can watch an order sit legitimately at `invoiced` before payment
   arrives. Paying instantly would hide the one state in this system that waits
   on the outside world.
2. For each invoice, `POST /invoices/{id}/payments` with:
   - `paymentReference` = `PAY-{invoiceReference}` — **deterministic by
     design**, so a retry after an ambiguous failure is recognised as a replay
     and answered `200 duplicate` rather than paying twice (R48);
   - `amount` = the invoice's own `totalAmount` and `currency`, copied
     unchanged — partial payment is out of scope and a mismatch is rejected
     (R49);
   - `valueDate` = now;
   - `source` = `robot`.
3. Counts `201` (paid), `200` (already paid by an earlier run — normal, not an
   error) and `409`/`422` (skipped) and logs the tally.

### 4.2 Expected effects

- Each paid invoice produces `payment.received.v1` then `credit.released.v1`,
  and the order walks `invoiced → paid → completed` (R24, R47).
- The retailer's `availableCredit` in `GET /credits` climbs back as exposure is
  released — the clearest single view of the ledger working.
- Running the robot twice over the same invoice set demonstrates idempotency
  live: the second pass is all `200 duplicate`, with no second payment and no
  second fact.

### 4.3 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PAYMENT_ROBOT_ENABLED` | `true` | Per-workflow switch. |
| `PAYMENT_ROBOT_INTERVAL_SECONDS` | `120` | Cron period. |
| `PAYMENT_AGE_MINUTES` | `2` | Minimum invoice age before it is paid. Raise it to demonstrate the waiting state; set `0` to pay immediately. |
| `PAYMENT_ROBOT_BATCH_SIZE` | `10` | Maximum invoices paid per run. |
| `PAYMENT_ROBOT_RETAILERS` | *(empty)* | Restrict to certain retailers, e.g. to leave one retailer permanently unpaid for the demo. |

---

## 5. Workflow 3 — Stock replenishment

| Property | Value |
|---|---|
| **Purpose** | Stop a long-running demo from starving. Without it the generator eventually exhausts the seeded stock and every order dies at `stock_rejected`, which is one demo, not a system. |
| **Trigger** | Cron / interval. |
| **Schedule** | Every `STOCK_REPLENISH_INTERVAL_SECONDS`, default **300 s**. |
| **Gateway endpoints** | `POST /auth/login`, `GET /stock`, `POST /stock/replenish` |
| **Writes** | One replenishment per company with low items. |

### 5.1 What it does

1. `GET /stock?belowThreshold=true&pageSize={STOCK_REPLENISH_BATCH_SIZE}` — the
   Gateway does the comparison against each item's `lowStockThreshold`, so the
   workflow carries no business rule of its own.
2. Groups the low items by `companyCode` and, for each group, `POST
   /stock/replenish` with one line per product and
   `units = STOCK_REPLENISH_TOP_UP_UNITS`.
3. Logs how many items were topped up.

Two deliberate properties:

- **`units` is a delta, not a target level**, so the endpoint is *not*
  idempotent — and the workflow does not pretend otherwise. It re-reads
  `belowThreshold` on every run, so an item already topped up simply does not
  come back in the next result set.
- **Replenishment emits no fact and appears in no order timeline.** It touches
  on-hand units only, never reservations, so invariant **F1**
  (`reservedUnits ≤ units`) cannot be broken by it. A stock top-up is an
  operational act outside every order's saga, and putting it in an order's
  history would be a lie.

### 5.2 Expected effects

- Stock levels recover visibly in the stock view.
- The rate of `409 STOCK_UNAVAILABLE` and of `stock_rejected` cancellations
  drops after a run — which is itself a nice thing to point at while explaining
  why the availability check is not a reservation.

### 5.3 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `STOCK_REPLENISH_ENABLED` | `true` | Per-workflow switch. |
| `STOCK_REPLENISH_INTERVAL_SECONDS` | `300` | Cron period. |
| `STOCK_REPLENISH_TOP_UP_UNITS` | `100` | Units added per low product. |
| `STOCK_REPLENISH_BATCH_SIZE` | `50` | Maximum low items handled per run. |
| `STOCK_REPLENISH_COMPANIES` | *(empty)* | Restrict to certain companies — leave one starved on purpose to keep the `stock_rejected` path demoable. |

---

## 6. Workflow 4 — Burst

| Property | Value |
|---|---|
| **Purpose** | Light up the broker console, the traces and the dashboards on demand, in front of a reviewer. |
| **Trigger** | **Manual webhook** — an HTTP `POST` to the workflow's webhook path, from a button, a terminal or the demo script. |
| **Schedule** | None. It never runs on its own. |
| **Gateway endpoints** | `POST /auth/login`, `GET /catalog/*`, `POST /orders` × `BURST_ORDER_COUNT` |
| **Writes** | `BURST_ORDER_COUNT` orders, default **20**. |

### 6.1 What it does

1. Accepts an optional JSON body overriding `count` and `compensationRatio` for
   this run only.
2. Builds `BURST_ORDER_COUNT` orders with the same composition logic as the
   generator (§3.1–§3.2), honouring `BURST_COMPENSATION_RATIO` so a burst
   contains a visible minority of compensating orders.
3. Fires them with a concurrency of `BURST_CONCURRENCY`, collecting each
   `orderId`.
4. Responds to the webhook caller with the count placed, the count refused at
   acceptance, and the list of order references — so a demo script can quote
   them.

### 6.2 Expected effects

- A visible spike in throughput on every dashboard, with per-order traces
  spanning HTTP → RPC → write model → fact stream → consumers (R56).
- Several sagas completing and several compensating **at once**, which is the
  moment the read model's out-of-order tolerance (R52) and the partition-key
  ordering guarantee (R15) stop being paragraphs and become observable.
- With `BURST_ORDER_COUNT` set high, a genuine over-limit credit rejection
  becomes near-certain as the seeded limits fill up — the non-simulated half of
  R44, on demand.

### 6.3 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BURST_ENABLED` | `true` | Per-workflow switch. |
| `BURST_ORDER_COUNT` | `20` | Orders per burst. |
| `BURST_CONCURRENCY` | `5` | Parallel in-flight requests. Kept modest so the burst exercises the system, not the laptop. |
| `BURST_COMPENSATION_RATIO` | `0.20` | Proportion engineered to total `.99`. |
| `BURST_WEBHOOK_PATH` | `otc-burst` | Webhook path segment. |

---

## 7. Enabling, disabling, and removing entirely

### 7.1 Three levels of off

| Level | How | Effect |
|---|---|---|
| **One workflow off** | `ORDER_GENERATOR_ENABLED` / `PAYMENT_ROBOT_ENABLED` / `STOCK_REPLENISH_ENABLED` / `BURST_ENABLED` = `false` | That workflow is imported but not activated. |
| **All workflows off** | `N8N_WORKFLOWS_ENABLED=false` | The container starts; nothing is imported or activated. Useful when a reviewer wants a completely quiet system to place one order by hand. |
| **No workflow engine at all** | Omit its **compose profile** | The container never starts. |

### 7.2 Removing the engine must not break the stack — and cannot

This is a requirement on the *architecture*, verified as part of the demo
checklist:

- **No service knows the workflow engine exists.** Nothing resolves its
  hostname, subscribes to it, or waits for it. It is a client of the Gateway,
  exactly like the web application and the API tests.
- **No test depends on it.** Every row of [`test-matrix.md`](./test-matrix.md)
  is provable with the engine absent; the API and end-to-end tests place their
  own orders and register their own payments through the same public endpoints.
- **Nothing seeded depends on it.** The seed job produces catalogue, stock and
  credit lines; the workflows only consume them.
- **The consequence of removing it is boredom, not breakage.** Sagas stop
  starting by themselves and invoices stop being paid by themselves, because the
  outside world went away — which is precisely the behaviour `saga.md` §6
  predicts, and a good thing to be able to demonstrate deliberately.

**Verification step:** bring the stack up without the workflow profile, place an
order through the UI, register the payment with the operator button, and watch
it reach `completed`. If anything else changes, the workflows were load-bearing
and the rule in §1 was broken somewhere.

---

## 8. Porting to assessments #8 and #9

| What changes | What does not |
|---|---|
| `OTC_GATEWAY_URL` — one value | The workflow JSON files |
| — | The endpoints, the request bodies, the query parameters |
| — | The `.99` engineering, the deterministic `paymentReference`, the thresholds |
| — | The environment-variable names and defaults |

If porting ever requires more than the base URL, one of two things has happened
and both are worth catching: either a workflow reached past the public API, or
an assessment diverged from [`openapi.yaml`](./openapi.yaml). The workflows are
therefore a cheap, continuous check that the trilogy's REST contract really is
identical across all three implementations.

---

## 9. Traceability

The workflows satisfy **no** requirement — they are demo automation. What they
*demonstrate*, live and unprompted, is:

| Demonstrated behaviour | Requirements it exercises |
|---|---|
| Orders flowing end to end to `completed` | R19 – R24, R47 |
| Compensation after credit refusal, both steps visible | R27, R28, R42, R44 |
| Compensation after a lost stock race, with no release issued | R26, R33 |
| Remittance idempotency by `paymentReference` | R48 |
| Availability check is not a reservation | R31 |
| Read model as the only query source, with honest pending state | R54, R55 |
| One trace per order across both brokers, under load | R56, R57, R59 |
