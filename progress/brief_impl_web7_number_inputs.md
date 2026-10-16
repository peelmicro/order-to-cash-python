# Brief — implementer, **#7** (`../order-to-cash-nestjs`) web app: malformed number-box text silently dropped (probe, then fix) — **full group** (money parsing)

**Authority:** the maintainer, 2026-10-15 (#9 Phase 16, session 3): "Go ahead with the probe-and-fix in #7". #7 is complete, and this is the only change authorised there. No commit (the maintainer commits at a wrap-up).

**The suspected defect** (found in #9, not yet probed in #7): in Chromium, a `type="number"` input whose text the browser cannot parse (`"1-2"`, `"12e"`, `"19.99-"`, `"5-"`) reports `value === ""` with `validity.badInput === true`, and fires no event that changes it. If the page treats `""` as "not typed", the order is placed at the catalogue price, or with no discount, and no error is shown. #9's evidence: `progress/review_web_app.md` "Stage 2 review", B1 (Chromium, production build), and #9's fix in `apps/web/src/app/pages/(app)/orders/place.page.ts` with its tests in `apps/web/src/app/place-order.spec.ts` (`grep -rln badInput apps/web/src`, leader, this session; read for the idea only; #7 is Vue/Nuxt). (#9's `components/draft-value.ts` is a separate fix, for a keystroke scramble, and is not part of this brief.)

## Population (leader's search, this session)

`grep -rn 'type="number"' apps/web/app --include=*.vue` in #7 gives five inputs: `app/pages/orders/place.vue:370`, `:381`, `:395` (quantity, unit price, line discount: read which is which), `app/pages/billing/index.vue:384` (Register payment; see the comment at `:374`), `app/pages/stock/index.vue:251` (replenish). Re-run the search, and also search for any number input not written as a literal attribute (`:type=`, components in `app/components/**` that render `<input>` with a type prop). State the commands and their full output.

## Step 1 — probe (before any edit)

For **each** of the five inputs, in Chromium against #7's **production build** (`nuxt build`, then the built server), type each malformed text and record: what the box shows, what the page shows, and the bytes the browser sends (or that nothing is sent). Controls: `"19.99"` → 1999 and `"0.29"` → 29 for money; a valid integer for quantity. #7 has `@playwright/test` (`apps/web/package.json`); scripts live outside tracked paths, in `../order-to-cash-python/.arm/web7/probe/` (git-ignored; #7 ignores no `.arm/`).

- **Do not start #7's compose stack** (`otc`): only one trilogy stack runs at a time, and #9's stage 3 is running at the same moment. Stub what the pages need: Playwright `page.route` for browser calls, plus a stub Gateway you start and stop by PID. The Nuxt server does call the Gateway itself: `server/api/orders/index.post.ts`, `invoices/[id]/payments.post.ts` and `stock/replenish.post.ts` use `gatewayFetch` (`server/utils/gateway.ts`), as the premise check verified. The stub Gateway is also where you read the bytes sent. How did #7's own tests reach these pages? (`apps/web/app/pages/**/*.spec.ts`, `e2e/`.)
- **Port: not 3010 and not 3000** (#9 uses 3010 during this session). Use 3017, set via `WEB_PORT`/`PORT`; check `ss -ltnp` first.
- Classify each input: **defect** (the malformed text is lost and something is sent, or the user is told nothing), or **safe** (refused in words, nothing sent), with the evidence.

## Step 2 — fix (every input classified defect; if none, stop after step 1 and report)

- Rule (the same as #9): malformed text is *typed but unparseable*. The page refuses it in words naming the field, and nothing is sent: no fallback to the catalogue price, no "no discount", no zero. Valid text keeps today's exact minor units.
- Mechanism: your choice, with the reason recorded. Either read `validity.badInput` in the handler, or switch the box to `type="text" inputmode="decimal"` (`numeric` for quantity), which is #8's choice (`../order-to-cash-dotnet/apps/web/src/features/orders/place-order-form.tsx`, find the input) so that #7's existing string parser sees the raw text. If you switch, say what happens to any `step`/`min` the box carried, and whether a test asserts `step` (#7 `app/pages/orders/place.currency.spec.ts`?).
- Keep the change to these inputs and their handlers/parsers. No refactor beyond it.

## Guards (each armed under #9's protocol: backup into `../order-to-cash-python/.arm/web7/` with `sha256`, the violation, the ONE named test, the verbatim failure, restore by `cp`, `cmp`)

1. Per input fixed, a component test in #7's Vitest suite: the box holds malformed text (if `type="number"` stays, jsdom cannot produce `badInput`: define `validity` on the element, as #9 did), and the test asserts **no request** and **the problem text shown**. One arm per input: delete the refusal.
2. A **population guard**: every number-like input under `apps/web/app` is in a literal expected set, and each member has its refusal. Arm by adding a bare input.
3. Re-run your step 1 probe on the fixed production build: every malformed text sends nothing and shows the problem; the controls still send 1999 / 29 / the integer.
4. Defeat list: state which rows apply to guard 2 (at least 3, 4, 5, 11 and 12) and the result of each.

## Gates (in `../order-to-cash-nestjs`)

`pnpm --filter` the web app's `test`, its typecheck and lint (read `apps/web/package.json` and #7's `init.sh`/root `package.json` for the exact commands), and `nuxt build`. Reconcile the test count with the count before your change (run it first). Every run under `setsid --wait timeout -k 10 …`; wait on PIDs, never `pgrep -f`.

## Bounds

- #7: `apps/web/app/**` (pages, components, lib, their specs) and a new `progress/impl_web_number_inputs.md`. Nothing else in #7: not `specs/`, `packages/`, `apps/<services>`, `feature_list.json`, `progress/history.md` (the leader writes that), `.gitignore`.
- #9: only `.arm/web7/**`. Do not read or touch `../order-to-cash-python/apps/web` beyond reading the two files named above.
- No git command that writes the index or working tree in either repo. No new package. Stop everything you start (`docker ps`, `ss -ltnp` before and after).

## Output

Write `../order-to-cash-nestjs/progress/impl_web_number_inputs.md`: the population search, the step 1 probe table (input × text → box, page, bytes, class), the mechanism chosen and why, the change per file, the guards and the arming table (mutation, test, verbatim message, `sha256`, `cmp`), the defeat-list rows, the step 3 probe table, the gates (with counts before and after), effort in minutes, `Packages installed: none`. Return only the record's path plus at most 5 lines.
