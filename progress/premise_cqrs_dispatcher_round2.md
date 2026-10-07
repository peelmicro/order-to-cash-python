# Premise check: brief_impl_cqrs_dispatcher_round2.md

VERIFIED   F1-F4 and "What must change" items 1-5 exist in review_cqrs_dispatcher.md (headings F1-F5, list items 1-6 at the end; F5 = leader).
VERIFIED   `./init.sh` ends coherent: "init.sh: environment and state are coherent", exit 0.
VERIFIED   feature 43 `cqrs_dispatcher` status in_progress (feature_list.json).
VERIFIED   decorator census (AST over services/*/src/**/*.py, callee via ast.unparse): app.get, asynccontextmanager, classmethod, dataclass, model_validator, property, staticmethod; exactly seven, no others.
FALSE      "CLAUDE.md's Phase 7 rule: when a syntax guard keeps losing, change its kind" : CLAUDE.md has no Phase 7 rule (only line 140 "when a syntax guard keeps losing, test the behaviour, or inspect what actually runs"); the Phase 7 rule is progress/current.md:41 item (3), "When a syntax guard loses twice, propose a change of kind (allow-list from a census, or a behaviour test) and a stopping rule".
VERIFIED   tests/architecture/test_money_guard.py has the census pattern (line 11 docstring, 89 allow-list, test_the_import_allowlist_is_the_census_derived_from_the_real_population at 644).
FALSE      "the reviewer's sentinels B1 and C1-C4" defined in the review: review line 73 says "sentinels for B1, C1-C4 above" but nothing above defines them (grep: only C1-C4 are CHECKPOINT headings, lines 87-96). Rule letters B and C exist in test_cqrs_registration_explicit.py, and the Q4 probe shapes are described in prose (decorator + loop drain, alias, partial, getattr, basename sibling), but no B1/C1-C4 labels exist anywhere.
CONFLICT   none. Temp files in services/*/src (brief) are allowed by the review; the review's "where feasible" for alias/partial/getattr is compatible with the brief's stopping rule.
