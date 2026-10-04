# Current session

**Feature:** none — Phase 4 closed, awaiting Phase 5
**Status:** idle
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Brief for phase 5 — `uv` workspace scaffold, shared kernel, contracts (step 8).** Three features, ids 6 → 7 → 8, in that order; one `in_progress` at a time.

- **`monorepo_scaffold` (id 6):** root `pyproject.toml` (`[tool.uv.workspace] members = ["packages/*", "services/*"]`, `dev` group, ruff, `mypy --strict` with the **only** override `aiokafka.*` and `asyncpg-stubs` in the dev group, pytest with asyncio loop scopes chosen and written down, DeprecationWarnings as errors with one targeted filter for `testcontainers.community.nats`, coverage); `uv.lock` committed; the six services + `seed` as `services/<name>/src/otc_<name>/{domain,application,infrastructure,presentation}` with a minimal FastAPI app and lifespan; `packages/cqrs` with `dependencies = []` asserted; import-linter forbidden / layers / independence contracts **each seen failing**, including a nested domain subpackage and `shared_kernel` (#8's NetArchTest selector missed both); the AST money guard armed on `float`, `/` and `decimal`; `apps/web` scaffolded with Analog under pnpm 12.8.1 (approved departure from #8); `quality.sh`. Process: **light** for the scaffold, but every guard is armed — they are countable claims.
- **`shared_kernel` (id 7):** `Money` (`int` minor units, no division — `domain-model.md` M3), `Quantity`, `GLN` (mod-10), `OrderNumber`, `UniqueId`, `Entity`, `AggregateRoot`, `DomainError`, the literal ISO 4217 exponent table (SA-5) with a JSON export for the web. Process: **full** (money domain) — implementer, then reviewer on Opus, defeat list.
- **`contracts_package` (id 8):** `scripts/generate_contracts.py` (AsyncAPI components extracted, datamodel-code-generator, OpenAPI models) with a drift check; the envelope and **one** serializer configuration (camelCase aliases, compact JSON, raw non-ASCII, `occurredAt` as `…mmmZ` from an explicit formatter); #8's 12 golden envelopes as the oracle — envelope byte-exact, payload semantically equal, key order not asserted. Process: **full** (wire contract).
- **Phase 1 findings that land here** (plan, phase 1 "Findings that change later phases"): `testcontainers.community.*` paths; `create-analog` runs `git init` (delete `apps/web/.git`, check `git status`); the template's own `AGENTS.md`/`CLAUDE.md` — **decide at the gate** keep/adapt/remove; pnpm `allowBuilds` in `apps/web/pnpm-workspace.yaml`, deny with a reason per entry; `resolve.tsconfigPaths: true` and remove `vite-tsconfig-paths`; spartan generator needs `components.json` first or it exits 0 having done nothing; consider a current `jsdom`.
- **Read each feature's `acceptance` in `feature_list.json`** — #8's review findings are written in as criteria; the effort entry names each as avoided or recurred.
- **Baselines** (`progress/history.md` of each sibling): #7 ~3.5h / ~1.5h / ~2.5h; #8 ~3h (one rejection) / ~1.25h (one rejection, six defects) / ~2.7h (mostly oracle capture, which #9 inherits).
- **Commits:** `monorepo_scaffold`, `shared_kernel`, `contracts_package`, one each.
- **Decision for the maintainer:** the template's nested `AGENTS.md`/`CLAUDE.md` in `apps/web` (go to the gate with a recommendation).
- **Infra note from phase 4:** the stack may still be running (`otcpy`); integration suites must pass with it **down** (#8 id 104).

---

## Template (reset to this on session close)

```markdown
# Current session

**Feature:** `<name>` (id <n>, phase <n>)
**Status:** <status>
**Session started:** <date>

## Goal

## Decisions taken this session

## Blockers

## Notes
```
