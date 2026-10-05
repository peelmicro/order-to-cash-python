# Premise check: brief_shared_kernel.md

VERIFIED   packages/shared_kernel/pyproject.toml has dependencies = [] : `cat` shows `dependencies = []`
VERIFIED   src/otc_shared_kernel/__init__.py is a placeholder : only file in src/otc_shared_kernel
VERIFIED   tests/architecture/test_money_guard.py, test_dependency_freedom.py exist (plus test_import_contract_coverage.py, test_mypy_policy.py, test_warning_policy.py) : `ls tests/architecture`
VERIFIED   money guard covers packages/shared_kernel/src + every service domain : test_money_guard.py:23-25 (glob services/*/src/otc_*/domain; rglob shared_kernel/src)
VERIFIED   AST guard forbids name `float` : test_money_guard.py:55 `node.id == "float"`
VERIFIED   test_dependency_freedom parametrised over shared_kernel and cqrs : test_dependency_freedom.py:11
VERIFIED   domain-import allowlist guard exists : test_money_guard.py:172 test_domain_and_shared_kernel_import_only_the_allowlist
VERIFIED   pyproject import-linter `shared-kernel-purity` and coverage config : pyproject.toml:204 and [tool.coverage.run] 119
VERIFIED   quality.sh section 6b is a marked TODO owned by feature 7 : quality.sh:37-43 `TODO(feature 7, shared_kernel)`
VERIFIED   domain-model.md section 2.1-2.5, M1-M4 : headings at 62/89/95/102/116; M1-M4 at 71-81
VERIFIED   2.3/CLAUDE.md name DES-, INV-, CR- : domain-model.md:100
VERIFIED   requirements.md R1 exists (R1-R4 range) : requirements.md:72
VERIFIED   test-matrix rows R1-R4 with Status column TODO, traceability rules at top; rule 3(b) scoped-and-ratified : test-matrix.md:89-92, rule 3
VERIFIED   openapi.yaml lines 44-60 carry SA-5 : Money section starts line 44, SA-5 at line 58, "EUR, GBP and USD are 2; JPY is 0; BHD is 3"
VERIFIED   #8 history.md lines 249-303 are the shared_kernel entry : line 249 `## shared_kernel (id 7, phase 5)`, 303 `---`
VERIFIED   #8 built only OrderNumber, history line ~266, D5 : history.md:266 `D5 - #7's sibling business references were not built`; src/SharedKernel has OrderNumber.cs only
VERIFIED   #8 src/SharedKernel files named (Money, Quantity, GLN, OrderNumber, UniqueId, Entity, AggregateRoot, DomainError, Errors/, CurrencyExponent) : `ls` shows all
VERIFIED   #8 tests/SharedKernel.UnitTests exists : `ls`
VERIFIED   #8 kept apps/web/src/lib/currency-exponents.json : `find` -> order-to-cash-dotnet/apps/web/src/lib/currency-exponents.json
VERIFIED   #8 has a both-directions table/JSON parity test : CurrencyExponentWebParityTests.cs:33 `..._InBothDirections`
VERIFIED   #8 Quantity has From(double) : Quantity.cs:32
VERIFIED   #8 D1, D6, D7 and the `0000000000000` GLN findings : history.md 249-303 text
VERIFIED   #7 built all four business references : business-reference.ts classes OrderNumber/DespatchReference/InvoiceReference/CreditLineReference, prefixes ORD/DES/INV/CR
VERIFIED   #7 has an exhaustive GLN single-digit-mutation sweep : gln.spec.ts:76 `rejects every single-digit mutation of a valid GLN`
VERIFIED   #7 shared-kernel domain dir is packages/shared-kernel/src/domain/ : find lists it
FALSE      "Status is already `in_progress`" for feature 7 : `grep '"id": 7,' -A8 feature_list.json` shows "status": "pending" (and git HEAD also pending); only feature 6 was changed to in_progress in the working tree
UNVERIFIABLE "feature 6 green" : would need the quality.sh / pytest suite
