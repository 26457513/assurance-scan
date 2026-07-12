# Blueprint FRs and Project Assurance

## Purpose

This document captures the model for reusable "blueprint" functional
requirements (FRs), project-local assurance requirements, and compliance
regime mappings.

The key principle is:

```text
Compliance is a lens over the assurance graph.
Project assurance is the full contract accepted for a specific codebase.
```

ASVS, NIST, JSP-453 or another framework should not be treated as the whole
universe of assurance. They are declared regimes or process lenses. The project
may also contain security or assurance obligations that are not covered by the
currently selected regime, or that have not yet been mapped to it.

Terminology in this document:

| Term | Meaning |
| --- | --- |
| Project assurance | The full accepted FR/TBT/evidence contract for a specific codebase. |
| Compliance regime / ruleset | A control catalog used as a compliance lens, such as ASVS or NIST. |
| Assurance framework | A process or gate model, such as JSP-453, that can depend on compliance and project assurance status. |
| Blueprint catalog | A reusable library of candidate security FR/TBT chains. It proposes project requirements; it does not prove them. |
| Project FR catalog | The accepted project-local assurance contract after human review. |

This document is a companion to:

- `docs/ASSURANCE_PLANNING_STUDIO.md`, which is authoritative for the
  upstream project planning workflow, config selection, blueprint review,
  project design contract and downstream handoff.
- `docs/RUNTIME_GRAPH_ARCHITECTURE.md`, which is authoritative for runtime
  graph construction, evidence, provenance, audit and proof readiness.
- `docs/FRAMEWORK_COCKPIT_DESIGN.md`, which is authoritative for cockpit UX,
  framework/gate views and frontend/backend responsibilities.

Archived docs are historical only and are not authoritative for this model.

## Why Blueprint FRs

Many assurance requirements are reusable across projects:

- session timeout and re-authentication
- access control enforcement
- audit logging
- password reset and credential lifecycle
- input validation and encoding
- file upload safety
- secret handling
- dependency and container vulnerability management
- API authorization
- error handling and information leakage

These are not product-feature requirements in the domain sense. They are
security and assurance expectations that frequently map to ASVS, NIST, SOC 2,
ISO 27001, internal policy or assurance-framework gates.

Blueprint FRs let us encode that reusable assurance intelligence once, then
instantiate it into a project-specific FR catalog for review.

## Recommended Starting Point

Use a versioned blueprint FR catalog that is itself shaped like an FR catalog,
instead of introducing a separate template-library schema immediately.

Example path:

```text
data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json
```

This is the lowest-risk model because it reuses the existing FR/TBT graph,
proposal, validation and dashboard paths. It lets us prove the 80/20 value of a
security-core library before committing to a larger template system.

## Identity Rules

Blueprint IDs and project IDs are different kinds of identity.

Blueprint IDs are stable across projects and keep the same `FR-` / `TBT-`
prefixes as project catalogs so blueprint catalogs remain valid FR catalogs.
The convention is:

```text
FR-BP-<REGIME>-<DOMAIN>-<NNN>
TBT-BP-<REGIME>-<DOMAIN>-<NNN>-<LETTER>
```

Use readable domains rather than terse abbreviations. For example:

```text
FR-BP-ASVS-AUTHENTICATION-001
TBT-BP-ASVS-AUTHENTICATION-001-A
FR-BP-ASVS-SESSION-MANAGEMENT-001
TBT-BP-ASVS-SESSION-MANAGEMENT-001-A
```

Project IDs are local to one accepted project catalog:

```text
FR-016
TBT-016-ASVS-A
```

Project FR IDs must not be treated as globally meaningful. A project FR may be
derived from a blueprint, copied from a blueprint and tailored, or written from
scratch.

## Lineage

Project FRs and TBTs should be able to record where they came from.

Example FR lineage:

```json
{
  "id": "FR-016",
  "title": "Session timeout and re-authentication",
  "derived_from": {
    "blueprint_catalog": "security-core",
    "blueprint_version": "asvs-5.0.0",
    "blueprint_fr": "FR-BP-ASVS-SESSION-MANAGEMENT-001",
    "blueprint_hash": "sha256:..."
  }
}
```

Example TBT lineage:

```json
{
  "id": "TBT-016-ASVS-A",
  "proves": ["FR-016"],
  "derived_from": {
    "blueprint_catalog": "security-core",
    "blueprint_version": "asvs-5.0.0",
    "blueprint_tbt": "TBT-BP-ASVS-SESSION-MANAGEMENT-001-A",
    "blueprint_hash": "sha256:..."
  }
}
```

Lineage supports:

- audit provenance
- drift detection when blueprint libraries change
- review of project-specific tailoring
- reproducible graph and proof manifests

Blueprint drift means the source blueprint changed after a project instantiated
it. That does not invalidate the accepted project FR/TBT by itself. It creates a
review signal: the project can keep the tailored requirement, adopt the updated
blueprint, or record why the older requirement remains appropriate.

## Applicability

Blueprint FRs should declare when they are likely to apply.

Example:

```json
{
  "applies_when": [
    "web_app",
    "authenticated_users",
    "session_based_auth"
  ],
  "not_applicable_when": [
    "static_site",
    "no_user_accounts"
  ]
}
```

A project profile can then be used to propose candidate blueprint FRs:

```json
{
  "project_type": ["web_app", "api"],
  "auth_model": ["authenticated_users", "session_based_auth"],
  "data_profile": ["personal_data", "admin_operations"],
  "deployment": ["containerized"]
}
```

The output should be a review-required config update proposal, not an automatic
mutation of the project catalog.

## Instantiation Workflow

Target workflow:

```text
Planning Studio project profile
  -> blueprint catalog selection
  -> review-required config update proposal
  -> human accepts, tailors, rejects or marks not applicable
  -> resolved project planning contract
  -> project FR catalog becomes part of the accepted assurance contract
  -> scans/tests produce evidence
  -> runtime graph resolves project assurance and compliance lenses
```

Blueprint selection should happen inside Planning Studio before Code Studio or
Code Generator start treating the requirement set as binding.
The Planning Studio may use an agent to recommend blueprints, but accepted
requirements are created only after human review.

Potential command:

```bash
asvs-scanner propose-blueprint-frs \
  --project tapestry-mono \
  --config-selection planning/config-selection.json \
  --blueprint data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json \
  --output planning/blueprint-proposal.json

asvs-scanner blueprint-decisions-to-config-update \
  --project tapestry-mono \
  --run-id planning-run-001 \
  --proposal planning/blueprint-proposal.json \
  --decisions planning/blueprint-decisions.json \
  --blueprint data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json \
  --output planning/config-update-proposal.json
```

The proposal should preserve:

- blueprint source and version
- blueprint artifact hash
- rationale for applicability
- assumptions
- proposed FR/TBT additions
- compliance mappings carried by the accepted FR/TBT definitions
- review status

Instantiation decisions should be first-class review records:

| Decision | Meaning |
| --- | --- |
| `proposed` | The blueprint FR/TBT is suggested but not accepted. |
| `accepted_as_is` | The project accepts the blueprint FR/TBT without material change. |
| `tailored` | The project accepts a modified version; the changed fields and rationale are recorded. |
| `rejected` | The project declines the candidate requirement with a reason. |
| `not_applicable` | The project reviewed applicability and determined the requirement does not apply. |

Only accepted or tailored items become part of the project assurance contract.

## Compliance Mapping Is Optional But Explicit

Every project FR remains first-class whether it maps to ASVS or not.

The graph should support this shape:

```text
FR
  -> TBT(s)
      -> expected evidence
      -> observed evidence
  -> optional compliance mappings
      -> ASVS row
      -> NIST control
      -> internal policy requirement
      -> framework gate criterion
```

If an FR does not map to ASVS, that must not mean the FR disappears. It means one
of several explicit states applies.

Recommended compliance mapping states:

| State | Meaning |
| --- | --- |
| `mapped` | The FR/TBT has one or more declared mappings to the selected regime. |
| `mapping_required` | The FR appears relevant to the selected regime, but no reviewed mapping exists yet. |
| `project_only` | The FR is required by the project assurance contract but is intentionally outside the selected regime. |
| `not_applicable` | The selected regime was considered and does not apply; a reason is required. |
| `mapped_elsewhere` | The FR maps to another declared regime or framework, but not the currently selected one. |

The UI should not say only "No compliance row mapped" because that is ambiguous.
It should explain which state applies and what action, if any, is required.

These states are primarily resolved graph/projection state. They may be derived
from accepted mappings, not-applicable decisions, rejected blueprint decisions,
project profile, scanner signals or human review notes. They should not be
blindly written back as canonical FR/TBT config fields unless the project has
made a reviewed decision that belongs in versioned config.

Before human review, `mapping_required` should be treated as a candidate or
review-required state, not as proof that the selected regime definitely applies.
The source of that candidate state should be visible: blueprint applicability,
scanner heuristic, agent recommendation or reviewer note.

## Project Assurance Can Raise The Bar

The application should make this position explicit:

```text
ASVS is one declared compliance lens.
The project assurance graph may contain requirements beyond that lens.
Those extra requirements are visible, evidenced and auditable.
```

This is a product strength. It prevents a false sense of safety where important
project-specific controls vanish because they are not currently mapped to ASVS.

Example display copy:

```text
FR-019 is required for project assurance.
No ASVS mapping is declared.
This does not reduce ASVS compliance directly, but it remains an open project
assurance obligation.
```

## Blueprint Compliance Mappings

Blueprints may include generic compliance mappings where the relationship is
stable.

Example:

```json
{
  "blueprint_tbt": "TBT-BP-ASVS-SESSION-MANAGEMENT-001-A",
  "compliance_mappings": [
    {
      "regime": "ASVS",
      "version": "5.0.0",
      "row": "v5.0.0-7.1.1",
      "relationship": "direct",
      "rationale": "Expired JWT rejection is direct evidence for the row."
    }
  ]
}
```

When a project instantiates the blueprint, those mappings can be proposed for
the project TBT. The project can accept, tailor or reject them.

## Project-Specific FRs

Some FRs will always be project-specific:

- domain workflow controls
- business-role approvals
- product-specific audit events
- tenant-specific data handling
- bespoke operational constraints

These should be authored directly in the project FR catalog or proposed by an
agent after source/product inspection. They can still map to ASVS, NIST or
another regime if a reviewed mapping is declared.

Project-specific FRs should not be forced into blueprint lineage. The lineage
field should be optional.

## Not Applicable And Rejected Items

If a blueprint FR is considered but not accepted, the project should be able to
record that decision.

Example:

```json
{
  "item": "FR-BP-ASVS-FILE-UPLOAD-001",
  "decision": "not_applicable",
  "reason": "The project has no user-controlled file upload surface.",
  "reviewed_by": "security-team",
  "reviewed_at": "2026-07-11"
}
```

This creates audit evidence that the requirement was considered, not silently
omitted.

## Runtime Graph Semantics

At runtime, the graph should show:

- blueprint lineage as provenance, not as proof
- project FRs as accepted assurance contract nodes
- TBTs as declared evidence obligations
- tests/scanner/manual artifacts as evidence nodes
- compliance rows as regime-specific lenses
- mapping-required/project-only/not-applicable states as explicit nodes or
  properties

Blueprints should not satisfy anything by themselves. Only project-accepted
FR/TBT definitions and observed evidence can contribute to resolved assurance.

## UI Expectations

The dashboard should make these distinctions obvious:

- Project FRs: show all accepted project requirements, including project-only
  requirements.
- Compliance Regime: show only requirements that map to that selected regime,
  plus explicit mapping-required/not-applicable summaries.
- Traceability Graph: show FR -> TBT -> evidence and optional compliance
  edges.
- Scanner Results: show whether scanner evidence maps directly to compliance
  rows, to project FR/TBT chains, or only to general security hygiene.
- Native Review Board / Project FR board: allow candidate blueprint FRs to be
  proposed, accepted, tailored or rejected.

The frontend should render backend graph projections. It should not infer
whether an FR is outside ASVS or merely unmapped.

## Proof And Audit Implications

For future zero-knowledge or trustless verification, blueprint and mapping
models place several requirements on the config:

- blueprint catalogs must be versioned and content-addressed
- project FR catalogs must record accepted config hashes
- lineage references must include stable IDs and source hashes
- instantiation decisions must record whether a blueprint was accepted as-is,
  tailored, rejected or marked not applicable
- not-applicable/project-only decisions must be signed or review-attributed
- compliance mappings must be versioned by regime and ruleset version
- graph manifests must commit to accepted config, mapping packs, evidence
  artifacts and graph root hashes

This lets a verifier check claims such as:

```text
The project satisfies all accepted ASVS 5.0.0 rows in scope.
```

without confusing that with:

```text
The project satisfies every project-only assurance requirement.
```

Those are different typed claims over the same committed runtime graph.

## Implementation Tasks

1. Add Planning Studio schemas and workflow modules described in
   `docs/ASSURANCE_PLANNING_STUDIO.md`.
2. Add optional `derived_from` lineage fields to FR and TBT schemas.
3. Add explicit compliance mapping status to project FR/TBT projections:
   `mapped`, `mapping_required`, `project_only`, `not_applicable`,
   `mapped_elsewhere`.
4. Create a first blueprint catalog fixture under
   `data/blueprints/security-core/asvs-5.0.0/`. Implemented for ASVS 5.0.0
   session-management obligations.
5. Add a project profile schema or small profile fixture for applicability
   matching, then align it with the Planning Studio `ProjectIntake` and
   `ProjectConfigSelection` schemas. Initial matching uses
   `ProjectConfigSelection` ruleset selections; richer profiles remain a
   follow-up.
6. Add a proposal command that converts applicable blueprint FRs into
   review-required blueprint selection proposals. Implemented as
   `propose-blueprint-frs`.
7. Add first-class blueprint instantiation decision records:
   `accepted_as_is`, `tailored`, `rejected`, `not_applicable`. Implemented via
   `blueprint-decision-log.schema.json`.
8. Extend graph construction to preserve blueprint lineage and explicit derived
   mapping status.
9. Update Project FR and Compliance Regime UI copy so unmapped FRs are not shown
   as silent gaps.
10. Add audit records for rejected/not-applicable blueprint FRs.
11. Include blueprint catalog hashes and project acceptance decisions in the
   graph manifest. Implemented at artifact-commitment level through
   `planning_artifacts` and `planning_artifacts_hash`; full graph nodes/edges
   for rejected/not-applicable decisions remain a follow-up.
12. Add tests proving blueprint instantiation does not count as evidence until
    the project accepts the FR/TBT and observed evidence exists. Backend tests
    now prove accepted blueprint decisions emit FR/TBT config updates only, not
    evidence.

## Open Questions

1. Should project profiles be explicit config files, inferred from scan
   discovery, or both?
2. Should `mapping_required` be a property of an FR, a TBT, or a separate graph
   review node?
3. Should rejected blueprint FRs live in the project FR catalog, a decision log,
   or the assurance instance?
5. What is the minimum security-core blueprint set needed to validate the 80/20
   assumption?
