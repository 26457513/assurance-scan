# Agent Loop Walkthrough

**Audience:** developers setting up an AI agent (Claude Code, Cursor, or any MCP-compatible client) to drive Assurance Scan.

This doc walks through the canonical workflow end-to-end: configure MCP, trigger a scan, poll for completion, fetch findings, investigate code, propose fixes in chat, apply, re-scan to verify.

---

## 1. Prerequisites

1. **Docker Desktop** running on the host.
2. **Assurance Scan image** pulled:
   ```bash
   docker pull namenottaken/assurance-scan:latest
   ```
3. **An FR catalogue** at `<your-project>/fr-catalog.json` (schema v2 — see `data/schemas/fr-catalog.v2.schema.json`).
4. **A mapping pack** (optional) at `<your-project>/evidence-mapping-pack.json` if your scanner rule IDs need explicit FR associations.

---

## 2. Start the service

From your project folder:

```bash
cd /path/to/my-project

docker run -d --name assurance-scan \
  -v "$PWD:$PWD" -w "$PWD" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$HOME/.assurance-scan:/data" \
  -p 127.0.0.1:8000:8000 \
  --restart unless-stopped \
  namenottaken/assurance-scan:latest
```

The server is now running on `http://127.0.0.1:8000`. Browse to it to verify.

If you'll use scanners that need DBs (Trivy, Grype, osv-scanner, ClamAV), prefetch once:

```bash
docker exec assurance-scan assurance-scan prefetch
```

This populates the named cache volumes. Takes a few minutes; runs once.

---

## 3. Configure your agent

### Claude Code

`~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "assurance-scan": {
      "transport": {
        "type": "streamable_http",
        "url": "http://127.0.0.1:8000/mcp"
      }
    }
  }
}
```

Or via CLI:

```bash
claude mcp add assurance-scan --transport http http://127.0.0.1:8000/mcp
```

### Cursor

In Settings → MCP Servers, add:

```json
{
  "assurance-scan": {
    "url": "http://127.0.0.1:8000/mcp"
  }
}
```

---

## 4. The canonical agent loop

Open a chat in your agent and prompt:

> Run an assurance scan on the current project, then list the gaps and propose fixes.

The agent will execute this sequence (no further prompting needed until review):

### 4.1 Validate catalogue
```python
# Tool call
load_fr_catalog(fr_catalog_path="./fr-catalog.json")
```
Returns fr_count, content_hash. If it errors, the catalogue is malformed — fix before scanning.

### 4.2 Trigger scan
```python
start_scan(
    fr_catalog_path="./fr-catalog.json",
    mapping_pack_path="./evidence-mapping-pack.json"
)
# → {"run_id": "20260807T...", "status": "queued"}
```

### 4.3 Poll until complete
```python
get_scan_status(run_id="<the-run-id>")
# Repeat every ~10s until status == "completed"
```
While polling, the SSE stream at `/api/scans/{run_id}/stream` emits `scanner_started` and `scanner_completed` events — useful if you build a custom UI.

### 4.4 Read findings
```python
get_findings(run_id="<the-run-id>")
# Returns the agent-facing findings.json payload:
# {
#   "schema_version": 1,
#   "run_id": "...",
#   "scanner_status": {"semgrep": "completed", "gitleaks": "failed", ...},
#   "summary": {"total": 47, "by_severity": {"HIGH": 12, ...}, "by_scanner": {...}},
#   "pr_strategy": "single" | "themed",
#   "findings": [
#     {
#       "id": "F-001",
#       "scanner": "semgrep",
#       "rule_id": "...",
#       "severity": "HIGH",
#       "file_path": "src/auth/session.py",
#       "line_start": 42,
#       "message": "...",
#       "theme": "...",
#       "fix_strategy": "single-file",
#       "compliance_tags": ["ASVS:v5.0.0-5.1.1"],
#       "fr_id": "FR-SESSION-001"
#     },
#     ...
#   ]
# }
```

### 4.5 Read gap analysis
```python
get_gap_analysis(run_id="<the-run-id>")
# Returns FRs in untested | to-be-tested | failed | manual-review | blocked
# state, each with a reason dict explaining why.
```

### 4.6 Investigate code
The agent uses its own Read / Grep tools to inspect the files mentioned in findings. The server doesn't participate — it has no code-reading tools.

### 4.7 Propose fixes
The agent presents a table in chat. Example:

```
| Finding                                    | Severity | File                                | Suggested fix                                                       |
|--------------------------------------------|----------|-------------------------------------|---------------------------------------------------------------------|
| Session timeout not set                    | HIGH     | src/auth/session.ts:42              | Add `timeout: 900_000` to session config                            |
| Hardcoded AWS key in config.py             | CRITICAL | src/config.py:8                     | Move to env var `AWS_ACCESS_KEY_ID`, rotate immediately             |
| eval() in expression evaluator             | HIGH     | src/calc.py:23                      | Replace with `ast.literal_eval` or dedicated parser                 |
| ...
```

### 4.8 User review
The user reads the table, replies with approval (or partial approval / edits / rejections). No server interaction — approval happens in chat.

### 4.9 Apply fixes
The agent uses its own Edit / Write tools to modify code. If there are many fixes (> 15 by default — `pr_strategy` is `themed`), the agent should batch them logically.

### 4.10 Re-scan to verify
```python
start_scan(fr_catalog_path="./fr-catalog.json", mapping_pack_path="./evidence-mapping-pack.json")
# Poll, then:
get_gap_analysis(run_id="<the-new-run-id>")
# Confirm: previously-failed FRs are now 'passed'
```

---

## 5. Managing waivers

Some FRs can't or shouldn't be fixed immediately. The agent can waive them:

```python
add_waiver(
    fr_id="FR-SOME-LEGACY-THING",
    reason="Legacy API being deprecated in Q4 — accepted risk until then.",
    waived_by="alice",
    expires_at="2026-12-31T00:00:00Z"  # optional
)
```

Waived FRs drop out of the gap analysis on subsequent scans. Revoke with `revoke_waiver(waiver_id=...)` when the issue is eventually resolved.

---

## 6. Operational notes

- **Concurrency:** one scan at a time per server. Multiple scans queue.
- **Per-scanner failures are recorded but don't fail the run.** If Gitleaks crashes, Semgrep still runs and the scan completes. The `scanner_status` field on the scan shows per-scanner state.
- **Catalogue edits:** just save the file. The next `start_scan` picks up the new version automatically — no reload command needed.
- **Persistent state:** everything lives in `$HOME/.assurance-scan/db.sqlite`. Back it up with `docker stop assurance-scan && cp ~/.assurance-scan/db.sqlite ~/.assurance-scan/db.sqlite.bak && docker start assurance-scan`.
- **Image updates:** `docker pull && docker stop && docker rm && docker run` (same start command). Alembic auto-migrates the DB on first start.

---

## 7. MCP tool reference

| Tool | Purpose |
|---|---|
| `load_fr_catalog` | Validate catalogue (and optional mapping pack). |
| `start_scan` | Enqueue a scan. Returns `run_id` immediately. |
| `get_scan_status` | Poll scan state + per-scanner status. |
| `cancel_scan` | Cancel a queued/running scan. Idempotent. |
| `list_scans` | List recent runs. |
| `get_findings` | Returns the agent-facing findings.json payload. Filterable by severity. |
| `get_gap_analysis` | FRs in `untested | to-be-tested | failed | manual-review | blocked` with reasons. |
| `add_waiver` | Create a standing waiver for an FR. |
| `revoke_waiver` | Revoke a waiver by ID. |

The server has no concept of "proposals" or "approvals" — those happen entirely in the agent's chat. The server is deterministic; the agent does the reasoning.

---

## 8. Sample catalogue (v2)

```json
{
  "schema_version": 2,
  "project": "my-app",
  "catalogue_version": "2026-08-07T00:00:00Z",
  "frs": [
    {
      "id": "FR-NO-SECRET-IN-SRC",
      "title": "No secrets in source",
      "description": "Source files must not contain hardcoded credentials.",
      "required_evidence": {
        "none_of": [
          {
            "type": "scanner-result",
            "source_kind": "gitleaks",
            "rule_id": "aws-access-key"
          },
          {
            "type": "scanner-result",
            "source_kind": "gitleaks",
            "rule_id": "github-pat"
          }
        ]
      },
      "satisfies": ["ASVS:v5.0.0-2.10.4"]
    },
    {
      "id": "FR-SESSION-TIMEOUT",
      "title": "Session timeout at 15 minutes",
      "description": "Sessions must expire after 15 minutes of inactivity.",
      "implemented_by": [{"kind": "file", "ref": "src/auth/session.ts"}],
      "required_evidence": {
        "all_of": [
          {
            "type": "unit-test",
            "name_pattern": "tests/auth/test_session.py::test_*timeout*",
            "expected_result": "pass"
          }
        ],
        "any_of": [
          {
            "type": "scanner-result",
            "source_kind": "trivy-config",
            "rule_id": "AWS-SessionTimeout-15min",
            "expected_result": "pass"
          }
        ]
      },
      "satisfies": ["ASVS:v5.0.0-5.1.1", "PCI:8.1.4"]
    }
  ],
  "na_rows": []
}
```

---

## 9. Troubleshooting

**`load_fr_catalog` returns validation error.** The catalogue is malformed against `fr-catalog.v2.schema.json`. The error message names the failing field. Fix and retry.

**Scanners show as `failed` in scan status.** Look at `error_message`. Common causes:
- Scanner DB missing → run `prefetch` (see §2).
- Scanner image can't be pulled → check Docker Hub access.
- Project path not readable → confirm `$PWD` is mounted correctly.

**`get_findings` returns `not_ready`.** Scan hasn't published findings yet. Poll `get_scan_status` until `status == "completed"`.

**No FRs in `get_gap_analysis`.** Either the catalogue loaded has zero FRs, or every FR is in a non-gap state (`passed` / `waived` / `has-evidence`).

**MCP client can't connect.** Server isn't running, or the bind address is wrong. Verify `docker ps` shows the container and `curl http://127.0.0.1:8000/health` returns `{"status":"ok",...}`.
