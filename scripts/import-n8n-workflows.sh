#!/bin/bash
# Imports the four committed n8n demo workflows (n8n/workflows/*.json) into the
# running n8n container (`otcpy-n8n`, compose project `otcpy`) — see
# specs/shared/n8n-workflows.md.
#
# This is the manual, run-it-whenever-you-like path. The automatic one runs on
# every `docker compose up`: the `n8n-init` one-shot service in
# docker-compose.infra.yml and infra/n8n/import-workflows-on-startup.sh. Both
# call the same `n8n import:workflow --separate --input=...` against the same
# mounted directory, so they cannot drift on WHAT they import; this one runs
# `docker exec` in the already-running container, the other is its own
# ephemeral container sharing the `n8n_data` volume and the PostgreSQL `n8n`
# database.
#
# Re-importing overwrites a workflow with the same `id` in place (never a
# duplicate) and DEACTIVATES it: `import:workflow` always lands a workflow
# inactive (measured in phase 20, "Deactivating workflow ..."). Unlike the
# automatic path, which re-publishes whatever was active before, this manual
# path leaves them inactive; activate the ones you want from the n8n UI
# (http://localhost:5678/workflows). Publishing from the n8n CLI (`n8n
# publish:workflow`) is documented by the CLI as needing a restart; phase 20
# measured a webhook answering at once in 2 of 3 trials and 404 until restart in
# the third, so restart n8n if a newly published workflow does not fire.
#
# This manual path has no N8N_WORKFLOWS_ENABLED gate, unlike the automatic one:
# a human running it explicitly always means it.
#
# Usage:
#   ./scripts/import-n8n-workflows.sh

set -e

CONTAINER=otcpy-n8n
WORKFLOW_DIR=/home/node/workflows

echo "Importing n8n workflows from $WORKFLOW_DIR into container $CONTAINER..."

if ! docker ps --format '{{.Names}}' | grep -q "^$CONTAINER$"; then
  echo "Error: container $CONTAINER is not running. Start it with:" >&2
  echo "  docker compose -p otcpy -f docker-compose.infra.yml --profile n8n up -d n8n" >&2
  echo "  (or scripts/dev-stack.sh up --with-n8n)" >&2
  exit 1
fi

docker exec "$CONTAINER" n8n import:workflow --separate --input="$WORKFLOW_DIR"

echo ""
echo "Done. Open http://localhost:5678/workflows to see the imported workflows."
echo "They are imported INACTIVE by design — activate the ones you want running from the UI."
