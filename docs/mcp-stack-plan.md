# Assurance Scan — MCP Stack Plan

**Status:** Draft v3 — 2026-08-06 (design converging)
**Supersedes:** `docs/archive/FRONTEND_DESIGN.md`, `docs/archive/FR_TRACEABILITY_PIVOT.md`
**Replaces:** v1 and v2 of this plan

> **What changed in v3:**
> - **DB-only storage.** Scanner findings, evidence, raw artifacts, curated outputs — all in SQLite. No file-based reports.
> - **Server-invoked-from-project-folder.** Reuses `run-local.sh`'s `$PWD:$PWD` mount trick. Eliminates the path-translation problem.
> - **One canonical approach.** No backward compatibility with the file-based CLI mode. One way to scan, one way to query, one way to storage.
> - **Resolved the remaining 4 open items:** config-file sync, TBT migration, state recompute triggers, evidence-to-spec matching.

---

## 1. Vision

A single-user, locally-running assurance service that:

1. Loads a project **Functional Requirements catalogue** (JSON, supplied by the user, source-controlled in the project repo).
2. Runs best-in-breed scan tools (Semgrep, Trivy, Grype, Syft, osv-scanner, ZAP, testssl, ClamAV) plus the project's own unit/integration/e2e tests.
3. Stores all scanner output, normalized findings, evidence, and computed state in SQLite.
4. Exposes everything through:
   - An **MCP-over-HTTP (Streamable HTTP)** endpoint that an AI agent (Claude Code, Cursor) calls as tools.
   - A **REST API** that the web frontend and external scripts use.
   - A **web UI** (SvelteKit app) for human review.
5. The agent reads findings, investigates code with its own tools, presents a recommended-fixes table in chat, the user approves, the agent applies fixes via its own Edit/Write tools, and re-scans to verify.

Packaged as a **single Docker image**. Started from the project folder. Browser at `http://localhost:8000`. MCP at `http://localhost:8000/mcp`. All persistent state in `$HOME/.assurance-scan/db.sqlite`.

---

## 2. Design principles

1. **Single image, single process.** SQLite + asyncio worker + uvicorn serving FastAPI + bundled SvelteKit frontend.
2. **DB-only storage.** Scanner output, findings, evidence, computed state — all in SQLite. Project folder is read-only. Nothing written to the user's repo (no `.assurance-scan/` directory, no gitignore management).
3. **One canonical approach.** The server is the only way to run scans. No file-based CLI fallback. No dual storage paths. No backward compatibility with v1 file-based reports.
4. **Server is invoked from the project folder.** Reuses the existing `$PWD:$PWD` mount trick. No path translation.
5. **The server is deterministic.** All LLM-driven reasoning happens in the agent that calls the MCP tools, not in the server. The server runs scanners, stores findings, computes state, exposes APIs.
6. **Project-declared config files live in the project repo.** FR catalogue, mapping pack, `assurance-tests.json` are source-controlled artifacts the server reads via bind mount. Catalogue path is supplied per-scan via flag, defaulting to `./fr-catalog.json`. No file watcher — the catalogue is re-read at the start of each scan, so edits naturally take effect on the next scan.
7. **No static dashboard generation.** The web UI reads live from the DB via REST/SSE. No `dashboard.html` is produced. (Drops `scripts/generate_dashboard.py`.)
8. **Schemas versioned.** v2 catalogue schema. v1 catalogues migrated on first scan against a project.

---

## 3. Model: TBT is a state, not an entity

The current design treats `TBT-*` (Test Basis Thing) as a first-class entity alongside `FR-*`. This conflates two things: an FR is a real entity; "to-be-tested" is a state an FR passes through.

**Drop TBT as an entity.** FRs have a lifecycle state. Evidence attaches directly to FRs.

```
Old:    FR  →  TBT  →  Evidence        (three entities)
New:    FR  →  Evidence                 (FR has a state field)
```

### FR lifecycle states (8)

Each FR is in exactly one state, computed from evidence in the latest run + standing waivers + dependency graph.

| State | Meaning |
|---|---|
| `untested` | No evidence, no required_evidence defined. |
| `to-be-tested` | required_evidence defined, no evidence collected. |
| `has-evidence` | Some evidence collected, sufficiency not yet evaluated. |
| `passed` | All required_evidence satisfied, no failures. |
| `failed` | Required evidence present, ≥1 result is `fail`. |
| `manual-review` | Conflict: same spec has both pass and fail results. |
| `waived` | Standing waiver exists (with reason, reviewer, date). |
| `blocked` | Depends on an FR not in `{passed, waived}`. |

### State precedence (mutual exclusivity)

States are evaluated top-down; first match wins:

```
waived
blocked        (any dep not in {passed, waived})
manual-review  (conflict within a single spec)
failed         (sufficient evidence, ≥1 fail)
passed         (sufficient evidence, all pass)
has-evidence   (some evidence, required_evidence not satisfied)
to-be-tested   (required_evidence defined, no evidence)
untested       (no required_evidence, no evidence)
```

### Computation

- **Scope:** latest run only. Past evidence visible on FR detail page but does not affect current state.
- **Trigger:** synchronous recompute within the same transaction as the triggering change (evidence insert, waiver change, catalogue change). If recompute fails, transaction rolls back and old state is preserved.
- **Blast radius:** recompute the directly-affected FR **plus transitive `depends_on` dependents** (because `blocked` state depends on upstream FRs). Cycle detection at catalogue load prevents infinite recursion.
- **Background safety net:** daily job recomputes all FRs in case of any drift.
- **Circular dependencies:** detected at catalogue load time; load fails with a clear error.

---

## 4. Model: Evidence

### Evidence types

| Type | Source | Examples |
|---|---|---|
| `scanner-result` | Best-in-breed scanner | Semgrep, Trivy, Grype, Syft, osv-scanner, ZAP, testssl, ClamAV |
| `unit-test` | Project unit tests | pytest, jest, go test |
| `integration-test` | Project integration tests | |
| `e2e-test` | Project end-to-end | Playwright, Cypress |
| `manual-attestation` | Human assertion | |
| `imported` | External test runner | JUnit XML, SARIF dropped in by user |
| `generated` | Assurance-scan-generated test | Created by agent to fill a gap |
| `proof-bundle` | Cryptographically signed | Existing format, retained |

### Typing rule

- **Type** = what the evidence semantically is.
- **Source** = how it got here (`worker-run`, `external-run`, `user-attested`).

Same Semgrep SARIF produced by the worker is `{type: scanner-result, source.kind: semgrep, source.run_kind: worker-run}`; the same SARIF dropped in by a user is `{source.run_kind: external-run}`.

### Evidence record shape

```json
{
  "id": "EV-20260806T101500Z-a1b2c3d4",
  "fr_id": "FR-SESSION-001",
  "type": "scanner-result",
  "source": {
    "kind": "semgrep",
    "rule_id": "python.lang.security.audit.session-timeout.A001",
    "scanner_version": "1.85.0",
    "run_kind": "worker-run",
    "run_id": "20260806T101500Z_3e675e29"
  },
  "result": "pass",
  "artifact_ref": "scanner_artifacts.id=42",          // ref to BLOB table
  "artifact_hash": "sha256:...",
  "collected_at": "2026-08-06T10:15:00Z",
  "confidence": 0.95,
  "notes": null
}
```

`result`: `pass | fail | info | manual`.

### FR catalogue v2 — required evidence per FR

```json
{
  "schema_version": 2,
  "project": "tapestry-mono",
  "catalogue_version": "2026-08-06T10:00:00Z",
  "frs": [
    {
      "id": "FR-SESSION-001",
      "title": "Session timeout after 15 minutes of inactivity",
      "description": "...",
      "implemented_by": [
        { "kind": "file", "ref": "src/auth/session.ts" }
      ],
      "required_evidence": {
        "all_of": [
          {
            "type": "unit-test",
            "name_pattern": "tests/auth/test_session.py::test_timeout_*",
            "expected_result": "pass"
          }
        ],
        "any_of": [
          {
            "type": "scanner-result",
            "source_kind": "semgrep",
            "rule_id": "python.lang.security.audit.session-timeout.A001",
            "expected_result": "pass"
          }
        ],
        "none_of": [
          {
            "type": "scanner-result",
            "source_kind": "semgrep",
            "rule_id": "python.lang.security.audit.no-session-timeout"
          }
        ]
      },
      "satisfies": ["ASVS:v5.0.0-5.1.1", "PCI:8.1.4"],
      "depends_on": []
    }
  ],
  "na_rows": []
}
```

### Sufficiency semantics

A spec is **satisfied** if at least one matching evidence record has `result == expected_result`. The FR's `required_evidence` is satisfied when:

- All entries in `all_of` are satisfied, AND
- At least one entry in `any_of` is satisfied (if non-empty), AND
- No entry in `none_of` has any matching evidence record.

**Conflict rule:** if any matching evidence record has `result == fail` while the spec's `expected_result` is `pass`, the spec is **conflicted** → FR is `manual-review`.

`info` results are informational — don't satisfy or conflict. `manual` requires human action — don't satisfy but don't conflict.

For v1: `all_of`, `any_of`, `none_of` cover the cases that matter. Richer rules (`at_least: N`, weights, freshness) deferred.

### Evidence-to-spec matching (concrete algorithm)

Python matching at compute time:

```python
def spec_matches_evidence(spec, evidence):
    if spec.type != evidence.type:
        return False
    if spec.type == "scanner-result":
        return (evidence.source.kind == spec.source_kind
                and evidence.source.rule_id == spec.rule_id)
    if spec.type in ("unit-test", "integration-test", "e2e-test"):
        # name_pattern is a glob (fnmatch) against the test's fully-qualified name
        # e.g. "tests/auth/test_session.py::TestSession::test_timeout_*"
        return fnmatch.fnmatchcase(evidence.source.test_name, spec.name_pattern)
    if spec.type == "manual-attestation":
        return True  # type-only match
    if spec.type == "imported":
        return evidence.source.format == spec.format
    return False
```

Test name format is fully-qualified: `<relative_path>::<ClassName>::<method_name>` for pytest-style, `<relative_path>::<test_name>` for jest-style. The JUnit XML parser produces this format from `classname` + `name` fields.

`confidence` is stored but not used in matching for v1.

### Project test discovery

Hybrid: convention + override.

**Override file:** `assurance-tests.json` in the project root:

```json
{
  "schema_version": 1,
  "tests": [
    {
      "id": "unit-pytest",
      "type": "unit-test",
      "command": ["pytest", "tests/", "--junit-xml=build/junit.xml"],
      "working_dir": ".",
      "env": {"CI": "1"},
      "result_parser": "junit-xml",
      "result_path": "build/junit.xml",
      "timeout_seconds": 300
    }
  ]
}
```

**Convention fallback** (if no `assurance-tests.json`):
- `package.json` `scripts.{test,test:unit,test:integration,test:e2e}`
- `pytest.ini` / `pyproject.toml` `[tool.pytest]` → `pytest --junit-xml=build/junit.xml`
- `go.mod` → `go test -v ./...` (parse stdout; no JUnit)
- `Makefile` targets `test-unit`, `test-integration`, `test-e2e`

For monorepos: nearest `assurance-tests.json` to the scan root wins. If none, conventional probe runs against the scan root only.

### Evidence-mapping pack

Maps evidence sources (scanner rules, test names) to FR IDs. Lives in the project repo alongside the catalogue:

```json
{
  "schema_version": 2,
  "mappings": [
    { "source": { "kind": "semgrep", "rule_id": "..." }, "fr_id": "FR-SESSION-001" },
    { "source": { "kind": "pytest", "name_pattern": "tests/auth/test_session.py::*" }, "fr_id": "FR-SESSION-001" }
  ]
}
```

### Compliance integration

`satisfies` is an array of strings referencing compliance rows: `"ASVS:v5.0.0-5.1.1"`. The server resolves these against the existing `data/frameworks/` snapshots (loaded at startup, cached in DB). UI shows compliance descriptions on hover.

### `findings.json` shape (agent-facing artifact)

Stored in `runs.findings_json`. Returned by the `get_findings` MCP tool. This is what the agent consumes to produce its recommended-fixes table.

```json
{
  "schema_version": 1,
  "run_id": "20260806T101500Z_3e675e29",
  "project": "tapestry-mono",
  "started_at": "2026-08-06T10:15:00Z",
  "completed_at": "2026-08-06T10:22:43Z",
  "scanner_status": {
    "semgrep": "completed",
    "trivy-fs": "completed",
    "grype": "completed",
    "gitleaks": "failed",
    "osv-scanner": "completed",
    "syft": "completed",
    "trivy-config": "completed"
  },
  "pr_strategy": "single",
  "summary": {
    "total": 47,
    "by_severity": {"CRITICAL": 3, "HIGH": 12, "MEDIUM": 24, "LOW": 8},
    "by_scanner": {"semgrep": 18, "trivy-fs": 14, "grype": 11, "osv-scanner": 4}
  },
  "findings": [
    {
      "id": "F-001",
      "scanner": "semgrep",
      "rule_id": "python.lang.security.audit.session-timeout.A001",
      "severity": "HIGH",
      "file_path": "src/auth/session.py",
      "line_start": 42,
      "line_end": 42,
      "message": "Session timeout not set; default is 0 (never expires).",
      "theme": "session-management",
      "fix_strategy": "single-file",
      "compliance_tags": ["ASVS:v5.0.0-5.1.1"],
      "fr_id": "FR-SESSION-001"
    }
  ]
}
```

Field semantics:
- **`scanner_status`**: per-scanner outcome. Failed scanners appear here so the agent knows what's missing.
- **`pr_strategy`**: `single` if all findings touch ≤ N distinct files (default N=15), else `themed`. Hints the agent on PR organization.
- **`theme`**: classification (e.g., `session-management`, `input-validation`, `secrets-leak`). Powers themed PRs.
- **`fix_strategy`**: `single-file` / `multi-file` / `config-only` / `dependency-update`. Hints the agent on the fix shape.
- **`fr_id`**: present when the finding maps to an FR via the mapping pack; absent otherwise.
- **`compliance_tags`**: derived from the FR's `satisfies` list when `fr_id` is set.

---

## 5. Architecture

Single Python process inside one container. Container is invoked from the project folder.

```
┌─────────────────────────────────────────────────────────────┐
│  Container: assurance-scan:latest                            │
│                                                              │
│  Started by user from project folder with:                   │
│    docker run -d \                                           │
│      -v "$PWD:$PWD" -w "$PWD" \                              │
│      -v /var/run/docker.sock:/var/run/docker.sock \          │
│      -v "$HOME/.assurance-scan:/data" \                      │
│      -p 127.0.0.1:8000:8000 \                                │
│      assurance-scan:latest                                   │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  uvicorn (one Python process)                      │     │
│  │  ├── FastAPI app                                   │     │
│  │  │   ├── /api/*         REST API                   │     │
│  │  │   ├── /mcp           MCP-over-HTTP (Streamable)  │     │
│  │  │   ├── /              Serves SvelteKit app       │     │
│  │  │   └── /health        Health check (no auth)     │     │
│  │  ├── SQLite (WAL mode)  → /data/db.sqlite          │     │
│  │  ├── Scan worker        (asyncio + asyncio.subprocess) │
│  │  └── Alembic migrations                            │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
       │                              │
       │ docker.sock                  │ bind mount (read-only)
       ▼                              ▼
   host Docker daemon            $PWD (project, read-only)
       │
       │ worker spawns scanner containers using
       │ the same $PWD:$PWD mount trick — no path translation
       ▼
   scanner containers (Semgrep, Trivy, Grype, ZAP, etc.)
   write stdout to pipes the worker reads
```

### Worker → scanner-container path

When the worker spawns a scanner container, it passes `$PWD` verbatim as both the host path and container path. Scanner sees the project at the same path the server does, the same path the user does. No translation.

Scanner output is captured via stdout pipe (for tools that support stdout) or via tmpfs mount (for tools that demand a writable file path — ZAP, ClamAV). The worker reads the output, inserts raw bytes into `scanner_artifacts`, parses findings into the `findings` table.

### Worker concurrency

`asyncio.subprocess` to spawn scanner containers. `asyncio.Semaphore` to bound concurrency (default 4 scanners in parallel). One active scan at a time per server (additional scans queued).

### Worker → scanner invocation strategy

For v1, the worker **wraps `docker-compose.security.yml`** rather than reimplementing each scanner's invocation in Python. The compose file is already 250+ lines of carefully-tuned per-scanner config (volume mounts, env vars, commands, working dirs, platform quirks like `linux/amd64` for ClamAV). Rewriting all of that in Python is real work with real edge cases.

The worker invokes scanners via `docker compose run --rm <service>`, captures stdout/stderr, and inserts results into the DB. The compose services are unchanged — they still write to bind-mounted `/reports/` paths; the worker reads the output files before the container exits and inserts content as BLOBs.

Migration path: in a later phase, if usage demands it, replace the compose wrap with native Python invocation per scanner. The DB schema and MCP tool surface don't change.

### Scanner cache volumes

Scanner DBs persist across scans via Docker named volumes, identical to today's setup:

| Volume | Used by | Path inside scanner container |
|---|---|---|
| `assurance-trivy-cache` | trivy-fs, trivy-config, trivy-image | `/root/.cache/` |
| `assurance-grype-db` | grype, grype-image | `/.cache/grype` |
| `assurance-osv-scanner-db` | osv-scanner | `/root/.cache/osv-scanner` |
| `assurance-clamav-db` | clamav | `/var/lib/clamav` |

The `assurance-` prefix avoids collisions with any user-named volumes. Worker creates them on first scan if absent. Prefetch subcommand seeds them ahead of time.

### Catalogue and config resolution

- **FR catalogue:** supplied per-scan via the `fr_catalog_path` option on `start_scan`. Defaults to `./fr-catalog.json` (relative to `$PWD`). Re-read fresh at the start of each scan — no caching, no file watcher.
- **Evidence-mapping pack:** supplied per-scan via `mapping_pack_path`. Defaults to `./evidence-mapping-pack.json`. Re-read each scan.
- **`assurance-tests.json`:** discovered per-scan. Convention fallback (package.json scripts, pytest config, etc.) applies if the file is absent.
- **Scanner failures:** every scanner outcome is recorded in `scanner_runs` (`status`, `error_message`). A failing scanner does not fail the run; the run completes with whatever scanners succeeded.

### Scanner inventory

| Group | Scanners | Trigger |
|---|---|---|
| Code (always) | Semgrep, Gitleaks, Trivy FS, Trivy Config, Syft, Grype, osv-scanner | every scan |
| Image (conditional) | Trivy image, Syft image, Grype image | `images` array on `start_scan` |
| URL (conditional) | ZAP baseline, testssl, security-headers | `urls` array on `start_scan` |
| Upload (conditional) | ClamAV | `uploads` array on `start_scan` |

Image scanners require images to be present in the host Docker daemon. The worker does not auto-build images from Dockerfiles in v1 — that's deferred to a later phase.

---

## 6. SQLite schema

### Core tables

```sql
schema_migrations (version, applied_at)
projects (id, name, host_path, fr_catalog_path, mapping_pack_path, assurance_tests_path, created_at, active_catalogue_snapshot_id)
catalogue_snapshots (id, project_id, snapshot_json, catalogue_version, created_at)
frs (id, project_id, fr_id, catalogue_snapshot_id, title, description, implemented_by_json, required_evidence_json, satisfies_json, depends_on_json)
runs (id, project_id, run_id, catalogue_snapshot_id, started_at, completed_at, status, scanner_status_json, commit_sha, options_json,
      findings_json, evidence_bundle_json, dashboard_payload_json)
scan_jobs (id, run_id, state, queued_at, started_at, completed_at, error_message)
scanner_runs (id, run_id, scanner_kind, status, started_at, completed_at, error_message, artifact_id)
scanner_artifacts (id, scanner_run_id, kind, content_blob, content_hash, size_bytes, created_at)
findings (id, run_id, scanner_kind, rule_id, severity, file_path, line_start, line_end, message, theme, fix_strategy, compliance_tags_json, raw_index, created_at)
evidence (id, project_id, fr_id, run_id, type, source_json, result, artifact_ref, artifact_hash, collected_at, confidence, notes)
fr_state (project_id, fr_id, run_id, state, computed_at, reason_json)
waivers (id, project_id, fr_id, reason, waived_by, waived_at, expires_at)
agent_actions (id, project_id, run_id, action_kind, actor, payload_json, occurred_at)  -- audit log of MCP/API calls that mutate state
```

### Key columns

- `runs.findings_json` — the rendered findings.json content (what `get_findings` MCP tool returns).
- `runs.evidence_bundle_json` — the evidence bundle.
- `runs.dashboard_payload_json` — the dashboard payload (used by the SvelteKit UI).
- `scanner_artifacts.content_blob` — gzip-compressed raw scanner output.
- `scanner_runs.status` and `scanner_runs.error_message` — per-scanner outcome; failures recorded, not discarded.
- `evidence.artifact_ref` — references `scanner_artifacts.id` (or null if manual).

### Migration system

Alembic from day one. Every schema change ships with a migration. Service refuses to start if DB is ahead of code's latest migration.

### Size management

- Typical scan: 5–20 MB compressed (raw SARIF/JSON + findings rows).
- Prune command: `DELETE FROM runs WHERE completed_at < ?` cascades to findings, evidence, scanner_artifacts.
- WAL mode + `PRAGMA journal_mode = WAL` for concurrent read during writes.

---

## 7. Auth & security

Single-user, localhost-only.

1. **Bind to `127.0.0.1` only.** Container port published as `127.0.0.1:8000:8000`. Remote access blocked at the bind layer.
2. **No token in v1.** Localhost binding is sufficient for single-user. (Revisit if multi-user ever added.)
3. **`GET /health` is the only unauthenticated endpoint.** Returns DB + worker + docker-socket status.
4. **Docker socket trust.** Same model as today's image: full socket access. Single-user, local, accepted risk.
5. **Filesystem access.** Container reads `$PWD` (read-only by scanner containers) and writes `/data`. No other host paths.

---

## 8. MCP tool surface

Nine tools, exposed over MCP Streamable HTTP transport. Stateless per call.

| Tool | Purpose |
|---|---|
| `load_fr_catalog` | Validate the catalogue (and mapping pack). Returns FRs with current states. Useful for the agent to confirm the catalogue is well-formed before scanning. |
| `start_scan` | Start a scan. Accepts options: `fr_catalog_path` (default `./fr-catalog.json`), `mapping_pack_path`, `images`, `urls`, `uploads`. Returns `run_id` immediately. Scan runs async. |
| `get_scan_status` | Poll: state, % complete, scanners done, partial findings. |
| `cancel_scan` | Cancel a running scan. Idempotent. |
| `list_scans` | List runs (paginated). |
| `get_findings` | Return the findings.json content for a run. Filterable by `?fr_id=`, `?severity=`. |
| `get_gap_analysis` | FRs in `to-be-tested`, `untested`, `failed`, `manual-review` state with reasons. |
| `add_waiver` | Create a standing waiver for an FR. |
| `revoke_waiver` | Revoke a waiver by ID. |

### What's NOT in the MCP surface (deliberately)

- **Catalogue edits.** Source-controlled artifact. Edit the file, save — the next `start_scan` call picks up the new version automatically (no cache, no watcher). `load_fr_catalog` re-validates without scanning.
- **Proposal generation/apply.** The agent does this naturally in chat using its own Edit/Write tools. No server-side proposal abstraction needed for the agent loop.
- **Direct code modification.** Server never writes to `$PWD`. The agent does that with its own tools.
- **Project management.** Project is implicit (set at container start). No `add_project` / `list_projects`.
- **Scanner DB management.** Auto-refresh every 24h. No MCP tool.

### The agent loop

```
agent: load_fr_catalog      → confirm catalogue loaded, see current state
agent: start_scan           → run_id
agent: get_scan_status      → poll until complete
agent: get_findings         → findings.json
agent: (uses own Read/Grep to investigate code)
agent: presents recommended-fixes table in chat
user:  reviews, approves (in chat)
agent: (uses own Edit/Write to apply fixes; batches if many)
agent: start_scan           → re-scan to verify
agent: get_findings         → confirm fixes landed
```

The server has zero awareness of "proposals" or "fixes." It just runs scanners, stores findings, exposes them. The agent reasons about fixes in its own context.

### Approval model: agent-driven, in-chat (locked)

**Decision:** the human-approval step happens in the agent's chat — Claude Code, Cursor, or whatever client the user is running. The user reviews the agent's recommended-fixes table as a normal chat message, replies with approval (or edits, or rejects), and the agent proceeds to apply fixes via its own Edit/Write tools.

**Why this and not a server-side approval flow:**
- Matches how agents naturally work today. No new UX to learn.
- No server-side state for "pending proposals" — keeps the server dumb and the DB simple.
- Approval history lives in the agent client's transcript, which is already where the user looks.
- Multi-reviewer approval (if ever needed) becomes a future v2 concern, not a v1 design constraint.

**What this means for the server:**
- No `propose_fixes`, `review_proposal`, `apply_proposal_selections` tools.
- No `proposals` or `proposal_selections` tables.
- The `agent_actions` audit log records state-mutating MCP/API calls (start_scan, add_waiver, etc.) for traceability — but the agent's reasoning and the user's approval are not in the server.
- The web UI shows scan history, findings, evidence, FR state. It does not show "pending proposals" because there's no such concept.

If the user wants to revisit this decision later (e.g., add a server-side review queue for high-stakes environments), it's a clean additive change — new tables, new MCP tools, no rewrite.

---

## 9. REST API surface

Mirror of MCP tools, plus SSE and health.

- `GET  /health`
- `POST /api/reload-catalogue` — explicit re-validate (catalogue is always re-read on next scan anyway, but this lets the agent/UI force a check)
- `POST /api/scans` — start a scan
- `GET  /api/scans` — list runs
- `POST /api/scans/{run_id}/cancel`
- `GET  /api/scans/{run_id}` — status + summary
- `GET  /api/scans/{run_id}/stream` — SSE for live updates (Last-Event-ID for resume)
- `GET  /api/scans/{run_id}/findings` — findings JSON, filterable
- `GET  /api/scans/{run_id}/gaps` — gap analysis
- `GET  /api/scans/{run_id}/artifacts/{scanner}` — raw scanner output (decompresses BLOB)
- `GET  /api/frs/{fr_id}` — full per-FR detail (evidence, history across runs)
- `GET  /api/frs/{fr_id}/history` — state transitions over time
- `GET  /api/waivers` / `POST /api/waivers` / `DELETE /api/waivers/{id}`

### SSE resumption

Each event has a monotonic `id`. Server keeps an in-memory ring buffer (1000 events). On reconnect with `Last-Event-ID`, replays missed events. For older events, client falls back to `GET /api/scans/{run_id}` snapshot.

---

## 10. Frontend

**Stack:** SvelteKit + Tailwind. Built in Dockerfile via multi-stage; served as static files by FastAPI. Reads live from the DB via REST + SSE — no static HTML generation, no per-run snapshot files.

**Pages:**
- `/` — Scan history for the current project (server is project-scoped, so no project list needed)
- `/scans/{run_id}` — Live scan view (SSE-driven), per-FR drill-down
- `/frs/{fr_id}` — FR detail: required evidence, collected evidence, history across runs, audit chain
- `/compliance` — Per-framework view (ASVS, PCI, etc.) with traffic-light rows
- `/settings` — Catalogue path, mapping pack path, prune controls

**SSE auth:** Native EventSource doesn't support auth headers. Use `fetch` with `ReadableStream` (or `event-source-polyfill`). For v1 with no auth, plain EventSource works.

**Dev workflow:**
- Backend: `uvicorn server.app:app --reload --port 8000`
- Frontend: `npm run dev -- --port 5173` in `frontend/`, Vite proxy forwards `/api/*` to `localhost:8000`
- Both share the same SQLite DB

---

## 11. Build pipeline

```dockerfile
# Stage 1: build frontend
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM docker:29-cli

ARG COMPOSE_VERSION=v5.4.0

RUN apk upgrade --no-cache && apk add --no-cache \
    bash coreutils curl findutils gawk git grep sed tar \
    python3 py3-pip py3-jsonschema py3-yaml \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Python web stack in a virtualenv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements-server.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-server.txt
# Pins: fastapi, uvicorn[standard], mcp, pydantic, alembic, aiosqlite, sqlalchemy

WORKDIR /opt/assurance-scan

COPY --from=frontend /app/build /opt/assurance-scan/server/static
COPY . /opt/assurance-scan

RUN chmod +x /opt/assurance-scan/server/entrypoint.sh \
    && ln -s /opt/assurance-scan/server/entrypoint.sh /usr/local/bin/assurance-scan

ENTRYPOINT ["assurance-scan"]
CMD ["serve"]
```

**`requirements-server.txt`** is pinned and hashed. Image size budget: ~280 MB.

**Multi-arch: linux/amd64 + linux/arm64 from day one.** Matches the current image. The build pipeline uses `docker buildx build --platform linux/amd64,linux/arm64 --push`. Frontend build (node:22-alpine) and Python deps are both multi-arch. Compose plugin download already handles arch via `$(uname -m)`.

Entrypoint script handles `serve` (default — start uvicorn), `mcp-config` (print MCP config snippet), `export` (write findings to a path).

---

## 12. Migration from current codebase

This is a clean break, not a compatibility exercise. v1 file-based reports are not migrated; the DB starts empty.

### What's reused (importable, unmodified)

- `scripts/scanner_parsers.py` — parses scanner output
- `scripts/artifact_hashing.py` — SHA-256 hashing
- `scripts/assurance_claims.py`, `scripts/assurance_proof_bundles.py` — proof bundle format
- `scripts/process/` — per-scanner processor modules

### What's modified (domain logic changes)

- `scripts/load_fr_catalog.py` — v2 schema only. No v1 reader.
- `scripts/resolve-assurance-status.py` — replace FR+TBT state machine with the 8-state FR-only machine (§3). Precedence ladder, synchronous per-FR recompute.
- `scripts/generate-evidence-bundle.py` — drop `target_tbt`; align with v2 schema.
- `scripts/publish_findings.py` — switch from file-write to DB-insert. Reads scanner output (from `scanner_artifacts`), parses, inserts normalized findings + curated JSON columns. Drops all gitignore-management logic (no files written to repo anymore).

### What's new

- `server/` — FastAPI app, MCP endpoint, SQLite layer (SQLAlchemy + aiosqlite), Alembic migrations
- `server/worker.py` — asyncio worker
- `server/mcp.py` — MCP Streamable HTTP endpoint
- `server/project_tests.py` — test discovery
- `server/matching.py` — evidence-to-spec matching (§4)
- `frontend/` — SvelteKit app
- `data/schemas/fr-catalog.v2.schema.json`
- `data/schemas/evidence.v2.schema.json`
- `data/schemas/evidence-mapping-pack.v2.schema.json`

### What's removed

- All `bin/assurance-scan` subcommands except `serve`, `mcp-config`, `export`
- `scripts/run-local.sh` — replaced by the server worker (was already deprecated for service mode)
- `scripts/generate_dashboard.py` — no static HTML generation; the SvelteKit UI replaces it
- File-based report writing paths (`reports/`, `sbom/`, `hashes/` directory layouts)
- Gitignore-management logic in `publish_findings.py` — nothing written to repo
- `docker-compose.security.yml` — replaced by direct container orchestration in the worker

### What's deprecated (sunset)

- v1 catalogue format — replaced by v2 with one-shot migration on first scan against a project
- TBT entity type — migration rewrites to FR state

### v1 → v2 catalogue migration (concrete TBT semantics)

Run automatically on first `load_fr_catalog` against a project with a v1 catalogue. Idempotent.

**Strategy: collapse TBTs into their parent FRs.** TBTs were never real entities — they were just FRs in disguise. Migration makes that explicit by folding each TBT into its parent. No new entities are created unless the TBT is an orphan.

For each TBT in the v1 catalogue:

1. **If the TBT has a parent FR:** collapse into the parent.
   - **Required evidence:** flatten the TBT's `all_of` / `any_of` / `none_of` specs into the parent's corresponding lists. Dedupe at the spec level (same `{type, source_kind, rule_id}` or `{type, name_pattern}` only counts once).
   - **Evidence:** re-point every evidence record that targeted the TBT to the parent FR ID.
   - **Satisfies:** merge the TBT's compliance rows onto the parent FR's `satisfies` list (dedupe).
   - **Implemented_by:** merge the TBT's code references onto the parent FR's `implemented_by` list (dedupe).
   - **The TBT entity is dropped.** Its title/description are appended to the parent's description as `> Migrated from TBT-<id>: <title>` for traceability.

2. **If the TBT has no parent FR (orphan):** promote to a standalone FR.
   - The new FR keeps its original `TBT-*` id verbatim (no rename — preserves evidence references without a re-point step).
   - All TBT fields (title, description, required_evidence, satisfies, implemented_by) become FR fields unchanged.

3. **Resulting FRs start in `to-be-tested` state** (initial).

**Known limitation — `any_of` divergence:** if a TBT and its parent both have `any_of` blocks with different specs, flattening into a single `any_of` weakens the semantics (originally both blocks had to be satisfied independently; after merge, only one needs to be). For v1 this is accepted — in practice, parented TBTs almost always have overlapping or identical `any_of` specs with their parent. The migration report flags any TBT where the parent and TBT `any_of` specs diverge, so a human can review and tighten if needed.

Migration writes a v2 catalogue next to the v1 (e.g., `fr-catalog.v2.json`) and emits a JSON migration report listing: collapsed TBTs (with parent FR IDs), promoted orphans, evidence re-point counts, and any `any_of` divergence warnings. User reviews and commits the v2 file. Server then loads the v2 catalogue.

### Test updates

Each test file under `tests/` gets updated for v2 schemas:
- `test_config_update_workflow.py` — drop, this workflow is removed in v3
- `test_publish_findings.py` — rewrite for DB-insert flow
- `test_authority_ruleset_sync.py` — review; likely unchanged (about scanner rules)
- `test_lockfile_injection.py` — review; lockfile injection still applies
- `test_planning_studio_workflow.py` — drop, planning studio is removed in v3

---

## 13. Operations

### Start the server (the only user-facing command)

```bash
cd /path/to/my-project

docker run -d --name assurance-mcp \
  -v "$PWD:$PWD" -w "$PWD" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$HOME/.assurance-scan:/data" \
  -p 127.0.0.1:8000:8000 \
  --restart unless-stopped \
  assurance-scan:latest
```

Server runs forever. User interacts via browser, MCP, or REST.

### Stop / restart

```bash
docker stop assurance-mcp && docker rm assurance-mcp
# Re-run the start command to restart
```

### Switching projects

```bash
docker stop assurance-mcp && docker rm assurance-mcp
cd /path/to/another-project
docker run -d --name assurance-mcp ... assurance-scan:latest
```

The same `$HOME/.assurance-scan/db.sqlite` serves multiple projects over time (keyed by absolute project path).

### Backup

```bash
docker stop assurance-mcp
cp "$HOME/.assurance-scan/db.sqlite" "$HOME/.assurance-scan/db.sqlite.bak"
docker start assurance-mcp
```

Or use SQLite's online backup API for zero-downtime backups (Phase 2 polish).

### Logs

- Server logs to stdout (container logs via `docker logs assurance-mcp`). Structured JSON, rotated by Docker's logging driver.
- Per-scan logs (scanner stderr, worker messages): stored in DB (`scan_jobs.error_message`, `scanner_runs.error_message`) for queryability.

### Health check

`GET /health` returns DB + worker + docker-socket status. Container `HEALTHCHECK` uses it.

### Data retention

- Default: keep all runs.
- `POST /api/prune` with `older_than_days` and `keep_latest` per project.
- Pruned runs: cascade delete to findings, evidence, scanner_artifacts.

### Disk watermark

Worker checks `/data` disk usage before starting each scan. Above 90%, scan rejected with clear error. Below 80%, scans accepted. Between: warning logged.

### Image updates

```bash
docker pull namenottaken/assurance-scan:latest
docker stop assurance-mcp && docker rm assurance-mcp
# Re-run the start command — Alembic auto-migrates on first start of new version
```

`$HOME/.assurance-scan/db.sqlite` persists across image updates. If migration fails, container exits with error and DB is untouched.

### Resource limits

- `max_concurrent_scans`: 1 (additional scans queued)
- `max_concurrent_scanners`: 4 (env override `ASSURANCE_SCAN_PARALLELISM`)
- `max_concurrent_image_builds`: 2 (env override `ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM`)

---

## 14. Phasing

### Phase 0 — Architecture spike (~1 week)

Prove the architecture end-to-end with one scanner before scaling. Reduces risk of discovering architectural issues at week 4 of Phase 1.

- SQLite schema baseline (just `runs`, `scanner_runs`, `scanner_artifacts`, `findings`) + Alembic baseline migration
- FastAPI app with `POST /api/scans`, `GET /api/scans/{id}`, `GET /api/scans/{id}/findings`, `GET /health`
- Worker that runs **Semgrep only** via `docker compose run`, captures output, inserts BLOB + findings rows
- SvelteKit "hello world" page that lists scans and shows findings
- Single-Dockerfile multi-arch build (linux/amd64 + linux/arm64)

**Exit criterion:** running scan against a sample project produces findings in the DB, viewable in the browser. No MCP, no FR model, no UI polish. Just the storage + worker + minimal UI pipeline working end-to-end on both arches.

If Phase 0 surfaces architectural problems, fix them now while the surface area is small.

### Phase 1 — Service foundation (~5 weeks)

- FastAPI app + `/api/*`, `/mcp`, `/health`
- SQLite schema + Alembic baseline + migration system
- Worker: asyncio + `asyncio.subprocess` orchestrating scanner containers
- DB-only storage: scanner output → BLOB, normalized findings → rows, curated JSON → run columns
- Per-scan catalogue resolution (flag + `./fr-catalog.json` default)
- Project test discovery (convention + `assurance-tests.json`)
- FR catalogue v2 schema + `load_fr_catalog` v2 reader
- TBT→state migration in `resolve-assurance-status.py` + precedence + synchronous recompute
- v1→v2 catalogue migration command (automatic on first scan against a project)
- Scanner inventory per §5 (code scanners always; image/URL/uploads conditional)
- Per-scanner failure recording in `scanner_runs`
- MCP tool surface (9 tools from §8)
- SvelteKit scaffold + minimal pages: scan history, scan detail with live updates, FR detail — reading live from DB
- Agent prompt strategy doc (MCP-specific companion to existing `fix-assurance-findings.md`)
- Test updates for v2 schemas
- `serve`, `mcp-config`, `export` subcommands

**No dashboard.html generation.** SvelteKit UI is the only review surface.

**End of Phase 1:** working service, usable via SvelteKit UI + MCP, single image.

### Phase 2 — Real frontend (~3 weeks)

- FR drill-down with audit chain visualization
- Per-FR history across runs
- Trends / "what changed" view
- Compliance view per framework
- Settings page (catalogue paths, prune controls)
- Export download from scan page

**End of Phase 2:** product-grade web UI.

### Phase 3 — Polish (~2 weeks)

- In-browser diff views for code changes between runs
- Zero-downtime backup (SQLite online backup API)
- Run snapshot import/export (share a run's DB rows + artifacts as a single file — useful for handoffs without going multi-user)
- End-to-end agent test: scan → investigate → propose → apply → re-scan → confirm
- Documentation: agent loop walkthrough for Claude Code and Cursor

**End of Phase 3:** full vision delivered.

**Total: ~11 weeks** (1 + 5 + 3 + 2).

---

## 15. Open questions (mostly resolved in v3)

1. **Compliance framework UI.** Per-framework view in Phase 2 — confirm needed vs. per-FR is enough.
2. **Scanner database management in service mode.** Today's 24h auto-refresh: keep as-is (recommended), or surface as a setting?
3. **At-least-N / freshness rules in required_evidence.** Defer to v3 unless real usage demands.
4. **Catalogue snapshot retention policy.** Default never-prune, or auto-prune after N runs?
5. **Image auto-build from Dockerfiles.** Deferred to a later phase (v1 requires pre-built images for image scanners). Confirm acceptable.

---

## 16. Out of scope (for now)

- Multi-user / team deployments
- Remote scan targets (git clone into the worker)
- RBAC and per-user permissions
- Cloud-hosted edition
- Plugin SDK for custom scanners
- Real-time collaboration (multiple users reviewing one proposal)
- Cross-project aggregation / portfolio view
- Stale-evidence freshness rules
- Auto-rollback of applied changes (manual rollback via DB restore only)
- Backward compatibility with v1 file-based CLI mode
- Server-side approval workflow for agent-proposed fixes (handled by the agent in chat — see §8)

---

## 17. Glossary

| Term | Meaning |
|---|---|
| **FR** | Functional Requirement. Central entity. |
| **FR catalogue** | JSON file in the project repo declaring FRs, each with required evidence and compliance links. v2 schema. |
| **Catalogue snapshot** | Immutable per-load copy of the FR catalogue, FK'd from every run that used it. |
| **Evidence** | Typed artifact supporting an FR. Has type, source, result, hash. |
| **Evidence-mapping-pack** | File mapping evidence sources to FR IDs. Lives in project repo. |
| **FR state** | One of 8 lifecycle states (§3). Computed from latest-run evidence + waivers + deps. |
| **Run** | One scan execution. |
| **Scan job** | State-machine record for a run: `queued | running | completed | failed | cancelled`. |
| **Scanner artifact** | Raw scanner output (SARIF, JSON) stored as gzip BLOB in DB. |
| **Finding** | Normalized per-issue row extracted from scanner output. |
| **Waiver** | Standing record that overrides FR state to `waived`. |
| **Worker** | Asyncio task within uvicorn that orchestrates scanner containers and project tests. |

---

## Next steps

- [ ] Review this v3 plan
- [ ] Confirm or override decisions (call out any to revisit)
- [ ] Resolve the 5 remaining open questions in §15
- [ ] Decide Phase 1 start date
- [ ] Scaffold `server/` and `frontend/` directories
- [ ] Write `data/schemas/fr-catalog.v2.schema.json`
- [ ] Write Alembic baseline migration
