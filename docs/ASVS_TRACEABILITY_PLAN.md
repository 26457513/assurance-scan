# ASVS traceability: compliance matrix + graph view

## Context

The ASVS Scanner currently produces a scanner-driven dashboard (overview, scanners, findings, fix plan). It does not link scanner output back to the compliance spreadsheet (`Barkley_Tapestry_ASVS_Traceability_Matrix_*.csv`, ~990 ASVS requirements). Reviewers cross-reference manually — they look at a Semgrep finding, then hunt through the spreadsheet to find the relevant ASVS row, then write the verdict by hand. That is the workflow we want to kill.

**Vision (end state):** two new dashboard tabs that share one underlying data model:

1. **Compliance Matrix tab** — the spreadsheet rendered with traffic-light status per row, computed from actual scanner output. Click a row → see culprit files (for fails) or clean evidence (for passes).
2. **Traceability Graph tab** — an ECharts force-directed graph showing the chain `ASVS chapter → ASVS requirement → scanner rule → file:line → finding`. Click any node → highlight its chain. Used for audit walkthroughs, not for triage. Also reachable in reverse: from a finding in the existing All Findings tab, jump straight to its ASVS impact.

Both read the same intermediate data: a mapping (`asvs_mapping.yaml`) that links ASVS IDs to scanner rule IDs, cross-referenced against scanner outputs from the current scan.

**Scope of this plan:** three sequential phases. Phase 1 (mapping generation) is the long pole and the foundation; nothing else works without it. Phase 2 (matrix tab) is the workhorse view reviewers live in. Phase 3 (graph tab) is the high-visibility "audit platform" view. Each phase delivers value on its own and unblocks the next.

## Architecture overview

```
                                +---------------------+
                                |  asvs_mapping.yaml  |   (human-curated, in repo)
                                +----------+----------+
                                           |
   ASVS spec CSV -----+                    |
                      |                    v
   scanner rule       |     +-----------------------------------+
   catalogs           +---->|  mapping generator (one-off,      |
                      |     |  LLM-assisted + human review)     |
   (download once)    |     +-----------------------------------+
                      |                    |
                      v                    v
                +---------------------------+
                |  asvs_mapping.yaml v1     |   (committed)
                +------------+--------------+
                             |
                             v
   per-scan inputs           |    at render time
   --------------            |    --------------
   evidence-manifest.json ---+-->+---------------------------------+
   scanner outputs           |   |  generate-dashboard.py          |
   project CSV (Barkley) ----+   |  - reads mapping (bundled)      |
                                |  - reads project CSV (flag)      |
                                |  - reads scanner outputs         |
                                |  - emits dashboard.html          |
                                |  - embeds graph.json payload     |
                                +---------------------------------+
                                              |
                                              v
                                +---------------------------------+
                                |  browser                        |
                                |  - Compliance Matrix tab (HTML) |
                                |  - Traceability Graph tab       |
                                |    (ECharts, CDN-loaded)        |
                                +---------------------------------+
```

**Data shapes:**

- **`asvs_mapping.yaml`** (source of truth, in repo, baked into image). Maps ASVS IDs to scanner rules. Per-entry review state stored as structured fields (not YAML comments) so it survives regen. Lives at `data/asvs_mapping.yaml` in the repo → `/opt/asvs-scanner/data/asvs_mapping.yaml` in the image (Dockerfile's `COPY .` includes it; the existing `rm -rf` step does not touch `data/`).
- **Per-scan graph payload** (`graph.json`, embedded in dashboard HTML as `<script type="application/json" id="traceability-data">`). Same data rendered two ways (table + graph). Machine-generated, never hand-edited.

## Phase 1 — Mapping generation

**Goal:** produce `data/asvs_mapping.yaml` covering the four ASVS 5.0 chapters most tractable to automated mapping, at high quality, plus a thin layer of section-level fallback for the other 13 chapters.

**ASVS 5.0 chapter scope for v1** (chapter numbering changed between ASVS 4.0 and 5.0 — this plan uses 5.0):

| Chapter | Title | Req count (L1+L2 / all) | Why in v1 scope |
|---|---|---|---|
| V1 | Encoding and Sanitization | 23 / 30 | Covered well by Semgrep (injection, encoding, deserialization) |
| V2 | Validation and Business Logic | 13 / 13 | Covered well by Semgrep (input validation, business logic) |
| V13 | Configuration | 16 / 21 | Covered by Trivy config (Dockerfile / k8s / IaC misconfigs) |
| V14 | Data Protection | 11 / 13 | Covered by Grype / Trivy vuln / Gitleaks / Trivy secret |

**v1 curated-mapping scope:** 63 L1+L2 requirements (77 if we include L3). Total ASVS 5.0 universe is 345 requirements (253 L1+L2 / 92 L3), so v1 covers 25% of the L1+L2 surface — the quarter most tractable to automated verification.

Other chapters (V3 Web Frontend, V4 API, V5 File Handling, V6 Authentication, V7 Sessions, V8 Authorization, V9 Tokens, V10 OAuth, V11 Crypto, V12 Comms, V15 Secure Coding, V16 Logging, V17 WebRTC) get section-level fallback only in v1.

### 1.1 Inputs (download once, commit to repo under `data/sources/`)

| Source | URL | Format | Notes |
|---|---|---|---|
| ASVS 5.0.0 standard | `https://github.com/OWASP/ASVS/tree/v5.0.0` under `5.0/en/` | Markdown per chapter (e.g. `0x10-V1-Encoding-and-Sanitization.md`) | Parsed in-repo (no pandoc/dicttoxml dep). Tables with `\| # \| Description \| Level \|` per section. Confirm empirical row counts during §1.1. |
| Project CSV (Barkley) | supplied by user via `--compliance-matrix` at generation time | CSV | Has `Automated Scan Tool` column already encoding mapping hints — feeds LLM as critique target, not as ground truth |
| Semgrep ASVS rules | `https://github.com/semgrep-old/rules-owasp-asvs` | YAML rules | MPL 2.0 license — attribution in `data/sources/LICENSES.md` |
| Semgrep community rules | `https://github.com/semgrep/semgrep-rules` | YAML rules | 4000+ rules; filter to `security-affecting` rulesets (categorisation lives in each rule's `metadata` block — filter on `confidence`, `impact`, `owasp` keys) |
| Trivy misconfig checks | `https://github.com/aquasecurity/trivy-checks` | Rego + metadata | Apache 2.0; IDs like `AVD-DS-0002`; OPA Rego files include title/description/severity |
| Gitleaks rules | `https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml` | TOML | MIT; ~150 rules with IDs + descriptions |
| ZAP passive rules | `https://www.zaproxy.org/docs/alerts/` | Markdown | Apache 2.0; stable IDs (e.g. `10096`); scrape and parse |
| security-headers | `scripts/security-headers.py` (in-repo) | Python source | 6 headers, hardcoded — extract to YAML |
| testssl.sh | `https://github.com/testssl/testssl.sh` | Bash | No stable IDs; map at category level only (TLS protocols, ciphers, etc.) |

A small Python script `scripts/build-mapping-sources.py` clones/fetches each, normalizes to intermediate JSON, and writes `data/sources/<scanner>_rules.json` + `data/sources/asvs_requirements.json`. Reviewers can rerun this when sources update.

**License attribution.** Each source's license + attribution URL is recorded in `data/sources/LICENSES.md` (CC BY-SA for ASVS, MPL 2.0 for Semgrep, Apache 2.0 for Trivy/ZAP, MIT for Gitleaks). Required for ASVS (CC BY-SA) and good practice for the rest.

**Trivy is treated as three sub-scanners** at the mapping layer (one Trivy scan emits three result types that map to different ASVS chapters):

| Sub-scanner | Trivy result key | Maps to ASVS |
|---|---|---|
| `trivy-vuln` | `Results[].Vulnerabilities[]` | V14.1 Dependencies |
| `trivy-config` | `Results[].Misconfigurations[]` | V14.7 Build & Deploy + scattered (e.g. DS-0026 non-root → V12.4 Container) |
| `trivy-secret` | `Results[].Secrets[]` | V8.3 Sensitive Data |

**Scanner Health UI stays unchanged** — Trivy remains one row with one PASS/WARN/FAIL/SKIPPED status in the existing matrix. The 3-way split is purely a mapping-layer distinction, surfaced only in the Compliance Matrix tab where it carries semantic weight.

### 1.2 Mapping generation (LLM-assisted)

Script: `scripts/generate-mapping.py`. Reads the intermediate JSON files + the project CSV, calls Claude per ASVS chapter, produces a candidate YAML.

**Chunking strategy:** one LLM call per ASVS chapter × per scanner sub-type. For the v1 scope (ASVS 5.0 chapters):
- V1 × {semgrep} → 1 call
- V2 × {semgrep} → 1 call
- V13 × {trivy-config} → 1 call
- V14 × {trivy-vuln, trivy-secret, grype, gitleaks, syft, osv-scanner} → 6 calls

~9 calls total. Each call sends the chapter's ASVS rows + the relevant scanner's rules with descriptions, asks the model to emit JSON. The model is told explicitly which (chapter, scanner) pair it's working on; out-of-scope emissions are dropped by the validator.

**LLM input hint — the project CSV column.** The Barkley CSV already has an `Automated Scan Tool` column with values like `"Semgrep (SAST) + manual code review"`. The LLM is given this column as a starting hypothesis per row ("the existing spreadsheet claims Semgrep covers this — do you agree? If yes, with what rule patterns?"). This turns the LLM task from open-ended generation to critique-and-refine, which is more reliable and faster to review.

**Universality.** The CSV hint shapes LLM reasoning but the output `asvs_mapping.yaml` is universal — it does not encode any project-specific applicability or scope decisions, which stay in the CSV. Any project scanning with this scanner stack gets the same ASVS↔rule mapping.

**Parroting guard.** If the LLM agrees with CSV hints ~100% of the time, that's suspicious — either the CSV was already perfect (unlikely) or the LLM is being lazy. The validator (§1.5) reports "% of mappings where LLM agreed with CSV hint vs. modified vs. rejected". If agreement >85%, flag for human spot-check before promoting any entries to `high` confidence.

**Prompt template (stored in `scripts/prompts/asvs-mapping.md`):**
- System: "You map OWASP ASVS requirements to scanner rules. Be conservative — only `high` confidence when the rule clearly verifies the requirement. Include reasoning so reviewers can sanity-check."
- User: chapter context + requirement text + rule list with descriptions + CSV's existing hint for each row
- Output: strict JSON, schema in §1.3 below

Convert JSON output to YAML with `yaml.safe_dump` (standard library `pyyaml`, already implied available — see §Dependencies). No `ruamel.yaml`.

### 1.3 Output schema (`data/asvs_mapping.yaml`)

```yaml
# Auto-generated by scripts/generate-mapping.py on 2026-07-15
# ASVS version: 5.0.0
# Scanner rule snapshots: as of <dates per source>
#
# Per-entry review state lives in the `review` field, NOT in YAML comments.
# This survives regeneration — the generator preserves existing review fields
# when re-running on the same ASVS ID + scanner.
#
# Expected file size: 100-200 KB at full coverage. Use `yq` for command-line
# inspection rather than hand-editing.

version: 1
asvs_version: "5.0.0"

requirements:
  v5.0.0-1.2.4:  # SQL injection prevention
    chapter: "V5.3 Output encoding and Injection Prevention"
    level: L1
    scanners:
      semgrep:
        - rule_id: "python.django.security.injection.sql.*"
          confidence: high
          reasoning: "Semgrep SQL injection ruleset directly verifies parameterized query use in Django ORM code."
          csv_hint_at_generation: "Semgrep (SAST) + manual code review"   # snapshot of CSV's Automated Scan Tool column at last gen
          review:
            status: reviewed          # one of: unreviewed | reviewed | rejected | stale | orphaned
            reviewer: "jon"
            date: "2026-07-15"
            note: "covers SELECT/INSERT/UPDATE/DELETE"
            rule_hash: "sha256:abc123..."   # see hash definition below
      trivy-vuln:
        - rule_id: "CVE-*"
          confidence: low
          reasoning: "Trivy finds vulnerable DB drivers but does not verify query safety. Included only as dependency CVE signal."
          csv_hint_at_generation: ""
          review:
            status: unreviewed
```

**Rule_id semantics.** A string. May be either:
- An exact rule ID (e.g. `DS-0002`) — matches one rule
- A glob pattern (e.g. `python.django.security.injection.sql.*`) — matches multiple rules via `fnmatch.fnmatch`

The LLM may emit either. The generator and dashboard both use `fnmatch` uniformly — exact IDs match themselves under fnmatch, so no special-casing.

**`rule_hash` definition.** SHA-256 of the JSON-normalized `{title, description, severity}` tuple from `data/sources/<scanner>_rules.json`. Canonicalisation: `json.dumps({...}, sort_keys=True, separators=(',', ':'))` then SHA-256. Hashed value stored as `rule_hash: "sha256:<hex>"`. On regen, recompute and compare — mismatch flips `review.status` to `stale`. Cosmetic changes (whitespace, capitalisation in non-hashed fields) do NOT trigger staleness; semantic changes (title/description/severity edits) do.

**Review state lives in data, not comments.** Generator preserves existing `review` blocks when re-running on the same `(asvs_id, scanner, rule_id)` tuple. Reviewers edit the field, never the comments. This survives regen without `ruamel.yaml`.

### 1.4 Review workflow

1. Generator produces v1 of the YAML covering V5, V8, V14.
2. Reviewer runs `scripts/review-mapping.py` — a small TUI that walks entries one at a time, lowest-confidence first. Each screen shows: ASVS requirement text, the rule's description, the LLM's reasoning, and (when present) the CSV hint that was critiqued. Reviewer presses `y` (reviewed, accept), `n` (rejected), `m` (needs discussion, mark medium), or `s` (skip). Writes the `review` block including `rule_hash`.
3. Reviewer eyeballs `high` confidence entries directly in the YAML for obvious false mappings — TUI focuses on the long tail.
4. Commit. The YAML is the source of truth until the next refresh (see §1.6).

**TUI behaviour on stale entries.** Stale entries surface at the top of the review queue. The TUI shows the old reasoning + a diff of the source rule's `{title, description, severity}` (old vs new). Same y/n/m/s treatment as new entries. **Never auto-re-prompt the LLM** — that would silently overwrite reviewed reasoning with potentially different LLM output. Reviewer can manually trigger a re-prompt via a `r` keystroke if they explicitly want fresh LLM input.

**Realistic time estimate:** V5/V8/V14 cover ~200 ASVS rows. Each row averages ~2 mappings → ~400 entries. With the TUI at ~30 seconds per entry, that's ~3-4 hours. Direct YAML review of high-confidence entries: another 2-3 hours. Total ~1 day of focused review.

### 1.5 Validation

Script: `scripts/validate-mapping.py`. Checks:
- Every ASVS ID in the YAML exists in the source CSV (no typos).
- Every `rule_id` resolves against `data/sources/<scanner>_rules.json` — either exact match or glob that matches at least one rule.
- No requirement is left with zero mappings AND marked as `automated` in the CSV (would be a coverage gap).
- Schema conformance (required fields present, `review.status` is one of: `unreviewed | reviewed | rejected | stale | orphaned`).
- **Coverage gap report:** list scanner rules in the source snapshots that aren't referenced by any ASVS row. Useful for "where could we add coverage?" analysis. Output written to `data/sources/coverage-gaps.md` (markdown table), committed on every generator run. CI workflow surfaces the report as a PR comment when changes are detected.
- **Parroting check:** report "% of LLM mappings that agreed with / modified / rejected the CSV hint". Flag if agreement >85% (see §1.2).
- **Orphan detection:** ASVS IDs in the YAML that no longer exist in the project CSV get `review.status: orphaned`. **Never auto-delete** — the mapping might be useful if the row returns in a future CSV revision. TUI surfaces orphaned entries at top of review queue so the reviewer can decide whether to keep, reject, or move to a separate `archived` section.

Runs in CI on every PR touching `data/asvs_mapping.yaml`, `data/sources/**`, or any `scripts/*-mapping.py`.

### 1.6 Updates (regen + merge)

When ASVS publishes a new version, a scanner adds rules, or the project CSV changes:

1. **Refresh sources** — re-run `scripts/build-mapping-sources.py` → refreshes `data/sources/`. **Cadence:** quarterly via maintainer manual trigger (no automation yet — automation is a Phase 4 candidate). Each refresh PR includes a diff of added/removed/changed rule IDs (generated by the build script) to make review tractable.
2. Re-run `scripts/generate-mapping.py --merge` → produces a new candidate YAML. The `--merge` flag means: for every `(asvs_id, scanner, rule_id)` tuple already in the existing YAML, **preserve** the entry as-is, **unless** the source rule's hash differs from the snapshotted `rule_hash` — in which case mark `review.status: stale`. Only LLM-generate mappings for new tuples, stale tuples, or tuples still marked `unreviewed`.
3. **Staleness detection** is automatic via `rule_hash` comparison. Reviewers don't have to spot drift manually.
4. Reviewer runs `scripts/review-mapping.py` again — TUI surfaces stale + new + changed + orphaned entries first, then anything still `unreviewed`.
5. Commit.

This makes ASVS upgrades and scanner refreshes cheap. The merge is conservative — once a human has reviewed a mapping, the LLM doesn't second-guess it unless the underlying rule actually changed.

### 1.7 Dependencies

The scanner image (`docker:27-cli` + `apk add python3`) needs these additional Python packages for the mapping lifecycle:

| Package | Used by | Notes |
|---|---|---|
| `pyyaml` | generator, validator, dashboard | Standard YAML I/O. Already implied; pin in requirements. |
| `requests` | `build-mapping-sources.py` | Fetching ASVS CSV, scanner rule files |
| `anthropic` | `generate-mapping.py` | Claude API client for mapping generation |
| `prompt_toolkit` | `review-mapping.py` | Pleasant TUI: side-by-side ASVS text + rule description, proper line wrapping, keybinding hints |

Add to a new `requirements-mapping.txt` (separate from runtime scanner deps — these are dev/maintainer tools, not needed in every scan). The Dockerfile stays unchanged; mapping tools run on the maintainer's machine, not inside the scan image.

Maintainer-side env: `ANTHROPIC_API_KEY` (Claude API access). Document in `scripts/generate-mapping.py --help` and the README's "Publishing A New Version" section.

The scan image only needs `pyyaml` to **read** the mapping at render time. `pyyaml` is part of standard Python image; verify it's installed in `scripts/preflight.sh` and add to the Dockerfile's `apk add` if missing.

### 1.8 Testing

| Test type | What | Where | CI |
|---|---|---|---|
| Unit | Traffic-light computation, rule pattern matching, NA handling, orphan handling, staleness detection | `scripts/test_compliance_matrix.py` | yes |
| Schema | Mapping YAML conformance (already in `validate-mapping.py`) | `scripts/validate-mapping.py` | yes |
| Snapshot | Rendered dashboard HTML for a fixture scan; PR-affecting changes require snapshot update (reviewable diff) | `tests/fixtures/sample-scan/` + `scripts/test_dashboard_snapshot.py` | yes |

Unit tests target the pure functions in §2.3 (compliance computation) and §1.5 (validation). Fast (<5s), no fixtures needed.

Snapshot test uses a committed sample scan output. Any change that affects rendering produces a diff in the snapshot file — reviewer sees the diff in the PR and either accepts (updates snapshot) or rejects (fixes the regression). Catches unintended visual/data regressions across all tabs, not just the new ones.

## Phase 2 — Compliance Matrix tab

**Goal:** a new dashboard tab showing the project CSV with computed traffic-light status per row, clickable to culprit files.

### 2.1 CLI wiring

- `bin/asvs-scanner`: accept `--compliance-matrix <path>` flag in the `scan` subcommand. Mirror the existing `--uploads` handling at line ~500: call `to_abs_path` to resolve to absolute, validate the file exists at scan time, pass through to `run-local.sh` via env (`ASVS_COMPLIANCE_MATRIX`). The CSV must be visible inside the container at the same absolute path (covered by the existing `"(dirname "$PWD"):(dirname "$PWD")"` mount — same pattern as the target repo itself).
- `run-local.sh`: thread the env var to `generate-dashboard.py` via a new `--compliance-matrix` flag.
- `scripts/generate-dashboard.py`: if flag is set, render the Compliance Matrix tab; if not, omit it entirely (no empty tabs).

### 2.2 CSV parsing

The Barkley CSV has 17 columns. Handling per column:

| Column | Action |
|---|---|
| `ASVS ID`, `Chapter`, `Section`, `Level`, `Requirement`, `Evidence Ref`, `Test Case Ref`, `Pen-test scope`, `Owner`, `Notes` | Keep, render in table or expandable detail |
| `Applicability` | Keep. Drives a distinct "Not Applicable" traffic-light state when value is `N/A` (see §2.3) |
| `Status` | Keep as a secondary column labelled "CSV Status" — reviewers compare the spreadsheet's declared status against the dashboard's computed status. **Not** used to compute traffic lights. |
| `Justification` | Move into expandable detail (long text, clutters table) |
| `Automated Scan Tool` | Drop from view (the mapping implies this; redundant) |
| `Tool Selection Rationale` | Drop from view (decision-process column, not data reviewers need) |

Parsing uses Python's `csv` module with `encoding='utf-8-sig'` to handle BOM and `errors='replace'` for any non-UTF-8 bytes (the Barkley CSV has copy-paste from Word, occasional smart quotes / em-dashes). One gotcha: the file has 3 preamble rows before the header (title, description, blank). Skip until the header row detected by `ASVS ID` literal.

### 2.3 Traffic-light computation

For each CSV row:

1. **Check `Applicability` first.** If the value is `N/A` (case-insensitive) → row is **NA** (distinct from "no coverage"). Visual: diagonal-stripe grey badge with literal "N/A" text, different from solid grey used for "no automated coverage". Show the justification from the `Justification` column in the expandable detail. Skip the rest of the computation.
2. **Look up `asvs_id` in `asvs_mapping.yaml`.** Get the per-scanner rule lists.
3. **For each scanner in the mapping:**
   - If scanner was SKIPPED this run → contributes AMBER.
   - If scanner ran and has 0 findings matching the rule patterns → contributes GREEN.
   - If scanner ran and has 1+ findings matching the rule patterns → contributes RED, with file:line list of **matching** findings.
4. **Roll up per row:**
   - Any RED → row is RED.
   - Else any AMBER → row is AMBER.
   - Else any GREEN → row is GREEN.
   - No mappings → row is GREY (no automated coverage — manual evidence required, link to manual checklist).

**Rule pattern matching** uses `fnmatch.fnmatch(rule_id, pattern)`. A scanner with 50 unrelated findings still verifies a row GREEN if none of those findings' rule IDs match the mapped patterns. The detail panel shows "0 matching findings" with the patterns checked, not "0 findings" — important distinction.

**Trivy sub-scanner split.** Trivy's three result types (`Vulnerabilities`, `Misconfigurations`, `Secrets`) are evaluated as three separate sub-scanners per §1.1. A single Trivy run contributes up to three independent traffic-light signals to a row.

### 2.4 Render

New function `render_compliance_matrix(csv_path, mapping, evidence, report_dir) -> str` in `generate-dashboard.py`. Emits a card containing:

- **Top:** summary tiles — X red, Y amber, Z green, W grey (uncategorized), V NA. Plus a single **"ASVS Coverage" KPI** computed as: `(Z / (X + Y + Z + W)) * 100` — N/A rows (`V`) excluded from the denominator. Display: `"Z of X+Y+Z+W applicable L1+L2 requirements covered (V excluded as N/A)"`. Mirrors the existing assurance KPIs on the Overview tab.
- **Group by chapter:** rows grouped under collapsible chapter headers (V1, V5, V8, ...), same pattern as the existing Scanner Matrix. Makes 990 rows scannable.
- **Filter bar:**
  - Free-text search by ASVS ID
  - Chapter dropdown (defaults to "all")
  - **Level filter:** L1 / L1+L2 / L1+L2+L3 (Barkley's audit is L2 — defaults to L1+L2)
  - Status filter: red / amber / green / grey / NA / all
  - **Culprit location filter:** free-text, matches against file paths OR URLs/endpoints in any RED finding attached to a row. Drives the codeowner workflow ("show me ASVS rows threatened by findings in `src/api/users.py`"). Renamed from "file filter" to cover ZAP/security-headers/testssl findings which don't have file paths.
- **Table:** columns = Traffic Light | ASVS ID | Section | Level | Requirement (truncated) | Applicability | CSV Status | Scanner count. Each row clickable.
- **Expanded row (on click):** full Requirement text, Justification, Evidence Ref, Test Case Ref, Notes.
  - If RED: list of culprit findings (scanner, rule_id, location, message, severity) — each clickable to jump to the All Findings tab filtered to that finding.
  - If GREEN: list of "verified by" scanners with **"0 matching findings"** against the listed rule patterns.
  - If AMBER: explanation of why (scanner skipped, manual evidence needed).
  - If GREY: list of suggested manual evidence items from `manual-evidence-required.md`.
  - If NA: the justification text from the CSV.

**Accessibility:**
- All traffic-light states have `aria-label` text ("fail", "manual", "pass", "no coverage", "not applicable"). Color is never the sole signal — colourblind users see the label.
- NA and GREY badges have distinct text labels ("N/A" vs "no coverage") AND distinct visuals (diagonal stripe vs solid), so they're differentiable by either modality.
- Table rows are keyboard-navigable: `tab` moves between rows, `enter` expands. Filter controls are reachable via keyboard. Expanded-row content announces via `aria-live="polite"`.
- Culprit findings list is a nested list with proper `role="list"` and `role="listitem"` semantics.

**Performance budget:** rendering the matrix should take <5s for 990 rows. Implementation precompiles fnmatch patterns per (scanner, rule_id) pair and caches per-scanner finding lists. If render time exceeds 10s, log a warning in `run.log`. The dominant cost is the per-row rule-pattern matching loop; the cache makes it O(rows × patterns) instead of O(rows × patterns × findings).

### 2.5 Files to modify

| File | Change |
|---|---|
| `bin/asvs-scanner` | Accept `--compliance-matrix` flag (mirror `--uploads` handling ~line 500), validate path, set env var |
| `run-local.sh` | Pass `ASVS_COMPLIANCE_MATRIX` through to dashboard generator |
| `scripts/generate-dashboard.py` | New `render_compliance_matrix()`, new tab wiring (~lines 1781, 1809 for tab buttons and panels), traffic-light computation helpers, ASVS Coverage KPI on Overview |
| `data/asvs_mapping.yaml` | The mapping file from Phase 1 (read at render time) |
| README.md | Document the new flag and tab |

## Phase 3 — Traceability Graph tab

**Goal:** an ECharts force-directed graph for visual exploration of the traceability chain. Layered on the same mapping + findings data as Phase 2.

### 3.1 Graph data shape

Per-scan JSON payload embedded in dashboard HTML:

```json
{
  "nodes": [
    {"id": "chapter:v5", "type": "chapter", "label": "V5 Validation, Sanitization & Encoding", "status": "fail"},
    {"id": "req:v5.0.0-1.2.4", "type": "requirement", "label": "SQL injection prevention", "status": "fail", "level": "L1"},
    {"id": "scanner:semgrep", "type": "scanner", "label": "Semgrep"},
    {"id": "rule:semgrep:python.django.security.injection.sql.sql-injection", "type": "rule", "label": "Python SQL Injection"},
    {"id": "finding:semgrep:0a1b2c", "type": "finding", "label": "SQL injection", "severity": "high"},
    {"id": "file:src/api/users.py", "type": "file", "label": "users.py", "finding_count": 3}
  ],
  "edges": [
    {"source": "chapter:v5", "target": "req:v5.0.0-1.2.4", "type": "contains"},
    {"source": "req:v5.0.0-1.2.4", "target": "rule:semgrep:python.django.security.injection.sql.sql-injection", "type": "verified_by"},
    {"source": "scanner:semgrep", "target": "rule:semgrep:python.django.security.injection.sql.sql-injection", "type": "owns"},
    {"source": "rule:semgrep:python.django.security.injection.sql.sql-injection", "target": "finding:semgrep:0a1b2c", "type": "emits"},
    {"source": "finding:semgrep:0a1b2c", "target": "file:src/api/users.py", "type": "located_at"}
  ]
}
```

Generator: `build_traceability_graph(mapping, evidence, scanner_outputs) -> dict`. Same input data as Phase 2; different shape.

If no `--compliance-matrix` flag was supplied, the graph payload is empty and the Traceability tab is omitted entirely (same pattern as Phase 2).

### 3.2 ECharts integration + entry points

ECharts loaded from CDN (`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`). One `<script>` tag in the dashboard. Falls back gracefully to a "graph unavailable (offline)" message if CDN unreachable — the table view in Phase 2 still works because it doesn't depend on ECharts.

New tab: `<div class="panel" id="tab-traceability">`. Contains:
- A sidebar of "scoped entry points" — Chapter selector (V1-V17), Scanner selector, Status selector (only failing, only passing, etc.), **specific finding ID** (passed as URL hash for cross-tab navigation). Default: "V5 + only failing."
- Main canvas: ECharts graph.
- Click handler: clicking a node opens the right-side detail panel (same content as Phase 2 expanded row).

**Cross-tab navigation — two directions:**

1. **Requirement → Graph.** From a row in the Compliance Matrix tab, a "Show in graph" button jumps to the Traceability tab with that requirement pre-centered.
2. **Finding → Graph.** From any row in the existing All Findings tab, a "Find ASVS impact" button jumps to the Traceability tab with that finding pre-centered. This is the high-value triage interaction: "Semgrep fired this SQL injection at users.py:42 — which ASVS rows does it threaten?"

Both work by setting `location.hash = '#traceability/center/<node-id>'` and having the graph tab's load handler read the hash. The hash survives refresh on `file://` URLs in modern browsers.

### 3.3 Performance — don't try to render 10k nodes

A naive "show everything" graph with ~990 requirements + thousands of rules + thousands of files is a hairball. Mitigations:

- **Scoped entry points.** User picks a chapter, a scanner, or a requirement before the graph loads. Default scope caps at one chapter + one status filter.
- **Collapsible categories.** "Files" are collapsed by default — expand to see them. Otherwise every Semgrep finding doubles the node count.
- **Pinned layouts.** Use fixed positions for chapter nodes (circle around the perimeter), force-directed only within a chapter. Visually stable across renders.
- **Soft cap.** If a scoped view would render >500 nodes, render the first 500 (highest-severity first) and show a non-blocking banner at top: "Displaying 500 of N — narrow filters to see all". Users still get value from a partial view; the banner makes the limit visible without blocking exploration.
- **Sub-chapter auto-scope.** If a single chapter still exceeds the cap (V14 is the likely candidate — 30+ requirements × multiple scanners), automatically sub-scope by section (V14.1, V14.2, etc.) and surface the active section in the sidebar. User can navigate sections without re-filtering.

### 3.4 Files to modify

| File | Change |
|---|---|
| `scripts/generate-dashboard.py` | New `render_traceability_graph()` function, new `build_traceability_graph()` helper, new tab wiring, ECharts `<script>` tag, hash-based cross-tab nav handlers, "Find ASVS impact" button on All Findings rows |
| `scripts/generate-dashboard.py` (CSS) | Add styles for the graph panel, sidebar, detail pane |
| README.md | Brief mention of the graph tab and its scope limitations |

No CLI changes — the same `--compliance-matrix` flag enables both Phase 2 and Phase 3.

## Critical files

**Existing, modified:**
- `bin/asvs-scanner` — `--compliance-matrix` flag in `scan` case (around line 477)
- `run-local.sh` — env var threading (near other `--image` / `--url` parsing around line 322)
- `scripts/generate-dashboard.py` — bulk of the work; new render functions, tab wiring, embedded graph payload, ASVS Coverage KPI

**New, in repo:**
- `data/asvs_mapping.yaml` — the curated mapping
- `data/sources/asvs_requirements.json` — ASVS spec snapshot
- `data/sources/{semgrep,trivy-vuln,trivy-config,trivy-secret,gitleaks,zap,security-headers,testssl}_rules.json` — scanner rule snapshots
- `data/sources/LICENSES.md` — license attribution for each source
- `data/sources/coverage-gaps.md` — auto-generated coverage gap report
- `scripts/build-mapping-sources.py` — fetches and normalizes source data
- `scripts/generate-mapping.py` — LLM-assisted mapping generator with `--merge` mode
- `scripts/validate-mapping.py` — schema/coverage validation, orphan-rules report, parroting check
- `scripts/review-mapping.py` — interactive TUI for review pass
- `scripts/test_compliance_matrix.py` — unit tests for §2.3 logic
- `scripts/test_dashboard_snapshot.py` — snapshot test for rendered dashboard
- `tests/fixtures/sample-scan/` — fixture scan data for snapshot tests
- `scripts/prompts/asvs-mapping.md` — prompt template for the LLM
- `requirements-mapping.txt` — Python deps for maintainer-side tooling (pyyaml, requests, anthropic, prompt_toolkit)
- `.github/workflows/validate-mapping.yml` — CI check; triggers on PRs touching `data/asvs_mapping.yaml`, `data/sources/**`, or any `scripts/*-mapping.py`

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **False "pass" signals** from wrong rule-to-ASVS mappings | Every mapping entry carries `confidence` + `reasoning`. Low/medium confidence → row stays amber, never auto-greens. Reviewed entries get a `review.status` field so we know which to trust. |
| **LLM produces broken YAML** | Generator emits JSON, converts to YAML via `yaml.safe_dump`. Schema validation in CI catches malformed entries. |
| **Mapping goes stale** (new ASVS version, new scanner rules) | `build-mapping-sources.py` is idempotent and re-runnable. `generate-mapping.py --merge` preserves human-reviewed entries. `rule_hash` snapshot detects semantic drift in underlying rules. CI runs `validate-mapping.py` which fails if rule IDs in the YAML don't exist in the source snapshots. |
| **LLM parrots CSV hint instead of critiquing** | Parroting guard: validator reports agreement %. >85% agreement flagged for spot-check. |
| **ECharts CDN unreachable** in airgapped scans | Phase 2 table view does not depend on ECharts — graph tab shows "offline" message, rest of dashboard works. Could vendor ECharts into the image later if needed. |
| **10k-node hairball** makes graph unusable | Scoped entry points + collapsible categories + per-chapter rendering cap + soft cap with banner + sub-chapter auto-scope. |
| **Project CSV format drifts** (Barkley changes columns) | CSV parser is defensive: required columns = `ASVS ID`, `Requirement`, `Applicability`; others optional. Unknown columns ignored. |
| **Review burden too high** | TUI focuses on lowest-confidence entries first. Reviewer presses y/n/m/s — ~30s per entry, ~1 day total for v1 scope. |
| **LLM cost / token usage** | ~11 calls × ~50k tokens each = ~550k tokens per generation pass. Cheap at Claude Sonnet rates (~$5). Regeneration only on ASVS or scanner updates — not per scan. |
| **Colourblind or screen-reader users can't distinguish traffic lights** | All states have `aria-label` text and distinct text labels, not just colour. |
| **Phase 2 bug breaks opted-in dashboards** | `--compliance-matrix` is opt-in; omit the flag and dashboard reverts to current behaviour. Mapping file is read-only at scan time; no irreversible state changes. |
| **Maintainer skips source refresh for too long** | Quarterly cadence documented; staleness detector catches per-rule drift when refresh does happen. Adds Risks row to README's "Publishing" section as reminder. |
| **CSV removed mid-audit** (Barkley drops ASVS rows) | Orphaned mappings preserved with `review.status: orphaned`; TUI surfaces for human decision; never auto-deleted. |

## Verification

**Phase 1 (mapping):**
```bash
# Install maintainer-side deps
pip install -r requirements-mapping.txt
export ANTHROPIC_API_KEY=...

# Generate fresh source snapshots
python3 scripts/build-mapping-sources.py

# Generate candidate mapping for V5, V8, V14
python3 scripts/generate-mapping.py --chapters V5,V8,V14 \
  --compliance-csv /path/to/Barkley_csv \
  --output data/asvs_mapping.yaml

# Validate
python3 scripts/validate-mapping.py data/asvs_mapping.yaml
# Expect: 0 schema errors, ~200 rows covered, every rule_id resolves,
#         coverage-gaps.md refreshed, parroting % within bounds,
#         orphan check passes (no rows removed from CSV since last gen)

# Review pass (interactive TUI)
python3 scripts/review-mapping.py data/asvs_mapping.yaml

# Run unit tests
pytest scripts/test_compliance_matrix.py
```

**Phase 2 (compliance matrix):**
```bash
# Rebuild image (mapping is baked in via COPY .)
docker build -t asvs-scanner:latest .

# Run a scan with the CSV
docker run --rm -it -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" -w "$PWD" \
  asvs-scanner:latest scan "$PWD" \
  --compliance-matrix "$PWD/Barkley_Tapestry_ASVS_Traceability_Matrix.csv"

# Open the dashboard, click "Compliance Matrix" tab
# Expect:
#   - Rows grouped by chapter, ~990 total visible
#   - Traffic lights match expectations (rows mapped to Semgrep should be red
#     if Semgrep fired matching rules)
#   - Filter by Level=L1+L2 narrows to ~253 rows
#   - Filter by Culprit Location "src/api/users.py" shows only rows with findings there
#   - N/A rows render with diagonal-stripe N/A badge and show justification on click
#   - CSV Status column preserved next to computed traffic light
#   - Click a red row → culprit findings listed, each clickable to All Findings tab
#   - Click a green row → "verified by <scanner>, 0 matching findings"
#   - Click a grey row → "no automated coverage, see manual checklist"
#   - ASVS Coverage KPI shows "Z of X+Y+Z+W applicable requirements covered (V excluded as N/A)"
#   - Screen reader announces traffic light state via aria-label
#   - Tab/enter keyboard navigation works through rows and filters

# Snapshot test
pytest scripts/test_dashboard_snapshot.py
```

**Phase 3 (graph):**
```bash
# Same scan as above; click "Traceability Graph" tab
# Expect:
#   - Sidebar with chapter/scanner/status selectors
#   - Default view loads "V5 + failing" → graph renders with <200 nodes
#   - Click any requirement node → right pane shows same content as Phase 2 row
#   - Click any file node → jumps to All Findings tab filtered to that file
#   - From All Findings tab: click "Find ASVS impact" on a finding → graph opens centered on that finding
#   - ECharts loads from CDN; if offline, message shown, rest of dashboard works
#   - Soft cap: selecting "V5 + all" or "all chapters + failing" triggers
#     banner "Displaying 500 of N — narrow filters to see all"
#   - Sub-chapter auto-scope: V14 alone triggers sub-scope to V14.1, V14.2, etc.
```

## Sequencing and time estimates

| Phase | Calendar time | Notes |
|---|---|---|
| Phase 1.1 (sources ingestion + LICENSES.md) | 1-2 days | Mostly mechanical; test that all sources fetch cleanly. Trivy split into 3 sub-scanners adds modest effort. Confirm empirical ASVS row counts before starting. |
| Phase 1.2 (LLM generation + prompt iteration + parroting guard) | 1-2 days | Iterate on prompt template; LLM gets CSV hint column as input. |
| Phase 1.4 (human review via TUI) | ~1 day | Faster than originally estimated thanks to TUI + CSV-seeded mappings + staleness auto-flagging. |
| Phase 1.8 (testing infrastructure) | 1 day | Unit + snapshot test scaffolding; runs in CI from day one. |
| Phase 2 (compliance matrix) | 5-7 days | Adds Level filter, culprit-location filter, chapter grouping, N/A handling, CSV Status column, accessibility pass, unit + snapshot tests. |
| Phase 3 (graph view) | 2-3 weeks | ECharts learning curve + perf tuning + cross-tab navigation (both directions) + soft-cap UX + sub-chapter auto-scope + accessibility. |

**Total:** ~4-5 weeks of focused work. Phase 1 review can overlap with starting Phase 2.

## Out of scope (Phase 4 candidates)

- Inline status editing (Pending → Pass) with persistence — would create a second source of truth.
- Audit PDF export of a single requirement's full traceability chain.
- Saved graph views (re-openable layouts).
- Extending mapping to all 14 ASVS chapters — only after V5/V8/V14 patterns are proven.
- Versioning the mapping per ASVS release (4.0.x vs 5.0.x simultaneously).
- Vendor ECharts into the image for airgapped graph support.
- Extend mapping to ingest commercial scanner outputs (Snyk, Veracode) — would require their CLI/API integration.
- Automate quarterly source refresh via scheduled GitHub Action.
- Diff tooling for CSV hint evolution (track how Barkley's `Automated Scan Tool` column changes between revisions).
