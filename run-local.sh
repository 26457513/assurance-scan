#!/usr/bin/env bash
# run-local.sh — ASVS Scanner local entrypoint.
#
# Usage:
#   ./run-local.sh <target-dir> [--image <name>]... [--url <url>]... [--uploads <dir>]... [--fr-catalog <json>] [--compliance-mapping-pack <json>] [--scanner-compliance-mapping-pack <json-or-dir>]... [--assurance-framework <json>] [--assurance-instance <json>]
#
# Examples:
#   ./run-local.sh /path/to/project
#   ./run-local.sh /path/to/project --image app:local
#   ./run-local.sh /path/to/project --url http://localhost:3000
#   ./run-local.sh /path/to/project --url https://localhost:8443
#   ./run-local.sh /path/to/project --uploads ./sample-files
#   ./run-local.sh /path/to/project --image app:local --url https://prod.example.com --uploads ./uploads

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RESET=$'\033[0m'
  C_DIM=$'\033[2m'
  C_BOLD=$'\033[1m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
  C_CYAN=$'\033[36m'
  C_BLUE=$'\033[34m'
else
  C_RESET=""
  C_DIM=""
  C_BOLD=""
  C_GREEN=""
  C_YELLOW=""
  C_RED=""
  C_CYAN=""
  C_BLUE=""
fi

DIVIDER="────────────────────────────────────────────────────────────"
SECTION_NO=0
RUN_START_EPOCH="${ASVS_RUN_START_EPOCH:-$(date +%s)}"
ASVS_PARALLELISM="${ASVS_PARALLELISM:-4}"
ASVS_DB_REFRESH_TTL_HOURS="${ASVS_DB_REFRESH_TTL_HOURS:-24}"
TIMING_LABELS=()
TIMING_SECONDS=()

banner() {
  printf '\n%s\n' "${C_CYAN}${C_BOLD}╭────────────────────────────────────────────╮${C_RESET}"
  printf '%s\n' "${C_CYAN}${C_BOLD}│              ASVS Scanner                  │${C_RESET}"
  printf '%s\n' "${C_CYAN}${C_BOLD}╰────────────────────────────────────────────╯${C_RESET}"
  printf '%s\n\n' "${C_DIM}Application Security Verification Standard security scanner${C_RESET}"
}

section() {
  SECTION_NO=$((SECTION_NO + 1))
  printf '\n%s\n' "${C_DIM}${DIVIDER}${C_RESET}"
  printf '%s\n' "${C_BOLD}${C_BLUE}${SECTION_NO}. $*${C_RESET}"
}

status_line() {
  local label="$1"
  local status="$2"
  local color="$3"
  printf '  %-28s %s%s%s\n' "$label" "$color" "$status" "$C_RESET"
}

ok() { status_line "$1" "ready" "$C_GREEN"; }
done_line() { status_line "$1" "done" "$C_GREEN"; }
current_line() { status_line "$1" "current" "$C_GREEN"; }
warn_line() { status_line "$1" "$2" "$C_YELLOW"; }
fail_line() { status_line "$1" "$2" "$C_RED"; }

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

format_duration() {
  local total="$1"
  local hours mins secs
  hours=$((total / 3600))
  mins=$(((total % 3600) / 60))
  secs=$((total % 60))
  if [ "$hours" -gt 0 ]; then
    printf '%dh %02dm %02ds' "$hours" "$mins" "$secs"
  elif [ "$mins" -gt 0 ]; then
    printf '%dm %02ds' "$mins" "$secs"
  else
    printf '%ds' "$secs"
  fi
}

record_timing() {
  TIMING_LABELS+=("$1")
  TIMING_SECONDS+=("$2")
}

truncate_text() {
  local text="$1"
  local max="$2"
  if [ "${#text}" -le "$max" ]; then
    printf '%s' "$text"
  else
    printf '%s...' "${text:0:$((max - 3))}"
  fi
}

print_timing_table() {
  local i total label seconds duration max_label label_col sep
  total="$1"
  max_label=54
  printf '\n%s\n' "${C_BOLD}${C_BLUE}Timing${C_RESET}"
  printf '  %s\n' "${C_DIM}┌────────────────────────────────────────────────────────┬────────────┐${C_RESET}"
  printf '  %s%-56s%s%12s%s\n' "${C_DIM}│${C_RESET}" "Step" "${C_DIM}│${C_RESET}" "Duration" "${C_DIM}│${C_RESET}"
  printf '  %s\n' "${C_DIM}├────────────────────────────────────────────────────────┼────────────┤${C_RESET}"
  for i in "${!TIMING_LABELS[@]}"; do
    label="$(truncate_text "${TIMING_LABELS[$i]}" "$max_label")"
    seconds="${TIMING_SECONDS[$i]}"
    duration="$(format_duration "$seconds")"
    printf '  %s %-54s %s %10s %s\n' "${C_DIM}│${C_RESET}" "$label" "${C_DIM}│${C_RESET}" "$duration" "${C_DIM}│${C_RESET}"
  done
  printf '  %s\n' "${C_DIM}├────────────────────────────────────────────────────────┼────────────┤${C_RESET}"
  printf '  %s %s%-54s%s %s %s%10s%s %s\n' "${C_DIM}│${C_RESET}" "$C_BOLD" "Total elapsed" "$C_RESET" "${C_DIM}│${C_RESET}" "$C_BOLD" "$(format_duration "$total")" "$C_RESET" "${C_DIM}│${C_RESET}"
  printf '  %s\n' "${C_DIM}└────────────────────────────────────────────────────────┴────────────┘${C_RESET}"
}

print_file_table() {
  printf '\n%s\n' "${C_BOLD}${C_BLUE}Files${C_RESET}"
  printf '  %-18s %s\n' "Item" "Path"
  printf '  %-18s %s\n' "------------------" "------------------------------------------------------------"
  printf '  %-18s %s%s%s\n' "Dashboard" "$C_CYAN" "$REPORT_DIR/dashboard.html" "$C_RESET"
  printf '  %-18s %s\n' "Fix prompt" "$REPORT_DIR/agent-investigation-prompt.md"
  printf '  %-18s %s\n' "Assurance prompt" "$REPORT_DIR/assurance-assessment-prompt.md"
  if [ -f "$REPORT_DIR/evidence-bundle.json" ]; then
    printf '  %-18s %s\n' "Evidence bundle" "$REPORT_DIR/evidence-bundle.json"
  fi
  if [ -f "$REPORT_DIR/agent-prompt-plan.json" ]; then
    printf '  %-18s %s\n' "Agent plan" "$REPORT_DIR/agent-prompt-plan.json"
  fi
  if [ -f "$REPORT_DIR/dashboard-payload.json" ]; then
    printf '  %-18s %s\n' "Dashboard payload" "$REPORT_DIR/dashboard-payload.json"
  fi
  printf '  %-18s %s\n' "Run summary" "$REPORT_DIR/scanner-run-summary.txt"
  printf '  %-18s %s\n' "Detailed log" "$REPORT_DIR/run.log"
  printf '  %-18s %s\n' "Timings" "$REPORT_DIR/timings.json"
  printf '  %-18s %s\n' "Validate" "asvs-scanner validate-report \"$REPORT_DIR\" --strict"
}

cache_stamp_name() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//'
}

cache_stamp_read() {
  local label stamp volume helper
  label="$(cache_stamp_name "$1")"
  stamp="${label}.stamp"
  volume="${ASVS_META_VOLUME:-${COMPOSE_PROJECT_NAME:-asvs-scanner}_db-meta}"
  helper="${ASVS_META_HELPER_IMAGE:-asvs-scanner:latest}"
  docker volume create "$volume" >/dev/null 2>&1 || return 1
  docker run --rm --entrypoint sh -v "$volume:/meta" "$helper" -c "cat /meta/$stamp 2>/dev/null || true" 2>/dev/null || true
}

prefetch_needs_refresh() {
  local label="$1"
  local stamp now stamp_age max_age

  if [ "${ASVS_DB_REFRESH_TTL_HOURS}" = "0" ]; then
    return 0
  fi

  stamp="$(cache_stamp_read "$label")"
  [ -n "$stamp" ] || return 0
  [[ "$stamp" =~ ^[0-9]+$ ]] || return 0

  now="$(date +%s)"
  stamp_age=$(( now - stamp ))
  max_age=$(( ASVS_DB_REFRESH_TTL_HOURS * 3600 ))
  [ "$stamp_age" -ge "$max_age" ]
}

mark_prefetch_refreshed() {
  local label stamp volume helper now
  label="$(cache_stamp_name "$1")"
  stamp="${label}.stamp"
  volume="${ASVS_META_VOLUME:-${COMPOSE_PROJECT_NAME:-asvs-scanner}_db-meta}"
  helper="${ASVS_META_HELPER_IMAGE:-asvs-scanner:latest}"
  now="$(date +%s)"
  docker volume create "$volume" >/dev/null 2>&1 || return 0
  docker run --rm --entrypoint sh -v "$volume:/meta" "$helper" -c "mkdir -p /meta && printf '%s\n' '$now' > /meta/$stamp" >/dev/null 2>&1 || true
}

prefetch_services_for_allowlist() {
  local only="$1"
  shift
  local services=("$@")
  if [ -z "$only" ]; then
    printf '%s\n' "${services[@]}"
    return
  fi

  local filtered=()
  local svc want
  IFS=',' read -ra ALLOW <<< "$only"
  for svc in "${services[@]}"; do
    for want in "${ALLOW[@]}"; do
      if [[ "$svc" == *"$want"* ]]; then
        filtered+=("$svc")
      fi
    done
  done
  printf '%s\n' "${filtered[@]}"
}

run_prefetch_services() {
  local log_file="$1"
  shift
  local services=("$@")
  local svc label rc

  [ ${#services[@]} -gt 0 ] || return 0

  section "Scanner database setup"
  [ -z "$log_file" ] || {
    echo ""
    echo "== Setup: ensuring scanner databases =="
  } >> "$log_file"

  for svc in "${services[@]}"; do
    label="${svc#prefetch-}"
    if [ "${ASVS_PREFETCH_FORCE:-0}" != "1" ] && ! prefetch_needs_refresh "$label"; then
      current_line "$label"
      [ -z "$log_file" ] || echo "==> $svc skipped; refreshed within ${ASVS_DB_REFRESH_TTL_HOURS}h TTL" >> "$log_file"
      continue
    fi
    [ -z "$log_file" ] || echo "==> $svc" >> "$log_file"
    if [ -n "$log_file" ]; then
      $COMPOSE_BIN -f "$SCRIPT_DIR/docker-compose.security.yml" --profile prefetch run --rm "$svc" >> "$log_file" 2>&1
    else
      $COMPOSE_BIN -f "$SCRIPT_DIR/docker-compose.security.yml" --profile prefetch run --rm "$svc" >/tmp/asvs-prefetch-"$svc"-$$.log 2>&1
    fi
    rc=$?
    if [ "$rc" -eq 0 ]; then
      ok "$label"
      mark_prefetch_refreshed "$label"
    else
      warn_line "$label" "warning (exit $rc)"
      [ -z "$log_file" ] || echo "WARN: $svc exited with code $rc. Continuing." >> "$log_file"
    fi
  done
}

usage() {
  cat <<USAGE
Usage:
  ./run-local.sh <target-dir> [--image <name>]... [--url <url>]... [--uploads <dir>]... [--fr-catalog <json>] [--scanner-compliance-mapping-pack <json-or-dir>]...
  ./run-local.sh prefetch                          # one-time DB pre-download
  ./run-local.sh prefetch --only trivy,osv         # prefetch specific DBs only
  ./run-local.sh --help

Examples:
  ./run-local.sh prefetch                          # optional: warm DB volumes ahead of time
  ./run-local.sh /path/to/project
  ./run-local.sh /path/to/project --image app:local
  ./run-local.sh /path/to/project --url http://localhost:3000
  ./run-local.sh /path/to/project --url https://localhost:8443
  ./run-local.sh /path/to/project --uploads ./sample-files

Scans automatically seed scanner database volumes before running. Use prefetch
when you want to warm a laptop ahead of time or refresh DBs explicitly
(osv-scanner publishes daily, Trivy/Grype/ClamAV on their own cadences).

Scanners run concurrently by default with ASVS_PARALLELISM=4. Use
ASVS_PARALLELISM=1 for sequential troubleshooting, or raise it on machines with
more CPU/RAM.

Scanner databases refresh at most once every ASVS_DB_REFRESH_TTL_HOURS hours
(default: 24). Set ASVS_DB_REFRESH_TTL_HOURS=0 to refresh every scan.

Output (per scan):
  reports/<timestamp>/executive-summary.md
  reports/<timestamp>/scanner-run-summary.txt
  reports/<timestamp>/evidence-manifest.json
  reports/<timestamp>/manual-evidence-required.md
  reports/<timestamp>/reports/   (raw scanner outputs)
  reports/<timestamp>/sbom/      (SBOMs)
  reports/<timestamp>/hashes/    (per-file SHA-256)
USAGE
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
TARGET_DIR=""
IMAGE_NAME=""
TARGET_URL=""
UPLOADS_DIR=""
IMAGE_NAMES=()
TARGET_URLS=()
UPLOADS_DIRS=()
SCANNER_COMPLIANCE_MAPPING_PACKS=()
PREFETCH_ONLY=""

if [ "${1:-}" = "" ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ "$1" = "prefetch" ]; then
  shift
  if [ "${1:-}" = "--only" ]; then
    PREFETCH_ONLY="$2"
    shift 2
  fi
  # Run prefetch and exit.
  # Compose interpolates ${TARGET_DIR}/RUN_ID for every service in the file
  # even when only running prefetch services, so set harmless dummy values.
  export TARGET_DIR="${TARGET_DIR:-/tmp}"
  export SCAN_SOURCE_DIR="${SCAN_SOURCE_DIR:-/tmp}"
  export RUN_ID="${RUN_ID:-prefetch}"
  export ASVS_PREFETCH_FORCE=1
  COMPOSE_BIN="${COMPOSE_BIN:-docker compose}"
  PREFETCH_SERVICES=(prefetch-trivy prefetch-grype prefetch-osv prefetch-clamav)
  mapfile -t PREFETCH_SERVICES < <(prefetch_services_for_allowlist "$PREFETCH_ONLY" "${PREFETCH_SERVICES[@]}")
  run_prefetch_services "" "${PREFETCH_SERVICES[@]}"
  echo ""
  echo "Prefetch complete. Databases cached in named volumes:"
  docker volume ls --filter "name=asvs-scanner" --format "{{.Name}}"
  exit 0
fi

# First positional = target dir
TARGET_DIR="$1"
shift

while [ $# -gt 0 ]; do
  case "$1" in
    --image)
      IMAGE_NAMES+=("${2:-}"); shift 2 ;;
    --url)
      TARGET_URLS+=("${2:-}"); shift 2 ;;
    --uploads)
      UPLOADS_DIRS+=("${2:-}"); shift 2 ;;
    --fr-catalog)
      FR_CATALOG="${2:-}"; shift 2 ;;
    --compliance-mapping-pack)
      COMPLIANCE_MAPPING_PACK="${2:-}"; shift 2 ;;
    --scanner-compliance-mapping-pack)
      SCANNER_COMPLIANCE_MAPPING_PACKS+=("${2:-}"); shift 2 ;;
    --assurance-framework)
      ASSURANCE_FRAMEWORK="${2:-}"; shift 2 ;;
    --assurance-instance)
      ASSURANCE_INSTANCE="${2:-}"; shift 2 ;;
    --junit-xml)
      JUNIT_XML="${2:-}"; shift 2 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

# Resolve uploads dirs to absolute paths if supplied.
for i in "${!UPLOADS_DIRS[@]}"; do
  if [ -n "${UPLOADS_DIRS[$i]}" ] && [[ "${UPLOADS_DIRS[$i]}" != /* ]]; then
    UPLOADS_DIRS[$i]="$(cd "$SCRIPT_DIR" && pwd)/${UPLOADS_DIRS[$i]}"
  fi
done

# Backward-compatible scalar values used by config/preflight and summary text.
IMAGE_NAME="${IMAGE_NAMES[0]:-}"
TARGET_URL="${TARGET_URLS[0]:-}"
UPLOADS_DIR="${UPLOADS_DIRS[0]:-}"
SCAN_SOURCE_DIR="${SCAN_SOURCE_DIR:-$TARGET_DIR}"
ASVS_IMAGE_NAMES="$(IFS=,; printf '%s' "${IMAGE_NAMES[*]}")"

# ---------------------------------------------------------------------------
# Resolve config (CLI > env > scanner-config.yaml > defaults)
# ---------------------------------------------------------------------------
export TARGET_DIR SCAN_SOURCE_DIR IMAGE_NAME ASVS_IMAGE_NAMES TARGET_URL UPLOADS_DIR
# shellcheck disable=SC1091
. "$SCRIPT_DIR/scripts/load-config.sh"

# ---------------------------------------------------------------------------
# Prepare report dir
# ---------------------------------------------------------------------------
if [ -z "${RUN_ID:-}" ]; then
  sha8="$(git -C "$TARGET_DIR" rev-parse --short=8 HEAD 2>/dev/null || od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_${sha8}"
fi
REPORT_DIR="$SCRIPT_DIR/reports/$RUN_ID"
mkdir -p "$REPORT_DIR/reports" "$REPORT_DIR/sbom" "$REPORT_DIR/hashes" "$REPORT_DIR/tmp"

export SCRIPT_DIR REPORT_DIR RUN_ID

if [ "${ASVS_BANNER_SHOWN:-0}" != "1" ]; then
  banner
fi
printf '%s\n' "${C_BOLD}Run ID:${C_RESET} $RUN_ID"
printf '%s\n' "${C_BOLD}Target:${C_RESET} $TARGET_DIR"
[ "$SCAN_SOURCE_DIR" = "$TARGET_DIR" ] || printf '%s\n' "${C_BOLD}Source snapshot:${C_RESET} $SCAN_SOURCE_DIR"
if [ ${#IMAGE_NAMES[@]} -gt 0 ]; then
  printf '%s\n' "${C_BOLD}Images:${C_RESET} ${IMAGE_NAMES[*]}"
fi
if [ ${#TARGET_URLS[@]} -gt 0 ]; then
  printf '%s\n' "${C_BOLD}URLs:${C_RESET} ${TARGET_URLS[*]}"
fi
if [ ${#UPLOADS_DIRS[@]} -gt 0 ]; then
  printf '%s\n' "${C_BOLD}Uploads:${C_RESET} ${UPLOADS_DIRS[*]}"
fi

# Initialise run.log
{
  printf 'ASVS security scan\n'
  printf 'Run ID: %s\n' "$RUN_ID"
  printf 'Target: %s\n' "$TARGET_DIR"
  [ "$SCAN_SOURCE_DIR" = "$TARGET_DIR" ] || printf 'Source snapshot: %s\n' "$SCAN_SOURCE_DIR"
  for image in "${IMAGE_NAMES[@]}"; do [ -n "$image" ] && printf 'Image: %s\n' "$image"; done
  for url in "${TARGET_URLS[@]}"; do [ -n "$url" ] && printf 'URL: %s\n' "$url"; done
  for uploads in "${UPLOADS_DIRS[@]}"; do [ -n "$uploads" ] && printf 'Uploads: %s\n' "$uploads"; done
  printf 'Reports: %s\n\n' "$REPORT_DIR"
} > "$REPORT_DIR/run.log"

if [ "${ASVS_IMAGE_BUILD_SECONDS:-0}" -gt 0 ] 2>/dev/null; then
  record_timing "image builds" "$ASVS_IMAGE_BUILD_SECONDS"
fi

# ---------------------------------------------------------------------------
# Phase 1 — Pre-flight
# ---------------------------------------------------------------------------
section "Pre-flight checks"
echo "== Pre-flight checks ==" >> "$REPORT_DIR/run.log"
if "$SCRIPT_DIR/scripts/preflight.sh" >> "$REPORT_DIR/run.log" 2>&1; then
  ok "environment"
else
  fail_line "environment" "failed"
  echo "ERROR: pre-flight checks failed. Run aborted." | tee -a "$REPORT_DIR/run.log"
  exit 1
fi

# ---------------------------------------------------------------------------
# Phase 2 — Scanners
# ---------------------------------------------------------------------------
# Pick compose binary detected by preflight (falls back to docker compose)
COMPOSE_BIN="${COMPOSE_CMD:-docker compose}"

LEVEL1_SERVICES=(semgrep gitleaks trivy-fs trivy-config syft grype osv-scanner)
LEVEL2_IMAGE_SERVICES=(trivy-image syft-image grype-image)
LEVEL2_URL_SERVICES=(zap-baseline security-headers)
LEVEL2_HTTPS_SERVICES=(testssl)
LEVEL2_UPLOADS_SERVICES=(clamav)

# Build the list of scanner run specs, plus SKIPPED entries for unrequested Level-2.
# Spec format: service|kind|target|suffix. Empty suffix preserves legacy output names.
SERVICES_TO_RUN=()
SKIPPED_RECORDS=()

add_skipped_record() {
  local scanner="$1"
  local reason="$2"
  SKIPPED_RECORDS+=("$scanner"$'\t'"$reason")
}

slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's|^[a-z]+://||; s|[^a-z0-9._-]+|-|g; s|^-+||; s|-+$||; s|[-.]{2,}|-|g' | cut -c1-64
}

suffix_for() {
  local target="$1"
  local count="$2"
  if [ "$count" -le 1 ]; then
    printf ''
  else
    local slug
    slug="$(slugify "$target")"
    printf -- '-%s' "${slug:-target}"
  fi
}

for s in "${LEVEL1_SERVICES[@]}"; do
  SERVICES_TO_RUN+=("$s|source||")
done

if [ ${#IMAGE_NAMES[@]} -gt 0 ]; then
  for image in "${IMAGE_NAMES[@]}"; do
    suffix="$(suffix_for "$image" "${#IMAGE_NAMES[@]}")"
    for s in "${LEVEL2_IMAGE_SERVICES[@]}"; do
      SERVICES_TO_RUN+=("$s|image|$image|$suffix")
    done
  done
else
  for s in "${LEVEL2_IMAGE_SERVICES[@]}"; do
    add_skipped_record "$s" "--image not supplied"
  done
fi

if [ ${#TARGET_URLS[@]} -gt 0 ]; then
  any_https=0
  for url in "${TARGET_URLS[@]}"; do
    suffix="$(suffix_for "$url" "${#TARGET_URLS[@]}")"
    for s in "${LEVEL2_URL_SERVICES[@]}"; do
      SERVICES_TO_RUN+=("$s|url|$url|$suffix")
    done
    case "$url" in
      https://*)
        any_https=1
        for s in "${LEVEL2_HTTPS_SERVICES[@]}"; do
          SERVICES_TO_RUN+=("$s|url|$url|$suffix")
        done
        ;;
    esac
  done
  if [ "$any_https" -eq 0 ]; then
    for s in "${LEVEL2_HTTPS_SERVICES[@]}"; do
      add_skipped_record "$s" "no HTTPS URL supplied"
    done
  fi
else
  for s in "${LEVEL2_URL_SERVICES[@]}"; do
    add_skipped_record "$s" "--url not supplied"
  done
  for s in "${LEVEL2_HTTPS_SERVICES[@]}"; do
    add_skipped_record "$s" "--url not supplied"
  done
fi

if [ ${#UPLOADS_DIRS[@]} -gt 0 ]; then
  for uploads in "${UPLOADS_DIRS[@]}"; do
    suffix="$(suffix_for "$uploads" "${#UPLOADS_DIRS[@]}")"
    for s in "${LEVEL2_UPLOADS_SERVICES[@]}"; do
      SERVICES_TO_RUN+=("$s|uploads|$uploads|$suffix")
    done
  done
else
  for s in "${LEVEL2_UPLOADS_SERVICES[@]}"; do
    add_skipped_record "$s" "--uploads not supplied"
  done
fi

# Write the SKIPPED entries to scanner-health.json immediately; the bundle
# generator will merge them with live PASS/WARN/FAIL classifications.
if [ ${#SKIPPED_RECORDS[@]} -gt 0 ]; then
  printf '%s\n' "${SKIPPED_RECORDS[@]}" | python3 -c 'import json, sys
records = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    name, reason = line.split("\t", 1)
    records.append({"name": name, "status": "SKIPPED", "reason": reason})
print(json.dumps({"scanners": records}, indent=2))
' > "$REPORT_DIR/scanner-health.json"
else
  printf '{"scanners": []}\n' > "$REPORT_DIR/scanner-health.json"
fi

if [ "${ASVS_AUTO_PREFETCH:-1}" != "0" ]; then
  AUTO_PREFETCH_SERVICES=(prefetch-trivy prefetch-grype prefetch-osv)
  if [ ${#UPLOADS_DIRS[@]} -gt 0 ]; then
    AUTO_PREFETCH_SERVICES+=(prefetch-clamav)
  fi
  run_prefetch_services "$REPORT_DIR/run.log" "${AUTO_PREFETCH_SERVICES[@]}"
else
  section "Scanner database setup"
  warn_line "database prefetch" "skipped"
  echo "== Setup: scanner database prefetch skipped by ASVS_AUTO_PREFETCH=0 ==" >> "$REPORT_DIR/run.log"
fi

if ! [[ "$ASVS_PARALLELISM" =~ ^[0-9]+$ ]] || [ "$ASVS_PARALLELISM" -lt 1 ]; then
  ASVS_PARALLELISM=1
fi

section "Scanner run (${#SERVICES_TO_RUN[@]} services, parallelism $ASVS_PARALLELISM)"
echo "== Scanner run: ${#SERVICES_TO_RUN[@]} services ==" >> "$REPORT_DIR/run.log"

# Quiet parallel pull to speed up first run, then reuse local images within the DB TTL window.
if prefetch_needs_refresh "scanner-images"; then
  echo "==> Pulling scanner images if needed" >> "$REPORT_DIR/run.log"
  if $COMPOSE_BIN -f "$SCRIPT_DIR/docker-compose.security.yml" pull --quiet >> "$REPORT_DIR/run.log" 2>&1; then
    ok "scanner images"
    mark_prefetch_refreshed "scanner-images"
  else
    warn_line "scanner images" "continuing"
    echo "WARN: one or more scanner image pulls failed; continuing with local images where possible." >> "$REPORT_DIR/run.log"
  fi
else
  current_line "scanner images"
  echo "==> Scanner image pull skipped; refreshed within ${ASVS_DB_REFRESH_TTL_HOURS}h TTL" >> "$REPORT_DIR/run.log"
fi

# Run each scanner. Tool-aware health classification happens in the bundle
# generator (PASS/WARN/FAIL based on output file, not exit code). Here we just
# record exit codes per scanner and continue on non-zero.
#
# After each source/config scanner, apply .scannerignore patterns if a
# .scannerignore file exists at the project root. Dependency scanners
# (trivy-fs, syft, grype, osv-scanner) are intentionally NOT filtered.
SCANNER_IGNORE_FILE="$SCAN_SOURCE_DIR/.scannerignore"
if [ -f "$SCANNER_IGNORE_FILE" ]; then
  SCANNER_IGNORE_ARG="--scanner-ignore $SCANNER_IGNORE_FILE"
  echo "Using exclusions from: $SCANNER_IGNORE_FILE" | tee -a "$REPORT_DIR/run.log"
else
  SCANNER_IGNORE_ARG=""
fi

EXIT_CODES_FILE="$REPORT_DIR/scanner-exit-codes.json"
SCANNER_JOBS_DIR="$REPORT_DIR/.scanner-jobs"
mkdir -p "$SCANNER_JOBS_DIR"
JOB_IDS=()
JOB_LABELS=()
JOB_KEYS=()

scanner_status_text() {
  local service="$1"
  local rc="$2"
  if [ "$rc" -eq 0 ]; then
    printf 'done'
    return
  fi

  case "$service" in
    gitleaks) printf 'findings detected' ;;
    osv-scanner) printf 'coverage limited' ;;
    semgrep|trivy-fs|trivy-config|trivy-image|grype|grype-image|zap-baseline|security-headers|testssl|clamav)
      printf 'completed with findings'
      ;;
    *) printf 'completed; check log' ;;
  esac
}

run_scanner_job() {
  local job_id="$1"
  local service="$2"
  local target_kind="$3"
  local target_value="$4"
  local output_suffix="$5"
  local job_log="$SCANNER_JOBS_DIR/$job_id.log"
  local job_meta="$SCANNER_JOBS_DIR/$job_id.meta"
  local job_rc="$SCANNER_JOBS_DIR/$job_id.rc"
  local job_seconds="$SCANNER_JOBS_DIR/$job_id.seconds"
  local started_at elapsed rc out_file

  (
    export OUTPUT_SUFFIX="$output_suffix"
    case "$target_kind" in
      image)
        export IMAGE_NAME="$target_value"
        export TARGET_URL="${TARGET_URLS[0]:-}"
        export UPLOADS_DIR="${UPLOADS_DIRS[0]:-/tmp/empty}"
        ;;
      url)
        export TARGET_URL="$target_value"
        export IMAGE_NAME="${IMAGE_NAMES[0]:-}"
        export UPLOADS_DIR="${UPLOADS_DIRS[0]:-/tmp/empty}"
        ;;
      uploads)
        export UPLOADS_DIR="$target_value"
        export IMAGE_NAME="${IMAGE_NAMES[0]:-}"
        export TARGET_URL="${TARGET_URLS[0]:-}"
        ;;
      *)
        export IMAGE_NAME="${IMAGE_NAMES[0]:-}"
        export TARGET_URL="${TARGET_URLS[0]:-}"
        export UPLOADS_DIR="${UPLOADS_DIRS[0]:-/tmp/empty}"
        ;;
    esac

    if [ -n "$target_value" ]; then
      echo "==> Running $service [$target_value]" > "$job_log"
    else
      echo "==> Running $service" > "$job_log"
    fi

    started_at="$(date +%s)"
    $COMPOSE_BIN -f "$SCRIPT_DIR/docker-compose.security.yml" run --rm "$service" >> "$job_log" 2>&1
    rc=$?

    case "$service" in
      semgrep)      out_file="$REPORT_DIR/reports/semgrep.sarif" ;;
      gitleaks)     out_file="$REPORT_DIR/reports/gitleaks.json" ;;
      trivy-config) out_file="$REPORT_DIR/reports/trivy-config.json" ;;
      *)            out_file="" ;;
    esac
    if [ -n "$out_file" ] && [ -n "$SCANNER_IGNORE_ARG" ]; then
      python3 "$SCRIPT_DIR/scripts/apply-scannerignore.py" \
        $SCANNER_IGNORE_ARG \
        --scanner "$service" \
        --output "$out_file" >> "$job_log" 2>&1 || true
    fi

    elapsed=$(( $(date +%s) - started_at ))
    printf '%s\n' "$rc" > "$job_rc"
    printf '%s\n' "$elapsed" > "$job_seconds"
    printf 'status=%s\n' "$(scanner_status_text "$service" "$rc")" > "$job_meta"
    if [ "$rc" -ne 0 ]; then
      echo "WARN: $service exited with non-zero code ($rc). Tool-aware classification happens in the bundle generator." >> "$job_log"
    fi
  )
}

printf '  %-28s %s\n' "scanner" "queued"
job_index=0
for spec in "${SERVICES_TO_RUN[@]}"; do
  IFS='|' read -r service target_kind target_value output_suffix <<< "$spec"
  job_index=$((job_index + 1))
  job_id="$(printf '%03d' "$job_index")"
  if [ -n "$target_value" ]; then
    job_label="$service [$target_value]"
  else
    job_label="$service"
  fi
  exit_key="$service$output_suffix"

  JOB_IDS+=("$job_id")
  JOB_LABELS+=("$job_label")
  JOB_KEYS+=("$exit_key")

  while [ "$(jobs -pr | wc -l | tr -d ' ')" -ge "$ASVS_PARALLELISM" ]; do
    wait -n 2>/dev/null || true
  done
  status_line "$job_label" "started" "$C_DIM"
  run_scanner_job "$job_id" "$service" "$target_kind" "$target_value" "$output_suffix" &
done
wait

printf '{\n  "exit_codes": {\n' > "$EXIT_CODES_FILE"
ec_first=1
echo "" >> "$REPORT_DIR/run.log"
echo "== Scanner logs ==" >> "$REPORT_DIR/run.log"
for i in "${!JOB_IDS[@]}"; do
  job_id="${JOB_IDS[$i]}"
  job_label="${JOB_LABELS[$i]}"
  exit_key="${JOB_KEYS[$i]}"
  rc="$(cat "$SCANNER_JOBS_DIR/$job_id.rc" 2>/dev/null || printf '1')"
  step_elapsed="$(cat "$SCANNER_JOBS_DIR/$job_id.seconds" 2>/dev/null || printf '0')"
  status="$(sed -n 's/^status=//p' "$SCANNER_JOBS_DIR/$job_id.meta" 2>/dev/null || true)"
  [ -n "$status" ] || status="completed; check log"

  record_timing "$job_label" "$step_elapsed"
  [ $ec_first -eq 1 ] || printf ',\n' >> "$EXIT_CODES_FILE"
  printf '    "%s": %d' "$(json_escape "$exit_key")" "$rc" >> "$EXIT_CODES_FILE"
  ec_first=0

  echo "" >> "$REPORT_DIR/run.log"
  cat "$SCANNER_JOBS_DIR/$job_id.log" >> "$REPORT_DIR/run.log" 2>/dev/null || true

  if [ "$rc" -eq 0 ]; then
    done_line "$job_label"
  else
    warn_line "$job_label" "$status"
  fi
done
printf '\n  }\n}\n' >> "$EXIT_CODES_FILE"

# ---------------------------------------------------------------------------
# Phase 3 — Manual evidence checklist
# ---------------------------------------------------------------------------
section "Report generation"
echo "" >> "$REPORT_DIR/run.log"
echo "== Report generation ==" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
python3 "$SCRIPT_DIR/scripts/manual-evidence-template.py" \
  --target-dir "$TARGET_DIR" \
  --run-id "$RUN_ID" \
  --output "$REPORT_DIR/manual-evidence-required.md" >> "$REPORT_DIR/run.log" 2>&1
record_timing "manual checklist" "$(( $(date +%s) - step_started_at ))"
done_line "manual checklist"

echo "==> Discovering project tests" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
if python3 "$SCRIPT_DIR/scripts/discover-project-tests.py" \
  --target-dir "$TARGET_DIR" \
  --output "$REPORT_DIR/reports/test-inventory.json" >> "$REPORT_DIR/run.log" 2>&1; then
  record_timing "test discovery" "$(( $(date +%s) - step_started_at ))"
  done_line "test discovery"
else
  record_timing "test discovery" "$(( $(date +%s) - step_started_at ))"
  warn_line "test discovery failed; continuing without native test inventory"
fi

if [ -n "${JUNIT_XML:-${ASVS_JUNIT_XML:-}}" ]; then
  JUNIT_PATH="${JUNIT_XML:-${ASVS_JUNIT_XML}}"
  if [ -f "$JUNIT_PATH" ]; then
    cp "$JUNIT_PATH" "$REPORT_DIR/reports/junit.xml"
    echo "Copied JUnit XML into reports/junit.xml" >> "$REPORT_DIR/run.log"
  fi
fi

echo "==> Generating assurance test pack" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
ASSURANCE_PACK_ARGS=(
  --target-dir "$TARGET_DIR"
  --report-dir "$REPORT_DIR"
  --test-inventory "$REPORT_DIR/reports/test-inventory.json"
)
if [ -n "${FR_CATALOG:-${ASVS_FR_CATALOG:-}}" ]; then
  PACK_CATALOG_PATH="${FR_CATALOG:-${ASVS_FR_CATALOG}}"
  if [ -f "$PACK_CATALOG_PATH" ]; then
    ASSURANCE_PACK_ARGS+=(--fr-catalog "$PACK_CATALOG_PATH")
  fi
fi
if python3 "$SCRIPT_DIR/scripts/generate-assurance-test-pack.py" "${ASSURANCE_PACK_ARGS[@]}" >> "$REPORT_DIR/run.log" 2>&1; then
  record_timing "assurance test pack" "$(( $(date +%s) - step_started_at ))"
  done_line "assurance test pack"
else
  record_timing "assurance test pack" "$(( $(date +%s) - step_started_at ))"
  warn_line "assurance test pack generation failed; continuing without VG_TEST_FRAMEWORK"
fi

# ---------------------------------------------------------------------------
# Phase 4 — Evidence bundle
# ---------------------------------------------------------------------------
echo "" >> "$REPORT_DIR/run.log"
echo "==> Generating evidence bundle" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
BUNDLE_ARGS=(
  --report-dir "$REPORT_DIR"
  --target-dir "$TARGET_DIR"
  --run-id "$RUN_ID"
)
for image in "${IMAGE_NAMES[@]}"; do
  [ -n "$image" ] && BUNDLE_ARGS+=(--image-name "$image")
done
for url in "${TARGET_URLS[@]}"; do
  [ -n "$url" ] && BUNDLE_ARGS+=(--target-url "$url")
done
for uploads in "${UPLOADS_DIRS[@]}"; do
  [ -n "$uploads" ] && BUNDLE_ARGS+=(--uploads-dir "$uploads")
done
if [ -n "${FR_CATALOG:-${ASVS_FR_CATALOG:-}}" ]; then
  BUNDLE_CATALOG_PATH="${FR_CATALOG:-${ASVS_FR_CATALOG}}"
  if [ -f "$BUNDLE_CATALOG_PATH" ]; then
    BUNDLE_ARGS+=(--fr-catalog "$BUNDLE_CATALOG_PATH")
  fi
fi
python3 "$SCRIPT_DIR/scripts/generate-evidence-bundle.py" "${BUNDLE_ARGS[@]}" >> "$REPORT_DIR/run.log" 2>&1
record_timing "evidence bundle" "$(( $(date +%s) - step_started_at ))"
done_line "evidence bundle"

# Best-effort git commit (used by dashboard and agent prompt)
GIT_COMMIT="$(git -C "$TARGET_DIR" rev-parse HEAD 2>/dev/null || echo "")"

# ---------------------------------------------------------------------------
# Phase 5 — Dashboard + agent prompt
# ---------------------------------------------------------------------------
echo "" >> "$REPORT_DIR/run.log"
echo "==> Generating agent prompt" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
PROMPT_ARGS=(
  --report-dir "$REPORT_DIR" \
  --target-dir "$TARGET_DIR" \
  --run-id "$RUN_ID"
)
if [ -n "$GIT_COMMIT" ]; then
  PROMPT_ARGS+=(--git-commit "$GIT_COMMIT")
fi
if [ -n "${FR_CATALOG:-${ASVS_FR_CATALOG:-}}" ]; then
  PROMPT_CATALOG_PATH="${FR_CATALOG:-${ASVS_FR_CATALOG}}"
  if [ -f "$PROMPT_CATALOG_PATH" ]; then
    PROMPT_ARGS+=(--fr-catalog "$PROMPT_CATALOG_PATH")
  fi
fi
if [ -n "${COMPLIANCE_MAPPING_PACK:-${ASVS_COMPLIANCE_MAPPING_PACK:-}}" ]; then
  COMPLIANCE_MAPPING_PACK_PATH="${COMPLIANCE_MAPPING_PACK:-${ASVS_COMPLIANCE_MAPPING_PACK}}"
  if [ -f "$COMPLIANCE_MAPPING_PACK_PATH" ]; then
    PROMPT_ARGS+=(--compliance-mapping-pack "$COMPLIANCE_MAPPING_PACK_PATH")
  else
    echo "WARN: Compliance mapping pack not found at $COMPLIANCE_MAPPING_PACK_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
if [ -n "${ASSURANCE_FRAMEWORK:-${ASVS_ASSURANCE_FRAMEWORK:-}}" ]; then
  PROMPT_FRAMEWORK_PATH="${ASSURANCE_FRAMEWORK:-${ASVS_ASSURANCE_FRAMEWORK}}"
  if [ -f "$PROMPT_FRAMEWORK_PATH" ]; then
    PROMPT_ARGS+=(--assurance-framework "$PROMPT_FRAMEWORK_PATH")
  fi
fi
if [ -n "${ASSURANCE_INSTANCE:-${ASVS_ASSURANCE_INSTANCE:-}}" ]; then
  PROMPT_INSTANCE_PATH="${ASSURANCE_INSTANCE:-${ASVS_ASSURANCE_INSTANCE}}"
  if [ -f "$PROMPT_INSTANCE_PATH" ]; then
    PROMPT_ARGS+=(--assurance-instance "$PROMPT_INSTANCE_PATH")
  fi
fi
python3 "$SCRIPT_DIR/scripts/generate-agent-prompt.py" "${PROMPT_ARGS[@]}" >> "$REPORT_DIR/run.log" 2>&1
record_timing "agent prompt" "$(( $(date +%s) - step_started_at ))"
done_line "agent prompt"

echo "==> Generating dashboard" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
DASHBOARD_ARGS=(--report-dir "$REPORT_DIR")
if [ -n "${FR_CATALOG:-${ASVS_FR_CATALOG:-}}" ]; then
  CATALOG_PATH="${FR_CATALOG:-${ASVS_FR_CATALOG}}"
  if [ -f "$CATALOG_PATH" ]; then
    DASHBOARD_ARGS+=(--fr-catalog "$CATALOG_PATH")
    echo "Using FR catalog: $CATALOG_PATH" >> "$REPORT_DIR/run.log"
    # Snapshot the FR catalog at scan time for time-travel support
    cp "$CATALOG_PATH" "$REPORT_DIR/fr-catalog.snapshot.json"
  else
    echo "WARN: FR catalog not found at $CATALOG_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
if [ -n "${COMPLIANCE_MAPPING_PACK:-${ASVS_COMPLIANCE_MAPPING_PACK:-}}" ]; then
  COMPLIANCE_MAPPING_PACK_PATH="${COMPLIANCE_MAPPING_PACK:-${ASVS_COMPLIANCE_MAPPING_PACK}}"
  if [ -f "$COMPLIANCE_MAPPING_PACK_PATH" ]; then
    DASHBOARD_ARGS+=(--compliance-mapping-pack "$COMPLIANCE_MAPPING_PACK_PATH")
    echo "Using compliance mapping pack: $COMPLIANCE_MAPPING_PACK_PATH" >> "$REPORT_DIR/run.log"
    cp "$COMPLIANCE_MAPPING_PACK_PATH" "$REPORT_DIR/compliance-mapping-pack.snapshot.json"
  else
    echo "WARN: Compliance mapping pack not found at $COMPLIANCE_MAPPING_PACK_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
for SCANNER_COMPLIANCE_MAPPING_PACK_PATH in "${SCANNER_COMPLIANCE_MAPPING_PACKS[@]}"; do
  if [ -e "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH" ]; then
    DASHBOARD_ARGS+=(--scanner-compliance-mapping-pack "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH")
    echo "Using scanner compliance mapping pack: $SCANNER_COMPLIANCE_MAPPING_PACK_PATH" >> "$REPORT_DIR/run.log"
    mkdir -p "$REPORT_DIR/scanner-compliance-mapping-packs"
    if [ -d "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH" ]; then
      cp -R "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH" "$REPORT_DIR/scanner-compliance-mapping-packs/$(basename "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH")"
    else
      cp "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH" "$REPORT_DIR/scanner-compliance-mapping-packs/$(basename "$SCANNER_COMPLIANCE_MAPPING_PACK_PATH")"
    fi
  else
    echo "WARN: Scanner compliance mapping pack not found at $SCANNER_COMPLIANCE_MAPPING_PACK_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
done
if [ ${#SCANNER_COMPLIANCE_MAPPING_PACKS[@]} -eq 0 ] && [ -n "${ASVS_SCANNER_COMPLIANCE_MAPPING_PACK:-}" ]; then
  if [ -e "$ASVS_SCANNER_COMPLIANCE_MAPPING_PACK" ]; then
    DASHBOARD_ARGS+=(--scanner-compliance-mapping-pack "$ASVS_SCANNER_COMPLIANCE_MAPPING_PACK")
    echo "Using scanner compliance mapping pack: $ASVS_SCANNER_COMPLIANCE_MAPPING_PACK" >> "$REPORT_DIR/run.log"
  else
    echo "WARN: Scanner compliance mapping pack not found at $ASVS_SCANNER_COMPLIANCE_MAPPING_PACK — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
if [ -n "${ASSURANCE_FRAMEWORK:-${ASVS_ASSURANCE_FRAMEWORK:-}}" ]; then
  ASSURANCE_FRAMEWORK_PATH="${ASSURANCE_FRAMEWORK:-${ASVS_ASSURANCE_FRAMEWORK}}"
  if [ -f "$ASSURANCE_FRAMEWORK_PATH" ]; then
    DASHBOARD_ARGS+=(--assurance-framework "$ASSURANCE_FRAMEWORK_PATH")
    echo "Using assurance framework: $ASSURANCE_FRAMEWORK_PATH" >> "$REPORT_DIR/run.log"
    cp "$ASSURANCE_FRAMEWORK_PATH" "$REPORT_DIR/assurance-framework.snapshot.json"
  else
    echo "WARN: Assurance framework not found at $ASSURANCE_FRAMEWORK_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
if [ -n "${ASSURANCE_INSTANCE:-${ASVS_ASSURANCE_INSTANCE:-}}" ]; then
  ASSURANCE_INSTANCE_PATH="${ASSURANCE_INSTANCE:-${ASVS_ASSURANCE_INSTANCE}}"
  if [ -f "$ASSURANCE_INSTANCE_PATH" ]; then
    DASHBOARD_ARGS+=(--assurance-instance "$ASSURANCE_INSTANCE_PATH")
    echo "Using assurance instance: $ASSURANCE_INSTANCE_PATH" >> "$REPORT_DIR/run.log"
    cp "$ASSURANCE_INSTANCE_PATH" "$REPORT_DIR/assurance-instance.snapshot.json"
  else
    echo "WARN: Assurance instance not found at $ASSURANCE_INSTANCE_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
if [ -n "${JUNIT_XML:-${ASVS_JUNIT_XML:-}}" ]; then
  JUNIT_PATH="${JUNIT_XML:-${ASVS_JUNIT_XML}}"
  if [ -f "$JUNIT_PATH" ]; then
    DASHBOARD_ARGS+=(--junit-xml "$JUNIT_PATH")
    echo "Using JUnit XML: $JUNIT_PATH" >> "$REPORT_DIR/run.log"
  else
    echo "WARN: JUnit XML not found at $JUNIT_PATH — skipping" >> "$REPORT_DIR/run.log"
  fi
fi
python3 "$SCRIPT_DIR/scripts/generate_dashboard.py" \
  "${DASHBOARD_ARGS[@]}" >> "$REPORT_DIR/run.log" 2>&1
record_timing "dashboard" "$(( $(date +%s) - step_started_at ))"
done_line "dashboard"

echo "==> Validating target report artifacts" >> "$REPORT_DIR/run.log"
step_started_at="$(date +%s)"
if python3 "$SCRIPT_DIR/scripts/validate-report-artifacts.py" --report-dir "$REPORT_DIR" >> "$REPORT_DIR/run.log" 2>&1; then
  record_timing "target artifact validation" "$(( $(date +%s) - step_started_at ))"
  done_line "target artifact validation"
else
  record_timing "target artifact validation" "$(( $(date +%s) - step_started_at ))"
  warn_line "target artifact validation reported issues; see run.log"
fi

# ---------------------------------------------------------------------------
# Final
# ---------------------------------------------------------------------------
RUN_TOTAL_SECONDS=$(( $(date +%s) - RUN_START_EPOCH ))
{
  printf '{\n'
  printf '  "total_seconds": %s,\n' "$RUN_TOTAL_SECONDS"
  printf '  "steps": [\n'
  for i in "${!TIMING_LABELS[@]}"; do
    [ "$i" -eq 0 ] || printf ',\n'
    escaped_label="$(printf '%s' "${TIMING_LABELS[$i]}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf '    {"name": "%s", "seconds": %s}' "$escaped_label" "${TIMING_SECONDS[$i]}"
  done
  printf '\n  ]\n'
  printf '}\n'
} > "$REPORT_DIR/timings.json"

{
  echo ""
  printf '%s\n' "${C_DIM}${DIVIDER}${C_RESET}"
  printf '%s\n' "${C_GREEN}${C_BOLD}ASVS scan complete${C_RESET}"
  printf '  %-18s %s\n' "Run ID" "$RUN_ID"
  printf '  %-18s %s\n' "Report folder" "$REPORT_DIR"
  print_timing_table "$RUN_TOTAL_SECONDS"
  echo ""
  printf '%s\n' "${C_CYAN}${C_BOLD}Open dashboard:${C_RESET}"
  printf '  %sopen "%s/dashboard.html"%s\n' "$C_BOLD" "$REPORT_DIR" "$C_RESET"
  print_file_table
} | tee -a "$REPORT_DIR/run.log"

exit 0
