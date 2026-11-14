#!/bin/bash
# Counted claim for feature 33 (n8n_workflows): the set of workflow ids in n8n's own PostgreSQL store
# (`n8n` database, table `workflow_entity`) is EXACTLY the four committed workflows, with no duplicate and no extra.
#
# The expected set is a literal below, never derived from the database it is checked against. It is also checked
# against n8n/workflows/*.json, so a renamed or added file fails here instead of drifting silently.
#
# Needs the `otcpy-postgres` container running (n8n itself need not be). Exit 0 = the set matches; 1 = it does not.
#
# Usage:
#   ./scripts/check-n8n-workflow-set.sh

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_CONTAINER=otcpy-postgres
DB_USER="${POSTGRES_N8N_USER:-otc_n8n}"
DB_NAME="${POSTGRES_DB_N8N:-n8n}"

EXPECTED="otcBurst
otcOrderGenerator
otcPaymentRobot
otcStockReplenishment"

files="$(python3 -I - "$ROOT/n8n/workflows" <<'PYEOF'
import json, pathlib, sys
for p in sorted(pathlib.Path(sys.argv[1]).glob("*.json")):
    print(json.loads(p.read_text())["id"])
PYEOF
)"
files="$(printf '%s\n' "$files" | sort)"

# `-t -A`: bare rows. Every row, not DISTINCT: a duplicate must show up as a duplicate.
actual="$(docker exec "$POSTGRES_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c 'select id from workflow_entity order by id')" \
  || { echo "FAIL: could not query $DB_NAME in $POSTGRES_CONTAINER (is it running?)" >&2; exit 1; }
actual="$(printf '%s\n' "$actual" | sort)"

status=0
if [ "$files" != "$EXPECTED" ]; then
  echo "FAIL: n8n/workflows/*.json ids differ from the expected set"
  echo "  expected: $(printf '%s' "$EXPECTED" | paste -sd' ' -)"
  echo "  files:    $(printf '%s' "$files" | paste -sd' ' -)"
  status=1
fi
if [ "$actual" != "$EXPECTED" ]; then
  echo "FAIL: workflow_entity ids differ from the expected set"
  echo "  expected ($(printf '%s\n' "$EXPECTED" | wc -l) rows): $(printf '%s' "$EXPECTED" | paste -sd' ' -)"
  echo "  actual   ($(printf '%s\n' "$actual" | grep -c .) rows): $(printf '%s' "$actual" | paste -sd' ' -)"
  status=1
fi
if [ "$status" -eq 0 ]; then
  echo "OK: workflow_entity holds exactly the 4 committed workflows: $(printf '%s' "$EXPECTED" | paste -sd' ' -)"
fi
exit "$status"
