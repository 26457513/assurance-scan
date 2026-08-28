#!/usr/bin/env bash
# load-config.sh — sourced by run-local.sh
# Applies configuration precedence: CLI args (already set by caller) > env vars
# > scanner-config.yaml > defaults. Exports the resolved values.

set -u

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SCANNER_CONFIG_FILE="${SCANNER_CONFIG_FILE:-scanner-config.yaml}"
ENV_FILE="${ENV_FILE:-.env}"
SCANNER_TIMEOUT_DEFAULT="${SCANNER_TIMEOUT_DEFAULT:-600}"

# Resolved config values (default tier)
NVD_API_KEY="${NVD_API_KEY:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
TRIVY_TOKEN="${TRIVY_TOKEN:-}"
SEMGREP_APP_TOKEN="${SEMGREP_APP_TOKEN:-}"
ZAP_API_KEY="${ZAP_API_KEY:-}"

# ---------------------------------------------------------------------------
# .env file (lowest file tier — env vars already exported take precedence)
# ---------------------------------------------------------------------------
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  . "$ENV_FILE"
  set +a
fi

# ---------------------------------------------------------------------------
# scanner-config.yaml (overrides .env unless env var is already exported)
# ---------------------------------------------------------------------------
yaml_get() {
  # tiny yaml reader: returns value for `key:` at top level, no nesting support.
  # Used only for the documented optional keys. Falls back to env vars.
  local key="$1"
  if [ ! -f "$SCANNER_CONFIG_FILE" ]; then
    return 0
  fi
  awk -v k="$key" '
    $0 ~ "^" k ":" {
      sub("^" k ":[[:space:]]*", "")
      gsub(/^"|"$/, "")
      print
      found=1
      exit
    }
  ' "$SCANNER_CONFIG_FILE"
}

if [ -z "${NVD_API_KEY:-}" ]; then
  NVD_API_KEY="$(yaml_get nvd_api_key)"
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
  GITHUB_TOKEN="$(yaml_get github_token)"
fi
if [ -z "${TRIVY_TOKEN:-}" ]; then
  TRIVY_TOKEN="$(yaml_get trivy_token)"
fi
if [ -z "${SEMGREP_APP_TOKEN:-}" ]; then
  SEMGREP_APP_TOKEN="$(yaml_get semgrep_app_token)"
fi
if [ -z "${ZAP_API_KEY:-}" ]; then
  ZAP_API_KEY="$(yaml_get zap_api_key)"
fi
if [ -z "${SCANNER_TIMEOUT_DEFAULT:-}" ]; then
  SCANNER_TIMEOUT_DEFAULT="$(yaml_get scanner_timeout_default)"
  SCANNER_TIMEOUT_DEFAULT="${SCANNER_TIMEOUT_DEFAULT:-600}"
fi

export NVD_API_KEY GITHUB_TOKEN TRIVY_TOKEN SEMGREP_APP_TOKEN ZAP_API_KEY
export SCANNER_TIMEOUT_DEFAULT SCANNER_CONFIG_FILE ENV_FILE
