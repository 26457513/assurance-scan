# Pivot: Functional-Requirement-Driven Traceability

## Status

**Draft.** Proposed pivot from the current scanner-driven Compliance Matrix (Phase 2, shipped) to a requirements-driven traceability platform with compliance as one view. This doc supersedes the long-term vision in [ASVS_TRACEABILITY_PLAN.md](ASVS_TRACEABILITY_PLAN.md) — the existing plan remains valid as the migration path for what we've already built.

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

## FR JSON schema (config-driven)

FRs are supplied as a JSON file in the project repo. The scanner reads it via a new `--fr-catalog <path>` flag. This is the simplest possible input — no parser, no discovery logic, no heuristics. Just JSON in, JSON out.

**Example `fr-catalog.json`** (lives in the project repo):

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

**Supported test types (each with a parser):**

| Type | Output format | Parser |
|---|---|---|
| `pytest` | JUnit XML | `scripts/parse_pytest.py` |
| `jest` | JUnit XML or custom JSON | `scripts/parse_jest.py` |
| `cypress` | JUnit XML | `scripts/parse_cypress.py` |
| `go test` | JUnit XML | `scripts/parse_go_test.py` |
| `kotlin/test` (JUnit) | JUnit XML | same parser |
| Generic JUnit XML | JUnit XML | works for any runner that emits JUnit |

**Why JUnit XML as the common format?** Every major test runner can emit it. It's stable, parseable, and includes pass/fail/skip + timing per test. The user runs their own tests (CI does this anyway), drops the JUnit XML in a known location (e.g. `<report-dir>/tests/junit.xml`), and the scanner picks it up.

**Lookup:** given a `verified_by` reference like `services/tapestry-backend/test/auth/test_login.py::test_valid_credentials`, the parser:
1. Loads the JUnit XML
2. Finds the `<testcase>` with matching classname + name
3. Returns: pass/fail/skip, duration, failure message

If no JUnit XML is supplied, the `verified_by` reference is marked "evidence missing" — not failed, just unverified.

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

## D3 graph visualization

D3 force-directed graph (not ECharts — D3 gives more flexibility for the multi-hop traversal we need). Layered on the same data as the Compliance Matrix.

**Node types:**
- `framework` (e.g. "ASVS 5.0", "NIST 800-53") — large, perimeter
- `framework_row` (e.g. "v5.0.0-6.1.1") — small, grouped by framework
- `fr` (e.g. "FR-001") — medium, central
- `category` (e.g. "authentication") — grouping label
- `code_file` — small
- `test` — small, coloured by pass/fail
- `scanner_finding` — small, coloured by severity
- `evidence_artifact` — small

**Edge types:**
- `satisfies` (fr → framework_row)
- `implements` (fr → code_file)
- `verified_by` (fr → test/scanner)
- `evidenced_by` (fr → evidence_artifact)
- `contains` (framework → framework_row)
- `belongs_to` (fr → category)

**Interactions:**
- Click any node → highlight its full chain in both directions
- Filter by framework, category, status, FR
- "Show me the chain for ASVS row X" or "Show me the chain for file Y" — bidirectional entry points
- Per-FR subgraph (avoid hairballs)

**Performance:** hard cap ~500 visible nodes; lazy-load deeper subgraphs on click.

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

| Phase | What | Effort | Notes |
|---|---|---|---|
| **0** (this doc) | Design doc, schema decisions | 1 day | You're reading it |
| **1** | FR JSON schema + parser; `--fr-catalog` flag; basic FR list view | 1 week | Establishes the new central abstraction |
| **2** | Code mapping (glob/file/symbol resolution at scan time); code files appear in graph | 1 week | Static analysis light |
| **3** | Test integration (JUnit XML parser); test results appear next to FRs | 1 week | Tests become first-class evidence |
| **4** | Scanner integration into FR model (existing scanners become test types) | 1 week | Mostly refactor, not new code |
| **5** | NIST 800-53 loader; multi-framework UI tabs | 1.5 weeks | Second framework proves the pattern |
| **6** | D3 graph visualization | 2-3 weeks | The headline feature |
| **7** | PCI-DSS, ISO 27001 loaders; framework-aware filters | 1.5 weeks | Coverage breadth |
| **8** | Polish, accessibility, performance, snapshot tests | ongoing | |

**Total:** ~3-4 months of focused work to reach Phase 6 (D3 graph working with multi-framework + tests). After that, value continues compounding with each new framework loader.

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

**New:**
- `data/schemas/fr-catalog.schema.json` — formal JSON Schema for the FR catalog ✅ created
- `data/frameworks/asvs/requirements.json` (moved from `data/sources/asvs_requirements.json`)
- `data/frameworks/asvs/scanner_mapping.yaml` (moved from `data/asvs_mapping.yaml`)
- `data/frameworks/nist_800_53/requirements.json` ✅ exists at `data/sources/nist_800_53_requirements.json` (will move)
- `scripts/build-framework-sources.py` (rename of `build-mapping-sources.py`)
- `scripts/parse_junit.py` — JUnit XML parser
- `scripts/resolve_code_refs.py` — glob/file/symbol resolver
- `scripts/load_fr_catalog.py` — FR JSON validator + loader (uses jsonschema)
- `scripts/validate_fr_catalog.py` — CI-runnable validator (validates + reports errors/warnings)
- `scripts/generate-dashboard.py` extensions: new FR Catalog tab, per-framework tabs, D3 graph tab

**Modified:**
- `bin/asvs-scanner` — add `--fr-catalog <path>` and `--junit-xml <path>` flags; **remove** `--compliance-matrix` flag (deleted per "no backward compat")
- `run-local.sh` — thread new flags; remove old `--compliance-matrix`
- `scripts/generate-dashboard.py` — **remove** `render_compliance_matrix` (Phase 2 code); replace with FR-driven equivalents
- `Dockerfile` — add `py3-jsonschema` to apk install

**Existing (no change):**
- All scanner wiring (Semgrep, Gitleaks, Trivy, Grype, etc.)
- All scanner output parsers — reframed as test types via `verified_by: scanner`
- The dashboard's existing tabs (Overview, Scanners, Findings, Fix Plan)

## Open questions

1. ~~JSON schema enforcement~~ — **decided**: jsonschema (Draft 2020-12), schema at `data/schemas/fr-catalog.schema.json`.
2. **D3 vs D3 + WebGL** for very large graphs? Default D3, revisit if performance demands.
3. ~~Where do JUnit XML files come from~~ — **decided**: user supplies via `--junit-xml <path>`. Scanner doesn't run code.
4. ~~Manual evidence artifacts stored where~~ — **decided**: file path references only. Scanner doesn't store content; just verifies existence.
5. **Custom framework loader** — same JSON shape as built-in frameworks, just user-supplied? Probably yes; defer until first custom framework request.
6. **Scanner-driven mappings (`asvs_mapping.yaml`)** — keep as input to the `verified_by: scanner` evidence type, or deprecate entirely once FR-driven `satisfies` mappings cover the same ground? See Decision section.
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
