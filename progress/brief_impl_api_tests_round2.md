# Brief — implementer, feature 31 `api_tests`, round 2 (review D1–D6; test and record fixes only)

**Task:** fix the six defects in `progress/review_api_tests.md` § Defects (D1–D6) and meet its § "What must change before re-review" (six items, lines 199–206). Each defect states its own fix and the arm to re-run. Feature 31 is `in_progress` (set by the reviewer). Read `CLAUDE.md` on disk for the arming protocol. Your predecessor's record is `progress/impl_api_tests.md`; amend it in place (§7, §10, §11, §12 and the fleet-test count), and add a new section "Round 2" listing each Dn with its change and its re-run arm verbatim.

## Inputs, per defect (lines as the reviewer gives them)

- **D1:** `tests/api/test_api_instruments.py:255-275` and `tests/api/api_support.py:257`.
  - Make the probe yield, and bound the `poll` call from outside, so that I9 (sleep deleted) and I10 (bound widened) each fail **with a message naming the claim** within seconds, not exit 124.
  - Re-run both arms and record the messages verbatim.
- **D2:** re-run the #8 backlog enumeration over `../order-to-cash-dotnet/feature_list.json` **with no id filter**.
  - Print the command and the full hit list; classify every hit. The reviewer names 38, 52, 54, 57, 60, 71, 73 and feature rows 5–29, which may be one group with a reason.
  - Name #8 id 57 (`completion_pair_has_no_causal_edge`) and #8 id 60 (`envelope_fixture_collisions_defeat_provenance_assertions`) as avoided or recurred, with the test that shows it. The reviewer's arm R24-ID57 is in `.arm/r31/arms_clean.log`.
- **D3:** `tests/api/test_black_box_api.py:215-223`. The outbox clause must identify the payment (its `paymentReference`, and the invoice or order it belongs to), not merely count to one.
  - Re-run the reviewer's R48-SUBST (the filter reads `control_invoice["invoiceReference"]`) and see it fail with a message naming the outbox.
  - Correct §11 (defeat-list row 3 applies).
- **D4:** `tests/api/test_money_representation.py:305-331, 374-378`. The completed order's detail meets `DETAIL_MINIMUM` unconditionally, or each cell's count must reach its minimum. Keep the R50 exemption for poll-time documents only.
  - Re-run the reviewer's R1-HC-T1 (`wire_response` reports `headerComplete: false` and drops `currency`) and see the main sweep fail.
- **D5:** the fleet-test count is 10, not 11. Re-derive it with `pytest --collect-only` and print the command.
- **D6:** add the effort record. Timings measured by the leader this session, from file times and the session log:
  - the brief was written 07:56:22 and the baseline `quality.sh` started 07:57:32;
  - the first run was cut by the Claude Code process exiting at about 08:59, with `api_support.py` armed at I9;
  - the run was resumed at about 15:52, the record last written 16:36:36 and the final `quality.sh` log 16:33:34;
  - the review ran from about 18:37 to 19:09:32 and was rejected;
  - the Mongo readiness fix (entry 217) and the `booted` race fix (entry 218) were separate light entries between 16:40 and 18:35.
  - Then round 2: your own start and end.

## Process and bounds

- Arms: backups in `.arm/n31r2/` with `sha256`; one named test per arm under `setsid --wait`, with a timeout that kills the process group; restore with `cp` + `cmp`; clear `__pycache__`; re-run green.
- After the fixes, run `tests/api/` once (developer infrastructure down) and then `./quality.sh` once. Wait on the PID and read the verdict from the log. If any test outside `tests/api/` fails, record it verbatim and return; do not re-run it to green.
- You may touch `tests/api/**`, `progress/impl_api_tests.md`, and feature 31's status line (set it to `in_review`).
  - No edit under `services/**`, `packages/**`, `specs/**`, `tests/observability/**` or `conftest.py`, other than temporary arms restored by `cp` + `cmp`.
  - No git command that writes the index or the working tree.
- Return only "result in `progress/impl_api_tests.md`" plus at most 4 lines.
