#!/usr/bin/env bash
# Optional SonarQube scan (phase 21). NOT part of quality.sh; needs the "sonar" compose profile running:
#   docker compose -f docker-compose.infra.yml --profile sonar up -d sonarqube
#   export SONAR_TOKEN=<a SonarQube user token>
#   ./scripts/sonar-scan.sh
#
# Coverage is NOT re-run here (the full suite takes ~25 minutes): the script converts the .coverage file
# that the last `uv run pytest --cov` (quality.sh section 6) wrote. Run that first; a stale file is the
# person running the scan's responsibility, the scanner cannot tell.
#
# The scanner is the plain sonar-scanner CLI in a throwaway container, so no new runtime lands on the host
# (the same choice as #7's `sonar:scan`). The tag is pinned: 12.1.0.3233_8.0.1 is the image whose digest
# (sha256:23ca0f13...) was the cached `latest` when this was written; `latest` is never used.
#   SONAR_SCANNER_IMAGE   override the image
#   SONAR_HOST_URL        default http://otcpy-sonarqube:9000 (resolved on the otcpy-net network)
#   SONAR_NETWORK         default otcpy-net
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${SONAR_TOKEN:-}" ]; then
    echo "SONAR_TOKEN is not set. Export a SonarQube user token first (README.md \"SonarQube\")." >&2
    exit 1
fi
if [ ! -f .coverage ]; then
    echo ".coverage not found: run \`uv run pytest --cov\` (quality.sh section 6) first." >&2
    exit 1
fi

uv run coverage xml -o coverage.xml

# The repository is mounted at its own absolute path so the absolute <source> entries of coverage.xml
# resolve inside the container; the container runs as the host user so .scannerwork is not root-owned.
docker run --rm \
    --user "$(id -u):$(id -g)" \
    --network "${SONAR_NETWORK:-otcpy-net}" \
    -v "$PWD:$PWD" -w "$PWD" \
    -e SONAR_TOKEN \
    "${SONAR_SCANNER_IMAGE:-sonarsource/sonar-scanner-cli:12.1.0.3233_8.0.1}" \
    -Dsonar.host.url="${SONAR_HOST_URL:-http://otcpy-sonarqube:9000}"
