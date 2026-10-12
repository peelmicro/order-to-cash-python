# Brief — reviewer, feature 25 `gateway_rest_auth` (phase 13, full group, round 1)

**Task:** approve or reject feature 25 (`in_review`). Inputs: the implementer's record `progress/impl_gateway_rest_auth.md` (294 lines; read its "Read this first" paragraph and §12 first), the brief it worked from `progress/brief_impl_gateway_rest_auth.md` (its Must-hold list is your checklist, with the eight acceptance items of `feature_list.json` id 25), the premise check `progress/premise_impl_gateway_rest_auth.md`, and the working tree (`git status`; nothing is committed). CLAUDE.md on disk is binding — `grep` it before quoting a rule.

## Already settled by the leader (do not re-open without new evidence)

- **`orderDiscount` refused by real Orders** (§12): an approved inherited ruling, `specs/orders_aggregate/design.md` §5.4 (#7 and #8 refuse a non-zero `orderDiscount` the same way). Not a finding against 25 — but check the Gateway maps Orders' refusal to the status `openapi.yaml` declares for `placeOrder`.
- **R62 replay not built in Orders** (§12): owned by feature 27 (`specs/shared/test-matrix.md` §8, R56 – R60, R62). The Gateway's half is forwarding the `Idempotency-Key` as `requestId`; check that half only.
- **The staged rename** `services/gateway/tests/test_gateway_health.py -> tests/unit/` (a `git mv`, a process breach the implementer disclosed; the leader leaves it staged and records it). Not a code finding.
- **The Billing guard** `services/billing/tests/unit/test_no_internal_payment_timer.py`: its literal was updated by `test_maintainer` at the leader's request to list the Gateway's two mentions (the record's first paragraph has the before / after). Confirm the guard still fails when a third, unsanctioned file mentions the subject.
- **`.env.example`** gained the Gateway block from the record's §11 (leader edit). Check each name equals a `validation_alias` in `services/gateway/src/otc_gateway/infrastructure/settings.py` and that the dev `JWT_SECRET` value is accepted by the boot (≥ 32 bytes).

## Where to push hardest (the inherited failure modes of this exact feature)

1. **The seam** (`docs/lessons.md` line 123; #8 D1): every subject and every request payload the Gateway sends is derived from or asserted against `asyncapi.yaml`, and the real-responder integration tests (`orders.create`, `billing.invoice.list`, `billing.payment.register`, plus whatever else ran real) actually drive the real hosts. Substitute a sibling subject in `application/rpc_subjects.py` and a sibling key in one request payload; both must fail by name.
2. **The anonymous-route sweep** (#8 D2): the public set is a literal, the protected set is derived by subtraction from the real routes — with FastAPI 0.142's lazy `_IncludedRouter` (record §12), confirm the population the sweep walks is the routes actually served (make a protected route public; add a new protected route that the sweep must pick up).
3. **JWT** (#8 row 3): expiry, issuer, malformed, `alg: none`, wrong key, algorithm confusion — each armed; check the record's flipped-signature flake fix is a guard, not a retry.
4. **The three surviving arms** `C3`, `C8`, `Q3a`: read the record's reasons; decide whether each is an acceptable disposition (fix / accept with evidence and a re-open trigger) or a blocking gap.
5. **Acceptance 6 and 7** (payment correlation id = order id; the `RpcError` → HTTP rows of `openapi.yaml:673-675`): one test per row, armed by substitution of a sibling code; the fixture's order id, invoice id and request id pairwise distinct.
6. **Acceptance 5 and 8** (registration guard at the Gateway's real n; the lambda residual "does not apply" claim — re-run the grep).
7. **Acceptance 4** (list / detail from MongoDB only): the two new import-linter contracts — arm one yourself in a way the implementer did not (e.g. a lazy import inside a function, or an import through `otc_gateway.composition`).
8. **E1** (#8: money fields of the detail body unasserted): transpose two totals in the read-model mapping; it must fail.
9. **The two departures from #7 / #8 the record calls deliberate**: the body validation through `model_validate_json` in a `WrapValidator` (does a body FastAPI would accept bypass it on any route?) and "order not projected" → 503 + `Retry-After` for the payment route (does `openapi.yaml` declare that status for `registerPayment`?).
10. **The ledger**: verify at least the security and seam rows' "#7 relied on X" / "#8 supplied Y" halves in the checkouts (file and line); for each Guard cell, "what turns red if the row were false" must have been seen.

## Process

- Arm on copies in `.arm/r25/` (backup + `sha256`, `cmp` after restore, clear `__pycache__` / `.mypy_cache`); a timeout kills the process group. Never two test runs against the same containers at once. Use the developer stack only if you need a live check (it is stopped; `docker compose -p otcpy -f docker-compose.infra.yml start`, then stop what you started).
- You may run `./quality.sh` once at the end (developer stack down); record exit code, pytest time and pass count. The implementer's final run was `1 failed, 4422 passed in 497.20s` (the one failure is the Billing guard now updated).
- Read-only: no source or test edit, no git command that writes the index or working tree.

## Output

`progress/review_gateway_rest_auth.md`: verdict APPROVED or REJECTED; blocking findings (each with the mutation that survived and the remedy), non-blocking findings with a disposition, the arming table of your own mutations, and the avoided / recurred check on #8's D1, D2, D3, E1. If APPROVED, set feature 25 to `done` (that line of `feature_list.json` only); if REJECTED, set it to `in_progress`. Return only "result in `progress/review_gateway_rest_auth.md`" plus the verdict and at most 4 lines.
