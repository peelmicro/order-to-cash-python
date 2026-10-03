# Current session

**Feature:** none — Phase 2 closed, awaiting Phase 3
**Status:** idle
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Brief for phase 3 — shared spec + public README (steps 4–5).**

- **What:** copy the seven files of `specs/shared/` from `../order-to-cash-dotnet` byte for byte, recording #8's HEAD SHA in the commit; reset `test-matrix.md` by the `SA-1` recipe (Status → `TODO`, counters 0/0/63, assessment-specific asides removed by class); copy `n8n/workflows/*.json` unchanged. Then the initial README, then the #9 row in #7's and #8's READMEs.
- **Proof, not assertion:** `init.sh` §5d must turn from WARN to OK against **both** siblings (6 files each); columns 1–4 of `test-matrix.md` identical on all 63 rows, by a script, not by eye; the leak sweep reported as command + full output + one classification per hit.
- **Commits:** spec copy on its own; README on its own; one commit in each sibling repository for its #9 row — each approved separately.
- **Process weight:** light (copy + docs). #7 ~2.5h, #8 ~0.75h for the spec copy.
- **Decision for the maintainer:** none expected. If the leak sweep finds a real stack term in the reusable part, it is reported as a defect against all three repositories, not fixed silently.

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
