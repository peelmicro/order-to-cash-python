# Premise check — brief_impl_orders_aggregate.md

VERIFIED requirements.md §6 (heading at line 113) holds OP-1 closed at the gate 2026-10-06 with the kernel as placement (sed -n 117p).
VERIFIED tasks 1.4-1.7 are the OP-1 A tasks (format_money to kernel) (grep -n on tasks.md lines 25-28); grep -i option on tasks.md finds no option-B text.
VERIFIED design.md §2 ledger (line 38), §10 Domain errors (303), §11 Test design (324), §12 Arming (338).
VERIFIED tasks.md preamble lists "Files this feature may touch" (lines 7-16).
VERIFIED feature 13 orders_aggregate is in_progress in feature_list.json (python json load).
VERIFIED ./quality.sh exists, executable (-rwxrwxr-x).
VERIFIED CLAUDE.md has the arming protocol (line 117) and the defeat list (line 129).
VERIFIED spec approved 2026-10-06 (progress/current.md:4); seed/orders/shared_kernel test dirs exist.
UNVERIFIABLE quality.sh runs with the stack stopped: quality.sh has no stack reference; the otcpy containers are currently running (docker ps); only running ./quality.sh with the stack down settles it.
FALSE/CONFLICT brief line 23 "Do not edit specs/ except ticking tasks.md boxes" vs tasks.md line 13 and task 6.6 (line 107), which mandate editing specs/shared/test-matrix.md (Status cell of R5-R10 and coverage counts). Brief line 9 "nothing outside" the list is fine.
Verdict: DO NOT ACT as written (1 conflict, 1 unverifiable).
