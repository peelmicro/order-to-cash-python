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
# `pnpm n8n:import` / scripts/import-n8n-workflows.sh path has no such gate;
# a human running it explicitly always means it).
#
# Every workflow always lands INACTIVE regardless of this flag or of the
# committed JSON's own `active` field — n8n's own `import:workflow` default
# behaviour (see scripts/import-n8n-workflows.sh's header for why: n8n 2.x
# only takes a newly-published/active workflow's activation live after the
# NEXT full server restart, which an init container importing into an
# ALREADY-RUNNING n8n cannot itself trigger cleanly — see
# progress/impl_n8n_workflows.md). A human activates the workflow(s) they
# want running from http://localhost:5678/workflows; that activation is a
# live REST-API call against the running server and takes effect
# immediately, no restart needed, and persists across restarts thereafter.

set -e

if [ "${N8N_WORKFLOWS_ENABLED:-true}" = "false" ]; then
  echo "n8n-init: N8N_WORKFLOWS_ENABLED=false — skipping import, nothing changed."
  exit 0
fi

echo "n8n-init: importing n8n/workflows/*.json (mounted at /home/node/workflows)..."
n8n import:workflow --separate --input=/home/node/workflows
echo "n8n-init: done. Workflows are imported INACTIVE — activate from the n8n UI to run them."
