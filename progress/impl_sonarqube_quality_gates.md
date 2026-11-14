# Implementation report — feature 34 `sonarqube_quality_gates` (phase 21, light, `sdd: false`)

Started 2026-11-14 13:32 CET. Finished 14:46 CET. `feature_list.json` NOT touched (the brief's bounds forbid it): the leader sets `in_review`.

## Summary

| Item | Result |
|---|---|
| 1. Coverage gate fails when breached, computed once across the workspace | DONE. One pytest process, one `.coverage`; artifact arms (domain-only, everything-but-domain) and a real pipeline arm (narrowed `testpaths`), each failing with its own message and exit code, each restored with `cp`/`cmp` and re-run green (full 5288-test run) |
| 2. ruff, mypy clean; import-linter green | DONE (outputs below) |
| 3. SonarQube scans Python and TypeScript to ANALYSIS SUCCESSFUL | DONE. Server confirms 487 Python + 96 TypeScript + 1 CSS source files and 480 + 38 test files; Python coverage imported with every path resolved. Quality gate `OK` (separate fact, below). TypeScript coverage is not imported (open point 1) |

## Files changed

- `sonar-project.properties` (new), `scripts/sonar-scan.sh` (new, executable).
- `quality.sh`: two comments only (SonarQube is not part of the script; section 6 is one process / one data file and where it was armed). `bash -n` clean. No step changed.
- `README.md`: section "Quality gates and SonarQube". `.env.example`: one comment (`SONAR_TOKEN`, `SONAR_HOST_URL`, `SONAR_NETWORK`, `SONAR_SCANNER_IMAGE`).
- `pyproject.toml`: unchanged (edited for arm 1b, restored, `cmp` identical, sha256 `4a1dd535…9a4e`, `git diff -- pyproject.toml` empty).
- `docker-compose.infra.yml`: unchanged (see open point 3). `.arm/phase21/` holds backups, logs and the token (git-ignored). No tests: item 3 is optional-tooling configuration, the proof is the live server (below); no R<n> row owned, so `test-matrix.md` is untouched.

## Item 2 — commands as `quality.sh` runs them (13:3x CET, before the long run)

```
$ uv run ruff format --check   -> 1259 files already formatted, exit 0
$ uv run ruff check            -> All checks passed!, exit 0
$ uv run mypy                  -> Success: no issues found in 985 source files, exit 0
$ uv run lint-imports          -> Contracts: 13 kept, 0 broken., exit 0
```

## Is coverage computed once across the workspace?

Yes. `quality.sh` section 6 is one `uv run pytest --cov` (`testpaths = ["tests", "packages", "services"]`, no xdist, `parallel` unset). The real run: `5288 passed in 1340.61s` (and `5288 passed in 934.79s` on the green re-run) with `5288 tests collected`; it wrote a single `.coverage` (no `.coverage.*` siblings). Inspecting it (`.arm/phase21/inspect.py`): tables `file, context, arc, line_bits, tracer`, **491 files, 1 context, has_arcs=1** (branch measurement; one `arc` row set per file, a set union of everything every test executed). Section 6b reads that same file through `coverage report --include`. Nothing is averaged per package. Totals: line+branch 96.40% overall (section 6, `Required test coverage of 60.0% reached`), domain+shared_kernel 98% (section 6b, exit 0).

## Item 1 arm (a): artifact corruption (the threshold is untouched)

Backup `.arm/phase21/coverage.good`, sha256 `cb3a1f77f872d1579c113df0400e0754249d463ca55f166410239d4f0c782653`. `corrupt.py` deletes `arc` rows. Each gate is run on its own, as the exact `quality.sh` command line (section 6's gate is `fail_under = 60` from `pyproject.toml`, run through `coverage report`, which is the call pytest-cov makes at the end of the run; arm (b) goes through pytest itself).

Domain-only (78 domain/shared_kernel files, 4542 arc rows deleted):
```
overall: TOTAL ... 81%                                  exit=0   (domain breach does not trip the overall gate)
6b:      Coverage failure: total of 0 is less than fail-under=80   exit=2
```
Everything-but-domain (413 files, 21781 arc rows deleted):
```
overall: Coverage failure: total of 16 is less than fail-under=60   exit=2
6b:      TOTAL 2169 23 386 18 98%                       exit=0   (overall breach does not trip the domain gate)
```
Restore: `cp .arm/phase21/coverage.good .coverage`, `cmp` identical, sha256 equal to the backup, both gates green (`TOTAL ... 96%` / `98%`, exit 0). Log: `.arm/phase21/arm1a.out`.

## Item 1 arm (b): a real exclusion in the pipeline

Mechanism chosen: **a test path left out of `testpaths`** (`["tests", "packages", "services"]` -> `["tests/architecture"]`). Why not a coverage `omit`: `omit` removes a file from numerator AND denominator, so it cannot create a shortfall, it raises the figure. Measured on the good data (read-only): `coverage report --omit='*/infrastructure/*'` gives 98% against 96%. So `omit` is a way to launder a gate, not to breach one; "the code the tests never ran" is the real Python analogue of #8's coverlet `Exclude` (data goes missing from the measurement), and it is what happens when someone narrows the pipeline.

Backup `.arm/phase21/pyproject.bak` (sha256 `4a1dd5351ed1c4c0b729f94a10f88423d05dfeb503a8991ad1e76ec1f3ae9a4e`), edit `testpaths` with `sed`, then the real commands:
```
$ uv run pytest --cov --cov-report=term-missing:skip-covered
TOTAL  14051  7192  2076  22  43%
FAIL Required test coverage of 60.0% not reached. Total coverage: 43.14%
703 passed in 110.10s                                    pytest exit=1
$ uv run coverage report --include='*/domain/*,packages/shared_kernel/*' --skip-covered --fail-under=80
Coverage failure: total of 53 is less than fail-under=80   exit=2
```
Restore: `cp .arm/phase21/pyproject.bak pyproject.toml`, `cmp` identical, sha256 equal, `git diff -- pyproject.toml` empty. Then the **full real green re-run** (`uv run pytest --cov --cov-report=term-missing:skip-covered`): `Required test coverage of 60.0% reached. Total coverage: 96.40%`, `5288 passed in 934.79s`, exit 0; section 6b on its output exit 0 (`.arm/phase21/pytest_rerun.log`, `rerun_6b.log`). No fixture-based arm of "only one test file" is needed: arm (b) already is the pipeline.

## Item 3 — SonarQube

- **Scanner:** `sonarsource/sonar-scanner-cli:12.1.0.3233_8.0.1`, pinned in `scripts/sonar-scan.sh`. Docker Hub lists that tag with digest `sha256:23ca0f13…`, and the cached `latest` has the same digest and image id (`sha256:8368f553…`), so the pin is exactly what was cached. The plain CLI analyses Python and TypeScript in one pass (Sensor Python, Sensor JavaScript/TypeScript/CSS), no new runtime on the host. It runs on `otcpy-net` against `http://otcpy-sonarqube:9000`.
- **File name:** `sonar-project.properties`. #8's rename reason (`dotnet-sonarscanner end` refuses to finish while that name exists) is specific to the .NET scanner and does not apply to the plain CLI, which reads that name from the working directory. Verified live: the scan read it (key `order-to-cash-python`).
- **Instance:** fresh `otcpy-sonarqube`, admin password changed through the API, token generated; both kept only in `.arm/phase21/sonar.env`.
- **Result:** `ANALYSIS SUCCESSFUL ... dashboard?id=order-to-cash-python`, `EXECUTION SUCCESS`, exit 0 (scan 2, `.arm/phase21/scan2.log`; scan 1 differed only by the tsconfig error below).
- **What the server imported** (`.arm/phase21/api_final.out`, through `/api/measures/component` and `/api/components/tree`):
  - Source files: `py 487, ts 96, css 1` (584); test files: `py 480, ts 38` (518). 491 files in `coverage.xml` minus the 4 `otc_contracts/generated/` files I exclude = 487: **the Python file count matches exactly**.
  - Coverage: `packages` 524 lines to cover / 2 uncovered; `services` 13136 / 395. coverage.py's own uncovered is 400 including the 3 generated lines (397 matches within generated). `conditions_to_cover 2076`, `uncovered_conditions 184` equal coverage.py's 2076 branches and 2076-1892 = 184 exactly. So every path resolved and branch data came through.
  - `apps/web`: 1750 lines to cover, 1750 uncovered, 0.0% (no coverage report imported). Project-wide `coverage 86.7` (line 86.1, branch 91.1) is therefore a blend of ~96-99% Python and 0.0% TypeScript.
- **Path-mapping arm (substitute a valid sibling, mount `-v "$PWD:/usr/src"`, project key `otcpy-arm-path`, deleted after):** `ANALYSIS SUCCESSFUL`, `EXECUTION SUCCESS`, exit 0, with
  ```
  WARN  Invalid directory path in 'source' element: /home/.../packages/contracts/src   (x10)
  ERROR Cannot resolve the file path 'otc_billing/__init__.py' of the coverage report, the file does not exist in all 'source'.
  ERROR Cannot resolve 491 file paths, ignoring coverage measures for those files
  ```
  and the server then reports `coverage 0.0, lines_to_cover 14144, uncovered_lines 14144`. An exit code of 0 and `ANALYSIS SUCCESSFUL` do not prove coverage was imported. The restore is the committed script (mount at the host path), re-run green above.
- **Quality-gate status (separate from ANALYSIS SUCCESSFUL):** `OK`. The gate is "Sonar way" on new code: one condition `new_violations GT 0` evaluated `actualValue 0` against `period PREVIOUS_VERSION` on a first analysis, so the status says nothing about the 525 existing issues. Be careful quoting it.
- **Issues and suppressions:** 525 issues (23 bugs, 2 vulnerabilities, 500 code smells, 0 hotspots, 17.1% duplicated lines). **I suppressed none** (no `sonar.issue.ignore`) because nothing blocked the gate, and I did not judge the findings. Top rules: `python:S5778` 293, `python:S8714` 54, `python:S7503` 23, `python:S1192` 20, `typescript:S2871` 11, `python:S5863` 10. The 2 vulnerabilities and the 23 bugs are not triaged (open point 2). Only exclusions: the generated code (`packages/contracts/src/otc_contracts/generated/**`, `apps/web/src/generated/**`), build output, `.arm/**`. **[CORRECTED in Round 2: the build-output patterns and `**/*.d.ts` were NOT in effect in scans 1-2, a missing backslash cut them off; fixed.]**
- **Defect found and fixed in the file:** the first scan logged `ERROR Failed to parse tsconfig .arm/e2e32/e2e.bak/tsconfig.json`, because the scanner walks the tree for tsconfig files (the `.arm/` scratch copy is git-ignored but still found). `sonar.typescript.tsconfigPaths` now lists the three `apps/web` tsconfigs and `.arm/**` is excluded; scan 2 has no `ERROR` line. Note `apps/web/e2e/tsconfig.json` logs "No files to analyze" (its files are analysed through the spec tsconfig; 38 TS test files were indexed).
- **Optionality:** `quality.sh` has no `sonar` command (comment only); `scripts/sonar-scan.sh` exits 1 without `SONAR_TOKEN` or without `.coverage`.

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied it with | #9 supplies it with |
|---|---|---|---|
| Coverage merge | per-workspace `vitest.config.mts` `coverage.thresholds`, each its own gate (`../order-to-cash-nestjs/sonar-project.properties:53` lists ten lcov files) | an inline Python script in `quality.sh` OR-ing `hits > 0` per `(file, line)` over 18 cobertura files (`../order-to-cash-dotnet/progress/impl_sonarqube_quality_gates.md:47`, "Mechanism chosen") | one pytest process = one `.coverage` (SQLite arc table = the union); no merge code to arm; guard: arm (a) and (b) above, checked to fail |
| Scanner | untagged `sonarsource/sonar-scanner-cli` through `docker run --network otc-net` (`../order-to-cash-nestjs/package.json:58`) | global `dotnet-sonarscanner begin/end` around the build (`../order-to-cash-dotnet/package.json:87`) | the same container image as #7, tag pinned (`12.1.0.3233_8.0.1`) in `scripts/sonar-scan.sh`; run as the host user, mounting the repo at its own path |
| Properties file name | `sonar-project.properties`, read by convention (`../order-to-cash-nestjs/sonar-project.properties`) | `sonar-scan.properties`, renamed because `dotnet-sonarscanner end` fails on the standard name (`../order-to-cash-dotnet/sonar-scan.properties:12`) | `sonar-project.properties`: the rename reason is .NET-specific; the plain CLI read it live |
| Coverage-report path mapping | lcov paths relative to each workspace (`sonar.javascript.lcov.reportPaths`, `sonar-project.properties:53`) | cobertura `TestResults/**` with repo-relative filenames (`sonar.cs.cobertura.reportsPaths`, `sonar-scan.properties:120`) | coverage.py writes absolute `<source>` plus source-relative filenames; resolved only because the container mounts the repo at the host path; guard: the `/usr/src` arm (0.0%, "Cannot resolve 491 file paths") and the server-side file count (487) |
| Generated-code exclusions | `packages/contracts/src/generated/**` (`sonar-project.properties:43`) | Migrations, `*ModelSnapshot.cs`, `apps/web/src/generated/**`, shadcn `ui/**` | `otc_contracts/generated/**` and `apps/web/src/generated/**`; alembic is outside `src/` and never scanned; the coverage gate itself does not exclude generated code (4 files, all but 3 lines covered) |
| Web coverage import | `sonar.javascript.lcov.reportPaths` for 8 apps (`:53`) incl. `apps/web` | not imported, documented as a gap (`sonar-scan.properties:56-65`) | not imported (open point 1) |
| Issue suppressions | one multicriteria rule, `typescript:S7739` (`sonar-project.properties:103-105`) | none | none |

## #8's arms for this mechanism (`../order-to-cash-dotnet/progress/impl_sonarqube_quality_gates.md`)

- Round 1, domain-only breach by zeroing artifact hits: **ported** (arm (a), domain-only, exit 2, overall stays green).
- Round 2, overall-only breach by corrupting the non-domain artifact: **ported** (arm (a), everything-but-domain).
- Round 3, real coverlet `Exclude` filter (did not cross a threshold): **ported in intent, not in mechanism**: coverlet `Exclude` has no coverage.py analogue that breaches (`omit` raises the figure, measured), so the real-pipeline arm is the narrowed `testpaths`, which does cross both gates.
- Each restore proven by `diff -rq` and a per-file `cmp` loop over 18 reports: **not applicable** (one data file, one `cmp`, plus sha256).
- Gate logic extracted verbatim from `quality.sh` and sourced: **not applicable** (no inline script exists; the gates are `coverage report` / `fail_under`, run as written).
- `dotnet format --verify-no-changes`: **not applicable**; its counterpart is item 2 above.
- Optionality both ways (no sonar container in the plain stack, `dc:up:sonar` alone, no `sonar` in `quality.sh`): **ported**: the `sonar` compose profile is unchanged, `quality.sh` has only a comment mentioning it; I did not start the plain infra stack (the dev stack was down and was not mine to start).
- `.sonarqube/` not in `.gitignore`: **not applicable** (the plain CLI's `.scannerwork/` is already ignored, and the container wrote none to the tree).
- Global scanner tool unpinned: **avoided** (pinned image tag).

## How to test it (commands I ran)

```bash
uv run ruff format --check && uv run ruff check && uv run mypy && uv run lint-imports
uv run pytest --cov --cov-report=term-missing:skip-covered          # the exact quality.sh section 6; 5288 passed
uv run coverage report --include='*/domain/*,packages/shared_kernel/*' --skip-covered --fail-under=80
docker compose -f docker-compose.infra.yml --profile sonar up -d sonarqube   # see open point 3 on this machine
SONAR_TOKEN=... ./scripts/sonar-scan.sh                              # ANALYSIS SUCCESSFUL
SONAR_TOKEN=... python3 -I .arm/phase21/api.py order-to-cash-python  # what the server imported
docker compose -f docker-compose.infra.yml --profile sonar stop sonarqube
```
At the end `otcpy-sonarqube` is `Exited (130)`; `docker ps` lists only containers that are not mine (`kb-poc-*`, testcontainers with random names and their ryuk). Volumes `otcpy_sonarqube_extensions` and `otcpy_sonarqube_logs` kept (`otcpy_sonarqube_data` does not exist, see open point 3).

## Open points for the leader

1. **[DISPOSED in Round 2: #8's choice applied as is, gap documented, no dependency, no exclusion.]** **TypeScript coverage is not imported.** Neither #7 nor #8's committed state imported `apps/web`'s coverage in a way #9 can copy: #7 imports lcov for 8 apps (each workspace's vitest config emits `lcov`), #8 left web coverage out and documented the gap. #9's `apps/web/vite.config.ts` has no `coverage` setting, so there is no report, and adding one needs `@vitest/coverage-v8` (an npm package, so not added). Consequence: `apps/web` is 0.0% in the server and the project-wide `coverage` is 86.7%. Decision for you: add the dependency and an lcov reporter later (a feature that owns `apps/web`), or add `sonar.coverage.exclusions=apps/web/**` so the headline figure is Python-only.
2. 23 bugs and 2 vulnerabilities are untriaged (the gate is `OK` only because nothing is "new"). Listing them was not requested; I did not suppress anything.
3. **[DISPOSED in Round 2: no compose change; free disk, as #7 did (`../order-to-cash-nestjs/progress/impl_sonarqube_quality_gates.md:146`); README note stays.]** **Environment, this machine:** the disk holding Docker is at 91% (`df`: 85 GB free of 916 GB), above Elasticsearch's 90% high watermark. The committed compose service crash-looped (49 restarts, `no_shard_available_action_exception`) and the `-Des.cluster.routing.allocation.disk.threshold_enabled=false` option did not help (ES ignores it as a system property). I ran it with a throwaway override (`.arm/phase21/sonar-override.yml`, `/opt/sonarqube/data` on a 3 GB tmpfs), not committed, because the compose file is outside what the brief let me change beyond comments. Consequence: the SonarQube database is gone after `stop`, and the first start of the committed service on this machine still fails until disk space is freed. The README documents the symptom. I removed the volumes `otcpy_sonarqube_data/logs/extensions` created by my own failed starts; they were created today and held nothing.
4. `scripts/sonar-scan.sh` does not run the tests (the suite takes 15-25 minutes) and converts the existing `.coverage`; a stale file gives stale coverage silently. Documented in the script and README.
5. `feature_list.json` still needs its status line set to `in_review` by you.

## Round 2 (leader's correction round, 2026-11-14 ~14:48-15:05 CET)

### 1. Defect fixed: missing continuation backslash in `sonar.exclusions`

Confirmed: `sonar-project.properties` line 65 `  .arm/**,` had no trailing `\`, and `.arm/phase21/scan2.log:43` shows `Excluded sources: ... **/dist/**, .arm/**, tests/** ...` without the six following patterns. Fixed (`  .arm/**,\`). The file parsed as Java properties (backslash continuation, `.arm/phase21/` ad-hoc script over the real file):

```
sonar.projectKey: 1 values      sonar.sources: 11 values        sonar.exclusions: 11 values
sonar.projectName: 1 values     sonar.tests: 13 values          sonar.typescript.tsconfigPaths: 3 values
sonar.sourceEncoding: 1 values  sonar.test.inclusions: 4 values sonar.python.version: 1 values
sonar.python.coverage.reportPaths: 1 values
```
10 logical keys, all begin with `sonar.`; none starts with `*` or a space; no stray key. The 11 exclusions are the 11 patterns written in the file (2 generated, `node_modules`, `dist`, `.arm`, `.angular`, `.nitro`, `.output`, `test-results`, `playwright-report`, `*.d.ts`).

### 2. Rescan on a fresh instance (tmpfs data, uncommitted `.arm/phase21/sonar-override.yml`, new admin password and token)

`.arm/phase21/scan3.log`, scanned from the `coverage.xml` of the same `.coverage` as round 1:
```
13:49:38.147 INFO    Excluded sources: packages/contracts/src/otc_contracts/generated/**, apps/web/src/generated/**, **/node_modules/**, **/dist/**, .arm/**, **/.angular/**, **/.nitro/**, **/.output/**, **/test-results/**, **/playwright-report/**, **/*.d.ts, tests/**, **/tests/**, apps/web/src/**/*.spec.ts, apps/web/e2e/**/*.ts
13:49:37.093 INFO  138 files ignored because of inclusion/exclusion patterns
13:49:38.218 INFO  1130 files indexed (done) | time=71ms
13:50:25.676 INFO  ANALYSIS SUCCESSFUL, you can find the results at: http://otcpy-sonarqube:9000/dashboard?id=order-to-cash-python
13:50:26.343 INFO  EXECUTION SUCCESS
```
All eleven patterns are listed now (the `tests/**` ... tail is the scanner's own addition of the test inclusions). Server (`.arm/phase21/api_round2.out`): source files `ts 96, py 487, css 1` (584), test files `ts 38, py 480` (518): **identical to round 1 (96 and 487); no difference to explain by file name.** `coverage 86.7` (line 86.1, branch 91.1; `lines_to_cover 15410`, `uncovered_lines 2147`, `conditions 2076/184 uncovered`), `apps/web` 0.0% (1750 lines), `alert_status OK`, `bugs 23`, `vulnerabilities 2`, `code_smells 500`: identical to round 1.

The leader's brief says `apps/web/src/vite-env.d.ts` "was therefore analysed". That is **not what the server shows**: the file is absent from the server in the fixed scan, and also absent when I re-scanned with the old (truncated) exclusion value (`-Dsonar.exclusions=` the first five patterns, project key `otcpy-arm-d`, deleted afterwards). The two server file lists (all source and test components, 1102 each) are `diff`-identical, `grep -c vite-env` gives 0 (`.arm/phase21/files_arm_d.txt`, `files_round2.txt`). So the defect was real in the file (the log proves it) but changed no result today: the scanner does not turn this one declaration file into a server component either way. The fix still matters for any `.d.ts` or `.angular`/`.nitro`/`.output` content that does get indexed.

### 3. Triage of every open BUG and VULNERABILITY (no code change, nothing suppressed)

Export: `/api/issues/search?types=BUG,VULNERABILITY&resolved=false`, all pages: **25 issues** (23 bugs, 2 vulnerabilities; `.arm/phase21/issues.tsv`). Round 1 listed rule counts as "S5863 10, S3862 1, S930 1, S2871 11, S2068 1, S5332 1": same 25. Classification: FP = false positive, TP = true positive. Disposition options: fix, suppress (written reason), accept.

| # | Key (first 8) | Rule | Sev | File:line | Message | Class | Evidence | Proposed disposition |
|---|---|---|---|---|---|---|---|---|
| 1 | a51a6bbe | python:S3862 | BLOCKER | `services/orders/src/otc_orders/application/saga/fact_handler.py:150` | Replace this expression with an iterable object | FP | `closed: tuple[SagaOutcome, float] \| None` (line 91), assigned through `nonlocal` in the work closure (94, 127, 142); line 149 `if closed is not None` narrows it to the tuple that `SagaMetrics.closed(outcome, milliseconds)` takes; `mypy --strict` accepts it. Sonar loses the type across the `nonlocal` closure | suppress, written reason (file-scoped multicriteria) |
| 2 | 904bb064 | python:S930 | BLOCKER | `services/gateway/src/otc_gateway/presentation/openapi_shape.py:44` | Remove this unexpected named argument 'separate_input_output_schemas' | FP | installed FastAPI 0.142.2: `'separate_input_output_schemas' in inspect.signature(fastapi.openapi.utils.get_openapi).parameters` is `True`; Sonar's bundled stub is older. The argument is load-bearing (comment at lines 40-42: the wire models' wrap serializer) | suppress, written reason |
| 3-6 | fec7a001, 2496262b, 7d97a0b5, b3577396 | python:S5863 | MAJOR | `packages/shared_kernel/tests/test_entity.py:23, 24, 29, 92` | same actual and expected expression | FP | 23: `Thing(identity) == Thing(identity)` builds two instances: the test IS `__eq__`; 24: same for `hash()`; 29: `Thing(UniqueId.new()) != Thing(UniqueId.new())` two different random ids; 92: `Counter(identity) == Counter(identity)` | suppress, written reason (equality-contract tests) |
| 7 | 15b452c0 | python:S5863 | MAJOR | `packages/shared_kernel/tests/test_gln.py:144` | same | FP | `GLN("4006381333931") == GLN("4006381333931")`: R4 value-object equality; the next line asserts `!=` on a different GLN | suppress (same entry) |
| 8 | 86f1caec | python:S5863 | MAJOR | `packages/shared_kernel/tests/test_money.py:255` | same | FP | `Money(100, "EUR") == Money(100, "EUR")` directly beside the `!=` GBP and the `not (==)` case (253-254): value equality | suppress (same entry) |
| 9-10 | 9f50509b, 89f4a0a8 | python:S5863 | MAJOR | `packages/shared_kernel/tests/test_quantity.py:96, 98` | same | FP | `Quantity(3) == Quantity(3)` and `hash(Quantity(3)) == hash(Quantity(3))`: the test is named "compares by value" and "hash" | suppress (same entry) |
| 11 | b4def94f | python:S5863 | MAJOR | `services/billing/tests/unit/test_credit_decision_port.py:60` | same | FP | `Approve() == Approve()`: two instances of a frozen dataclass, equality of the `Approve` decision | suppress (same entry) |
| 12 | 12f67997 | python:S5863 | MAJOR | `services/seed/tests/unit/test_deterministic_parity.py:59` | same | FP | `deterministic_id("order:42") == deterministic_id("order:42")`: the determinism claim is two calls of the same function; line 60 proves distinct inputs differ | suppress (same entry) |
| 13 | 82523e8e | typescript:S2871 | CRITICAL | `apps/web/src/app/pages/(app)/orders/place.page.ts:253` | Provide a compare function ... localeCompare | FP | sorts ISO 4217 currency codes (three uppercase ASCII letters, `code.length > 0` filter); UTF-16 code-unit order equals alphabetical order for them, and it is locale-independent, which is wanted for a code list | accept with evidence (or suppress) |
| 14 | f12d259f | typescript:S2871 | CRITICAL | `apps/web/src/app/testing/number-boxes.ts:15` | same | FP | test-id strings sorted so two lists compare equal (`error-text.sweep.spec.ts:858` uses the list in `includes`); any deterministic order serves | suppress (test sweep helpers) |
| 15-20 | c10548c4, 5ab18ed5, 8eef0714, 7beb9846, 1c3c5504, 8c9c7b57 | typescript:S2871 | CRITICAL | `apps/web/src/app/testing/page-sweep.ts:78, 303, 388, 389, 390, 395` | same | FP | `out.sort()`, `[...out].sort()`, `[...seen.load].sort()` etc.: string sets sorted for deterministic comparison against `toEqual` expectations; locale ordering is not a requirement | suppress (test sweep helpers) |
| 21 | 4c364ad0 | typescript:S2871 | CRITICAL | `apps/web/src/app/testing/page-sweep.ts:150` | Provide a compare function to avoid sorting elements alphabetically | TP (latent, harmless today) | `failing` is `number[]` of HTTP statuses (`status >= 400`); `.sort()` is lexicographic. All values are three-digit (4xx, 5xx), for which lexicographic equals numeric order, so nothing goes wrong now; a 4-digit or 2-digit status would sort wrongly | fix in this phase: `.sort((a, b) => a - b)` (one token, test-only file) |
| 22-23 | 8db6a3fd, 822cc527 | typescript:S2871 | CRITICAL | `apps/web/src/server/testing/harness.ts:65, 69` | same | FP | `routeFilesOnDisk()` / `middlewareOnDisk()` return directory listings sorted for `toEqual(EXPECTED_MIDDLEWARE)` (`routes.sweep.spec.ts:105`); a fixed order against a fixed list | suppress (test harness) |
| 24 | d671d877 | typescript:S2068 | MAJOR (VULNERABILITY) | `apps/web/src/server/testing/bff-contract.ts:306` | Review this potentially hard-coded password | FP | a request body `username=attacker&password=attackers-own` inside a CSRF-refusal test (the BFF must answer 403 before reading it); a literal fixture of an attacker, in a `testing/` file, no credential of any system | suppress, written reason |
| 25 | e572ebde | typescript:S5332 | MINOR (VULNERABILITY) | `apps/web/src/server/testing/fake-gateway.ts:46` | Using http protocol is insecure | FP | `new URL(recorded.url, 'http://x')` uses `http://x` only as the base so a relative request URL can be parsed for `.pathname`; no connection is made | suppress, written reason |

Grouped by rule (25 = 23 bugs + 2 vulnerabilities):

| Rule | Count | True / False positive | Proposed disposition |
|---|---|---|---|
| python:S5863 | 10 | 0 / 10 | one multicriteria suppression for equality-contract tests |
| typescript:S2871 | 11 | 1 / 10 (page-sweep.ts:150 is TP, latent) | fix the one; the other ten accepted or suppressed with a reason (production site `place.page.ts:253` is ASCII codes) |
| python:S3862 | 1 | 0 / 1 | suppress file-scoped (`fact_handler.py`) |
| python:S930 | 1 | 0 / 1 | suppress file-scoped (`openapi_shape.py`) |
| typescript:S2068 | 1 | 0 / 1 | suppress, test fixture |
| typescript:S5332 | 1 | 0 / 1 | suppress, URL base only |
| **Total** | **25** | **1 TP / 24 FP** | |

None of the 25 is a production defect today. Nothing was fixed or suppressed (the TP fix is code, outside this round's bounds).

Code smells, count per rule (500 total, 42 rules, no triage; `.arm/phase21/smells.out`): python:S5778 293; python:S8714 54; python:S7503 23; python:S1192 20; python:S1172 9; python:S3415 9; typescript:S9027 8; typescript:S1186 7; python:S1110 6; python:S3776 5; python:S8572 5; typescript:S878 4; typescript:S8786 4; python:S5864 4; python:S3516 4; typescript:S7780 3; typescript:S3776 3; python:S5806 3; typescript:S3358 3; typescript:S5906 3; typescript:S6582 3; typescript:S7763 3; typescript:S4624 2; python:S108 2; typescript:S4782 2; typescript:S2004 2; and one each of typescript:S7722, S6557, S4123, S6644, S7761, S7750, S7765, S7781, S2925, S7649, python:S1700, S107, S6353, S7632, S7504, S5727.

### 4. Web coverage: #8's choice, applied as is

`sonar-project.properties` and the README now say "as in #8" with the citation `../order-to-cash-dotnet/sonar-scan.properties:48-65` (the documented gap) and `:105-109` (its `sonar.coverage.exclusions` has only the generated and `ui/**` entries, no `apps/web` exclusion). No dependency, no `sonar.coverage.exclusions` for `apps/web`: it stays at 0.0% in the server.

### End state

`otcpy-sonarqube` stopped; `docker ps` lists only `kb-poc-*`. `scan_arm_d` project deleted from the server. Tmpfs data is gone again (open point 3 of round 1, disposed).

## Round 3 (maintainer's disposition "fix 1, suppress 24")

### 1. Fix: `apps/web/src/app/testing/page-sweep.ts:150`

Backup `.arm/phase21/page-sweep.ts.bak` (sha256 before `c503627c3dca62a655b187e6bd29856def5f04fe9af86564679601756c880af9`). Line 150 is now `...).sort((a, b) => a - b);` (`git diff --stat`: 1 insertion, 1 deletion). Importers of `page-sweep.ts` (grep over `apps/web/src`, `e2e`, `scripts`):
`testing/page-test.ts`, `stack-label.spec.ts`, `login.spec.ts`, `billing.spec.ts`, `orders-list.spec.ts`, `order-detail.spec.ts`, `stock.spec.ts`, `session.spec.ts`, `place-order.spec.ts`, `error-text.sweep.spec.ts`, `billing-order-link.spec.ts` (and a comment in `orders-fixtures.ts`).
Run as `quality.sh` section 7 runs it (`npx --yes pnpm@12.8.1 -C apps/web`, `.arm/phase21/web_r3.log`): `install --frozen-lockfile` ok; `run --if-present lint` exit 0 (the template ships no lint script, so it is skipped); `types:check` exit 0 ("types:check OK"); `test:ci` (the whole suite, a superset of the importing specs): **Test Files 35 passed (35), Tests 687 passed (687)**, exit 0. I did not run the `build` step (not asked).

### 2. Suppressions: 14 entries for 24 issues

Pairs counted from `issues.tsv` (rule, file): S3862 x1 file (1 issue), S930 x1 (1), S5863 x6 files (10), S2871 x4 files (10, after the fix; page-sweep.ts has 6 left), S2068 x1 (1), S5332 x1 (1) = **14 (rule, file) pairs = 24 issues**. `sonar-project.properties` has `sonar.issue.ignore.multicriteria=e1..e14`, each `eN.ruleKey` + `eN.resourceKey` with the exact file path (no glob, no global rule off), with the reason (from the triage rows, with the code evidence) above each rule's group. The page-sweep note says the S2871 entry would also hide a regression of line 150 and that this was accepted. Re-parsed as Java properties: 11 non-entry keys (the 10 of round 2 plus `sonar.issue.ignore.multicriteria` with 14 ids), 28 `eN.*` keys, ids 14, orphans none, missing none, every id has a ruleKey and a resourceKey, no `resourceKey` contains `*`, no stray key, no key not starting with `sonar.`. The `(app)` parentheses in `place.page.ts`'s path worked (the rescan shows it suppressed).

### 3. Rescan (fresh instance: container recreated, tmpfs wiped, new admin password and token; override uncommitted)

```
Excluded sources: packages/contracts/src/otc_contracts/generated/**, apps/web/src/generated/**, **/node_modules/**, **/dist/**, .arm/**, **/.angular/**, **/.nitro/**, **/.output/**, **/test-results/**, **/playwright-report/**, **/*.d.ts, tests/**, **/tests/**, apps/web/src/**/*.spec.ts, apps/web/e2e/**/*.ts
14:32:04.806 INFO  ANALYSIS SUCCESSFUL, you can find the results at: http://otcpy-sonarqube:9000/dashboard?id=order-to-cash-python
```
Server (`.arm/phase21/report4.out`): `/api/issues/search?types=BUG,VULNERABILITY&resolved=false` **total 0**; `bugs 0`, `vulnerabilities 0`; **code smells 500** (unchanged: the suppressions swallowed only their 24); source files `ts 96, py 487, css 1`; test files `ts 38, py 480`; `coverage 86.7` (unchanged, `apps/web` still the documented 0.0%); quality gate `OK` (first analysis, no conditions yet).

Arming (backup `.arm/phase21/sonar-project.properties.bak`, sha256 `cda83152c8ac01fb68b1c2f6e12892daa6998e27041f676baadade484fa1ef0c`): removed `e1` (S3862 `fact_handler.py`) and `e11` (S2871 `page-sweep.ts`) from the id list, rescanned (`scan5_arm.log`, same instance, second analysis): **7 open BUG issues**, exactly the expected ones: `page-sweep.ts:78, 303, 388, 389, 390, 395` (6, S2871) and `fact_handler.py:150` (1, S3862); the page-sweep list has NO line 150, which also proves the fix (the line is no longer flagged). Quality gate `ERROR` (`new_violations` 7 > 0). Restore with `cp`, `cmp` identical, same sha256; rescan (`scan6.log`): total 0 open bugs and vulnerabilities, 500 smells, gate `OK` with `new_violations` 0.

### 4. README

One bullet added to the SonarQube section (24 false positives suppressed rule-by-file with reasons, 1 latent bug fixed, 0 open bugs and vulnerabilities on the last scan).

### End state

`otcpy-sonarqube` stopped; `docker ps` lists only `kb-poc-*`.
