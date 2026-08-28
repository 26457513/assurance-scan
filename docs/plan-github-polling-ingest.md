# Plan: CI → assurance-scan server sync (Phase 2 — pull model)

Status: draft for review — 2026-08-18
Precedes: nothing. Follows: `plan-github-actions-sarif.md` (phase 1, shipped).

## Objective

Completed GitHub Actions scans are ingested into the assurance-scan server DB
within ~1 minute, with no inbound exposure on the local machine. The server
polls GitHub; CI pushes nothing.

## Non-goals

- No tunnels, public endpoints, or open ports (that's why pull, not push).
- No change to CI scanning itself beyond one extra file in the artifact zip.
- No realtime (webhooks) — 60s polling is fast enough; escalate later only
  if a real need appears.
- No FR/catalogue evaluation for CI runs — findings + provenance only
  (matches phase 1 scope; the heavy workflow can attach later).

## Design

### 1. Artifact payload: `findings.json` (CI side, small)

`ci-scan.py` already holds everything in memory; it writes a
`findings.json` into the workspace beside the SARIF, and the workflow adds
it to the `assurance-scan-results` zip. Shape mirrors the orchestrator's
`_publish_findings` payload so ingest reuses existing storage conventions:

```json
{
  "schema_version": 1,
  "source": "github-actions",
  "repo": "26457513/doc2context",
  "run_url": "https://github.com/…/actions/runs/…",
  "scanner_status": {"semgrep": "ok", "gitleaks": "ok", "…": "…"},
  "durations": {"semgrep": 12.3},
  "summary": {"total": 174, "by_severity": {"HIGH": 40}, "by_scanner": {}},
  "findings": [
    {"id": "F-001", "scanner": "semgrep", "rule_id": "…", "severity": "HIGH",
     "file_path": "…", "line_start": 24, "line_end": 24, "message": "…",
     "theme": null, "fix_strategy": null, "compliance_tags": []}
  ]
}
```

### 2. Poller (server side, the main new code)

An in-process asyncio task started from `main.py` lifespan — no new process
to supervise; `dev.sh`/docker bring it up with the app.

Every 60s (configurable via env, default `POLL_INTERVAL_SECONDS=60`):

1. For each repo in `POLL_REPOS` (comma list, pattern
   `26457513/{project}`): `GET /repos/{repo}/actions/runs?per_page=10`,
   filter workflow name `assurance-scan` — successful AND failed runs
   (failures ingest as failed runs; see §3).
2. Skip runs already ingested — CI runs use `run_id = "gh-{github_run_id}"`,
   so idempotency is a PK lookup, no new state.
3. For each new run (newest first): fetch run metadata (branch, head SHA,
   timestamps, URL) → find the `assurance-scan-results` artifact → download
   zip (token-authed redirect) → read `findings.json`, `assurance.sarif`,
   `sbom.cyclonedx.json` → ingest all three (§3).
4. Ingest; one repo's failure never aborts the cycle.

Conditional requests (ETag) on the runs listing keep the rate-limit
footprint near zero even at 60s.

### 3. Ingest mapping (no migrations)

| GitHub | DB |
|---|---|
| repo full name | `Run.project_path = "github:{owner}/{repo}"` — auto-registers in the projects registry (derived view), visually distinct from local paths |
| run id | `Run.run_id = "gh-{id}"` |
| branch / head SHA / timestamps / URL | `Run.git_branch`, `commit_sha`, `started_at`, `completed_at`, `options_json.run_url` |
| `scanner_status` map | one `ScannerRun` row per scanner (completed/failed) — the run detail UI then renders CI runs like local ones |
| `findings[]` | `Finding` rows via the existing `FindingRepository.bulk_insert` |
| whole payload | `Run.findings_json` (same convention as orchestrator `mark_completed`) |
| run conclusion `failure` | `Run.status = "failed"` + `error_message` from GitHub (no findings to insert) |
| — | `ScanJob` row created in the run's final state |
| SARIF + SBOM blobs | `ScannerArtifact` rows (kinds `sarif`, `cyclonedx-json`) under a synthetic `ScannerRun` of kind `assurance-scan` — reuses existing storage, no migration. Future phases present these in the UI and let agents query them. |

### 4. On-demand poll (the button)

- `POST /api/poller/poll-now` — triggers one poll cycle immediately,
  returns the cycle result (runs seen / ingested / skipped).
- Frontend (scans page): a refresh-style button — scanning now happens on
  GitHub, so this is "refresh results from GitHub".
- Banner (scans page): when a project's latest run is `failed`, show a
  banner naming the project and linking to the run for investigation.

### 5. Auth + config (server-side env, never in any repo)

| Env | Value |
|---|---|
| `POLL_REPOS` | `26457513/doc2context` |
| `POLL_INTERVAL_SECONDS` | `60` |
| `GITHUB_POLL_TOKEN` | fine-grained PAT: Actions **Read** + Contents Read, scoped to the org's repos — note the existing `ASSURANCE_SCAN_TOKEN` is Contents-only and will NOT work |

## Verification

1. Unit: payload → ingest mapping (fixtures for findings.json; assert run +
   findings + scanner_runs rows and idempotent re-ingest of same run id).
2. Local end-to-end: run poller against doc2context's real history → CI
   runs appear in the UI with branch/commit; poll again → zero duplicates.
3. Button: click → immediate cycle reflected in scans list.

## Decisions (resolved at review, 2026-08-18)

1. Repos config: env list, pattern `POLL_REPOS=26457513/{project}`.
2. Poll-now button lives on the **scans page**.
3. SARIF + SBOM blobs **are stored** (ScannerArtifact rows) — a future
   phase presents them in the UI and exposes them to agent queries.
4. Failed workflow runs **are ingested** as failed runs, and the scans
   page shows a banner when a project's latest run failed.
