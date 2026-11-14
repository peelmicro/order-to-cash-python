#!/bin/sh
# One-shot: imports the four committed n8n demo workflows on every
# `docker compose up` — the `n8n-init` service in docker-compose.infra.yml,
# same "one-shot, restart: no, depends_on: service_healthy" shape as
# kafka-init (infra/kafka/create-topics.sh) and idempotent for the same
# reason: re-importing a workflow with the same `id` overwrites it in place,
# so running this again on every `up` re-asserts the four committed
# workflows match n8n/workflows/*.json exactly — it never creates a
# duplicate.
#
# Gated by N8N_WORKFLOWS_ENABLED, per specs/shared/n8n-workflows.md §7.1
# ("All workflows off ... nothing is imported or activated") — this is the
# ONE place that rule is enforced for the auto-import path (the manual
# scripts/import-n8n-workflows.sh path has no such gate;
# a human running it explicitly always means it).
#
# A workflow that is NEW to the instance lands INACTIVE, whatever the committed
# JSON's own `active` field says: that is `n8n import:workflow`'s own behaviour
# (see scripts/import-n8n-workflows.sh's header for why n8n 2.x only takes a
# newly-published workflow live after the NEXT server restart, which an init
# container importing into an ALREADY-RUNNING n8n cannot itself trigger; phase 20
# measured it less strictly: a webhook workflow answered at once in 2 of 3 trials).
#
# A workflow that was ALREADY ACTIVE is kept active. Measured in phase 20, not
# inherited: `import:workflow` DEACTIVATES any workflow it overwrites ("Deactivating
# workflow ..."), so the claim this header used to make, that a human activation
# "persists across restarts", was false for every `docker compose up` that re-ran
# this job. So the script now records which workflows are active BEFORE the import
# and publishes exactly those again AFTER it. Content is still re-asserted from the
# committed JSON on every run (idempotent, no duplicate); only the activation flag
# is carried across. Because the n8n server is already running when this job runs,
# a re-published workflow takes effect in the server on its next start, and the
# one that the server already had live keeps running: this job never touches the
# running server's registered triggers.
#
# A human activates the workflow(s) they want from http://localhost:5678/workflows.

set -e

if [ "${N8N_WORKFLOWS_ENABLED:-true}" = "false" ]; then
  echo "n8n-init: N8N_WORKFLOWS_ENABLED=false — skipping import, nothing changed."
  exit 0
fi

# `|| true`: no active workflow, or a failed listing, must not block the import itself;
# the id filter keeps only lines that are workflow ids (the CLI also prints log lines).
ACTIVE_BEFORE="$(n8n list:workflow --active=true --onlyId 2>/dev/null | grep -E '^[A-Za-z0-9_-]+$' || true)"

echo "n8n-init: importing n8n/workflows/*.json (mounted at /home/node/workflows)..."
n8n import:workflow --separate --input=/home/node/workflows

for id in $ACTIVE_BEFORE; do
  echo "n8n-init: $id was active before the import — publishing it again."
  n8n publish:workflow --id="$id"
done
echo "n8n-init: done. New workflows are INACTIVE; those that were active stay active. Activate from the n8n UI to run them."
