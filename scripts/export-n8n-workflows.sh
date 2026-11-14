#!/bin/bash
# Exports the four committed n8n demo workflows back out of the running n8n
# container (`otcpy-n8n`) into n8n/workflows/ — the reverse of
# import-n8n-workflows.sh, so the committed JSON is what n8n itself produces
# after an edit in the UI, never hand-written.
#
# Exports by workflow ID (not `--all`) so a stray test/probe workflow someone
# left in the instance is never committed — see specs/shared/n8n-workflows.md
# for what each of the four IDs is.
#
# Exports the CURRENT (draft/editor) version of each workflow, i.e. what the n8n
# UI shows now. Pass --published for the published/live version instead (n8n's
# own `export:workflow --published` flag).
#
# n8n's raw `export:workflow` output wraps the workflow in a one-element array
# and embeds this instance's own identity and bookkeeping — `shared[].project`
# (the logged-in operator's real name and email), `versionId`/`activeVersionId`/
# `versionCounter`, `createdAt`/`updatedAt`, `triggerCount`, `isArchived`, empty
# `tags`/`pinData`/`staticData`/`meta`. None of that is portable and the project
# block is a real person's PII that must never land in a committed file. This
# script unwraps the array and keeps only the minimal portable shape (id, name,
# nodes, connections, active, settings): the shape the four files were authored
# in and that `import:workflow` accepts, so a diff shows only real changes.
#
# The files are shared byte-for-byte with #7 and #8: a round-trip with no edit in
# between must leave `git status --short n8n/` empty (phase 20 checked it).
#
# Usage:
#   ./scripts/export-n8n-workflows.sh [--published]

set -e

CONTAINER=otcpy-n8n
HOST_WORKFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/n8n/workflows"
CONTAINER_WORKFLOW_DIR=/home/node/workflows
PUBLISHED_FLAG=""
if [ "$1" = "--published" ]; then
  PUBLISHED_FLAG="--published"
fi

if ! docker ps --format '{{.Names}}' | grep -q "^$CONTAINER$"; then
  echo "Error: container $CONTAINER is not running. Start it with: docker compose -p otcpy -f docker-compose.infra.yml --profile n8n up -d n8n" >&2
  exit 1
fi

declare -A WORKFLOWS=(
  [otcOrderGenerator]="1-order-generator.json"
  [otcPaymentRobot]="2-payment-robot.json"
  [otcStockReplenishment]="3-stock-replenishment.json"
  [otcBurst]="4-burst.json"
)

echo "Exporting n8n workflows from container $CONTAINER..."
for id in "${!WORKFLOWS[@]}"; do
  file="${WORKFLOWS[$id]}"
  echo "  $id -> n8n/workflows/$file"
  docker exec "$CONTAINER" n8n export:workflow --id="$id" $PUBLISHED_FLAG --output="$CONTAINER_WORKFLOW_DIR/.export-$file"
  python3 - "$HOST_WORKFLOW_DIR/.export-$file" "$HOST_WORKFLOW_DIR/$file" << 'PYEOF'
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    data = json.load(f)
workflow = data[0] if isinstance(data, list) else data

portable = {
    "id": workflow["id"],
    "name": workflow["name"],
    "nodes": workflow["nodes"],
    "connections": workflow["connections"],
    "active": workflow["active"],
    "settings": workflow.get("settings", {"executionOrder": "v1"}),
}

with open(dst, "w") as f:
    json.dump(portable, f, indent=2)
    f.write("\n")
PYEOF
  rm -f "$HOST_WORKFLOW_DIR/.export-$file"
done

echo ""
echo "Done. n8n/workflows/*.json now reflects what n8n itself has for these four workflows"
echo "(stripped of this instance's own identity/bookkeeping fields — see this script's header)."
echo "Review the diff before committing — 'git diff n8n/workflows/'."
