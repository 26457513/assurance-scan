# Framework Cockpit Design

## Status

**Draft target schema model for review.** This captures the schema/JSON structure for the new assurance cockpit approach. Draft target schema files, review fixtures and validators now exist, while some runtime graph builders and dashboard projections are still being tightened to consume the model consistently.

There is no backward compatibility requirement for this design. The goal is one clean, complete set of schemas that works for the new approach.

Changes since the previous review:

- Keeps FR as **Functional Requirement**.
- Makes **TBT Test Basis** a first-class object.
- Splits `framework` into `ruleset` and `assurance_framework`.
- Removes process `levels` in favour of the settled `assurance_profiles` schema field.
- Adds unified status vocabularies, evidence policy, complete schema inventory and implementation sequencing.
- Adds draft target JSON Schema files and small cross-linked fixtures for review.
- Adds dependency-free cross-file fixture validation for IDs and provenance links that JSON Schema cannot enforce.

## Relationship To Runtime Graph Architecture

This document describes the framework cockpit user experience and the config required to support it. `docs/RUNTIME_GRAPH_ARCHITECTURE.md` is the authoritative runtime architecture for graph construction, graph projections, provenance manifests, audit chains and zero-knowledge proof readiness.

`docs/ASSURANCE_PLANNING_STUDIO.md` is the authoritative upstream model for
project planning, config selection, blueprint review, approved design contracts
and downstream handoff. The cockpit should display the approved obligations and
runtime evidence derived from that contract; it should not create or approve the
planning contract itself.

The frontend should carry very little assurance logic. It should render precomputed graph projections, apply user-facing filters, expand selected nodes, copy generated prompts/commands and show context. It must not be the source of truth for:

- FR/TBT sufficiency
- gate readiness
- compliance-row pass/fail state
- scanner blocking semantics
- waiver or compensating-control effects
- evidence provenance
- proof/audit manifest generation

Those decisions belong in the backend graph/status engine. The dashboard payload may cache convenient projections for static rendering, but every projection must trace back to graph nodes, graph edges and versioned source artifacts.

Gate and criterion readiness follow the same rule. When a framework criterion or assurance-instance mapping points to an FR, TBT or compliance row, the cockpit displays the backend-resolved graph status for that target, including direct scanner blockers inherited from mapped compliance rows. The browser can filter, group and explain those blockers; it must not recompute whether they block the gate.

Superseded or historical design docs are kept in `docs/archive/` and may also exist in generated runtime mirrors for older reports. They are not authoritative for new cockpit, graph, schema, audit or proof work.

## Implementation Status

| Area | Current position | Target |
|---|---|---|
| Ruleset, FR, TBT and evidence schemas | Implemented and under validation. | Runtime graph uses these as versioned source artifacts. |
| Assurance framework and instance schemas | Implemented, now including explicit waiver, compensating-control, decision and approval support. | Process cockpit uses these without embedding project state into reusable framework language. |
| Dashboard payload schema | Implemented and aligned with graph node/edge vocabulary. | Payload is a generated graph plus named projections, not hand-authored state. |
| Cockpit UI | Partially implemented in the static dashboard. | UI filters and presents backend projections with minimal local state. |
| Scanner-compliance semantics | Implemented as versioned mapping packs, still being refined in UI projections. | Direct scanner mappings can block a compliance row; unmapped/general findings remain visible but non-specific. |
| Proof/audit readiness | Architectural target documented in the runtime graph architecture. | Every claim can be backed by hashes, manifests, signatures or attestations without exposing source code unnecessarily. |

## Problem

The dashboard now has two different things that can both be called "frameworks":

1. **Compliance rulesets** such as ASVS, NIST 800-53, CIS, ISO 27001, PCI-DSS.
2. **Industry or organisational assurance frameworks** such as JSP-453.

Those are related, but they are not the same layer.

ASVS and NIST define compliance rules or controls. JSP-453 defines an assurance process: gates, approvals, roles, criteria, meetings, artefacts and decision points. JSP-453 may reference ASVS/NIST/CIS/ISO rules, but it also has its own language and evidence needs.

The JSP-453 page should therefore not feel like an ASVS page with a process graph attached. It should feel like a framework cockpit: "Where am I in this assurance process, what must be true to pass the next gate, who needs to be involved, and which compliance rulesets are blocking progress?"

## Proposed Mental Model

The richest and least confusing hierarchy is:

```text
Assurance framework
  -> process / route / assurance profile
    -> gate
      -> gate criteria
        -> mapped compliance rulesets
          -> compliance rows / controls
            -> FR Functional Requirements
              -> TBT Test Basis
                -> evidence
```

For the current project this means:

```text
JSP-453
  -> assurance path
    -> Gate 3: Authority to Test
      -> criteria: security plan, roles, code assurance, evidence readiness
        -> ASVS rows, later NIST/CIS/ISO rows
          -> FR-016, FR-021, FR-064...
            -> TBT-016, TBT-021, TBT-064...
              -> test results, scanner results, document excerpts, approvals
```

This keeps JSP-453 as the process lens, while ASVS/NIST remain compliance lenses.

## Terminology

The UI should use distinct names for distinct layers:

| Current / ambiguous term | Preferred term | Meaning |
|---|---|---|
| Framework | Assurance framework | JSP-453 or another process/assurance framework. In JSON this should be `assurance_framework`. |
| Compliance framework | Compliance ruleset | ASVS, NIST 800-53, CIS, ISO 27001, PCI-DSS. In JSON this should be `ruleset`. |
| Process gates | Gates | Decision points in the assurance framework. |
| ASVS levels | ASVS levels | L1/L2/L3 are ASVS-specific maturity levels. |
| JSP-453 levels | Assurance profile / route | If JSP-453 has route/depth concepts, model them separately from ASVS L1/L2/L3. Do not display these as ASVS-style levels. |
| Group | Epic | Existing FR groupings can be treated as epics. |
| FR | Functional Requirement | Project-owned requirement that maps to code and compliance rows. |
| TBT | Test Basis | Test/control/review basis used to prove one or more FRs. |
| Evidence | Evidence artifact/result | Observed result or artifact produced by a TBT, such as a JUnit result, scanner result, document excerpt, approval record or screenshot. |

## Core Provenance Model

The canonical trace chain is:

```text
Compliance ruleset row
  -> FR Functional Requirement
    -> TBT Test Basis
      -> Evidence
```

This same chain should be used in the graph, row expansion panels, JSP-453 gate context panel and agentic prompts.

An FR can have one or more TBTs. A TBT can support more than one FR where the same test basis genuinely proves multiple requirements. Evidence is not implemented; it is observed, collected or reviewed from a TBT.

`TBT.proves` is the canonical relationship. Any FR view that says "verified by TBT-016-ASVS-A" should be derived from TBT records, not maintained as a second source of truth on the FR.

## FR Ownership

FRs are project-owned definitions. They are not canonical rows copied from ASVS, NIST, JSP-453 or another catalogue.

The developer, product owner or security team writes the FR text for the application being assessed. Standards can and should inform the wording, but the final FR is a statement of project behaviour. For example:

```text
FR-016: Session timeout and re-authentication

The application must expire inactive sessions after the agreed timeout,
terminate invalid sessions, and require re-authentication before sensitive
actions or after risk-relevant events.
```

In this example:

- `FR-016` is a project-assigned stable identifier.
- `016` has no universal meaning outside this FR catalog.
- The wording is project-authored, even if derived from ASVS/NIST/JSP-453 expectations.
- External standards are recorded as mappings, not treated as the FR itself.

The provenance chain should therefore read:

```text
standard/control expectation
  -> project FR
    -> TBT
      -> evidence
```

This lets a team draft FRs from standards and code analysis, but still requires human review because the FR catalog is effectively a project assurance contract.

## TBT Ownership

TBTs are first-class project assurance objects, not just optional labels on test references.

A TBT describes the basis on which an FR is proven. It can represent:

- a unit test basis
- an integration test basis
- an end-to-end test basis
- a load/performance test basis
- a scanner rule/check
- a manual review
- a document review
- an approval or ceremony

Each TBT should state what it proves, what kind of evidence it is expected to produce, and its lifecycle status. Runtime pass/fail/missing state belongs to evidence, not to the TBT definition.

## Page Structure

The JSP-453 page should become the principal view for that assurance framework.

Recommended layout:

1. **Header**
   - Framework name, version, route/profile.
   - Current gate readiness summary.
   - No generic scan summary boxes on this page.

2. **Framework Controls**
   - Route / assurance depth selector.
   - Compliance ruleset filter: All, ASVS, NIST, CIS, ISO, custom.
   - Evidence state filter: blockers, manual review, passed, missing.
   - These controls request or filter backend graph projections; they do not recompute assurance state in the browser.

3. **Gate Flow**
   - D3 process graph as the main visual.
   - Gate nodes arranged vertically in process order.
   - Roles hub and role nodes attached to each gate.
   - Gate colour reflects backend-computed readiness for the selected route/profile.
   - Clicking a gate updates the context panel.
   - Clicking a roles hub shows all required roles for that gate.
   - Clicking a role shows the role's responsibility, party, assignment status and blocking impact.

4. **Context Panel**
   - Wider right-hand panel.
   - Shows selected gate/role/criterion details.
   - Lists criteria needed before the gate can pass.
   - Lists mapped compliance rules grouped by ruleset.
   - Lists manual ceremonies/evidence needed.
   - Lists blockers with enough detail to act.
   - Receives grouped rows from the graph projection rather than reconstructing the assurance chain locally.

5. **Crosswalk / Evidence Gaps**
   - Either sub-tabs under JSP-453 or sections in the context panel.
   - Crosswalk shows: gate -> criterion -> ruleset row -> FR -> TBT -> evidence.
   - Evidence gaps show what is missing and whether it is:
     - missing role assignment
     - missing manual approval
     - missing document
     - missing test evidence
     - failing scanner evidence
     - unmapped compliance row

## Gate Context Panel

Each selected gate should answer five questions:

1. **What is this gate for?**
   - Gate name, description, continuation rule.

2. **Who must be involved?**
   - Required roles.
   - Role type: owner, approver, consulted, informed.
   - Assignment state and missing-role blockers.

3. **What must be completed?**
   - Gate criteria.
   - Mandatory vs optional criteria.
   - Manual ceremonies, meetings, approvals or documents.

4. **Which compliance rulesets are relevant?**
   - Group rows by ruleset:
     - ASVS
     - NIST 800-53
     - CIS
     - ISO 27001
     - custom
   - Show row/control ID, title, FR mapping and result/readiness status.
   - If no code compliance rules are mapped for a governance gate, show that explicitly rather than leaving an empty table.

5. **What is blocking the gate?**
   - Missing criteria.
   - Missing or failed evidence.
   - Missing roles.
   - Manual review still required.

## Compliance Ruleset Presentation

The JSP-453 page should not be limited to ASVS.

When data is available, the context panel should group mapped rows like this:

| Ruleset | Rows | Passed | Missing | Failed | Manual |
|---|---:|---:|---:|---:|---:|
| ASVS | 18 | 0 | 18 | 0 | 0 |
| NIST 800-53 | 6 | 0 | 4 | 0 | 2 |
| CIS | 3 | 1 | 2 | 0 | 0 |

Below that summary, users should be able to expand each ruleset to see the actual rows and their provenance chains.

If only ASVS is currently mapped, the UI should still use the ruleset terminology so the page does not have to be redesigned when NIST/CIS/ISO mappings arrive.

## Graph Principles

The graph should show the process first, not every underlying compliance/test node by default.

Recommended defaults:

- Gate flow shows gates, role hubs and roles.
- Selecting a gate reveals criteria and mapped rulesets in the context panel.
- A "show dependencies" action can request the projection for one gate only.
- Dependency expansion should show the projected chain:
  - gate
  - criterion
  - compliance row/control
  - FR
  - TBT
  - evidence
- Avoid rendering all FR/TBT/evidence nodes for the whole assurance framework at once. The backend graph can be complete while the dashboard view remains focused.

This gives users an intuitive process view first, while still allowing trace-level inspection.

## Frontend Projection Contract

The cockpit frontend is a projection viewer, not the assurance engine.

It may:

- filter graph projections by framework, route, ruleset, scanner, gate, FR, TBT and evidence state
- select and expand graph nodes
- sort and group projection rows
- show context panels and prompts derived from selected nodes
- copy deterministic commands or agent prompts generated by the backend

It must not own:

- FR/TBT sufficiency calculation
- gate or criterion readiness calculation
- compliance-row status calculation
- scanner evidence strength or blocking rules
- waiver or compensating-control effects
- provenance hashing, manifest generation or proof claim construction

Those outputs should arrive in the dashboard payload as graph nodes, graph edges, evidence records, status summaries and named projections. The browser can keep temporary UI state such as selected cards or expanded panels, but persisted assurance state must come from versioned config, observed evidence and regenerated graph payloads.

## Scanner Evidence In The Cockpit

Scanner results are evidence, but they are not all equally specific.

`RUNTIME_GRAPH_ARCHITECTURE.md` is authoritative for the scanner evidence model. This section summarizes how the cockpit should present that model.

- A direct scanner-compliance mapping can support or block the mapped compliance row. If the scanner fails on a direct ASVS row mapping, that failure remains visible even when a bespoke TBT test passes.
- A compliance-domain scanner mapping is a broader signal. It should appear under the relevant ruleset/domain, but it should not be presented as proof of a specific FR/TBT unless a reviewed mapping says so.
- A general finding has no specific ruleset edge. It should remain visible as scanner evidence grouped by scanner/type, but it must not silently change FR/TBT sufficiency.

The cockpit should therefore present separate lanes or sections for:

```text
FR/TBT evidence
direct scanner evidence for mapped compliance rows
domain scanner evidence
general/unmapped scanner findings
```

The dashboard payload should use the graph-derived `scanner_evidence`
projection for these buckets rather than recomputing scanner semantics in the
browser. The current projection exposes direct blocker counts, mapped signal
counts, domain signal counts and unmapped inventory counts from the normalized
runtime graph.

This avoids the confusing case where a TBT looks "passed" while a directly mapped scanner result is failing. The TBT can be passed and the compliance row can still be blocked by independent scanner evidence.

## Waivers And Compensating Controls

Waivers and compensating controls are reviewed states, not passes.

They should be first-class graph nodes connected to the target they affect:

```text
Waiver -> applies_to -> FR/TBT/ruleset row/gate/criterion
Compensating control -> applies_to -> FR/TBT/ruleset row/gate/criterion
Decision -> applies_to -> gate/criterion
Waiver/compensating control/decision -> evidences -> supporting artifact
Waiver/compensating control/decision -> approved_by -> approval/signature reference
```

`RUNTIME_GRAPH_ARCHITECTURE.md` is authoritative for graph edge vocabulary. This cockpit doc should use those edge names rather than inventing UI-specific relationship types.

The cockpit should show:

- target and scope
- reason and limitations
- approver, approval time and signature/reference where present
- expiry or review date
- supporting evidence references
- status effect: `waived` or `compensating_control`

Neither state should be counted as passing evidence. They can clear a hard gate/criterion blocker only where a typed target and reviewed policy allow it, and the graph/projection must show the resulting `waived`, `compensating_control`, `partial` or `manual_review` state explicitly.

## Cockpit-Relevant Data Model Implications

The target model should use explicit nouns and avoid overloaded fields. This table is a cockpit-relevant subset of the complete schema inventory below; it intentionally focuses on artifacts the cockpit has to explain to users.

The target artifacts should be:

| Artifact | Owner | Purpose |
|---|---|---|
| Ruleset snapshots | Tool / standards source | Stable copies of ASVS, NIST, CIS, ISO, PCI rows/controls. |
| Glossary catalog | Tool-owned, reviewed with schema changes | Canonical terms, aliases, deprecated labels, schema field links and tooltip copy. |
| FR catalog | Project team, optionally generated then reviewed | Project-owned Functional Requirements and their compliance mappings. |
| FR catalog `tbts` section | Project team / assurance agent, then reviewed | Test Basis definitions proving FRs. Kept with FRs to avoid another required input file. |
| Evidence bundle | Scanner/test runner/manual review process | Observed evidence produced by TBTs. |
| Assurance framework catalog | Framework owner / tool | Reusable JSP-453-style gates, roles, criteria and process language. |
| Assurance instance | Project team / assessor | Project-specific role assignments, gate evidence, waivers, compensating controls, approvals and gate decisions. Kept separate from reusable JSP-453 framework language. |

The FR catalog should model project requirements and their mappings:

```text
FR -> satisfies -> compliance ruleset row
FR -> implemented_by -> code
```

The FR catalog `tbts` section should model assurance checks:

```text
TBT -> proves -> FR
TBT -> expected_evidence -> evidence type
```

The evidence bundle should model observed proof:

```text
Evidence -> produced_by -> TBT
Evidence -> result_status -> passed / failed / partial / missing / manual_review / waived / compensating_control / not_observed
Evidence -> source_locator -> file/page/section/line/excerpt where applicable
```

The runtime graph joins TBT definitions to observed evidence records:

```text
TBT -> evidences -> Evidence
Evidence -> produced_by -> TBT
```

The assurance framework catalog should model reusable process language:

```text
JSP-453 -> process -> gate -> criteria -> roles -> requirement placeholders
```

The separate assurance instance should model this project's response to the framework:

```text
gate criterion -> FR reference
gate criterion -> TBT reference
gate criterion -> compliance ruleset row reference
gate criterion -> manual evidence / approval / waiver / compensating control / decision
gate role -> assigned party / approval status
```

That allows a gate to depend on:

- process evidence only
- compliance rows only
- FR-to-evidence chains
- manual ceremonies
- any combination of the above

## Historical Migration Notes

The target model replaced several overlapping earlier representations rather than layering on top of them. This section is retained as trace context for older reports and generated runtime mirrors; it should not be read as a list of current schema fields.

| Current model | Problem | Target direction |
|---|---|---|
| FR `verified_by` entries with optional `test_id` | TBT is hidden inside a test reference and can conflict with generated test-pack IDs. | Top-level FR catalog `tbts`; `TBT.proves` is canonical. |
| FR evidence `status: auto/manual` | Mixes evidence resolution mode with evidence result. | Evidence uses `result_status`; resolution mode is derived from evidence type. |
| Process criterion `evidence[]` | Mixes reusable framework requirements with project-specific evidence state. | Assurance framework has criterion `requirements`; assurance instance maps those to project FR/TBT/evidence/approval state. |
| FR `process_mappings` | Stores project-specific JSP-453 mappings inside the FR catalog. | Move to assurance instance `criterion_mappings`. |
| Assurance test-pack `fr_id`, `framework_rows`, `process_gates` | Flattens TBT provenance and uses old compliance/process language. | Use `tbt`, `frs`, `ruleset_rows` and `assurance_gates`; treat generated assurance packs as draft inputs that populate or update `tbts` and evidence records. |

## Glossary Catalog

Terminology should be machine-readable, not only documented in prose.

The target model should include a glossary catalog:

```text
data/schemas/glossary.schema.json
data/glossary/core-terms.json
```

The glossary provides:

- canonical labels
- abbreviations
- plain-language definitions
- aliases and deprecated aliases
- "not this" disambiguation
- related terms
- schema field links
- tooltip copy for the dashboard

Primary uses:

- dashboard tooltips and help panels
- schema descriptions
- generated prompts
- docs consistency checks
- validation warnings for deprecated terms such as ambiguous `framework`
- reviewer-friendly explanations of FR, TBT, evidence, ruleset and assurance framework

## Suggested Schema Direction

Use `ruleset` for ASVS/NIST/CIS/ISO/PCI. Use `assurance_framework` for JSP-453 and similar process frameworks. Avoid using `framework` as a generic field name in new schemas.

Keep the FR catalog mostly compliance-ruleset-agnostic. It may contain light
`satisfies` convenience links for traceability, but regime-specific
sufficiency rules belong in compliance mapping packs:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "frs": [
    {
      "id": "FR-016",
      "title": "Session timeout and re-authentication",
      "lifecycle_status": "in_scope",
      "description": "The application must expire inactive sessions after the agreed timeout, terminate invalid sessions, and require re-authentication before sensitive actions or after risk-relevant events.",
      "satisfies": [
        {"ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
        {"ruleset": "NIST-800-53", "row": "AC-12"}
      ],
      "implemented_by": [
        {"type": "file", "path": "src/session.ts"}
      ]
    }
  ],
  "tbts": [
    {
      "id": "TBT-016-ASVS-A",
      "title": "Session timeout integration test basis",
      "type": "integration",
      "lifecycle_status": "planned",
      "proves": ["FR-016"],
      "evidence_policy": "automated_required",
      "expected_evidence": [
        {"type": "test_result", "format": "junit"}
      ]
    }
  ]
}
```

In this model, the UI can still display `FR-016 -> verified by -> TBT-016-ASVS-A`, but that relationship is derived from `TBT-016-ASVS-A.proves`.

Represent evidence as observed proof, not implemented proof:

```json
{
  "evidence": [
    {
      "id": "EVD-016-A",
      "type": "test_result",
      "result_status": "missing",
      "produced_by": "TBT-016-ASVS-A",
      "source": "junit/session-timeout.xml"
    },
    {
      "id": "EVD-039-DOC",
      "type": "document",
      "result_status": "manual_review",
      "produced_by": "TBT-039-DOC",
      "source": "docs/design.md",
      "source_locator": "section 3.4, lines 144-147",
      "source_excerpt": "Short supporting excerpt..."
    }
  ]
}
```

Keep reusable assurance framework criteria separate from project gate state:

```json
{
  "schema_version": 1,
  "assurance_framework": "JSP-453",
  "processes": [
    {
      "id": "JSP453-P1",
      "title": "Digital Services Assurance Path",
      "gates": [
        {
          "id": "G3",
          "title": "Authority to Test Submission and DEAB",
          "criteria": [
            {
              "id": "G3-C4",
              "title": "Code assurance evidence is ready",
              "evidence_policy": "manual_plus_automated",
              "requirements": [
                {"type": "fr_placeholder", "ref": "SESSION_MANAGEMENT"},
                {"type": "ruleset_row", "ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
                {"type": "manual_artifact", "ref": "ATT submission pack"}
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Then project-specific assurance state maps placeholders to real FRs/TBTs/evidence:

```json
{
  "schema_version": 1,
  "assurance_framework": "JSP-453",
  "project": "example-app",
  "selected_profile": "baseline",
  "criterion_mappings": [
    {
      "criterion": "G3-C4",
      "requirements": [
        {"type": "fr", "ref": "FR-016"},
        {"type": "tbt", "ref": "TBT-016-ASVS-A"},
        {"type": "ruleset_row", "ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
        {"type": "manual_artifact", "ref": "ATT submission pack", "evidence": "EVD-G3-ATT-PACK"}
      ]
    }
  ],
  "role_assignments": [
    {"gate": "G3", "role": "ROLE-DELIVERY-TEAM-SECURITY-LEAD", "party": "Security Team", "approval_status": "pending"}
  ]
}
```

The runtime graph and its named projections can then emit:

```text
Gate -> criterion -> ruleset row -> FR -> TBT -> evidence
```

and also:

```text
Gate -> criterion -> manual approval/document/meeting
```

Framework joins are explicit, never implied. JSP-453 and future assurance
framework nodes may exist in the runtime graph as process context, but they only
join the FR/TBT/compliance/evidence chain when a gate criterion has a typed
framework requirement or a project assurance-instance `criterion_mappings`
entry. Unmapped gates and criteria remain visible in the framework cockpit, but
they do not count as assurance proof and should not create edges into ASVS,
NIST, FRs, TBTs or evidence.

## Complete Schema Inventory

This is the complete intended schema/JSON set for the new approach.

| Artifact | Proposed schema file | Proposed JSON file pattern | Required by app | Purpose |
|---|---|---|---:|---|
| Shared schema definitions | `data/schemas/defs.schema.json` | schema-only | yes | Shared IDs, status enums, evidence enums and graph vocabulary used by other schemas to prevent drift. |
| Glossary catalog | `data/schemas/glossary.schema.json` | `data/glossary/core-terms.json` | yes | Canonical terminology, aliases, deprecated labels, schema field links and UI tooltip copy. |
| Ruleset snapshot | `data/schemas/ruleset.schema.json` | `data/rulesets/<ruleset>/<version>.json` | yes | Tool-owned snapshot of ASVS/NIST/CIS/ISO/PCI rows or controls. |
| Scanner rules catalog | `data/schemas/scanner-rules.schema.json` | `data/scanners/<scanner>/rules.json` | no | Optional scanner-native rule metadata. Compliance mappings live in scanner-compliance mapping packs. |
| Scanner-compliance mapping pack | `data/schemas/scanner-compliance-mapping-pack.schema.json` | `data/scanner-mappings/<ruleset>/<version>/<scanner>.json` | yes when scanner evidence is used | Versioned, reviewed scanner finding selectors mapped to compliance rows, compliance domains, or general findings. |
| Compliance mapping pack | `data/schemas/compliance-mapping-pack.schema.json` | `data/rulesets/<ruleset>/mapping-packs/<pack>.json` or project override | yes when compliance regime views are enabled | Versioned, reviewed ruleset-row-to-FR/TBT mappings with sufficiency policy. |
| FR catalog | `data/schemas/fr-catalog.schema.json` | `<project>/fr-catalog.json` or generated artifact | yes | Project-owned FRs and top-level TBT definitions. |
| Evidence bundle | `data/schemas/evidence-bundle.schema.json` | generated report artifact | yes | Observed evidence produced by tests, scanners and manual review. |
| Assurance framework catalog | `data/schemas/assurance-framework.schema.json` | `data/assurance-frameworks/<framework>.json` | no unless process view enabled | Reusable JSP-453-style gates, roles, criteria and process language. |
| Assurance instance | `data/schemas/assurance-instance.schema.json` | `<project>/assurance-instance.<framework>.json` or generated artifact | no unless process view enabled | Project-specific role assignments, criterion mappings, waivers, compensating controls, approvals and decisions. |
| Dashboard payload | `data/schemas/dashboard-payload.schema.json` | embedded in generated dashboard/report | yes | Normalised render payload consumed by the static dashboard. |
| Agent prompt plan | `data/schemas/agent-prompt-plan.schema.json` | generated report artifact | no | Structured deficiencies, fixes and assurance-test recommendations for agent prompts. |
| Config update proposal | `data/schemas/config-update-proposal.schema.json` | `proposal.json` or generated report artifact | no | Review-gated FR/TBT, mapping, assurance-instance and manual-evidence updates produced by an agent or assessor. |
| Assurance test pack | `data/schemas/assurance-test-pack.schema.json` | generated report artifact | no | Ephemeral or commit-ready assessment pack for copied native tests, wrappers and proposed assurance tests. |

Rules:

- These schemas are the target set. The app should not preserve the older overlapping shapes as parallel first-class models.
- Existing inputs can be regenerated or converted into this shape, but compatibility with old field names is not a design goal.
- Runtime report payloads should record the schema IDs/versions used to generate them.
- Cross-file integrity is enforced by a validator because JSON Schema cannot fully prove that an ID in one file exists in another file.
- The canonical scanner mapping schema is `scanner-compliance-mapping-pack.schema.json`; older `scanner_mapping` / `scanner-mapping-pack` naming is historical and should not be revived as a parallel model.

## Project Schema Definitions For Review

This section describes the project-facing schema definitions at a reviewable level. The corresponding JSON Schema files live under `data/schemas/` and the review fixtures live under `data/fixtures/target-schemas/`.

### Glossary Catalog

Purpose: canonical terms and tooltip/help copy.

Implemented draft files:

```text
data/schemas/glossary.schema.json
data/glossary/core-terms.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "title": "Core Assurance Glossary",
  "description": "Canonical terms for assurance traceability.",
  "terms": []
}
```

Term object:

```json
{
  "id": "fr",
  "canonical": "Functional Requirement",
  "abbreviation": "FR",
  "definition": "A project-owned requirement describing behaviour the application must provide.",
  "domain": "core",
  "aliases": ["project requirement"],
  "deprecated_aliases": ["functional rule"],
  "not": ["ASVS row", "NIST control"],
  "related_terms": ["tbt", "evidence"],
  "schema_fields": ["frs[].id", "tbts[].proves"],
  "ui_label": "FR",
  "tooltip": "Project-owned functional requirement, proven by one or more TBTs."
}
```

### Ruleset Snapshot

Purpose: tool-owned compliance rows or controls from ASVS, NIST, CIS, ISO, PCI or another ruleset.

Recommended file pattern:

```text
data/rulesets/<ruleset>/<version>.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "ruleset": "ASVS",
  "version": "5.0.0",
  "title": "OWASP Application Security Verification Standard",
  "source": {
    "url": "https://example.invalid/source",
    "license": "CC-BY-SA-4.0",
    "retrieved_at": "2026-07-06T00:00:00Z"
  },
  "rows": []
}
```

Ruleset row object:

```json
{
  "id": "v5.0.0-5.1.1",
  "title": "Session management requirement",
  "description": "Verify that session controls meet the ruleset requirement.",
  "group": "V5",
  "section": "V5.1",
  "level": "L1",
  "parent": null,
  "metadata": {
    "chapter": "V5",
    "section_name": "Validation, Sanitization and Encoding"
  }
}
```

Rules:

- Uses `ruleset`, not `framework`.
- Ruleset-specific fields belong in `metadata` unless they are common display fields.
- ASVS levels remain ruleset row attributes, not assurance framework profiles.

### Scanner Rules Catalog

Purpose: optional scanner-native rule metadata. Scanner-to-ruleset mappings are deliberately kept out of this catalog and live in versioned scanner-compliance mapping packs.

Recommended file pattern:

```text
data/scanners/<scanner>/rules.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "scanner": "semgrep",
  "version": "1.0",
  "rules": []
}
```

Scanner rule object:

```json
{
  "id": "python.flask.security.injection",
  "title": "Potential injection vulnerability",
  "severity": "high",
  "description": "Scanner rule description.",
  "evidence_type": "scanner_result"
}
```

Rules:

- Scanner rules are not FRs and not TBTs by themselves.
- A scanner rule can be used by a TBT of type `scanner`.
- Scanner-to-ruleset mappings must be declared in scanner-compliance mapping packs so the scanner version, ruleset version, traceability strength and limitations are reviewed together.

### FR Catalog

Purpose: project-owned Functional Requirements and their Test Basis definitions.

Recommended file name:

```text
fr-catalog.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "generated_at": "2026-07-06T00:00:00Z",
  "scope": {},
  "na_rows": [],
  "frs": [],
  "tbts": []
}
```

Fields:

| Field | Required | Meaning |
|---|---:|---|
| `schema_version` | yes | Schema version for this target schema. |
| `project` | yes | Project/repository name. |
| `generated_at` | no | Timestamp for generated or updated catalogs. |
| `scope` | no | Ruleset-specific scope, keyed by `ruleset`, not generic framework. |
| `na_rows` | no | Explicit out-of-scope ruleset rows with reasons. |
| `frs` | yes | Project-owned Functional Requirements. |
| `tbts` | no | Test Basis definitions proving one or more FRs. |

FR object:

```json
{
  "id": "FR-016",
  "title": "Session timeout and re-authentication",
  "lifecycle_status": "in_scope",
  "category": "authentication",
  "description": "Project-authored requirement text.",
  "assignments": [
    {"party": "auth-team", "responsibility": "owner"}
  ],
  "implemented_by": [
    {"type": "file", "path": "src/session.ts", "label": "Session manager"}
  ],
  "satisfies": [
    {"ruleset": "ASVS", "row": "v5.0.0-5.1.1"}
  ]
}
```

FR fields:

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable project-owned FR identifier. |
| `title` | yes | Short human-readable title. |
| `lifecycle_status` | yes | `draft`, `in_scope`, `deferred`, `not_applicable`, `retired`. |
| `category` | no | UI grouping, presented as Epic. |
| `description` | no | Project-authored requirement prose. |
| `assignments` | no | RACI-style role/team assignments; `owner` is derived for display from the assignment with `responsibility: owner`. |
| `implemented_by` | no | Code references. |
| `satisfies` | no | Compliance ruleset rows satisfied by this FR. |

TBT object:

```json
{
  "id": "TBT-016-ASVS-A",
  "title": "Session timeout integration test basis",
  "type": "integration",
  "lifecycle_status": "planned",
  "proves": ["FR-016"],
  "evidence_policy": "automated_required",
  "expected_evidence": [
    {"type": "test_result", "format": "junit"}
  ]
}
```

TBT fields:

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable TBT identifier. |
| `title` | yes | Human-readable test basis title. |
| `type` | yes | `unit`, `integration`, `e2e`, `load`, `scanner`, `manual_review`, `document_review`, `approval`. |
| `lifecycle_status` | yes | `planned`, `implemented`, `deprecated`. |
| `proves` | yes | FR IDs proven by this TBT. This is the canonical FR/TBT relationship. |
| `evidence_policy` | yes | Sufficiency policy for evidence. |
| `expected_evidence` | no | Expected evidence kinds/formats. |

### Evidence Bundle

Purpose: observed or reviewed proof produced by TBTs.

Recommended file name:

```text
evidence-bundle.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "generated_at": "2026-07-06T00:00:00Z",
  "evidence": []
}
```

Evidence object:

```json
{
  "id": "EVD-016-A",
  "type": "test_result",
  "result_status": "missing",
  "produced_by": "TBT-016-ASVS-A",
  "source": "junit/session-timeout.xml",
  "source_locator": "testcase session_timeout",
  "source_excerpt": "Optional short excerpt",
  "reviewer": "security-assessor",
  "reviewed_at": "2026-07-06T00:00:00Z"
}
```

Evidence fields:

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable evidence identifier. |
| `type` | yes | `test_result`, `scanner_result`, `document`, `approval`, `screenshot`, `manual_note`. |
| `result_status` | yes | `passed`, `failed`, `partial`, `missing`, `manual_review`, `waived`, `compensating_control`, `not_observed`. |
| `produced_by` | yes | TBT ID that produced or requested this evidence. |
| `source` | no | File/path/tool output/reference. |
| `source_locator` | no | Precise location within the source. Optional in JSON Schema; required by validation/policy for strong document, screenshot and manual-note evidence where available. |
| `source_excerpt` | no | Short supporting excerpt. |
| `reviewer` | no | Human reviewer for manual evidence. |
| `reviewed_at` | no | Review timestamp. |

### Assurance Framework Catalog

Purpose: reusable JSP-453-style process language.

Recommended file name:

```text
assurance-framework.jsp-453.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "assurance_framework": "JSP-453",
  "title": "JSP 453 Digital Services Assurance Gate Process",
  "assurance_profiles": [],
  "roles": [],
  "processes": []
}
```

Gate criterion object:

```json
{
  "id": "G3-C4",
  "title": "Code assurance evidence is ready",
  "description": "Required code assurance evidence is available for Authority to Test.",
  "evidence_policy": "manual_plus_automated",
  "requirements": [
    {"type": "fr_placeholder", "ref": "SESSION_MANAGEMENT"},
    {"type": "ruleset_row", "ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
    {"type": "manual_artifact", "ref": "ATT submission pack"}
  ]
}
```

Assurance framework rules:

- Must not contain project-specific parties, approvals or evidence results.
- May contain placeholders that an assurance instance maps to project FRs/TBTs/evidence.
- Uses the settled schema field `assurance_profiles`, not generic `levels`. Human-facing profile labels remain open to review.

### Assurance Instance

Purpose: project-specific response to an assurance framework.

Recommended file name:

```text
assurance-instance.jsp-453.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "assurance_framework": "JSP-453",
  "selected_profile": "baseline",
  "criterion_mappings": [],
  "role_assignments": [],
  "waivers": [],
  "decisions": []
}
```

Criterion mapping object:

```json
{
  "criterion": "G3-C4",
  "requirements": [
    {"type": "fr", "ref": "FR-016"},
    {"type": "tbt", "ref": "TBT-016-ASVS-A"},
    {"type": "evidence", "ref": "EVD-016-A"},
    {"type": "manual_artifact", "ref": "ATT submission pack", "evidence": "EVD-G3-ATT-PACK"}
  ]
}
```

Role assignment object:

```json
{
  "gate": "G3",
  "role": "ROLE-DELIVERY-TEAM-SECURITY-LEAD",
  "party": "Security Team",
  "approval_status": "pending",
  "approval_ref": "TICKET-123"
}
```

Assurance instance rules:

- Stores project-specific mappings, parties, approvals, waivers, compensating controls and decisions.
- Does not redefine reusable gate criteria.
- Replaces `process_mappings` as the home for project-specific assurance mappings.

### Dashboard Payload

Purpose: normalised render payload consumed by the generated static dashboard.

Recommended location:

```text
embedded in dashboard.html or emitted as dashboard-payload.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "generated_at": "2026-07-06T00:00:00Z",
  "inputs": {
    "fr_catalog": "fr-catalog.json",
    "evidence_bundle": "evidence-bundle.json",
    "assurance_framework": "assurance-framework.jsp-453.json",
    "assurance_instance": "assurance-instance.jsp-453.json"
  },
  "summary": {},
  "ruleset_views": {},
  "fr_catalog_view": {},
  "graph": {},
  "assurance_views": {},
  "deficiencies": []
}
```

Rules:

- The dashboard payload is derived data, not a hand-authored project input.
- It may contain cached graph projections for fast static rendering.
- Projection rows and denormalised relationships must still be traceable back to their source graph node, graph edge, artifact and ID.
- The static dashboard should filter, expand and present these projections, not compute assurance status from raw fragments.

### Agent Prompt Plan

Purpose: structured deficiencies, suggested fixes and suggested assurance tests for generated prompts.

Recommended generated file:

```text
agent-prompt-plan.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "project": "example-app",
  "generated_at": "2026-07-06T00:00:00Z",
  "mode": "assessment_first",
  "deficiencies": [],
  "fix_recommendations": [],
  "assurance_recommendations": []
}
```

Deficiency object:

```json
{
  "id": "DEF-001",
  "severity": "high",
  "type": "missing_evidence",
  "summary": "TBT-016-ASVS-A has no passing evidence.",
  "affected": {
    "frs": ["FR-016"],
    "tbts": ["TBT-016-ASVS-A"],
    "ruleset_rows": [{"ruleset": "ASVS", "row": "v5.0.0-5.1.1"}],
    "gates": ["G3"]
  },
  "recommended_action": "Assess existing tests before generating new test code."
}
```

Rules:

- Default mode is assessment-first.
- Prompt plans should not instruct an agent to generate large test suites unless explicitly requested.
- Every recommendation should reference FR/TBT/evidence/ruleset/gate IDs where applicable.

### Assurance Test Pack

Purpose: ephemeral or commit-ready assessment pack for copied native tests, wrappers and proposed assurance tests. This pack is not evidence by itself; it is an assessment and test-design artifact that can later produce evidence when tests are approved and executed.

Recommended generated file:

```text
generated-tests/VG_TEST_FRAMEWORK/manifest.json
```

Top-level shape:

```json
{
  "schema_version": 1,
  "name": "VG_TEST_FRAMEWORK",
  "mode": "ephemeral",
  "generated_at": "2026-07-06T00:00:00Z",
  "target_dir": "/workspace/project",
  "source_inventory": "reports/test-inventory.json",
  "summary": {},
  "safety_policy": {
    "default": "non_destructive",
    "project_mount": "safe_worktree",
    "network": "disabled unless scanner/runtime flags explicitly provide a target URL",
    "writes_allowed": ["report bundle", "temporary runner workspace"]
  },
  "tests": []
}
```

Test-pack entry:

```json
{
  "pack_id": "TBT-016-ASVS-A",
  "tbt": "TBT-016-ASVS-A",
  "frs": ["FR-016"],
  "title": "Session timeout integration test basis",
  "source": "planned_tbt",
  "type": "integration",
  "runner": "containerized integration runner",
  "status": "planned",
  "assessment": "needs_design",
  "safety": "non_destructive",
  "pack_path": "integration/TBT-016-ASVS-A.test.js",
  "ruleset_rows": [{"ruleset": "ASVS", "row": "v5.0.0-5.1.1"}],
  "assurance_gates": ["G3"],
  "cases": [],
  "rationale": "Declared TBT/FR verification target has no generated assurance test implementation in this pack yet.",
  "suggested_test": "Design a non-destructive integration assurance test specification."
}
```

Rules:

- `tbt` is the canonical provenance identifier for a proposed or generated assurance test.
- `frs` is plural because one TBT can prove more than one Functional Requirement.
- `ruleset_rows` uses compliance ruleset language, not assurance framework language.
- `assurance_gates` references gate IDs from the selected assurance framework.
- Copied native tests are review inputs and must not be counted as passing evidence unless execution evidence is later observed.
- Generated or wrapper tests must be non-destructive by default and should be written only after explicit approval.

### Cross-File Validator

Purpose: validate universal provenance joins across target schema fixtures.

Implemented script:

```text
scripts/validate-target-schema-fixtures.py
```

Checks:

- unique FR, TBT, evidence, ruleset row, role, gate and criterion IDs
- expected target schema files exist, no unexpected schema files are present, and every schema file is parseable JSON
- TBTs prove existing FRs
- evidence is produced by existing TBTs
- scanner rules map to existing ruleset rows
- FRs satisfy existing ruleset rows
- assurance criteria reference existing ruleset rows
- assurance instance mappings reference existing criteria, FRs, TBTs and evidence
- waivers and compensating controls have unique IDs and structured targets reference known graph/config objects where supplied
- assurance test-pack entries reference existing TBTs, FRs, ruleset rows and gates
- role assignments reference existing gates and roles
- dashboard graph edges reference existing graph nodes
- agent prompt deficiencies and recommendations reference existing IDs
- glossary terms are unique and `related_terms` point to defined glossary terms

The validator is intentionally dependency-free so it can run in constrained scan/report environments.

### Agent-Assisted Config Authoring

Purpose: use an agent up front to propose versioned, reviewable assurance config rather than relying on an agent during scan/report runtime.

Implemented prompt:

```text
scripts/prompts/assurance-config-authoring.md
```

Implemented proposal schema:

```text
data/schemas/config-update-proposal.schema.json
```

Rules:

- The agent authors proposed config only; runtime matching remains deterministic.
- New agent output starts as `review_status: proposed`.
- Proposed config changes are returned as config update proposals, then validated, reviewed and applied by controlled tooling.
- The prompt covers FR/TBT authoring, compliance mappings, framework mappings, scanner-compliance evidence signals and artifact mappings.
- Scanner mappings must include scanner/version or ruleset snapshot provenance.
- Evidence strength must be explicit: `strong`, `supporting`, `weak`, `manual_review` or `not_sufficient`.
- Scanner "no findings" must not be treated as strong evidence unless the TBT and regime sufficiency policy explicitly allow it.
- Ambiguous legacy tests, documents and scanner outputs become review questions or weak/supporting proposals, not accepted evidence.
- Accepted config is later validated by the cross-file validator before the dashboard or report can rely on it.

This keeps agentic judgement in the maintainable config-authoring phase while preserving auditable, repeatable scan behaviour.

## Evidence Policy

Each TBT and each gate criterion should declare what evidence is sufficient. Recommended policy values:

| Policy | Meaning |
|---|---|
| `all_required` | Every required item must be met. |
| `any_required` | At least one required item must be met. |
| `automated_required` | Automated test/scanner evidence must pass; manual evidence alone is insufficient. |
| `manual_plus_automated` | Both manual evidence and automated evidence are required. |
| `manual_decision` | A human approval/waiver/decision is expected before the item can pass. |

This prevents a broad document or one partial test from accidentally satisfying a gate that needs stronger evidence.

## Status Vocabulary

Do not reuse one `status` enum across all objects. Each domain should have a small, explicit vocabulary.

| Domain | Field | Values | Meaning |
|---|---|---|---|
| FR lifecycle | `lifecycle_status` | `draft`, `in_scope`, `deferred`, `not_applicable`, `retired` | Whether the project requirement is in scope as a requirement. |
| TBT lifecycle | `lifecycle_status` | `planned`, `implemented`, `deprecated` | Whether the test basis exists as a planned or implemented assurance check. Runtime execution readiness belongs to the assurance test pack or graph projection, not the TBT definition. |
| Assurance test pack entry | `status` | `copied`, `planned`, `generated`, `ready_to_run`, `executed`, `deprecated` | Canonical pack-entry lifecycle. Review-required and blocked states are represented by assessment, safety, evidence state or graph projection fields rather than this enum. |
| Evidence result | `result_status` | `passed`, `failed`, `partial`, `missing`, `manual_review`, `waived`, `compensating_control`, `not_observed` | The observed result for a piece of evidence. `waived` and `compensating_control` are explicit non-pass states. |
| Approval | `approval_status` | `pending`, `approved`, `rejected`, `waived` | Human approval or waiver state. |
| Gate readiness | `readiness_status` | `ready`, `blocked`, `partial`, `manual_review`, `waived` | Derived state for a gate or criterion. |

Replacement of current status terms should be explicit during implementation. For example:

| Current value/context | Target value |
|---|---|
| FR evidence `status: auto` | evidence is machine-resolved; result becomes `passed`, `failed` or `missing` after scan. |
| FR evidence `status: manual` | evidence `result_status: manual_review` until reviewed or waived. |
| process evidence `met` | evidence `result_status: passed` or approval `approval_status: approved`, depending on type. |
| process evidence `manual` / `pending` | `manual_review` or `pending`, depending on evidence vs approval domain. |
| criterion `met` | criterion `readiness_status: ready`. |
| criterion `blocked` | criterion `readiness_status: blocked`. |

This is deliberately stricter than the current implementation. It avoids treating lifecycle state, evidence result, approval state and gate readiness as the same kind of status.

The runtime graph may expose a reconciled display status for cards, rows and nodes, but that display value should be derived from the source-domain fields above and should never be written back as canonical config.

## Levels and Routes

ASVS L1/L2/L3 should remain ASVS concepts.

For JSP-453 and other assurance frameworks, use neutral assurance language until the real source document confirms exact terms:

- route
- assurance profile
- assurance depth
- risk tier
- criticality tier

The UI can show a selector, but it must not imply that JSP-453 has ASVS-style L1/L2/L3 levels unless the source document says so.

Recommended interim wording:

```text
Assurance profile: Baseline / Enhanced / High assurance
```

In new schemas, use the settled field `assurance_profiles`, not generic `levels`. Generic `levels` is too likely to be confused with ASVS L1/L2/L3. The remaining open question is what labels the UI should show for assurance profile values.

## Historical Schema Replacement Notes

The target schema set replaced earlier overlapping JSON shapes. This section is retained as historical migration context for older report mirrors and old design notes; it is not a list of current supported fields.

Replacement mapping:

| Current field/model | Target schema shape |
|---|---|
| FR `requirements` | FR catalog `frs` |
| FR `satisfies[].framework` | FR catalog `satisfies[].ruleset` |
| FR `scope` keyed by framework | FR catalog `scope` keyed by ruleset |
| FR `na_rows[].framework` | FR catalog `na_rows[].ruleset` |
| FR inline `verified_by[].test_id` | FR catalog top-level `tbts[].id` |
| FR inline `verified_by` relationship | derived from `tbts[].proves` |
| process top-level `framework` | assurance framework `assurance_framework` |
| process `levels` | assurance framework `assurance_profiles` |
| process `criteria[].evidence` | assurance framework `criteria[].requirements` plus project assurance-instance mappings |
| FR `process_mappings` | assurance instance `criterion_mappings` |
| assurance test-pack `fr_id` / `framework_rows` / `process_gates` | assurance test-pack `frs` / `ruleset_rows` / `assurance_gates`, FR catalog `tbts`, evidence bundle records and ruleset mappings |

Regeneration is acceptable. The implementation does not need to keep old field names alive as supported public input.

## Universal Row Expansion Pattern

The same provenance model should apply across table views:

```text
Compliance row / gate criterion
  -> FR
    -> TBT
      -> evidence
```

For a passed item:

- show the full chain
- show the evidence artefact/result that proves it
- identify whether the evidence is automated or manual

For a missing item:

- show ghost nodes for missing FR/TBT/evidence where useful
- classify the deficiency:
  - missing FR mapping
  - missing test design
  - missing test result
  - missing manual artefact
  - failed evidence

For a manual pass:

- show the exact document/section/line/page where possible
- do not treat a broad document reference as strong evidence unless it is pinpointed
- record reviewer/status where human judgement is involved
- distinguish "document exists" from "document reviewed and accepted"

## Decisions

1. FR means Functional Requirement.
2. FR identifiers and wording are project-owned.
3. TBT is a first-class Test Basis object.
4. Evidence is observed or reviewed, not implemented.
5. ASVS L1/L2/L3 are ASVS-only concepts.
6. JSP-453 should use assurance profile/route terminology until the real JSP terms are confirmed.
7. Broad document references should not automatically pass evidence.
8. Gate criteria and TBTs need explicit evidence policy.
9. `ruleset` should describe ASVS/NIST/CIS/ISO/PCI mappings.
10. `assurance_framework` should describe JSP-453-style process frameworks.
11. TBTs live as a top-level `tbts` section in the FR catalog.
12. `TBT.proves` is canonical; FR verified-by views are derived.
13. Project-specific gate state lives in a separate assurance instance model.
14. FR `category` should be presented as Epic in the UI.
15. Source locators are required for strong manual/document evidence where available; the gap is enforcement and review state, not merely field availability.

## Open Review Questions

1. What are the correct JSP-453 route/profile terms from the source document?
2. Which gates should reference code compliance rules directly, and which are process-only gates?
3. Should dependency expansion in the JSP-453 graph show criterion/ruleset/FR/TBT/evidence nodes inline, or should the graph stay process-only with dependencies in the context panel?
4. Where exactly should the JSP-453 crosswalk live: as a sub-view beside Gate Flow, or as expandable sections in the context panel?
5. What exact JSP-453 source terms should replace interim profile names such as Baseline / Enhanced / High assurance?

## Implementation Sequencing

### Batch A: UI Terminology Only

No schema break.

- Rename visible labels so the UI distinguishes assurance frameworks from compliance rulesets.
- Rename JSP-453 level controls away from ASVS-style L1/L2/L3.
- Present FR `category` groupings as Epics.
- Add empty states for process-only gates and gates with no mapped compliance rows.
- Use glossary definitions for key tooltips where practical.

Acceptance criteria:

- JSP-453 page uses "Assurance framework" or "JSP-453 Assurance", not generic "Framework".
- ASVS/NIST/CIS/ISO are labelled "Compliance rulesets".
- No JSP-453 control displays ASVS L1/L2/L3 unless the selected ruleset view is ASVS.
- A gate with zero mapped ruleset rows shows an explicit empty state.
- FR, TBT, Evidence, Ruleset and Assurance Framework tooltips match the glossary.

### Batch B: Target Schema Contract

Schema contract work. Most schema replacement has been implemented; remaining work should focus on shared definitions, graph vocabulary centralization and stricter runtime adoption.

- Maintain the complete target schema set.
- Add/validate the glossary schema and core glossary.
- Keep overloaded `framework` fields out of new schemas; use `ruleset` and `assurance_framework`.
- Keep process `levels` out of new schemas; use `assurance_profiles`.
- Keep project process mappings in a project assurance instance model.
- Keep older overlapping schema shapes out of the supported public model.

Acceptance criteria:

- Target schemas reject ambiguous old fields in strict mode.
- Glossary JSON validates against `data/schemas/glossary.schema.json`.
- FR catalog schema defines `frs` and top-level `tbts`.
- FR catalog schema uses `ruleset`, not `framework`, for compliance mappings.
- Assurance framework schema uses `assurance_framework`, not generic `framework`.
- Assurance instance schema owns criterion mappings, role assignments, waivers, compensating controls and decisions.

### Batch C: TBT And Evidence Model

Core provenance work.

- Make top-level `tbts` part of the FR catalog model.
- Make `TBT.proves` canonical.
- Add explicit evidence policy.
- Add evidence result records using `result_status`.
- Enforce source locator/reviewer state for manual document evidence where available.

Acceptance criteria:

- The runtime graph projection emits FR -> TBT relationships from `TBT.proves`.
- A TBT with no evidence appears as missing evidence, not as a pass.
- Manual document evidence without a locator is flagged as weak/manual review.
- One TBT can prove multiple FRs without duplicate evidence nodes.

### Batch D: Assurance Framework And Instance

JSP-453 modelling work.

- Keep reusable JSP-453 gate/role/criterion language in an assurance framework catalog.
- Keep project role assignments, waivers, compensating controls, decisions and evidence mappings in an assurance instance.
- Framework criteria use reusable requirement types: `fr_placeholder`, `ruleset_row`, `manual_artifact`, `approval`, `waiver`, `compensating_control` and `decision`.
- Assurance instance mappings use concrete project requirement types: `fr`, `tbt`, `evidence`, `ruleset_row`, `manual_artifact`, `approval`, `waiver`, `compensating_control` and `decision`.

Acceptance criteria:

- The same JSP-453 framework catalog can be reused by two projects.
- Project-specific parties and approvals are absent from the reusable framework catalog.
- Gate readiness is computed by the backend graph/status engine from assurance framework criteria, assurance instance state and evidence results.
- Criteria and gates inherit direct scanner blockers only through typed mappings to FRs, TBTs or compliance rows; unmapped process context remains visible but does not affect FR/TBT assurance rollups.
- Approved gate/criterion waivers or compensating controls clear hard process blockers without counting as passing evidence; explicit decisions can set gate/criterion readiness to ready, blocked, partial, manual review or waived.

### Batch E: JSP-453 Cockpit Rendering

UI/data rendering work.

- Keep Gate Flow as the principal JSP-453 page view.
- Render the graph process-first by default.
- Render dependency expansion client-side from embedded static JSON, not by network lazy loading.
- Group gate compliance rows by ruleset in the context panel.
- Add crosswalk/evidence-gap rendering once placement is decided.

Acceptance criteria:

- Static dashboard HTML contains enough embedded JSON to expand one selected gate without network calls.
- Initial graph shows gates, roles hub and roles without loading every FR/TBT/evidence node.
- Selecting a gate shows ruleset summaries, criteria, roles, blockers and evidence policy.
- Dependency expansion shows only the selected gate's criterion/ruleset/FR/TBT/evidence chain.
