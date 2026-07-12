#!/usr/bin/env bash
# preflight.sh — Phase 1 validation for the scanner run.
#
# Emits INFO/WARNING/ERROR lines to stderr and writes config-status.json.
# Exits non-zero on first ERROR. Warnings do not stop the run.

set -u

PREFLIGHT_ERRORS=0
PREFLIGHT_WARNINGS=0
PREFLIGHT_LOG="${PREFLIGHT_LOG:-preflight.log}"

# JSON accumulator
CONFIG_STATUS_JSON=""
add_check() {
  # args: name, status (INFO|WARNING|ERROR), message
  local name="$1" status="$2" message="$3"
  local escaped
  escaped=$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')
  if [ -z "$CONFIG_STATUS_JSON" ]; then
    CONFIG_STATUS_JSON=$(printf '{"name":"%s","status":"%s","message":"%s"}' \
      "$name" "$status" "$escaped")
  else
    CONFIG_STATUS_JSON=$(printf '%s, {"name":"%s","status":"%s","message":"%s"}' \
      "$CONFIG_STATUS_JSON" "$name" "$status" "$escaped")
  fi
}

log_info()    { printf 'INFO     %s\n' "$*" >&2; }
log_warning() { printf 'WARNING  %s\n' "$*" >&2; }
log_error()   { printf 'ERROR    %s\n' "$*" >&2; }

# --- Docker installed -------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  log_info "Docker installed"
  add_check "docker_installed" "INFO" "Docker is installed"
else
  log_error "Docker is not installed or not on PATH"
  add_check "docker_installed" "ERROR" "Docker not installed"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
fi

# --- Docker daemon running --------------------------------------------------
if docker info >/dev/null 2>&1; then
  log_info "Docker daemon running"
  add_check "docker_daemon" "INFO" "Docker daemon responding"
else
  log_error "Docker daemon not responding (is Docker Desktop running?)"
  add_check "docker_daemon" "ERROR" "Docker daemon not responding"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
fi

# --- Docker Compose ---------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
  log_info "Docker Compose (v2 plugin) available"
  add_check "docker_compose" "INFO" "Docker Compose v2 plugin available"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
  log_info "Docker Compose (legacy binary) available"
  add_check "docker_compose" "INFO" "Docker Compose legacy binary available"
else
  log_error "Docker Compose is not available"
  add_check "docker_compose" "ERROR" "Docker Compose not available"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
fi

# --- Internet connectivity --------------------------------------------------
# Docker registry returns 401 to unauthenticated /v2/ probes — that still
# proves reachability. Don't use curl -f here; any HTTP response means OK.
if command -v curl >/dev/null 2>&1; then
  http_code=$(curl -sS --max-time 5 -o /dev/null -w "%{http_code}" https://registry-1.docker.io/v2/ 2>/dev/null || echo "000")
  if [ "$http_code" != "000" ]; then
    log_info "Internet connectivity OK (registry returned HTTP $http_code)"
    add_check "internet" "INFO" "Registry reachable (HTTP $http_code)"
  else
    log_error "No internet connectivity to container registry (required to pull scanner images)"
    add_check "internet" "ERROR" "Cannot reach registry-1.docker.io"
    PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
  fi
else
  log_warning "curl not available — skipping internet connectivity check"
  add_check "internet" "WARNING" "curl not available, skipped"
  PREFLIGHT_WARNINGS=$((PREFLIGHT_WARNINGS + 1))
fi

# --- Target project exists --------------------------------------------------
if [ -z "${TARGET_DIR:-}" ]; then
  log_error "TARGET_DIR not set"
  add_check "target_dir" "ERROR" "TARGET_DIR not set"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
elif [ ! -d "$TARGET_DIR" ]; then
  log_error "Target folder does not exist: $TARGET_DIR"
  add_check "target_dir" "ERROR" "Does not exist: $TARGET_DIR"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
else
  log_info "Target folder OK: $TARGET_DIR"
  add_check "target_dir" "INFO" "Target folder exists"
fi

# --- Reports directory writable --------------------------------------------
if [ -z "${REPORT_DIR:-}" ]; then
  log_error "REPORT_DIR not set"
  add_check "report_dir" "ERROR" "REPORT_DIR not set"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
elif ! mkdir -p "$REPORT_DIR/reports" "$REPORT_DIR/sbom" "$REPORT_DIR/hashes" 2>/dev/null; then
  log_error "Cannot create report subdirectories under $REPORT_DIR"
  add_check "report_dir" "ERROR" "Cannot create $REPORT_DIR"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
elif ! touch "$REPORT_DIR/.write-test" 2>/dev/null; then
  log_error "Reports directory not writable: $REPORT_DIR"
  add_check "report_dir" "ERROR" "Not writable: $REPORT_DIR"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
else
  rm -f "$REPORT_DIR/.write-test"
  log_info "Reports directory writable: $REPORT_DIR"
  add_check "report_dir" "INFO" "Reports directory writable"
fi

# --- Disk space available (≥ 5 GB) -----------------------------------------
# Check the writable report volume rather than the scanner image filesystem.
# In Docker Desktop the image overlay can be small even when the mounted target
# volume has ample space for reports, SBOMs and scanner output.
DISK_CHECK_PATH="${REPORT_DIR:-${TARGET_DIR:-$SCRIPT_DIR}}"
DISK_FREE_KB=$(df -k "$DISK_CHECK_PATH" 2>/dev/null | awk 'NR==2 {print $4}')
DISK_FREE_GB=$((DISK_FREE_KB / 1024 / 1024))
if [ -z "$DISK_FREE_KB" ]; then
  log_warning "df unavailable — skipping disk space check"
  add_check "disk_space" "WARNING" "df unavailable"
  PREFLIGHT_WARNINGS=$((PREFLIGHT_WARNINGS + 1))
elif [ "$DISK_FREE_GB" -lt 5 ]; then
  log_error "Insufficient disk space at $DISK_CHECK_PATH: ${DISK_FREE_GB}GB free (need ≥5GB)"
  add_check "disk_space" "ERROR" "${DISK_FREE_GB}GB free at $DISK_CHECK_PATH, need ≥5GB"
  PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
else
  log_info "Disk space OK at $DISK_CHECK_PATH: ${DISK_FREE_GB}GB free"
  add_check "disk_space" "INFO" "${DISK_FREE_GB}GB free at $DISK_CHECK_PATH"
fi

# --- Optional --image ------------------------------------------------------
IMAGE_CHECKS=()
if [ -n "${ASVS_IMAGE_NAMES:-}" ]; then
  IFS=',' read -ra IMAGE_CHECKS <<< "$ASVS_IMAGE_NAMES"
elif [ -n "${IMAGE_NAME:-}" ]; then
  IMAGE_CHECKS=("$IMAGE_NAME")
fi

for image in "${IMAGE_CHECKS[@]}"; do
  [ -n "$image" ] || continue
  if docker image inspect "$image" >/dev/null 2>&1; then
    log_info "Image OK: $image"
    add_check "image" "INFO" "Image exists: $image"
  else
    log_error "Image not found locally: $image (build it first with 'docker build -t $image <path>')"
    add_check "image" "ERROR" "Image not found: $image"
    PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
  fi
done

# --- Optional --url --------------------------------------------------------
if [ -n "${TARGET_URL:-}" ]; then
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS -o /dev/null --max-time 10 "$TARGET_URL" 2>/dev/null; then
      log_info "Target URL reachable: $TARGET_URL"
      add_check "target_url" "INFO" "URL reachable"
    else
      log_warning "Target URL not reachable (scanner may still attempt to run): $TARGET_URL"
      add_check "target_url" "WARNING" "URL not reachable on host (ZAP will run inside container)"
      PREFLIGHT_WARNINGS=$((PREFLIGHT_WARNINGS + 1))
    fi
  fi
  case "$TARGET_URL" in
    https://*)
      log_info "HTTPS URL — testssl.sh will run"
      add_check "https" "INFO" "testssl.sh will run"
      ;;
    http://*)
      log_info "HTTP URL — testssl.sh will be SKIPPED (HTTPS only)"
      add_check "https" "INFO" "testssl.sh SKIPPED (HTTP)"
      ;;
  esac
fi

# --- Optional --uploads ----------------------------------------------------
if [ -n "${UPLOADS_DIR:-}" ]; then
  if [ ! -d "$UPLOADS_DIR" ]; then
    log_error "Uploads directory does not exist: $UPLOADS_DIR"
    add_check "uploads_dir" "ERROR" "Does not exist: $UPLOADS_DIR"
    PREFLIGHT_ERRORS=$((PREFLIGHT_ERRORS + 1))
  else
    log_info "Uploads dir OK: $UPLOADS_DIR"
    add_check "uploads_dir" "INFO" "Uploads dir exists"
  fi
fi

# --- Optional API keys -----------------------------------------------------
if [ -n "${NVD_API_KEY:-}" ]; then
  log_info "NVD_API_KEY set (not required; Dependency-Check is not used)"
  add_check "nvd_api_key" "INFO" "Set, not required"
else
  log_info "NVD_API_KEY not set (not required; Dependency-Check is not used)"
  add_check "nvd_api_key" "INFO" "Not set, not required"
fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
  log_info "GITHUB_TOKEN set"
  add_check "github_token" "INFO" "Set"
else
  log_info "GITHUB_TOKEN not set (optional)"
  add_check "github_token" "INFO" "Not set (optional)"
fi

if [ -n "${TRIVY_TOKEN:-}" ]; then
  log_info "TRIVY_TOKEN set"
  add_check "trivy_token" "INFO" "Set"
else
  log_info "TRIVY_TOKEN not set (optional)"
  add_check "trivy_token" "INFO" "Not set (optional)"
fi

if [ -n "${SEMGREP_APP_TOKEN:-}" ]; then
  log_info "SEMGREP_APP_TOKEN set"
  add_check "semgrep_app_token" "INFO" "Set"
else
  log_info "SEMGREP_APP_TOKEN not set (optional)"
  add_check "semgrep_app_token" "INFO" "Not set (optional)"
fi

if [ -n "${ZAP_API_KEY:-}" ]; then
  log_info "ZAP_API_KEY set"
  add_check "zap_api_key" "INFO" "Set"
else
  log_info "ZAP_API_KEY not set (optional, baseline scan does not require it)"
  add_check "zap_api_key" "INFO" "Not set (optional)"
fi

# --- Finalise --------------------------------------------------------------
CONFIG_STATUS_JSON="{\"errors\": $PREFLIGHT_ERRORS, \"warnings\": $PREFLIGHT_WARNINGS, \"checks\": [$CONFIG_STATUS_JSON]}"

if [ -n "${REPORT_DIR:-}" ]; then
  printf '%s' "$CONFIG_STATUS_JSON" > "$REPORT_DIR/config-status.json"
fi

# Also export COMPOSE_CMD for caller
export COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"

if [ "$PREFLIGHT_ERRORS" -gt 0 ]; then
  log_error "Pre-flight failed with $PREFLIGHT_ERRORS error(s), $PREFLIGHT_WARNINGS warning(s)"
  exit 1
fi

if [ "$PREFLIGHT_WARNINGS" -gt 0 ]; then
  log_warning "Pre-flight passed with $PREFLIGHT_WARNINGS warning(s)"
else
  log_info "Pre-flight passed"
fi
exit 0
