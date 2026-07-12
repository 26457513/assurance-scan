# Pivot: Functional-Requirement-Driven Traceability

## Status

**Draft.** Proposed pivot from the current scanner-driven Compliance Matrix (Phase 2, shipped) to a requirements-driven traceability platform with compliance as one view. This doc supersedes the long-term vision in [ASVS_TRACEABILITY_PLAN.md](ASVS_TRACEABILITY_PLAN.md) — the existing plan remains valid as the migration path for what we've already built.

**Doc structure** (use this map to navigate — doc is intentionally one file rather than split, to keep the contract closed):

| Section cluster | What's there |
|---|---|
| **Meta** (Status, Glossary, Context, Vision, Phased scope, Risks, Decisions) | Why we're pivoting, what we're building, in what order |
| **Data model** (FR JSON schema, Evidence resolution, Multi-framework loaders, Code mapping, Test integration, Scanner integration) | What the data looks like |
| **Contracts** (Dashboard input payload, Scan history retention, Derived indices, CI workflow, Fixture scan spec) | The bridge between backend and frontend |
| **Migration** (Migration path, Critical files) | What changes from current code |

For frontend UX details, see [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md). For schema rationale, see [FRAMEWORK_COMPARISON.md](FRAMEWORK_COMPARISON.md) (historical).

## Glossary

Terms used across this doc and [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md). New contributors should read this first.

| Term | Meaning |
|---|---|
| **FR** | Functional Requirement. The central abstraction. Project-defined, lives in `fr-catalog.json`. |
| **FR catalog** | The project's `fr-catalog.json` file containing all FRs + scope + na_rows. Supplied via `--fr-catalog` flag. |
| **Framework** | A compliance framework: ASVS, NIST 800-53, PCI-DSS, ISO 27001, NIST CSF. Each has a snapshot in `data/frameworks/<fw>/`. |
| **Compliance row** (or framework row) | A single requirement within a framework. E.g. `v5.0.0-6.1.1` is an ASVS row; `IA-2` is a NIST 800-53 row. |
| **satisfies** | FR → compliance row relationship. Says "this FR addresses this compliance row". |
| **implemented_by** | FR → code relationship. Glob, file, or symbol reference. |
| **verified_by** | FR → test/scanner relationship. The thing that proves the FR works. |
| **evidence** | Typed artifact supporting an FR. Auto (scanner/test) or manual (doc/screenshot). |
| **Traffic light** | 4-state UI indicator: green=satisfied, red=failed, amber=unaddressed, NA=not applicable. Plus grey=filtered out. |
| **Scope** | Project-level declaration of which framework levels/baselines/SAQs are in scope. E.g. `ASVS: {levels: [L1, L2]}`. |
| **na_rows** | Top-level list of compliance rows explicitly marked not-applicable for this project, with reasons. |
| **Scanner** | A security tool that produces findings: Semgrep, Trivy, Grype, Gitleaks, etc. |
| **Finding** | A single issue from a scanner. Has rule_id + file:line + severity. |
| **Audit chain** | Ordered traversal: compliance row → FR → code → test → evidence. Powers Audit Mode step-through. |
| **Dashboard payload** | The consolidated JSON `generate-dashboard.py` emits. The contract between backend and frontend. |
| **Scan history** | Retained past scans under `<project>/.asvs-scanner/scan-history/`. Enables time travel. |
| **Attention ring** | Red dashed ring around a graph node indicating "needs attention" (orphan, stale evidence, etc.) — distinct from red fill (failed evidence). |
| **Audit mode** | Graph tab toggle that locks to one compliance row + step-through chain. |
| **Time travel** | Comparing two scans to see what changed. |

## Context

We shipped a Compliance Matrix tab that maps ASVS requirements → scanner rules → findings, with traffic lights per row. It works, but it's a **single-framework, scanner-only** view of traceability. The actual engineering reality is broader:

- Teams think in **functional requirements** (FRs): "user login", "data export", "audit log". Compliance is a property of FRs, not the other way round.
- Evidence isn't just security scanner output. **Unit, integration, and e2e tests** are the primary evidence that an FR is implemented correctly. Scanners are one test type among several.
- Real projects answer to **multiple frameworks** (ASVS, NIST 800-53, PCI-DSS, ISO 27001, customer-specific). Maintaining separate maps per framework is unsustainable.
- Auditors ask **"show me the chain of evidence for this control"** — they want to walk from compliance row → FR → code → test, in either direction.

The scanner-driven approach hits a ceiling here. We need FRs as the central abstraction.

## Vision

A traceability platform where the **functional requirement** is the hub. Everything else — code, tests, scanners, compliance frameworks — connects through FRs.

```
                       Compliance Frameworks
                       (ASVS, NIST, PCI, ISO, custom)
                              ↑       ↑
                              |       |
                              |  satisfies
                              |       |
                              ↓       |
    Code ─── implements ──→  FR  ←── verified_by  ─── Test
                              ↑       ↑
                              |       |
                              |  evidenced_by
                              |       |
                              ↓       |
                          Evidence artifacts
                          (scanner outputs, manual docs, screenshots)
```

**Properties of this model:**

1. **FR is project-specific.** Universal data (ASVS rows, scanner rules) lives in the asvs-scanner repo. Project-specific data (FRs, which code implements them, which tests verify them) lives in the project repo.
2. **One FR can map to many framework rows.** FR "user authentication via OAuth" might satisfy ASVS V6, NIST IA-2, PCI 8.2.1 — all at once.
3. **Tests are first-class evidence.** A passing pytest/jest/cypress run is stronger evidence than a scanner pass, because it proves behaviour rather than absence of patterns.
4. **Scanners are just a test type.** Semgrep, Trivy, Gitleaks become "automated test runners" whose results feed the same evidence pipeline as unit tests.
5. **D3 graph is the primary visualization.** Force-directed graph with multi-hop traversal: click any node, see its full chain in any direction.

### Alice the auditor — a 90-second walkthrough

To make the design concrete. Alice is auditing Tapestry for ASVS L2 compliance. She opens the dashboard URL after a scan finishes.

**0:00 — Lands on Overview tab.** Sees 6 KPI tiles. ASVS Coverage reads "45 of 235 applicable (19%)". NIST-800-53 Coverage reads "12 of 103 applicable (12%)". FR Catalog tile reads "28 functional requirements, 23 with test coverage". She clicks the ASVS Coverage tile.

**0:05 — Jumps to ASVS tab** with filter pre-set to "show only failing/unaddressed". Seides 187 amber rows (unaddressed) and 3 red rows (failed). The 3 red rows are at the top. She clicks the first: `v5.0.0-13.3.1` Secrets management.

**0:15 — Row expands.** Shows: claimed by FR-AUTH. FR-AUTH is implemented by 2 files. Verified by 3 tests + 1 scanner. Scanner `trivy-config:DS-0031` failed. Below the chain: culprit finding details — `Dockerfile:5`, severity HIGH, message "Secrets passed via build-args".

**0:30 — Clicks "Show in graph".** Graph tab opens, centred on `v5.0.0-13.3.1`. She sees the node, plus edges to FR-AUTH (teal), FR-AUTH to two files (lavender), FR-AUTH to three tests + one scanner (gold). All green except the scanner node — red fill, red ring. Clicks the scanner finding.

**0:45 — Detail panel opens** with finding message, file path, line number, remediation advice. She clicks "Open file" to view the Dockerfile.

**1:00 — Confirms the issue.** Adds an annotation to the scanner node: "Confirmed — Dockerfile has hardcoded API key in build-args. Notifying auth team." Annotation saves to localStorage.

**1:15 — Switches to Findings tab.** Filters by `Dockerfile`. Sees the same finding plus two gitleaks findings on the same file. Clicks "Find ASVS impact" on each — both jump back to the Graph with the FRs/compliance rows they threaten.

**1:30 — Exports.** Clicks "Export" → "PDF of chain for v5.0.0-13.3.1". Gets a tidy PDF with the compliance row, FR, code references, failing scanner finding, and her annotation. Drops into the audit report.

**Total elapsed: ~90 seconds.** Without this platform, the same audit step takes Alice 30+ minutes of cross-referencing the spreadsheet, the scanner outputs, the codebase, and Jira.

That's the design target. Every feature in this doc exists to make that walkthrough fast.

## FR JSON schema (config-driven)

FRs are supplied as a JSON file in the project repo. The scanner reads it via a new `--fr-catalog <path>` flag. This is the simplest possible input — no parser, no discovery logic, no heuristics. Just JSON in, JSON out.

**Minimal viable catalog** — the smallest valid catalog. Start here, expand as you go:

```json
{
  "version": 1,
  "project": "my-app",
  "requirements": [
    {"id": "FR-001", "title": "First requirement", "status": "active"}
  ]
}
```

That's it. Five lines. The dashboard will show one FR with no compliance links, no code claims, no evidence. From here you add `implemented_by`, `verified_by`, `satisfies`, `evidence`, `parent`, `scope`, `na_rows` as your project needs them.

**Example `fr-catalog.json`** (lives in the project repo) — a fuller example with hierarchical FRs, multiple frameworks in scope, and explicit out-of-scope declarations:

```json
{
  "version": 1,
  "project": "tapestry-mono",
  "generated_at": "2026-07-15T...",
  "scope": {
    "ASVS": {"levels": ["L1", "L2"]},
    "NIST-800-53": {"baselines": ["MODERATE"]},
    "PCI-DSS": {"saq": ["A"]}
  },
  "na_rows": [
    {"framework": "ASVS", "row": "v5.0.0-6.2.x", "reason": "Biometric auth not implemented"},
    {"framework": "ASVS", "row": "v5.0.0-17.x.x", "reason": "WebRTC not used"}
  ],
  "requirements": [
    {
      "id": "FR-AUTH",
      "title": "User authentication",
      "category": "authentication",
      "description": "All user-facing authentication flows: OAuth login, session management, password reset, rate limiting.",
      "status": "active",
      "owner": "auth-team",
      "implemented_by": [
        {"type": "glob", "path": "services/tapestry-backend/src/auth/**", "label": "Auth module"}
      ],
      "satisfies": [
        {"framework": "ASVS", "row": "v5.0.0-6.1.1"},
        {"framework": "ASVS", "row": "v5.0.0-6.1.2"},
        {"framework": "NIST-800-53", "row": "IA-2"}
      ]
    },
    {
      "id": "FR-AUTH-OAUTH",
      "parent": "FR-AUTH",
      "title": "OAuth 2.0 login flow",
      "category": "authentication",
      "description": "Users sign in via Google/Microsoft OAuth. Session expires after 8 hours. Failed attempts rate-limited.",
      "status": "active",
      "owner": "auth-team",
      "implemented_by": [
        {"type": "file", "path": "services/tapestry-backend/src/auth/oauth.ts", "label": "OAuth handler"},
        {"type": "file", "path": "services/tapestry-backend/src/middleware/authenticate.ts", "label": "Auth middleware"}
      ],
      "verified_by": [
        {"type": "unit", "ref": "services/tapestry-backend/test/auth/test_login.py::test_valid_credentials"},
        {"type": "unit", "ref": "services/tapestry-backend/test/auth/test_session_expiry.py"},
        {"type": "e2e", "ref": "tests/e2e/login_flow.spec.ts"},
        {"type": "scanner", "ref": "semgrep:python.django.security.injection.sql.*"},
        {"type": "scanner", "ref": "trivy-config:DS-0002"}
      ],
      "satisfies": [
        {"framework": "ASVS", "row": "v5.0.0-6.1.3"},
        {"framework": "NIST-800-53", "row": "IA-2(1)"}
      ],
      "evidence": [
        {"type": "manual", "ref": "docs/auth-design.md", "status": "manual"},
        {"type": "screenshot", "ref": "docs/screenshots/login-flow.png", "status": "manual"}
      ]
    },
    {
      "id": "FR-AUTH-OAUTH-VERIFY",
      "parent": "FR-AUTH-OAUTH",
      "title": "OAuth token verification",
      "category": "authentication",
      "description": "Verify OAuth tokens are cryptographically valid, not expired, and issued by an approved provider.",
      "status": "active",
      "implemented_by": [
        {"type": "symbol", "path": "services/tapestry-backend/src/auth/oauth.ts:verifyToken", "label": "Token verifier"}
      ],
      "verified_by": [
        {"type": "unit", "ref": "services/tapestry-backend/test/auth/test_oauth_verify.py"}
      ]
    },
    {
      "id": "FR-002",
      "title": "Data export to CSV",
      "category": "data-export",
      "description": "Admins can export filtered datasets to CSV. Exports are streamed and audit-logged.",
      "status": "active",
      "implemented_by": [{"type": "glob", "path": "services/tapestry-backend/src/export/**"}],
      "verified_by": [
        {"type": "unit", "ref": "services/tapestry-backend/test/export/test_csv_export.py"},
        {"type": "scanner", "ref": "trivy-vuln:CVE-*"}
      ],
      "satisfies": [
        {"framework": "ASVS", "row": "v5.0.0-14.2.4"}
    {
      "id": "FR-002",
      "title": "Data export to CSV",
      "category": "data-export",
      "description": "Admins can export filtered datasets to CSV. Exports are streamed and audit-logged.",
      "status": "active",
      "implemented_by": [{"type": "glob", "path": "services/tapestry-backend/src/export/**"}],
      "verified_by": [
        {"type": "unit", "ref": "services/tapestry-backend/test/export/test_csv_export.py"},
        {"type": "scanner", "ref": "trivy-vuln:CVE-*"}
      ],
      "satisfies": [
        {"framework": "ASVS", "row": "v5.0.0-14.2.4"}
      ]
    }
  ]
}
```

**Schema rules:**

- `id` — project-unique, stable identifier (`FR-001`, `FR-AUTH-001`, anything consistent)
- `category` — free-form label for grouping in the UI ("authentication", "data-export", etc.)
- `status` — one of `draft`, `active`, `deprecated`, `proposed`. Drives UI filtering.
- `parent` — **optional**. Present only for sub-requirements. Supports hierarchical FRs (e.g. `FR-AUTH-OAUTH` under `FR-AUTH`). Rendered as a collapsible tree in the UI. See "Granularity conventions" under Code mapping strategy for usage patterns.
- `implemented_by` — list of code references. Each has a `type` (`glob`/`file`/`symbol`), a `path`, and an optional `label` for human-friendly display. See Code mapping strategy for the full type reference.
- `implemented_by` — list of code references. Each has a `type`:
  - `glob` — pattern matched against the codebase (`src/auth/**`)
  - `file` — specific file
  - `symbol` — file:function or file:Class (for precise links; resolved by simple regex/grep, no AST parsing required)
- `verified_by` — list of test references. Each has a `type`:
  - `unit`, `integration`, `e2e` — file path or `file::test_name` reference, resolved against the project's test runner output
  - `scanner` — `<scanner-name>:<rule_id_or_glob>` reference, resolved against scanner outputs from the current scan
- `satisfies` — list of `{framework, row, status?, reason?}` pairs. `status` defaults to `satisfied`; can be `na` (out of scope) with a `reason` for explicit per-project scoping. Cross-links the FR to compliance framework rows.
- `evidence` — list of typed artifacts matching `verified_by` semantics. Each has `type` (`scanner`, `test`, `manual`, `screenshot`) and `status` (`auto` = pass/fail driven by result, `manual` = always green if file exists):
  ```json
  "evidence": [
    {"type": "scanner", "ref": "semgrep:python.security.injection.sql.*", "status": "auto"},
    {"type": "test", "ref": "tests/auth/test_login.py::test_valid_credentials", "status": "auto"},
    {"type": "manual", "ref": "docs/auth-design.md", "status": "manual"}
  ]
  ```

These refinements come from comparing ASVS (testable "Verify that" statements with maturity levels) and NIST 800-53 (imperative controls with hierarchical enhancements and baseline allocations). See [FRAMEWORK_COMPARISON.md](FRAMEWORK_COMPARISON.md) for the full analysis. The schema now accommodates both styles without framework-specific code in the FR layer.

**Why JSON and not YAML?** JSON is universally parseable (no PyYAML dep), more familiar to engineers contributing to project repos, and the file is auto-generated/edited anyway (vs hand-curated like the universal mapping). If reviewers want comments, they can use JSON5 or JSON-C; we'll support whichever the project picks.

**Why per-project?** FRs ARE the project. Each project owns its FR catalog, version-controlled alongside the code. The scanner just reads it.

**Project-level scope and N/A declarations:**

Two top-level fields in the FR catalog drive which compliance rows are in scope for this project:

- **`scope`** — declares the project's target level / baseline / tier per framework. Different frameworks use different scoping dimensions (ASVS uses Levels L1/L2/L3; NIST 800-53 uses Baselines LOW/MODERATE/HIGH/PRIVACY; PCI-DSS uses SAQ types; NIST CSF uses Implementation Tiers; ISO 27001 has no scoping dimension — all Annex A controls apply). The dashboard filters visible compliance rows per tab using this.

  ```json
  "scope": {
    "ASVS": {"levels": ["L1", "L2"]},
    "NIST-800-53": {"baselines": ["MODERATE"]},
    "PCI-DSS": {"saq": ["A"]}
  }
  ```

  Frameworks not in `scope` either default to "all rows in scope" (for frameworks without levels) or are hidden from view. Adding new frameworks = adding new keys here.

- **`na_rows`** — explicit per-project out-of-scope declarations for compliance rows that have no related FR. Example: ASVS V17 (WebRTC) — project doesn't use WebRTC, no FR exists, but we still need to mark V17 rows as N/A.

  ```json
  "na_rows": [
    {"framework": "ASVS", "row": "v5.0.0-6.2.x", "reason": "Biometric auth not implemented"},
    {"framework": "ASVS", "row": "v5.0.0-17.x.x", "reason": "WebRTC not used"}
  ]
  ```

  Distinct from per-FR `satisfies` entries with `status: "na"` (which are for cases where an FR exists but doesn't address all related compliance rows).

**Compliance row state machine** (how the dashboard treats each row per framework tab):

| State | Trigger | Dashboard treatment |
|---|---|---|
| **In scope, satisfied** | FR has `satisfies` entry for the row | Traffic light (green/red/amber) |
| **In scope, unaddressed** | No FR claims this row, no N/A mark | Coverage gap (highlighted as "needs FR") |
| **Out of scope (filtered)** | Project's `scope` excludes this level/baseline | Hidden or greyed out |
| **Out of scope (explicit)** | Row listed in `na_rows`, or FR `satisfies` has `status: "na"` | "Not applicable" badge + reason |

**Formal JSON Schema.** The contract for `fr-catalog.json` is defined at `data/schemas/fr-catalog.schema.json` (Draft 2020-12). The schema enforces required fields, enum values, ID patterns, and reference shapes. `scripts/load_fr_catalog.py` validates against it at scan time using the `jsonschema` Python package. CI runs the same validation on every PR that touches an `fr-catalog.json` file. The schema is versioned (`"version": 1`); future incompatible changes bump the version with a migration path.

**Schema rules reference:**

- `id` — project-unique, stable identifier. Pattern: `^[A-Za-z0-9][A-Za-z0-9_.-]*$`. Recommended hierarchical IDs (e.g. `FR-AUTH-OAUTH-VERIFY`) match the `parent` chain for readability.
- `title` — short label, 5-10 words.
- `category` — free-form grouping label. Use consistent spelling across the catalog (typos create phantom categories in the UI).
- `status` — one of `draft`, `active`, `deprecated`, `proposed`. Drives UI filtering. `active` = currently in scope.
- `description` — full prose. What the requirement does, key constraints, edge cases.
- `owner` — optional. Team or person responsible. Free-form (e.g. `"auth-team"`, `"@alice"`).
- `parent` — optional. ID of the parent FR for hierarchical catalogs. Must reference another requirement's `id` in the same catalog.
- `default_granularity` (top-level, optional) — declares the project's typical FR granularity (`module`, `feature-folder`, `component`, `file`, `function`, `class`, `service`). Documentation hint for reviewers; not enforced. See "Granularity conventions" under Code mapping strategy.
- `implemented_by` — list of code references. Each has `type` (`glob`/`file`/`symbol`), `path`, optional `label`. See Code mapping strategy.
- `verified_by` — list of test references. Each has `type` (`unit`/`integration`/`e2e`/`scanner`), `ref`.
- `satisfies` — list of `{framework, row, status?, reason?}` pairs. `status` defaults to `satisfied`; can be `na` with required `reason`.
- `evidence` — list of typed artifacts matching `verified_by` semantics. Each has `type` (`scanner`/`test`/`manual`/`screenshot`), `ref`, `status` (`auto` = pass/fail driven by result, `manual` = always green if file exists).

## Evidence resolution (how traffic lights compute)

**Scanner evidence** (`verified_by: {type: "scanner", ref: "semgrep:python.security.injection.sql.*"}`):

1. At scan time, the dashboard reads scanner outputs (semgrep SARIF, gitleaks JSON, trivy-* JSON, grype JSON, security-headers JSON).
2. For each scanner output, extract findings with their rule IDs.
3. For each `verified_by` scanner ref, parse `<scanner-name>:<pattern>` and use `fnmatch` to match against actual finding rule IDs.
4. Result: 0 matches → evidence passes (green). 1+ matches → evidence fails (red), culprit findings listed.

**Test evidence** (`verified_by: {type: "unit", ref: "tests/auth/test_login.py::test_valid_credentials"}`):

1. At scan time, read the JUnit XML supplied via `--junit-xml <path>` (single file, can be a concatenation of multiple runners' output).
2. Parse `<testcase>` entries by `classname` + `name`.
3. For each `verified_by` test ref, find the matching testcase.
4. Result: testcase present and passed → green. Failed → red with failure message. Skipped → amber with skip reason.

**Missing test evidence (no JUnit XML supplied):**

If `verified_by` has test references but no `--junit-xml` was supplied, the evidence state is **"missing"** — amber traffic light, with a UI hint: "Supply JUnit XML via `--junit-xml <path>` to verify N test references." This is distinct from "failed" (red) and from "no tests defined" (grey). Missing evidence is a call to action; failed evidence is a problem; no tests defined is a coverage gap.

**Manual evidence** (`evidence: {type: "manual", ref: "docs/auth-design.md", status: "manual"}`):

1. At scan time, check if the referenced file exists (resolved relative to the project root).
2. Result: file exists → green, with a "last modified" timestamp shown. File missing → red with "evidence artifact not found".

Manual evidence doesn't fail based on content (the scanner can't read the design doc) — only on absence. Reviewers manually inspect content during audit.

## Cross-service and monorepo FRs

A single FR can claim code across multiple services via multiple `implemented_by` entries:

```json
{
  "id": "FR-COLLAB",
  "title": "Real-time document collaboration",
  "implemented_by": [
    {"type": "glob", "path": "services/tapestry-backend/src/collab/**", "label": "Backend collab module"},
    {"type": "glob", "path": "services/excalidraw-editor/src/collab/**", "label": "Excalidraw collab hooks"},
    {"type": "file", "path": "packages/shared/crdt.ts", "label": "Shared CRDT library"}
  ]
}
```

The dashboard's "click a file → see all FRs" view shows the file under each claiming FR. No exclusivity — files can be claimed by many FRs at many levels.

## UI rendering of state machine

Each compliance framework tab shows:

- **Top: scope header.** "ASVS L1+L2 · NIST 800-53 MODERATE baseline · PCI SAQ A" — makes the project's scope explicit
- **Coverage KPI:** "X of Y in-scope rows satisfied (Z unaddressed, W not applicable)"
- **Filter bar:** search by row ID, filter by family/chapter, filter by status
- **Table rows:**
  - Satisfied green rows: traffic light + row ID + family/section + clickable to FR
  - Failed red rows: traffic light + row ID + clickable culprit findings
  - Unaddressed amber rows: highlighted with "needs FR" badge — surfacing coverage gaps deliberately
  - Filtered out (level/baseline not in scope): greyed out, hidden by default with "show out-of-scope" toggle
  - N/A rows: diagonal-stripe grey "N/A" badge with reason tooltip

The 4-state model is deliberately visible. Auditors want to see what's covered AND what's deliberately not covered — both are signals of rigour. Hiding either creates doubt.

## Multi-framework loaders

Each compliance framework has a loader that produces a normalized JSON snapshot. We already have fetchers for ASVS and NIST 800-53. Adding new frameworks follows the same pattern:

| Framework | Source | Status | Coverage |
|---|---|---|---|
| ASVS 5.0 | `OWASP/ASVS` markdown at tag v5.0.0 | ✅ Done | 345 reqs |
| NIST 800-53 Rev 5 | `usnistgov/oscal-content` OSCAL JSON | ✅ Done | 1,196 controls (20 families) |
| NIST CSF 2.0 | NIST CSRC Reference Tool | ⏸️ Deferred — JS-driven download, no direct URL | ~108 subcategories |
| PCI-DSS 4.0 | PCI Security Standards Council | ⏸️ Deferred — paid / requires account | ~280 requirements |
| ISO 27001:2022 | ISO (paid, ~CHF 158) | ⏸️ Deferred — paid, need community extract or paid source | 93 Annex A controls |
| CIS Benchmarks | CIS GitHub org (per-technology) | ⏸️ Planned | varies |
| Custom | User-supplied CSV/JSON in same shape | ⏸️ Planned | varies |

Two frameworks (ASVS + NIST 800-53) cover both structural archetypes — testable statements + imperative controls, flat hierarchy + parent-child enhancements — which is sufficient to validate the FR schema. See [FRAMEWORK_COMPARISON.md](FRAMEWORK_COMPARISON.md) for the structural analysis.

**Loader contract:** each produces `data/sources/<framework>_requirements.json` with shape:

```json
{
  "meta": {"source": "...", "fetched_at": "...", "license": "...", "count": N},
  "requirements": [
    {"id": "<framework-specific>", "title": "...", "description": "...", "level": "..." }
  ]
}
```

Once loaded, the framework is just another node type in the graph. No special-casing per framework.

## Code mapping strategy

The hardest part of FR-driven traceability is connecting FRs to actual code. Three reference types, each with an optional `label` for human-friendly display:

**Glob (default — module/directory level)**
- `implemented_by: [{"type": "glob", "path": "src/auth/**", "label": "Auth module"}]`
- Resolved by walking the codebase at scan time, expanding globs to file lists
- No parser needed — just `pathlib.Path.glob()`
- The natural way to claim an entire module / package / feature folder
- ~80% of references in practice

**File (specific file)**
- `implemented_by: [{"type": "file", "path": "src/middleware/authenticate.ts", "label": "Auth middleware"}]`
- Direct file path; just verify the file exists
- Used for one-off files outside a module pattern, or for files shared across modules

**Symbol (function/class within a file)**
- `implemented_by: [{"type": "symbol", "path": "src/auth/login.ts:authenticateUser", "label": "Login function"}]`
- Resolved by simple regex `def authenticateUser\(|function authenticateUser\(|const authenticateUser` against the file
- No AST parsing — just pattern match
- Used when an FR maps to a single function within a larger file

**Labels (optional, all types)**
- The `label` field is human-readable metadata for the UI
- Dashboard shows "Auth module (12 files)" instead of raw `src/auth/**` path
- Useful for non-developer reviewers (auditors, product, legal)

### Granularity conventions

Don't force one granularity across all FRs — different requirements are naturally different sizes. Instead, encourage **hierarchical FRs** with the `parent` field so each project can layer from coarse to fine:

```
FR-AUTH             (module-level: src/auth/**)
├── FR-AUTH-OAUTH   (file-level: src/auth/oauth.ts)
│   └── FR-AUTH-OAUTH-VERIFY  (symbol-level: oauth.ts:verifyToken)
├── FR-AUTH-SESSION (file-level: src/auth/session.ts)
└── FR-AUTH-RATE    (file-level: src/middleware/rate-limit.ts)
```

UI renders this as a collapsible tree. Auditors drill from "tell me about authentication" → "show me OAuth" → "show me token verification". Coverage gaps are visible at any level.

**Per-ecosystem defaults** (recommendations, not enforcement):

| Ecosystem | Natural default | Maps to |
|---|---|---|
| Atomic Python | Directory (package) | `glob` with directory pattern |
| Go | Directory (package) | `glob` with directory pattern |
| Node.js (general) | Directory or single file | `glob` or `file` |
| React | Feature folder or component | `glob` for folder, `symbol` for component |
| Hooks (React/Node) | Function | `symbol` |
| Java | Class | `symbol` (with `class:` prefix) |
| Rust | Module within crate | `glob` with module path |

**Many-to-many is fine.** A file can be claimed by multiple FRs at different levels. `src/auth/oauth.ts` might be claimed by `FR-AUTH` (module-level via glob), `FR-AUTH-OAUTH` (file-level), and `FR-AUTH-OAUTH-VERIFY` (symbol-level). Each layer adds context; none owns the file exclusively. The dashboard's "click a file → see all FRs" view shows every layer.

**Project default granularity** should be declared in the FR catalog header so reviewers know what to expect. Example: a React frontend project might default to feature-folder level; an atomic-Python project might default to module level. The schema accommodates any choice; this is documentation, not enforcement.

**What we don't do (at least initially):**
- AST-based call graph analysis
- Import dependency tracing
- Dynamic analysis / coverage reports

These would give richer data but multiply the implementation cost. Stick with static pattern matching; revisit if needed.

## Test integration

Tests are evidence. We need to ingest their results without forcing a specific test runner.

**Universal format: JUnit XML.** Every major test runner can emit it (pytest via `--junit-xml`, jest via `--reporters=default --reporters=jest-junit`, cypress via `cypress-multi-reporters`, go test via `go-junit-report`, Kotlin/Java via surefire). Stable, parseable, includes pass/fail/skip + timing per test. The user runs their own tests in CI, drops the JUnit XML at a known location, and the scanner picks it up.

**Parser spec (`scripts/parse_junit.py`):**

```
Input: one or more JUnit XML files supplied via --junit-xml
       (can be repeated; parser concatenates results from all files)

Processing:
  1. Parse each <testsuite> and <testcase> element
  2. Normalise to flat list of test result dicts:
     {
       "classname": "tests.auth.test_login",        # from <testcase classname=...>
       "name": "test_valid_credentials",            # from <testcase name=...>
       "file": "tests/auth/test_login.py",          # from testcase file= attr OR derived from classname
       "status": "pass" | "fail" | "skip" | "error",
       "duration_ms": 142,
       "failure_message": "...",                    # present only when fail/error
       "skip_reason": "..."                         # present only when skip
     }
  3. Build lookup index: {(file_or_classname, name): result_dict}

Output: serialised to test_results section of the dashboard payload
```

**Reference resolution.** Given a `verified_by` reference like `tests/auth/test_login.py::test_valid_credentials`, the resolver:
1. Splits on `::` — left side is the file path, right side is the test name
2. Looks up `(file, name)` in the index
3. If not found, falls back to classname matching (some runners put the file path in classname)
4. Returns the result dict, or `None` if no match

**Missing test behavior.** If `verified_by` has a test reference but no JUnit XML was supplied at scan time, the evidence state is **"missing"** — distinct from "failed". The dashboard shows amber with hint: "Supply JUnit XML via `--junit-xml <path>` to verify N test references."

**Multi-file concatenation.** Users with multiple test runners (e.g. pytest + jest) supply multiple `--junit-xml` flags. The parser merges all into one index. Test name collisions across runners are resolved by including the source file in the lookup key.

## Scanner integration

What we've already built fits in cleanly. Scanners become "automated test types" with their own output parsers:

| Scanner | Output | Maps to |
|---|---|---|
| Semgrep | SARIF | `verified_by: [{"type": "scanner", "ref": "semgrep:<rule_id>"}]` |
| Gitleaks | JSON | `verified_by: [{"type": "scanner", "ref": "gitleaks:<rule_id>"}]` |
| Trivy config | JSON | `verified_by: [{"type": "scanner", "ref": "trivy-config:<rule_id>"}]` |
| Grype | JSON | `verified_by: [{"type": "scanner", "ref": "grype:<rule_id>"}]` |
| etc. | | |

The current `asvs_mapping.yaml` becomes one possible mapping source — it links ASVS rows directly to scanners. In the FR-driven model, that link is decomposed: ASVS row ← FR ← scanner. Both models coexist; the FR model is richer.

## Dashboard input payload

The single contract between `generate-dashboard.py` (backend) and the dashboard's JavaScript (frontend). One JSON document, embedded in `dashboard.html` as `<script type="application/json" id="dashboard-data">`, plus written to disk as `dashboard-data.json` for snapshot tests and scan history.

**Top-level shape:**

```json
{
  "scan": {
    "run_id": "20260704T1432Z_<sha8>",
    "timestamp": "2026-07-04T14:32:00Z",
    "project": "tapestry-mono",
    "target_dir": "/path/to/project",
    "git_commit": "abc12345",
    "scanner_image_tag": "namenottaken/asvs-scanner:latest"
  },
  "scope": {
    "ASVS": {"levels": ["L1", "L2"]},
    "NIST-800-53": {"baselines": ["MODERATE"]}
  },
  "fr_catalog": {
    "version": 1,
    "requirements": [...],
    "na_rows": [...]
  },
  "frameworks": {
    "ASVS": {
      "version": "5.0.0",
      "rows": [
        {"id": "v5.0.0-1.1.1", "chapter": "V1", "level": 2, "title": "...", "description": "...", "state": "unaddressed|satisfied|failed|na|filtered", "claimed_by": ["FR-AUTH-OAUTH"]}
      ],
      "coverage": {
        "satisfied": 45, "failed": 3, "unaddressed": 187, "na": 12, "filtered": 6,
        "applicable": 235, "coverage_pct": 19.1
      }
    },
    "NIST-800-53": {...}
  },
  "scanner_findings": {
    "semgrep": [{"rule_id": "...", "file": "...", "line": 42, "severity": "HIGH", "message": "..."}, ...],
    "gitleaks": [...],
    "trivy-config": [...],
    "trivy-vuln": [...],
    "grype": [...],
    "security-headers": [...]
  },
  "test_results": {
    "tests_run": 234, "passed": 231, "failed": 2, "skipped": 1,
    "results": [
      {"file": "tests/auth/test_login.py", "name": "test_valid_credentials", "status": "pass", "duration_ms": 142}
    ]
  },
  "derived": {
    "coverage_heatmap": {
      "ASVS": {"V1": {"satisfied": 5, "applicable": 23, "pct": 21.7}, "V2": {...}, ...},
      "NIST-800-53": {"AC": {...}, "AT": {...}, ...}
    },
    "framework_equivalences": [
      {"fr_ids": ["FR-AUTH"], "rows": [{"framework": "ASVS", "row": "v5.0.0-6.1.1"}, {"framework": "NIST-800-53", "row": "IA-2"}]}
    ],
    "reverse_lookup": {
      "by_finding": {"semgrep:python.security.injection.sql.sql-injection": [{"fr_id": "FR-AUTH-OAUTH", "compliance_rows": [{"framework": "ASVS", "row": "v5.0.0-1.2.4"}]}]},
      "by_file": {"src/auth/oauth.ts": [{"fr_id": "FR-AUTH-OAUTH", "compliance_rows": [...]}]}
    },
    "audit_chains": {
      "v5.0.0-6.1.1": {"fr_ids": ["FR-AUTH-OAUTH"], "ordered_chain": ["FR-AUTH-OAUTH", "src/auth/oauth.ts", "tests/auth/test_login.py::test_valid_credentials"]}
    }
  },
  "graph": {
    "nodes": [
      {"id": "fr:FR-AUTH-OAUTH", "type": "fr", "label": "OAuth login", "status": "satisfied", "needs_attention": false},
      {"id": "file:src/auth/oauth.ts", "type": "file", "label": "oauth.ts", "needs_attention": false},
      {"id": "test:tests/auth/test_login.py::test_valid_credentials", "type": "test", "label": "test_valid_credentials", "status": "pass"}
    ],
    "edges": [
      {"source": "fr:FR-AUTH-OAUTH", "target": "file:src/auth/oauth.ts", "type": "implements", "strength": "strong"},
      {"source": "fr:FR-AUTH-OAUTH", "target": "test:tests/auth/test_login.py::test_valid_credentials", "type": "verified_by", "strength": "strong"}
    ]
  },
  "validation_warnings": [
    {"severity": "error|warn", "code": "fr_catalog.schema_invalid|scanner_output.missing|...", "message": "...", "fr_id": "FR-X (optional)"}
  ]
}
```

**Size budget:** target <2MB compressed. The largest contributor is `scanner_findings` (potentially thousands of entries on big scans). If over budget: paginate findings (load on demand via separate JSON file), or strip failure messages (frontend fetches on click). Monitored via CI; >2MB triggers a warning in `run.log`.

**Computation.** `generate-dashboard.py` produces this payload at scan time by:
1. Loading the FR catalog + validating against JSON Schema
2. Loading framework snapshots from bundled `data/frameworks/<fw>/requirements.json`
3. Reading scanner outputs (`reports/*.json`)
4. Reading JUnit XML (if supplied)
5. Computing per-framework `coverage` and per-row `state`
6. Building `derived` indices (see "Derived indices" section)
7. Building `graph.nodes` and `graph.edges`
8. Emitting the consolidated JSON

**Validation warnings** are non-fatal problems surfaced to the UI: schema validation issues, missing evidence files, scanner outputs that didn't parse. The dashboard renders these as a dismissible banner — never blocks the dashboard from loading.

## Scan history retention

For time travel and cross-scan navigation. The frontend assumes the dashboard can load any past scan and compare two scans.

**Path layout** (per project):

```
<project-root>/.asvs-scanner/
├── runtime/                              # current scan's runtime (existing)
│   └── reports/<RUN_ID>/                 # current scan's report dir (existing)
└── scan-history/                         # NEW — retained scans
    ├── index.json                        # scan picker reads this
    ├── <RUN_ID_1>/
    │   ├── evidence-manifest.json
    │   ├── dashboard-data.json           # the consolidated payload (from above)
    │   ├── fr-catalog.snapshot.json      # FR catalog at scan time (NEW)
    │   └── scope.snapshot.json           # project scope at scan time
    ├── <RUN_ID_2>/
    │   └── ...
    └── <RUN_ID_N>/                        # up to retention limit
```

**`index.json` shape:**

```json
{
  "project": "tapestry-mono",
  "retention_policy": {"max_scans": 5, "max_age_days": null},
  "scans": [
    {
      "run_id": "20260704T1432Z_abc12345",
      "timestamp": "2026-07-04T14:32:00Z",
      "git_commit": "abc12345",
      "git_branch": "main",
      "scope": {"ASVS": {"levels": ["L1","L2"]}},
      "fr_catalog_sha": "sha256:...",     # for change detection
      "coverage_summary": {"ASVS": {"satisfied": 45, "failed": 3, "coverage_pct": 19.1}}
    }
  ]
}
```

**Retention policy:** default keep last 5 scans per project (`ASVS_SCAN_HISTORY_MAX=5` env var). Configurable by age (`ASVS_SCAN_HISTORY_MAX_AGE_DAYS=90`). Older scans evicted FIFO on each new scan completion.

**FR catalog snapshot.** Every scan copies the active `fr-catalog.json` into `<RUN_ID>/fr-catalog.snapshot.json` at scan start. This is the source of truth for "what FRs existed when this scan ran" — enables:
- Comparing scans even if FRs were added/removed between them
- Time travel without "FR definitions changed, comparison invalid" failures
- Reproducing past audit findings exactly

**Backend changes required:**
- `run-local.sh`: after dashboard generation, copy `evidence-manifest.json`, `dashboard-data.json`, `fr-catalog.snapshot.json`, `scope.snapshot.json` to `scan-history/<RUN_ID>/`
- New helper: `scripts/record-scan-history.py` updates `scan-history/index.json`, evicts old scans per retention policy
- Dashboard reads `scan-history/index.json` (via embedded data in the payload, or a separate fetch) to populate the scan picker

**Comparison mode** (frontend computes diffs):
- Two scans' `dashboard-data.json` files are both available
- Frontend diffs FR catalogs (added/removed/changed), compliance row states (newly-satisfied/failed/NA), findings (new/resolved)
- No backend "diff computation" — pure frontend given both snapshots
- Rationale: keeps backend simple, lets users adjust comparison logic via filter ("show only changes" etc.)

## Derived indices

Computed at scan time by `generate-dashboard.py`, embedded in the `derived` block of the dashboard payload. Each is a small JSON the frontend reads directly — no runtime computation needed.

### `coverage_heatmap`

Chapter × framework matrix showing per-cell coverage stats. Powers the Overview tab's heatmap view.

```json
{
  "ASVS": {
    "V1": {"satisfied": 5, "failed": 1, "unaddressed": 18, "na": 2, "filtered": 0, "applicable": 24, "coverage_pct": 20.8},
    "V2": {"satisfied": 3, ...},
    ...
  },
  "NIST-800-53": {
    "AC": {"satisfied": 12, "failed": 2, "unaddressed": 89, "na": 5, "filtered": 39, "applicable": 103, "coverage_pct": 11.7},
    "AT": {...}
  }
}
```

Computation: iterate every in-scope compliance row, bucket by chapter/family, count states. O(rows) — cheap.

### `framework_equivalences`

Groups of compliance rows across frameworks that share FRs. Powers the "Cross-framework equivalents" graph entry point.

```json
[
  {
    "fr_ids": ["FR-AUTH"],
    "rows": [
      {"framework": "ASVS", "row": "v5.0.0-6.1.1"},
      {"framework": "ASVS", "row": "v5.0.0-6.1.2"},
      {"framework": "NIST-800-53", "row": "IA-2"}
    ]
  },
  {
    "fr_ids": ["FR-AUTH", "FR-AUDIT"],
    "rows": [{"framework": "ASVS", "row": "v5.0.0-7.1.1"}]
  }
]
```

Computation: invert the FR→`satisfies` mapping to get compliance_row→FRs. Group compliance rows by their FR set. Two rows are "equivalent" if they share at least one FR.

### `reverse_lookup`

Two indices for "what does this X impact?" queries. Powers the Findings → "Find ASVS impact" button and the file → FRs view in the Graph tab.

```json
{
  "by_finding": {
    "semgrep:python.security.injection.sql.sql-injection": [
      {"fr_id": "FR-AUTH-OAUTH", "compliance_rows": [{"framework": "ASVS", "row": "v5.0.0-1.2.4"}]}
    ],
    "trivy-config:DS-0031": [...]
  },
  "by_file": {
    "src/auth/oauth.ts": [
      {"fr_id": "FR-AUTH-OAUTH", "compliance_rows": [...]}
    ]
  }
}
```

Computation:
- `by_finding`: iterate scanner findings, for each finding's rule_id match against FR `verified_by: scanner` patterns via fnmatch. For each matching FR, collect its `satisfies` rows.
- `by_file`: iterate code files claimed by FRs (`implemented_by`), invert to file→FRs, attach each FR's `satisfies` rows.

### `audit_chains`

Ordered traversal per compliance row, for Audit Mode step-through in the Graph tab.

```json
{
  "v5.0.0-6.1.1": {
    "fr_ids": ["FR-AUTH-OAUTH"],
    "ordered_chain": [
      "fr:FR-AUTH-OAUTH",
      "file:src/auth/oauth.ts",
      "test:tests/auth/test_login.py::test_valid_credentials",
      "evidence:docs/auth-design.md"
    ]
  }
}
```

Computation: for each in-scope compliance row that has at least one claiming FR, build the deterministic chain:
1. FR node(s) claiming this row
2. Code file(s) those FRs implement (depth-first, sorted by file path)
3. Test(s) those FRs are verified by (sorted by test file path)
4. Evidence artifact(s) attached to those FRs (sorted by type: scanner, test, manual, screenshot)

Deterministic order ensures Audit Mode's prev/next is stable across renders.

### Computation cost

All four indices run at scan time as part of `generate-dashboard.py`. Combined cost: O(rows + findings + files) — linear in scan size. On a Tapestry-scale scan (~253 ASVS rows + ~1000 findings + ~500 files), expect <2 seconds added to dashboard generation. Acceptable.

## D3 graph visualization

The full graph design — node/edge types, layout modes, visual encoding (color=status, shape=type, edge colour/style), entry-point picker, audit mode, power features, performance — lives in [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md#the-graph-tab--full-design).

Backend produces the graph data via `dashboard-data.json → graph.nodes + graph.edges` (see "Dashboard input payload" section). Frontend renders it. The two are linked by that contract; no graph-related logic on the backend side.

**Why D3 over ECharts:** more flexibility for multi-hop traversal and custom layouts (force-directed, hierarchical, concentric, Sankey). ECharts is easier for standard chart types; this isn't a standard chart type.

**Soft cap, not hard cap:** D3 force layout becomes janky above ~500 simultaneous nodes on commodity hardware. We soft-cap with a non-blocking banner ("Displaying 500 of N — narrow filters to see all") and default to per-FR subgraphs (one FR + neighbours = ~20-50 nodes) rather than rendering the whole graph at once.

## CI workflow

Backend CI runs on every PR. Workflow file: `.github/workflows/ci.yml`. Jobs:

| Job | Triggers on | What it checks |
|---|---|---|
| `validate-fr-schema` | Any PR touching `data/schemas/fr-catalog.schema.json` or `**/fr-catalog.json` | Runs `scripts/validate_fr_catalog.py` against the schema; reports errors |
| `validate-mapping` | PRs touching `data/asvs_mapping.yaml` or `data/sources/**` | Runs existing `scripts/validate-mapping.py` |
| `dashboard-snapshot` | PRs touching `scripts/generate-dashboard.py` or `assets/dashboard.js` | Regenerates dashboard from fixture scan; diffs against `tests/fixtures/expected-dashboard.html`. Snapshot updates require explicit `--update-snapshot` flag. |
| `payload-size` | PRs touching `scripts/generate-dashboard.py` or `data/sources/**` | Asserts `dashboard-data.json` <2MB for the fixture scan |
| `bundle-size` | PRs touching `assets/**` | Asserts total JS bundle <500KB |
| `scan-history` | PRs touching `scripts/record_scan_history.py` or `run-local.sh` | Runs scanner twice against fixture, verifies both scans retained, verifies FIFO eviction after 6th run |
| `js-unit-tests` | PRs touching `assets/**` | Vitest with coverage targets (state 90%, utils 80%, graph 60%) |

**Failure policy:** all jobs must pass for PR merge (branch protection). Snapshot updates and bundle-size increases (>10%) require reviewer sign-off via label.

## Fixture scan spec

`tests/fixtures/sample-scan/` is the canonical sample scan for dashboard snapshot tests, payload-size checks, and scan-history tests. Contents:

```
tests/fixtures/sample-scan/
├── fr-catalog.json                  # 5 FRs (3 active, 1 deprecated, 1 hierarchical parent+child)
├── evidence-manifest.json           # Standard manifest with 8 scanners
├── junit.xml                        # 12 testcases (10 pass, 1 fail, 1 skip)
├── reports/
│   ├── semgrep.sarif                # 2 findings (1 SQL injection, 1 XSS)
│   ├── gitleaks.json                # 1 finding (AWS key)
│   ├── trivy-config.json            # 1 finding (DS-0031 secrets in build-args)
│   ├── trivy-fs.json                # 0 findings (clean)
│   ├── grype.json                   # 2 findings (1 HIGH CVE, 1 MEDIUM CVE)
│   └── security-headers.json        # 1 missing header (CSP)
└── expected-dashboard.html          # Committed snapshot — regenerates via --update-snapshot
```

**FR catalog fixture design** (5 FRs covering every schema feature):

| FR ID | Parent | Has implemented_by | Has verified_by | Has satisfies | Has evidence | Purpose |
|---|---|---|---|---|---|---|
| FR-AUTH | — | glob (3 files) | scanner + unit | ASVS 6.1.1, NIST IA-2 | manual + screenshot | Typical fully-specced FR |
| FR-AUTH-OAUTH | FR-AUTH | file (1) + symbol (1) | unit (2) | ASVS 6.1.3 | — | Hierarchical child FR |
| FR-EXPORT | — | glob | scanner + integration | ASVS 14.2.4 | — | FR with scanner glob match |
| FR-DEPRECATED | — | — | — | — | — | `status: deprecated` — exercises status filter |
| FR-NOLINK | — | glob | — | — | — | Active FR but no compliance links — exercises "internal-only" state |

**Test scenarios the fixture enables:**
- All 4 traffic light states appear (satisfied/failed/unaddressed/NA)
- Hierarchical FR rendering (parent + child)
- Scanner findings link to FRs (reverse lookup working)
- Test results link to FRs (verified_by resolution working)
- Manual evidence existence check (docs/auth-design.md committed)
- Coverage KPIs computable (5 FRs, 4 compliance rows claimed, etc.)

The fixture is committed and version-controlled. Updates require explicit snapshot update + reviewer sign-off.

## Migration path (no backward compatibility)

The scanner-driven Compliance Matrix built on `develop` (Phase 2) is **being replaced, not preserved**. The decision is deliberate — maintaining two data models (scanner-driven + FR-driven) is exactly what the pivot was meant to escape.

**What's retained from `develop`:**

| From `develop` | Becomes in `pivot` |
|---|---|
| `scripts/build-mapping-sources.py` (ASVS + scanner rule fetchers) | Same script, extended with NIST 800-53 fetcher (done). Will rename to `build-framework-sources.py` once multi-framework is proven. |
| `data/sources/*.json` snapshots (ASVS, gitleaks, trivy-config, trivy-vuln, security-headers) | Same files, retained as scanner rule catalogs |
| `data/asvs_mapping.yaml` | Reframed as one framework's mapping — moves to `data/frameworks/asvs/scanner_mapping.yaml` (orthogonal to FR catalog) |
| `scripts/generate-mapping.py` + `scripts/validate-mapping.py` | Same scripts, still useful for the ASVS scanner-rule mapping |
| `scripts/enrich-mapping-llm.py` | Same — Path B enrichment of scanner mappings |
| `requirements-mapping.txt`, `data/sources/LICENSES.md` | Same |
| py3-yaml in Dockerfile | Same |

**What's deleted from `develop`:**

| From `develop` | Disposition |
|---|---|
| Phase 2 Compliance Matrix tab (`render_compliance_matrix` in `generate-dashboard.py`) | **Deleted.** Replaced by the FR-driven multi-framework tab set. |
| `--compliance-matrix` flag in `bin/asvs-scanner` and `run-local.sh` | **Deleted.** Replaced by `--fr-catalog`. |
| `data/asvs_mapping.yaml` consumption in the dashboard | Reframed — scanner rule mappings feed the `verified_by: scanner` evidence type, but the dashboard's primary input is the FR catalog. |

**What's new in `pivot`:**

| New | Purpose |
|---|---|
| `--fr-catalog <path>` flag | Primary input — points to project's `fr-catalog.json` |
| `--junit-xml <path>` flag | Test results from any runner that emits JUnit XML |
| `scripts/load_fr_catalog.py` | JSON Schema validation + reference resolver |
| `data/schemas/fr-catalog.schema.json` | Formal JSON Schema for the FR catalog |
| FR Catalog tab + per-framework tabs in dashboard | New UI |
| D3 traceability graph (Phase 6) | New visualization |

## Phased scope

Phase numbering is **shared with [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md#phased-delivery)** — "Phase N" means the same thing in both docs. Each phase ships backend + frontend together so the slice is independently useful.

| Phase | What ships (backend + frontend combined) | Effort | MVP? |
|---|---|---|---|
| **0** (this doc) | Design docs, schema decisions, NIST 800-53 fetcher | 1 day | — |
| **1** | FR catalog parser + `--fr-catalog` flag + JSON Schema validation. FR Catalog tab + ASVS framework tab working end-to-end. Cross-tab deep-linking. Empty/loading/error states. Mobile responsive for non-graph tabs. Scanner integration into `verified_by`. | 2-3 weeks | ✅ |
| **2** | Findings "Find ASVS impact" button. Reverse lookup index. | 1 week | ✅ |
| **3** | Additional framework tabs (NIST 800-53, PCI, ISO as loaders land). Filter presets. Coverage heatmap on Overview. | 1.5 weeks | — |
| **4** | Graph tab MVP: force-directed only, two entry points (FR picker, compliance row picker), click highlight, fan-out cap. Desktop-only. | 2 weeks | — |
| **5** | Graph power features: hierarchical + concentric + Sankey layouts, audit mode, deep-linking to graph state, keyboard nav, PNG/SVG export. | 2-3 weeks | — |
| **6** | Time travel: scan picker, comparison mode, FR catalog snapshot retention, diff highlighting. JUnit XML test integration. | 2 weeks | — |
| **7** | Annotations (localStorage), PDF export, cross-framework equivalents view. Code mapping (glob/file/symbol resolution at scan time). | 1.5 weeks | — |
| **8** | Polish: a11y pass full audit, snapshot test infrastructure, performance tuning, JS unit test coverage targets, light mode, print stylesheet. PCI-DSS, ISO 27001, NIST CSF loaders as sources allow. | ongoing | — |

**MVP = Phases 1-2** (≈3-4 weeks). After Phase 2, the platform is genuinely useful: an auditor can see FRs, see compliance coverage, click a finding to see what it threatens.

**Total to Phase 6** (time travel working): ~10-13 weeks of focused work. After that, value continues compounding with each new framework loader and polish pass.

**Phase numbering rationale:** combined backend+frontend phases avoid the confusion of "frontend Phase 1 vs backend Phase 1". Each phase delivers a slice a user can see and use.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **FR catalog becomes stale** (project changes, FRs not updated) | FR catalog diff against codebase glob coverage; warn when code exists that no FR claims |
| **FR maintenance burden** | Make FR catalog part of code review; CI check that any new file in `src/**` either matches an existing FR glob or has `# untracked` annotation |
| **Multi-framework row explosion** (one FR maps to 20+ framework rows) | UI groups framework rows by framework; default to showing top 3; expand for more |
| **Test runner diversity** | JUnit XML is the universal format; require projects to emit it; document the per-runner flag |
| **D3 hairballs at scale** | Hard cap visible nodes; per-FR subgraphs; lazy loading |
| **Schema drift between projects** | JSON schema validation in the scanner (jsonschema); versioned schema (`"version": 1`) with migration path |
| **Schema drift between projects** | JSON schema validation in the scanner (jsonschema); versioned schema (`"version": 1`) with migration path |
| **FR catalog maintenance feels like overhead vs value** | Show value early — FR Catalog tab in Phase 1 gives immediate visibility into code structure even before compliance tabs light up. Don't gate adoption on having full compliance coverage from day one. |

## Critical files (planned)

**New (data + schemas):**
- `data/schemas/fr-catalog.schema.json` — formal JSON Schema for the FR catalog ✅ created
- `data/schemas/dashboard-payload.schema.json` — formal JSON Schema for the consolidated dashboard input payload (see "Dashboard input payload" section)
- `data/frameworks/asvs/requirements.json` (moved from `data/sources/asvs_requirements.json`)
- `data/frameworks/asvs/scanner_mapping.yaml` (moved from `data/asvs_mapping.yaml`)
- `data/frameworks/nist_800_53/requirements.json` ✅ exists at `data/sources/nist_800_53_requirements.json` (will move)
- `tests/fixtures/sample-scan/` — fixture scan with FR catalog + scanner outputs + JUnit XML + framework snapshots. Powers dashboard snapshot tests.

**New (scripts):**
- `scripts/build-framework-sources.py` (rename of `build-mapping-sources.py`)
- `scripts/parse_junit.py` — JUnit XML parser (spec in "Test integration" section)
- `scripts/resolve_code_refs.py` — glob/file/symbol resolver
- `scripts/load_fr_catalog.py` — FR JSON validator + loader (uses jsonschema)
- `scripts/validate_fr_catalog.py` — CI-runnable validator (validates + reports errors/warnings)
- `scripts/compute_derived_indices.py` — produces coverage_heatmap, framework_equivalences, reverse_lookup, audit_chains
- `scripts/record_scan_history.py` — copies scan artifacts to scan-history/, updates index.json, evicts per retention policy
- `scripts/generate-dashboard.py` extensions: new FR Catalog tab, per-framework tabs, D3 graph tab; emits consolidated dashboard-data.json payload

**Modified:**
- `bin/asvs-scanner` — add `--fr-catalog <path>` and `--junit-xml <path>` flags; **remove** `--compliance-matrix` flag (deleted per "no backward compat")
- `run-local.sh` — thread new flags; remove old `--compliance-matrix`; call `record_scan_history.py` after dashboard generation
- `scripts/generate-dashboard.py` — **remove** `render_compliance_matrix` (Phase 2 code); replace with FR-driven equivalents; emit consolidated `dashboard-data.json` payload
- `Dockerfile` — add `py3-jsonschema` to apk install

**Existing (no change):**
- All scanner wiring (Semgrep, Gitleaks, Trivy, Grype, etc.)
- All scanner output parsers — reframed as test types via `verified_by: scanner`
- The dashboard's existing tabs (Overview, Scanners, Findings, Fix Plan)

**Per-project artifacts created at scan time:**
- `<report-dir>/dashboard-data.json` — consolidated payload (also embedded in dashboard.html)
- `<report-dir>/fr-catalog.snapshot.json` — FR catalog at scan time (for time travel)
- `<report-dir>/scope.snapshot.json` — project scope at scan time
- `<project>/.asvs-scanner/scan-history/<RUN_ID>/` — retained copy of the above
- `<project>/.asvs-scanner/scan-history/index.json` — scan picker index



## Open questions

1. ~~JSON schema enforcement~~ — **decided**: jsonschema (Draft 2020-12), schema at `data/schemas/fr-catalog.schema.json`.
2. **D3 vs D3 + WebGL** for very large graphs? Default D3, revisit if performance demands.
3. ~~Where do JUnit XML files come from~~ — **decided**: user supplies via `--junit-xml <path>`. Scanner doesn't run code.
4. ~~Manual evidence artifacts stored where~~ — **decided**: file path references only. Scanner doesn't store content; just verifies existence.
5. **Custom framework loader** — same JSON shape as built-in frameworks, just user-supplied? Probably yes; defer until first custom framework request.
6. ~~Scanner-driven mappings (`asvs_mapping.yaml`)~~ — **decided**: kept, reframed as input to the `verified_by: scanner` evidence type. See Migration Path.
7. **Pre-commit hook vs CI-only** validation for FR catalog changes. Both? CI-only initially, pre-commit optional.

## Decision needed before proceeding

- ✅ ~~Approve pivot direction~~ — done, on `pivot` branch
- ✅ ~~Endorse FR JSON schema~~ — done, refinements in this revision
- ✅ ~~Pick next framework after ASVS~~ — NIST 800-53 (done in Phase 0a)
- ✅ ~~No backward compatibility~~ — Phase 2 Compliance Matrix being deleted

**Open decisions for Phase 1 start:**

- JSON Schema file location: `data/schemas/fr-catalog.schema.json` (proposed)
- Validation library: `jsonschema` Python package (proposed — no extra runtime dep beyond pyyaml + jsonschema, both lightweight)
- Scanner-driven mappings (`asvs_mapping.yaml`) — keep as input to the `verified_by: scanner` evidence type, or deprecate entirely once FR-driven `satisfies` mappings cover the same ground?
- Pre-commit hook vs CI-only validation for FR catalog changes

Once these are settled, Phase 1 implementation starts: build the FR catalog parser, `--fr-catalog` flag, JSON Schema validation, and a basic FR list view in the dashboard. That's the foundation everything else hangs off.
