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

## Multi-framework loaders

Each compliance framework has a loader that produces a normalized JSON snapshot. We already have one for ASVS (`scripts/build-mapping-sources.py`'s `fetch_asvs`). Adding new frameworks follows the same pattern:

| Framework | Source | Loader | Coverage |
|---|---|---|---|
| ASVS 5.0 | `OWASP/ASVS` markdown | ✅ Done | 345 reqs |
| NIST 800-53 | NIST Special Publication 800-53 Rev 5 (XML/JSON via NIST Cyber Watch) | `fetch_nist_800_53()` | ~1,200 controls |
| PCI-DSS 4.0 | PCI Security Standards Council (paid download or community extracts) | `fetch_pci_dss()` | ~280 requirements |
| ISO 27001:2022 | ISO (paid) or community controls catalogs | `fetch_iso_27001()` | 93 controls |
| CIS Benchmarks | CIS GitHub org (per-technology) | `fetch_cis()` | varies |
| Custom | User-supplied CSV/JSON in same shape | `fetch_custom()` | varies |

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

## Migration path (what we've built becomes what)

| Current (shipped) | Pivoted (target) |
|---|---|
| `data/asvs_mapping.yaml` | One input to the framework loaders; still maintained |
| `scripts/build-mapping-sources.py` (ASVS only) | Extends to multi-framework |
| `scripts/generate-mapping.py` | Becomes framework-row → scanner-rule mapping; orthogonal to FR mapping |
| Compliance Matrix tab | Becomes one of multiple framework tabs (ASVS / NIST / PCI / ...) |
| `asvs_mapping.yaml` schema | Becomes `data/frameworks/asvs/mapping.yaml`; same shape |
| Phase 3 (ECharts graph, planned) | Becomes D3 graph with FRs as central nodes |
| `--compliance-matrix` flag | Stays — backward compat |
| **NEW** `--fr-catalog` flag | Becomes primary input |

**Backward compatibility:** projects that supply only `--compliance-matrix` (no FR catalog) keep working — they get the current scanner-driven Compliance Matrix. Projects that supply `--fr-catalog` unlock the FR-driven model with both tabs available.

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
| **Two data models (scanner-driven + FR-driven) confuse users** | Single dashboard, two tabs, clearly labelled. Eventually scanner-driven view becomes "Quick Mode" and FR-driven is default |

## Critical files (planned)

**New:**
- `data/frameworks/asvs/requirements.json` (moved from `data/sources/asvs_requirements.json`)
- `data/frameworks/asvs/mapping.yaml` (moved from `data/asvs_mapping.yaml`)
- `data/frameworks/nist_800_53/requirements.json`
- `data/frameworks/pci_dss/requirements.json`
- `scripts/build-framework-sources.py` (rename of `build-mapping-sources.py`)
- `scripts/parse_junit.py` — JUnit XML parser
- `scripts/resolve_code_refs.py` — glob/file/symbol resolver
- `scripts/load_fr_catalog.py` — FR JSON validator + loader
- `scripts/generate-dashboard.py` extensions: new FR tab, multi-framework support, D3 graph tab

**Modified:**
- `bin/asvs-scanner` — add `--fr-catalog` flag, `--junit-xml` flag
- `run-local.sh` — thread new flags
- `Dockerfile` — add D3 vendored if we go that route

**Existing (no change):**
- All scanner wiring (Semgrep, Gitleaks, Trivy, Grype, etc.)
- All scanner output parsers (just reframed as test types)
- The dashboard's existing tabs (Overview, Scanners, Findings, Fix Plan)
- The existing Compliance Matrix tab (becomes one of several framework tabs)

## Open questions

1. **JSON schema enforcement** — pydantic, jsonschema, or hand-rolled? Probably jsonschema (no extra dep beyond what's in the image).
2. **D3 vs D3 + WebGL** for very large graphs? Default D3, revisit if performance demands.
3. **Where do JUnit XML files come from in a typical workflow?** User supplies via flag, or scanner runs the tests itself? Default: user supplies (scanner shouldn't run code).
4. **Manual evidence artifacts** (screenshots, docs) — stored where? Just file path references; scanner doesn't store content.
5. **Custom framework loader** — same JSON shape as built-in frameworks, just user-supplied?

## Decision needed before proceeding

- Approve this pivot direction (vs continuing Phase 3 as planned)?
- Endorse the FR JSON schema?
- Pick the next framework to add after ASVS — NIST 800-53 (US gov), PCI-DSS (payment), or ISO 27001 (general)?

Once approved, Phase 1 can start: build the FR catalog parser, `--fr-catalog` flag, and a basic FR list view in the dashboard. That's the foundation everything else hangs off.
