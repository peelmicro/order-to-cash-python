#!/usr/bin/env bash
# quality.sh — the single quality gate, run from the repository root.
#
# Order: ruff format --check, ruff check, mypy, lint-imports, contracts drift check,
# pytest with coverage, then the web gates. `set -euo pipefail`: the first failing step stops
# the script with that step's own exit code (armed in progress/impl_monorepo_scaffold.md).
#
# Exit codes: 0 = every gate passed; non-zero = the exit code of the first failing step.

set -euo pipefail

cd "$(dirname "$0")"

section() { printf '\n── %s\n' "$1"; }

section "1. ruff format --check"
uv run ruff format --check

section "2. ruff check"
uv run ruff check

section "3. mypy --strict (packages, services, tests)"
uv run mypy

section "4. import-linter (forbidden, layers, independence contracts)"
uv run lint-imports

section "5. contracts drift check"
# SLOT: feature 8 (contracts_package) fills this with `uv run python scripts/generate_contracts.py --check`.
# Nothing generates contracts yet, so there is nothing to drift; do NOT replace this with a no-op that
# prints "ok".
echo "SLOT (not implemented): contracts drift check is owned by feature 8 (contracts_package)"

section "6. pytest + coverage (overall gate: fail_under in pyproject.toml, >= 60%)"
uv run pytest --cov --cov-report=term-missing:skip-covered

section "6b. domain coverage (>= 80%)"
# TODO(feature 7, shared_kernel): the >= 80% domain gate is NOT enforced yet. Every domain file is a
# placeholder with zero statements, and `coverage report --fail-under=80` over zero statements
# passes vacuously at 100% (measured). A gate that cannot fail is not a gate; feature 7 adds the
# first real domain code and must wire `coverage report --include=<domain paths> --fail-under=80`
# here and arm it. Until then this prints the number and does not gate.
uv run coverage report --include='*/domain/*,packages/shared_kernel/*' --skip-covered | tail -n 3 || true

section "7. web (apps/web): install, lint, test, build"
# The pnpm version has ONE source: apps/web/package.json `packageManager`. It is run through npx
# because the machine's global pnpm is the corepack-managed 11.22.0, which refuses this project
# (and corepack resolves the pin from the cwd, not from `-C`).
PNPM_VERSION="$(node -p "require('./apps/web/package.json').packageManager.split('@')[1]")"
pnpm_web() { npx --yes "pnpm@${PNPM_VERSION}" -C apps/web "$@"; }
pnpm_web install --frozen-lockfile
# The Analog template ships no lint script, so --if-present skips it; a lint script added later runs here.
pnpm_web run --if-present lint
pnpm_web run test:ci
pnpm_web run build

printf '\nquality.sh: all gates passed\n'
