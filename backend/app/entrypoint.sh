#!/usr/bin/env bash
# Container entrypoint. Routes subcommands to the right action.
#
#   serve        (default) run DB migrations then start uvicorn
#   mcp-config   print MCP client config snippet (Phase 1)
#   export       write findings.json to a path (Phase 1)
#   help         show usage
#
# All commands run inside the Python venv at /opt/venv.

set -euo pipefail

VENV=/opt/venv
APP_DIR=/opt/assurance-scan
ALEMBIC="${VENV}/bin/alembic"
UVICORN="${VENV}/bin/uvicorn"

# Capture the project root from `docker run -w "$PWD"` BEFORE we cd into
# APP_DIR. The server reads ASSURANCE_SCAN_PROJECT_ROOT to know where the
# user's project lives (for catalogue resolution, scanner bind-mounts).
# We cd into APP_DIR so Python imports `app.main` from the image copy
# (which has the built frontend in app/static), not from the host's
# bind-mounted source tree (which doesn't).
export ASSURANCE_SCAN_PROJECT_ROOT="${ASSURANCE_SCAN_PROJECT_ROOT:-$(pwd)}"

cd "${APP_DIR}"

case "${1:-serve}" in
  serve)
    echo "[entrypoint] project root: ${ASSURANCE_SCAN_PROJECT_ROOT}"
    echo "[entrypoint] app dir: $(pwd)"
    echo "[entrypoint] running migrations"
    "${ALEMBIC}" -c "${APP_DIR}/alembic.ini" upgrade head
    echo "[entrypoint] starting uvicorn"
    shift || true
    exec "${UVICORN}" app.main:app \
      --host "${ASSURANCE_SCAN_HOST:-127.0.0.1}" \
      --port "${ASSURANCE_SCAN_PORT:-8000}" \
      "$@"
    ;;

  mcp-config)
    cat <<CONFIG
{
  "mcpServers": {
    "assurance-scan": {
      "transport": {
        "type": "streamable_http",
        "url": "http://127.0.0.1:${ASSURANCE_SCAN_PORT:-8000}/mcp"
      }
    }
  }
}
CONFIG
    ;;

  prefetch)
    shift || true
    # Optional --only trivy,grype,osv,clamav
    only_flag=""
    if [ "${1:-}" = "--only" ]; then
      shift
      only_flag="$1"
      shift
    fi
    exec "${VENV}/bin/python" -c "
import asyncio, sys
sys.path.insert(0, '${APP_DIR}')
from app.prefetch import prefetch, available_scanners

names = '${only_flag}'.split(',') if '${only_flag}' else available_scanners()
result = asyncio.run(prefetch(names, project_path='${PWD}'))
for name, status in result.items():
    print(f'{name}: {status}')
"
    ;;

  export)
    echo "Export (Phase 1 — not yet implemented)" >&2
    exit 1
    ;;

  help|--help|-h)
    cat <<USAGE
Assurance Scan

Usage:
  assurance-scan serve              Start the server (default)
  assurance-scan mcp-config         Print MCP client config snippet
  assurance-scan export <path>      Write findings to a path
  assurance-scan help               Show this message

Server configuration via environment:
  ASSURANCE_SCAN_HOST                Bind host (default 127.0.0.1)
  ASSURANCE_SCAN_PORT                Bind port (default 8000)
  ASSURANCE_SCAN_DB_PATH             SQLite path (default /data/db.sqlite)
  ASSURANCE_SCAN_PARALLELISM         Max concurrent scanners (default 4)
  ASSURANCE_SCAN_LOG_LEVEL           Logging level (default INFO)
USAGE
    ;;

  *)
    echo "Unknown subcommand: ${1}" >&2
    echo "Run 'assurance-scan help' for usage." >&2
    exit 2
    ;;
esac
