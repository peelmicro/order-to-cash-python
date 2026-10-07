# Premise check: brief_impl_cqrs_dispatcher.md
VERIFIED packages/cqrs/src/otc_cqrs holds only __init__.py with a docstring (ls: only __init__.py, content `"""otc-cqrs."""`)
VERIFIED CLAUDE.md quotation (grep line 78 matches verbatim)
VERIFIED feature 43 status in_progress (feature_list.json)
VERIFIED #8 ece0f2e = "feat(cqrs): hand-rolled dispatcher..." touching src/Cqrs and tests/Cqrs.UnitTests
VERIFIED 4c6ed34 orders acceptance (Program.cs calls AddDispatcher); 5a84e81 fulfillment (AddDispatcher last); 17ce0d1 billing (AddDispatcher last)
VERIFIED #8 history.md 676-729 is the cqrs_dispatcher entry; D1 (singleton scope capture), D7 (MediatR guard read wrong source), D8 (MethodInfo.Invoke dropped CA2016), D9 (reviewer.md stale), D10 advisory (hardcoded 3 paths of 21), Notes for #9 all as described
VERIFIED ../order-to-cash-dotnet/src/Cqrs/ and tests/Cqrs.UnitTests/ exist
VERIFIED #7 uses @nestjs/cqrs under apps/orders/src (grep -l hits, e.g. app.module.ts)
VERIFIED find services -name composition.py returns only services/seed/src/otc_seed/composition.py
VERIFIED features 15, 17, 19, 23, 24, 25 each carry a "carried from cqrs_dispatcher" acceptance item
VERIFIED test_dependency_freedom.py parametrized over shared_kernel, cqrs asserting dependencies == []
VERIFIED pyproject.toml contracts domain-purity (all service domains) and shared-kernel-purity forbid otc_cqrs; test_import_contract_coverage.py asserts it
VERIFIED packages/shared_kernel/tests/test_mypy_rejects_float.py runs mypy --strict via subprocess, with reject and accept (control) tests
CONFLICT (minor) feature 43 acceptance item 2 reads "handlers registered explicitly in each composition root"; the brief bars creating composition roots and the item in feature 43 itself was not amended to say its per-service half is carried (the carrying is on features 15,17,19,23,24,25). Brief's own scope split covers it via test handlers, but item 2 as written in feature 43 cannot be fully met under the brief.
NOTED: brief says "six services" (CLAUDE.md wording); services/ also has seed, a composition root exists there.
