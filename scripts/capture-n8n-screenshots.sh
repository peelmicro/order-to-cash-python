#!/bin/bash
# Regenerates the README's n8n images (docs/screenshots/n8n-*.png) from a THROWAWAY n8n: SQLite, no volume of ours, not on
# otcpy-net, the committed n8n/workflows mounted read-only. It never touches the real otcpy-n8n or its owner, needs no
# credentials from you, and puts no real person's identity in an image: the owner is the fictional Demo Owner / demo@example.com
# with a password generated for this run and kept in memory only.
#
# Needs Docker and Chromium for Playwright (npx --yes pnpm@12.8.1 -C apps/web exec playwright install chromium).
# N8N_CAPTURE_PORT (default 5679) is the host port, bound to 127.0.0.1. The container and its anonymous volume are removed on every exit.
#
# Usage:
#   ./scripts/capture-n8n-screenshots.sh

set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=otcpy-n8n-capture
PORT="${N8N_CAPTURE_PORT:-5679}"
IMAGE=n8nio/n8n:2.36.2
export N8N_URL="http://127.0.0.1:${PORT}"
export DEMO_EMAIL=demo@example.com
DEMO_PASSWORD="Aa1-$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)"
export DEMO_PASSWORD
export OUT_DIR="$ROOT/docs/screenshots"

if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "Error: port $PORT is in use; set N8N_CAPTURE_PORT to a free port." >&2
  exit 1
fi

cleanup() { docker rm -f -v "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:5678" \
  -e N8N_DIAGNOSTICS_ENABLED=false -e N8N_PERSONALIZATION_ENABLED=false -e N8N_VERSION_NOTIFICATIONS_ENABLED=false \
  -e N8N_TEMPLATES_ENABLED=false -e N8N_HIRING_BANNER_ENABLED=false -e N8N_ONBOARDING_FLOW_DISABLED=true \
  -e GENERIC_TIMEZONE=Europe/Madrid -e TZ=Europe/Madrid \
  -v "$ROOT/n8n/workflows:/home/node/workflows:ro" "$IMAGE" >/dev/null

echo "Waiting for n8n on $N8N_URL ..."
for _ in $(seq 1 90); do
  curl -fsS -o /dev/null "$N8N_URL/healthz/readiness" 2>/dev/null && break
  sleep 2
done
curl -fsS -o /dev/null "$N8N_URL/healthz/readiness" || { echo "Error: n8n did not become ready" >&2; exit 1; }

docker exec "$NAME" n8n import:workflow --separate --input=/home/node/workflows

curl -fsS -X POST "$N8N_URL/rest/owner/setup" -H 'content-type: application/json' \
  -d "{\"email\":\"$DEMO_EMAIL\",\"firstName\":\"Demo\",\"lastName\":\"Owner\",\"password\":\"$DEMO_PASSWORD\"}" >/dev/null

node "$ROOT/scripts/capture-n8n-screenshots.mjs"
ls -l "$OUT_DIR"/n8n-*.png
