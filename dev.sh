#!/usr/bin/env bash
# dev.sh — start the Assurance Scan stack as containers (server + UI in one image).
#
# Usage:
#   ./dev.sh               start the server container (builds the image first time)
#   ./dev.sh --build       force an image rebuild (needed after code changes)
#   ./dev.sh --prefetch    refresh scanner vulnerability DBs after start (first run only)
#
# UI is served by the container itself (bundled SvelteKit build), no Vite needed.
# All containers — server and scanner siblings — carry the compose labels that
# make Docker Desktop group them under "assurance-scan".
set -euo pipefail

cd "$(dirname "$0")"

IMAGE="${ASSURANCE_SCAN_IMAGE:-assurance-scan:dev}"
CONTAINER=assurance-scan-server
PORT="${ASSURANCE_SCAN_UI_PORT:-8742}"
BUILD=0
PREFETCH=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --prefetch) PREFETCH=1 ;;
    *) echo "Unknown flag: $arg (supported: --build, --prefetch)" >&2; exit 2 ;;
  esac
done

docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not running — start Docker Desktop first." >&2; exit 1; }

# Load local env (GITHUB_POLL_TOKEN etc.) if present.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

if (( BUILD )) || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building ${IMAGE} (frontend + server are baked in)…"
  docker build -t "$IMAGE" .
fi

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "Starting ${CONTAINER} from ${IMAGE}…"
docker run -d --name "$CONTAINER" \
  -p "127.0.0.1:${PORT}:8000" \
  -e GITHUB_POLL_TOKEN="${GITHUB_POLL_TOKEN:-}" \
  -e GITHUB_ORG="${GITHUB_ORG:-26457513}" \
  -e POLL_REPOS="${POLL_REPOS:-}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$HOME/Development:$HOME/Development" \
  -v "$HOME/.assurance-scan:/data" \
  -w "$PWD" \
  --label com.docker.compose.project=assurance-scan \
  --label com.docker.compose.service=server \
  "$IMAGE" serve

printf "Waiting for health"
ok=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then ok=1; break; fi
  printf "."; sleep 1
done
if (( ! ok )); then
  echo " FAILED — last logs:"
  docker logs --tail 30 "$CONTAINER"
  exit 1
fi
echo " ok"

if (( PREFETCH )); then
  docker exec "$CONTAINER" assurance-scan prefetch
fi

echo "UI:      http://localhost:${PORT}"
echo "Stop:    docker rm -f ${CONTAINER}"
echo "Logs:    docker logs -f ${CONTAINER}"
