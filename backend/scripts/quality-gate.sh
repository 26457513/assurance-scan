#!/usr/bin/env bash
# Deterministic local/CI quality gate for Assurance Scan.
#
# Usage:
#   python3 -m venv .venv
#   .venv/bin/pip install -r backend/requirements/dev.txt
#   QUALITY_GATE_PYTHON=.venv/bin/python backend/scripts/quality-gate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPOSITORY_ROOT="$(cd "$BACKEND_ROOT/.." && pwd)"
PYTHON_COMMAND="${QUALITY_GATE_PYTHON:-python3}"
PYTHON_BIN="$($PYTHON_COMMAND -c 'import sys; print(sys.executable)')"
SEMGREP_IMAGE="semgrep/semgrep:1.136.0@sha256:cda1b566fafbf6010a02a3ea1d265b1c8eba4380e489a13891a102243d81ca6f"
APP_IMAGE="assurance-scan-quality-gate-app:local"
CI_IMAGE="assurance-scan-quality-gate-ci:local"
CLI_IMAGE="assurance-scan-quality-gate-cli:local"

cd "$REPOSITORY_ROOT"

run_step() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  "$@"
}

run_step "Ruff" "$PYTHON_BIN" -m ruff check --config backend/pyproject.toml backend
run_step "Mypy" bash -c 'cd "$1" && "$2" -m mypy --config-file pyproject.toml' _ "$BACKEND_ROOT" "$PYTHON_BIN"
run_step "Backend tests" "$PYTHON_BIN" -m pytest -q -c backend/pyproject.toml backend/tests
run_step "Schema fixtures" "$PYTHON_BIN" backend/scripts/validate-target-schema-fixtures.py
run_step "Python compilation" "$PYTHON_BIN" -m compileall -q backend/app backend/scripts backend/tests

printf '\n==> Shell syntax\n'
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find backend -type f -name '*.sh' -not -path '*/__pycache__/*' -print0)

run_step "Semgrep" docker run --rm \
  --volume "$REPOSITORY_ROOT:/src:ro" \
  --workdir /src \
  "$SEMGREP_IMAGE" \
  semgrep scan \
  --config backend/semgrep.yml \
  --error \
  --strict \
  --metrics off \
  --disable-version-check \
  --no-git-ignore \
  --exclude .venv \
  --exclude node_modules \
  --exclude .svelte-kit \
  --exclude __pycache__ \
  backend/app backend/scripts frontend/src .github/workflows backend/resources/templates \
  Dockerfile backend/Dockerfile.ci backend/Dockerfile.cli

printf '\n==> Frontend dependencies\n'
(cd frontend && npm ci --ignore-scripts)
run_step "Frontend dependency audit" npm --prefix frontend audit --audit-level=low
run_step "Frontend check" npm --prefix frontend run check
run_step "Frontend tests" npm --prefix frontend test --if-present
run_step "Frontend build" npm --prefix frontend run build

run_step "Application Dockerfile validation" docker build --check -f Dockerfile .
run_step "CI Dockerfile validation" docker build --check -f backend/Dockerfile.ci .
run_step "CLI Dockerfile validation" docker build --check -f backend/Dockerfile.cli .
run_step "Application Compose validation" docker compose -f compose.yaml config --quiet
run_step "Scanner Compose validation" env \
  SCAN_SOURCE_DIR="$REPOSITORY_ROOT" \
  RUN_ID=quality-gate \
  docker compose -f docker-compose.security.yml config --quiet
run_step "Application image build" docker build --tag "$APP_IMAGE" -f Dockerfile .
run_step "Application entrypoint smoke" docker run --rm "$APP_IMAGE" help
run_step "Application import smoke" docker run --rm --entrypoint python "$APP_IMAGE" -c \
  'import app.main; assert app.main.app is not None'
run_step "CI image build" docker build --tag "$CI_IMAGE" -f backend/Dockerfile.ci .
run_step "CI entrypoint smoke" docker run --rm "$CI_IMAGE" --help
run_step "CLI image build" docker build \
  --build-arg VERSION=0.1.0 \
  --build-arg REVISION=0000000000000000000000000000000000000000 \
  --tag "$CLI_IMAGE" \
  -f backend/Dockerfile.cli .
run_step "CLI entrypoint smoke" docker run --rm "$CLI_IMAGE" --version

run_step "Tracked diff whitespace" git diff --check
run_step "Repository source hygiene" "$PYTHON_BIN" backend/scripts/check-source-hygiene.py

printf '\nQuality gate passed.\n'
