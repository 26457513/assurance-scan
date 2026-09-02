#!/usr/bin/env bash
# dev.sh — start the Assurance Scan stack as containers (server + UI in one image).
#
# Usage:
#   ./dev.sh               start the existing local image
#   ./dev.sh --build       rebuild and start the local image
#
# UI is served by the container itself (bundled SvelteKit build), no Vite needed.
# Local project scans run through the separate CLI container; the web server
# does not receive the Docker socket or a host source mount.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${ASSURANCE_SCAN_UI_PORT:-8742}"
BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    *) echo "Unknown flag: $arg (supported: --build)" >&2; exit 2 ;;
  esac
done

docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not running — start Docker Desktop first." >&2; exit 1; }

test -f .env || { echo "ERROR: copy .env.example to .env and configure the development GitHub App." >&2; exit 1; }
install -d -m 700 .secrets

if (( BUILD )); then
  docker compose up -d --build server
else
  docker compose up -d server
fi

printf "Waiting for health"
ok=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then ok=1; break; fi
  printf "."; sleep 1
done
if (( ! ok )); then
  echo " FAILED — last logs:"
    docker compose logs --tail 30 server
  exit 1
fi
echo " ok"

echo "UI:      http://localhost:${PORT}"
echo "Stop:    docker compose down"
echo "Logs:    docker compose logs -f server"
