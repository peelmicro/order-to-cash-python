# Brief — spec_author, feature 13 `orders_aggregate` (phase 8)

**Task:** write `specs/orders_aggregate/{requirements,design,tasks}.md` for feature 13, then set its `status` from `pending` to `spec_ready` in `feature_list.json` (edit only that one line; no other agent writes the file while you run). Stop there: the human gate follows. Return a summary of at most 15 lines; the detail lives in the files.

## Inputs (exact paths)

- Feature entry: `feature_list.json`, id 13 — six acceptance items, including "rehydrate validates its invariants on every load" and "cancelled requires a reason, set inside the accepted transition".
- Shared spec (read-only): `specs/shared/requirements.md` (R5–R10), `specs/shared/domain-model.md` (§3.3 Table T-1), `specs/shared/test-matrix.md`.
- #8's spec: `../order-to-cash-dotnet/specs/orders_aggregate/{requirements,design,tasks}.md` (128 / 546 / 92 lines).
- #7's spec: `../order-to-cash-nestjs/specs/orders_aggregate/{requirements,design,tasks}.md`.
- #8's effort entry and review findings: `../order-to-cash-dotnet/progress/history.md` lines 629–675 (one defect: two of `Rehydrate`'s four checks survived deletion; advisories A1–A5; "Notes for #9").
- #8's code for citations: `../order-to-cash-dotnet/src/Orders/Domain/`; #7's: `../order-to-cash-nestjs/apps/orders/src/domain/`.
- What #9 already has: `services/orders/src/otc_orders/domain/` contains only `__init__.py` and `value_objects/__init__.py`; the shared kernel is `packages/shared_kernel/src/otc_shared_kernel/` (`money.py`, `quantity.py`, `unique_id.py`, `business_reference.py`, `currency_exponent.py`, `entity.py`, `errors.py`, `gln.py`).
- Architecture guards the domain code will meet: `tests/architecture/test_money_guard.py` (read it for the domain import allow-list and forbidden names), `tests/architecture/test_write_path_population.py`, and the import-linter contracts in `pyproject.toml`.

## What to decide, and how

- `requirements.md` is a pointer document citing R5–R10 verbatim (as #8's is); no new `R<n>` unless genuinely new, and any new one is flagged.
- `design.md` carries the Python design and the **ported-idiom ledger** (one row per idiom: "#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z", each half cited with file and line from the checkouts; where #9 hand-builds a property, `tasks.md` names the guard test). Include the Python questions from CLAUDE.md "Porting from #7 and #8" that apply to a pure domain (integer division, typing gaps, frozen dataclasses/`frozenset` immutability, enum token tables).
- Map each #8 finding from the history entry (the defect and A1–A5) to an explicit design decision or task: avoided how, with which armed test. The `Rehydrate` defect must end as named tests that fail when each load-time check is deleted.
- Before carrying any open point to the gate, check what #8 and #7 did (both checkouts are on disk). Go to the gate with recommendations and evidence; a genuine open point names why no citation was available.
- `tasks.md` names the files the feature may touch, derived from what the design needs (if an architecture test or import-linter contract must change, say so there; do not leave it to a brief). Tests are tasks inside the loop, and each guard has an arming task.
- `specs/shared/` is read-only. If you conclude it is wrong or incomplete, write the proposal as `SA-6` in `requirements.md` and say so in your summary; do not edit `specs/shared/`.

## Bounds

- Write only `specs/orders_aggregate/**` and the one status line of `feature_list.json`. No code, no tests, no git command that writes the index or working tree.
- Markdown: no hard line-wraps in prose.
