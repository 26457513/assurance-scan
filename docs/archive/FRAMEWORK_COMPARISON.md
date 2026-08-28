# Framework Comparison: ASVS vs NIST 800-53

> **Status: Historical.** This doc was written during Phase 0 to validate the FR schema design against two structurally different frameworks. The schema refinements it proposed were incorporated into [FR_TRACEABILITY_PIVOT.md](FR_TRACEABILITY_PIVOT.md) (specifically: evidence promoted to typed entries, parent field for hierarchical frameworks, satisfies with status="na"). For the current schema, see [FR_TRACEABILITY_PIVOT.md](FR_TRACEABILITY_PIVOT.md) and [`backend/resources/schemas/fr-catalog.schema.json`](../../backend/resources/schemas/fr-catalog.schema.json). This doc is kept as a record of the design rationale; no longer the source of truth.

## Why this doc exists

Before finalising the FR JSON schema (see [FR_TRACEABILITY_PIVOT.md](FR_TRACEABILITY_PIVOT.md)), we need to see how real compliance frameworks are structured. If the FR schema is designed against only one framework, it bakes in that framework's idiosyncrasies. By comparing two structurally different frameworks — ASVS (testable "verify" statements with maturity levels) and NIST 800-53 (imperative controls with hierarchical enhancements and baseline allocations) — we identify which fields are universal and which need framework-specific extensions.

This doc uses snapshots in `backend/resources/sources/asvs_requirements.json` (345 reqs) and `backend/resources/sources/nist_800_53_requirements.json` (1196 controls) produced by `backend/scripts/build-mapping-sources.py`.

## Side-by-side structure

| Property | ASVS 5.0 | NIST 800-53 Rev 5 |
|---|---|---|
| **Source format** | Markdown per chapter | OSCAL JSON |
| **Total entries** | 345 | 1196 |
| **Top-level grouping** | Chapter (V1–V17) | Family (AC, AT, AU, ... — 20 families) |
| **Sub-grouping** | Section (V1.1, V1.2, ...) | Control + enhancement (`ac-2`, `ac-2(1)`) |
| **Entry ID format** | `v5.0.0-1.1.1` (versioned dotted) | `ac-1` or `ac-2(1)` (family-number-enhancement) |
| **Description style** | "Verify that..." (testable statement) | "Develop, document, disseminate..." (imperative with parameter placeholders) |
| **Maturity scoping** | Level (L1, L2, L3) per row, in the row | Baselines (LOW, MODERATE, HIGH, PRIVACY) in separate profile files, not per-row |
| **Parameterisation** | None — descriptions are concrete | `{{ insert: param, ac-1_prm_1 }}` placeholders, parameters listed separately |
| **Hierarchy** | Flat (chapter → section → requirement, no parents) | Two-level (control → enhancement, with `parent` field) |
| **License** | CC BY-SA 4.0 | US Government work — public domain |
| **Update cadence** | Yearly (~5.0 → 5.0.1 patches) | Yearly (Rev 5 → 5.1 → 5.2 ...) |

## Sample entries

### ASVS

```json
{
  "id": "v5.0.0-1.1.1",
  "chapter": "V1",
  "section": "V1.1",
  "section_name": "Encoding and Sanitization Architecture",
  "level": 2,
  "description": "Verify that input is decoded or unescaped into a canonical form only once...",
  "source_file": "0x10-V1-Encoding-and-Sanitization.md"
}
```

### NIST 800-53

```json
{
  "id": "ac-1",
  "family": "AC",
  "family_title": "Access Control",
  "title": "Policy and Procedures",
  "description": "Develop, document, and disseminate to {{ insert: param, ac-1_prm_1 }}...",
  "class": "SP800-53"
}
```

With enhancement:

```json
{
  "id": "ac-2(1)",
  "family": "AC",
  "family_title": "Access Control",
  "parent": "ac-2",
  "title": "Automated System Monitoring and Alerts",
  "description": "...",
  "class": "SP800-53-enhancement"
}
```

## Universal fields (present in both)

These are the **must-haves** for any framework entry:

| Field | Purpose | ASVS | NIST |
|---|---|---|---|
| `id` | Stable identifier, used in FR `satisfies` mappings | `v5.0.0-1.1.1` | `ac-1` |
| `title` | Short label | (none — ASVS uses section_name + description) | `Policy and Procedures` |
| `description` | Full prose | "Verify that..." | "Develop, document, disseminate..." |

**FR schema field:** `satisfies: [{framework, row}]` — `row` is just the `id` from the framework. That part of the schema is stable across frameworks.

## Framework-specific fields

These vary per framework and shouldn't be hardcoded into the universal FR schema:

| Field | Framework | Used for |
|---|---|---|
| `level` (L1/L2/L3) | ASVS | Maturity scoping, per-row |
| `chapter`, `section`, `section_name` | ASVS | Grouping for UI |
| `family`, `family_title` | NIST | Grouping for UI (equivalent role to ASVS chapter) |
| `parent` | NIST | Hierarchical enhancements |
| `class` | NIST | Distinguishes base control vs enhancement |
| `parameters` | NIST | Parameterised descriptions (`ac-1_prm_1`) |
| Baseline allocations (LOW/MOD/HIGH) | NIST | Scoping by deployment sensitivity |

**Decision:** these stay in the framework-specific snapshot JSON, not in the universal FR schema. The FR schema just references the framework row by ID; the framework's own snapshot provides the rest of the structure when rendering.

## Description text differences — important

This is the most consequential structural difference:

**ASVS descriptions are testable statements:**
> "Verify that input is decoded or unescaped into a canonical form only once..."

A scanner finding directly answers whether this is true. The test → evidence chain is natural.

**NIST descriptions are imperative controls:**
> "Develop, document, and disseminate to {{ insert: param, ac-1_prm_1 }}..."

These describe a control implementation, not a verifiable claim. The placeholders (`{{ insert: param, ... }}`) need to be filled in with project-specific values. A scanner finding rarely answers whether a NIST control is "implemented" — that's a manual/operational question.

**Implication for the FR schema and dashboard:**

1. For ASVS rows, traffic-light computation works (scanner finding → red/green).
2. For NIST rows, traffic-light computation mostly doesn't work — most NIST controls are operational/policy, not scanner-testable. They'll show as amber/grey unless explicitly mapped to a scanner or test.
3. **The dashboard must distinguish "scanner-verified" from "manually-verified" evidence types.** A control can be satisfied by:
   - Scanner pass (green, automated)
   - Test pass (green, automated, evidence = JUnit XML)
   - Manual artifact (green, manual, evidence = doc reference)
   - Or none of the above (amber/grey)

This was already implied in the FR schema (`verified_by` array with type field), but NIST makes it essential — without manual evidence support, most NIST rows can never go green.

## Refinements to the FR schema

Based on the comparison, three changes to the FR schema proposed in [FR_TRACEABILITY_PIVOT.md](FR_TRACEABILITY_PIVOT.md):

### 1. Make `evidence` first-class (not just a tag)

Current proposal had `evidence` as a flat list. Promote to typed entries matching `verified_by` semantics:

```json
"evidence": [
  {"type": "scanner", "ref": "semgrep:python.security.injection.sql.*", "status": "auto"},
  {"type": "test", "ref": "tests/auth/test_login.py::test_valid_credentials", "status": "auto"},
  {"type": "manual", "ref": "docs/auth-design.md", "status": "manual"},
  {"type": "screenshot", "ref": "docs/screenshots/login-flow.png", "status": "manual"}
]
```

The `status` field drives traffic-light computation: `auto` = green/red based on result, `manual` = always green if file exists.

### 2. Add `parent` field for hierarchical frameworks

Some FRs may be sub-requirements of others (mirrors NIST enhancements). Add optional `parent`:

```json
{
  "id": "FR-001.1",
  "parent": "FR-001",
  "title": "OAuth session expiry",
  ...
}
```

Not all projects use this; the field is optional. Rendered as a collapsible sub-requirement in the UI.

### 3. Framework rows can be N/A explicitly

The original FR schema assumed `satisfies` lists frameworks the FR addresses. We also need a place to mark framework rows as out-of-scope per project:

```json
"satisfies": [
  {"framework": "ASVS", "row": "v5.0.0-6.1.1", "status": "satisfied"},
  {"framework": "ASVS", "row": "v5.0.0-6.1.5", "status": "na", "reason": "Project doesn't use biometric auth"}
]
```

`status: "satisfied"` is the default; `status: "na"` lets the project explicitly mark rows as out-of-scope with reasoning, which is what the user wants to see in the UI ("this row is out of scope because...").

## What other frameworks will likely add

We don't have NIST CSF, ISO 27001, or PCI-DSS sources yet (paid or behind logins). Predicting their structure from public docs:

| Framework | Expected new field | Why |
|---|---|---|
| **NIST CSF 2.0** | Function / Category / Subcategory hierarchy (3 levels, like ASVS section) | CSF is structured as Function → Category → Subcategory |
| **ISO 27001:2022** | Annex A vs Clause 4-10 split | Two distinct sections — Annex A is the 93 controls, Clauses 4-10 are the ISMS requirements |
| **PCI-DSS 4.0** | Requirement group + sub-requirement (12 main reqs, ~280 sub-reqs) | Hierarchical, like NIST enhancements |

None of these break the universal FR schema. They all reduce to: ID + title + description + framework-specific grouping + optional parent. The current schema accommodates them.

## Open questions (deferred to schema v1 implementation)

1. **Parameter substitution for NIST descriptions.** Do we strip `{{ insert: param, X }}` placeholders and render as `[Parameter X]` for display? Or expose the parameters list and let users fill them in per-project?
2. **Baseline allocation for NIST.** When a project specifies "we're a MODERATE baseline," do we filter the visible NIST rows automatically?
3. **Cross-framework mapping.** Some controls overlap (ASVS V8 Authorization ↔ NIST AC-2 ↔ ISO A.9). Should the FR schema support `equivalent_to: [{framework, row}]` to inherit coverage? Probably not in v1 — adds complexity; can be a derived view later.

## Recommendation

The FR schema proposed in the pivot doc is sound, with three refinements above. Implementing v1 against ASVS + NIST 800-53 covers both styles (testable + imperative) and the structural variations (flat + hierarchical, level-based + baseline-based scoping). When CSF/ISO/PCI sources are added later, the schema extends without breaking changes.

**Next:** start implementing Phase 1 of the pivot — FR catalog parser + `--fr-catalog` flag + basic FR list view. The schema is now stable enough to code against.
