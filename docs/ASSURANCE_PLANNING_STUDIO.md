# Planning Studio

## Purpose

This document defines the upstream planning workflow that creates a structured
planning/design contract before code is written or assessed. Assurance config is
derived from that approved contract by the Assurance Generator.

The core principle is:

```text
human intent + versioned config + agent recommendations
  -> approved planning/design contract
  -> generated assurance config
  -> code design and implementation
  -> assurance evidence against the accepted artifacts
```

The Planning Studio is influenced by VibeGuide's setup profile, resolved
contract, config package and approval model, but it is more assurance-native.
Its primary output is not a free-form design document. Its primary output is a
typed, versioned, review-approved planning contract that can be rendered as a
design/SOW document, transformed by the Assurance Generator into graph-ready
assurance config, and consumed by downstream agents and the Assurance Engine.

## Product Boundary

The target product chain is:

```text
Planning Studio
  -> Assurance Generator
  -> SOW Studio
  -> Code Studio
  -> Code Generator
  -> Assurance Engine

Governance Engine governs approvals, waivers, decisions and audit across all stages.
```

The responsibilities are distinct:

| Product stage | Responsibility |
| --- | --- |
| Planning Studio | User-facing intake, config selection, questionnaire answers, blueprint review, bespoke requirements and planning-contract approval. |
| Assurance Generator | Generates assurance-ready config from the approved planning contract: FR catalog, TBTs, compliance mappings, expected evidence and assurance obligations. |
| SOW Studio | User-facing review, editing and approval of the human-readable SOW, design document, governance pack and procurement artifacts. |
| Code Studio | User-facing technical design workspace for architecture, module boundaries, API/data model decisions and implementation-plan approval. |
| Code Generator | Implements code and assurance tests from the approved Code Studio handoff, under deterministic gates. |
| Assurance Engine | Verifies implementation evidence against the accepted FR/TBT/compliance graph. |
| Governance Engine | Cross-cutting approval, waiver, compensating-control, not-applicable, signature and audit lifecycle. |

Studio means human-facing choice, review and approval. Generator means a
service that creates structured artifacts from approved inputs. Engine means a
deterministic/runtime service that evaluates, verifies, enforces or governs.

Planning Studio does not replace Code Studio initially. It constrains it. Code
Studio should consume the approved planning contract instead of inventing core
requirements, compliance scope or governance expectations from scratch.

The Assurance Engine should also remain a bounded engine until its current
implementation is stable. The intended sequence is:

```text
1. Finish the Assurance Engine foundation in this repository.
2. Stabilize schemas, graph vocabulary, evidence, claims, proof and runner
   contracts.
3. Build the file-backed Planning Studio foundation against those contracts.
4. Integrate Planning Studio and the seven product boundaries into VibeGuide.
5. Move or wrap the Assurance Engine inside VibeGuide as a bounded service when
   the engine contract is stable.
```

This keeps the core assurance model from being disturbed by product-integration
churn while it is still settling, while still leaving a clear path to a single
VibeGuide workflow later.

The handoff rule is:

```text
asvs-scanner finishes Assurance Engine and planning-contract foundations
  -> active docs move into VibeGuide
  -> Planning Studio implementation starts on a VibeGuide branch
  -> each product boundary is built with VibeGuide's typed Python atomic/workflow
     modules and gated quality checks
```

This repository should not become the long-term home for user-facing Planning
Studio, SOW Studio, Code Studio or Code Generator implementation. It may host
file-backed schemas, fixtures and proof-of-contract modules while the Assurance
Engine contract is stabilizing.

## Relationship To Live Docs

This document is authoritative for the upstream project planning and design
contract workflow.

- `docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md` defines reusable blueprint FR/TBT
  catalogs, project-specific assurance requirements and compliance mapping
  states.
- `docs/RUNTIME_GRAPH_ARCHITECTURE.md` defines the runtime graph, evidence,
  audit, manifest and proof model that consumes the accepted planning outputs.
- `docs/FRAMEWORK_COCKPIT_DESIGN.md` defines the assurance-framework cockpit UX
  and graph-projection responsibilities.

Archived docs are historical only. They are not authoritative for the Planning
Studio, runtime graph, cockpit, schemas, audit or proof model.

## Modes

The workflow must work before code exists and after code exists.

### Greenfield

Use when the project is being planned before implementation.

```text
project intent
  -> config selection
  -> high-level questions
  -> blueprint FR/TBT recommendations
  -> project-specific requirements
  -> approved planning contract
  -> SOW Studio / Code Studio / Code Generator
```

The output contains expected evidence and deterministic gates, but observed
evidence will usually be missing until implementation and scans/tests happen.

### Existing Codebase

Use when code already exists.

```text
project intent
  -> config selection
  -> repository analysis and scanner/test discovery
  -> blueprint FR/TBT recommendations
  -> map existing tests and code evidence
  -> project-specific gap review
  -> approved planning contract
  -> Assurance Engine remediation workflow
```

Existing code can inform applicability, but it should not silently define the
assurance contract. Agent findings remain recommendations until reviewed.

Existing-codebase mode should reuse current repository discovery entry points
where possible. In this repository that means wrapping, rather than replacing,
the existing test/artifact discovery paths such as `scripts/discover-project-tests.py`
and `scripts/load_target_artifacts.py`.

## User Experience

The user should not start with a blank SOW. The experience should guide them
from broad selections to specific accepted obligations.

### Canonical Journey

The full product journey is:

```text
Project intake
  -> Config selection
  -> Blueprint FR/TBT selection
  -> Project-specific FR authoring
  -> Assurance config generation
  -> Design/SOW generation
  -> Code Studio / Code Generator handoff
  -> Implementation and assurance-test creation
  -> Scan and evidence collection
  -> Runtime assurance graph
  -> Review and remediation loop
  -> Assurance claim / proof export
```

The same journey must work when no code exists yet and when the user is
bringing an existing codebase under assurance control.

### Stage Responsibilities

| Stage | User experience | Source of truth / output |
| --- | --- | --- |
| Project intake | User describes product, domain, users, risk, deployment, integrations and data sensitivity. | `project-intake.schema.json` |
| Config selection | User or agent selects compliance regimes, assurance framework, architecture pattern, governance profile, evidence expectations and deployment constraints. | `project-config-selection.schema.json` |
| Blueprint FR/TBT selection | Agent proposes reusable blueprint FR/TBT chains; user accepts, tailors, rejects or marks not applicable. | `blueprint-selection-proposal.schema.json` plus accepted config-update proposals |
| Project-specific FR authoring | User adds bespoke product, domain, workflow or above-standard requirements not covered by blueprints. | `project-specific-requirements.schema.json` |
| Assurance config generation | Assurance Generator resolves accepted blueprints, bespoke requirements, mappings, ownership, expected evidence, waivers and decisions into graph-ready assurance artifacts. | `resolved-project-planning-contract.schema.json` and `project-assurance-contract.schema.json` |
| Design/SOW generation | System renders a human-readable design/SOW view from the approved contract. | `project-design-document-manifest.schema.json` and rendered document artifacts |
| Code Studio / Code Generator handoff | Downstream agents receive approved constraints, not raw unreviewed recommendations. | `code-studio-handoff-pack.schema.json` and `code-generator-handoff-pack.schema.json` |
| Implementation and assurance-test creation | Code and tests are created against approved FR/TBT obligations and deterministic gates. | Source code plus `assurance-test-pack.schema.json` |
| Scan and evidence collection | Scanner and approved tests produce observed evidence. | `evidence-bundle.schema.json` |
| Runtime assurance graph | Runtime graph joins FRs, TBTs, compliance rows, blueprint lineage, scanner results, evidence, waivers, decisions and claims. | `graph-manifest.schema.json` and dashboard payload |
| Review and remediation loop | User reviews gaps, unsupported FRs, failing scanner evidence, missing tests and required decisions. | Config-update proposals, board state and review/audit records |
| Assurance claim / proof export | System exports claims, manifests, hashes and proof-ready evidence commitments. | `assurance-claim.schema.json` and `assurance-proof-bundle.schema.json` |

### Planning Studio Flow

1. Choose project mode: greenfield or existing codebase.
2. Select high-level config: application type, architecture pattern, technology
   stack, compliance regimes, assurance framework, security posture, governance
   profile, deployment target and agent autonomy.
3. Answer config-driven high-level questions.
4. Review agent-recommended blueprint FR/TBT chains.
5. Accept, tailor, reject or mark candidate blueprint obligations as not
   applicable.
6. Add bespoke project-specific requirements and constraints.
7. Review generated project design/SOW and graph-ready assurance config.
8. Approve the contract.
9. Hand the approved planning contract to Assurance Generator, then hand the
   generated SOW/Code artifacts to SOW Studio, Code Studio and Code Generator.

The human-readable design/SOW is a rendered view. The typed resolved planning
contract is the source of truth.

Downstream code generation must not invent its own assurance model. Assurance
Generator, SOW Studio, Code Studio, Code Generator and the Assurance Engine
consume the approved Planning Studio contract, its config references and its
immutable hashes. Agents may propose refinements, but those refinements must
return to the Planning Studio or config-update workflow before they become
binding assurance obligations.

## Python Module Shape

Implementation should follow the same atomic/workflow split used in VibeGuide:
small typed atomic modules for deterministic transformations, and workflow
modules for orchestration, review state and side effects.

Best-practice implementation rules:

- schema first, typed Python models second, workflow orchestration third
- atomic modules are deterministic and side-effect free
- workflow modules own explicit file/database side effects and audit records
- every accepted mutation has an actor, timestamp, source artifact and hash
- draft, proposal and approved states are separate in schemas and tests
- no UI state is treated as assurance state
- every slice runs the relevant VibeGuide-style gates before the next slice

Initial implementation should live in this repository while the assurance
contract shape is still stabilizing. Once the schemas and handoff packs are
stable, the same module boundaries can be promoted into VibeGuide.

Recommended package layout:

```text
scripts/planning_studio/
  atomic/
    project_intake.py
    config_selection.py
    questionnaire_builder.py
    answer_normalizer.py
    blueprint_recommender.py
    repository_analysis.py
    existing_test_mapper.py
    project_requirement_authoring.py
    planning_contract_resolver.py
    assurance_contract_builder.py
    design_document_renderer.py
    handoff_pack_builder.py
  workflows/
    planning_session_workflow.py
    config_selection_workflow.py
    questionnaire_workflow.py
    blueprint_review_workflow.py
    project_requirement_workflow.py
    planning_approval_workflow.py
    handoff_workflow.py
  models.py
  storage.py
  validators.py
```

`models.py` should contain typed Python models or dataclasses that mirror the
JSON schemas. `storage.py` should hide whether state is file-backed or
database-backed. `validators.py` should run schema validation plus cross-file
checks that JSON Schema cannot express.

### Atomic Modules

| Module | Inputs | Output | Side effects |
| --- | --- | --- | --- |
| `project_intake` | User intent, project mode, product summary | `ProjectIntake` | None |
| `config_selection` | Available config package index, user selections | `ProjectConfigSelection` | None |
| `questionnaire_builder` | Selected config packages, intake | `Questionnaire` | None |
| `answer_normalizer` | User answers, questionnaire schema | `ProjectDesignAnswers` | None |
| `blueprint_recommender` | Intake, selected config, answers, blueprint catalogs | `BlueprintSelectionProposal` | None |
| `repository_analysis` | Source repo path, Graphify or scanner discovery artifacts, target artifact loaders | `RepositoryAnalysisSummary` | None |
| `existing_test_mapper` | Repository analysis, discovered native tests, FR/TBT catalog candidates | `ExistingEvidenceMappingProposal` | None |
| `project_requirement_authoring` | User-authored bespoke requirements, agent suggestions | `ProjectSpecificRequirementSet` | None |
| `planning_contract_resolver` | Intake, config selection, answers, accepted blueprints, bespoke requirements | `ResolvedProjectPlanningContract` | None |
| `assurance_contract_builder` | Resolved planning contract | `ProjectAssuranceContract` | None |
| `design_document_renderer` | Resolved planning contract, project assurance config | `ProjectDesignDocument` | None |
| `handoff_pack_builder` | Resolved planning contract, design document, project assurance config | `CodeStudioHandoffPack` and `CodeGeneratorHandoffPack` | None |

Atomic modules should be deterministic. They should not mutate accepted config,
write approvals or inspect live UI state.

### Workflow Modules

| Module | Responsibilities | Side effects |
| --- | --- | --- |
| `planning_session_workflow` | Create/resume planning sessions, track current step, lock review state. | Writes draft session state. |
| `config_selection_workflow` | Persist selected package refs, unknowns and not-applicable selections. | Writes draft config selection. |
| `questionnaire_workflow` | Presents questions, stores answers, records skipped/unknown decisions. | Writes draft answers. |
| `blueprint_review_workflow` | Stores candidate blueprint decisions: accept, tailor, reject, not applicable. | Writes review decisions and proposal artifacts. |
| `project_requirement_workflow` | Stores bespoke FRs, constraints and governance notes. | Writes draft project requirement set. |
| `planning_approval_workflow` | Freezes approved contract versions after human review. | Writes immutable accepted contract, approval events and hashes. |
| `handoff_workflow` | Publishes approved handoff packs to downstream MCP servers. | Writes handoff artifacts and audit records. |

Workflow modules may write files or database records, but only the approval
workflow may promote draft/proposal data into an accepted project contract.

## Planning State Machine

Planning sessions should use explicit states.

| State | Meaning | May produce downstream handoff? |
| --- | --- | --- |
| `draft` | Intake, config selection or answers are still being edited. | No |
| `recommendations_ready` | Agent or deterministic recommendations are available for review. | No |
| `review_required` | The user must accept, tailor, reject or mark items not applicable. | No |
| `approved` | The planning contract has been reviewed and frozen. | Yes |
| `superseded` | A newer approved contract replaces this one. | No, except for historical audit |
| `rejected` | The planning session was closed without acceptance. | No |

Blueprint candidate decisions should use:

| Decision | Meaning |
| --- | --- |
| `pending_review` | Candidate is proposed but not accepted. |
| `accepted_as_is` | Candidate becomes a project obligation without material change. |
| `tailored` | Candidate becomes a project obligation with recorded changes. |
| `rejected` | Candidate is not accepted; reason required. |
| `not_applicable` | Candidate was reviewed and does not apply; reason required. |

Only `accepted_as_is` and `tailored` decisions can contribute to the approved
project assurance contract.

Allowed planning-session transitions:

```text
draft -> recommendations_ready
draft -> rejected
recommendations_ready -> review_required
recommendations_ready -> draft
review_required -> draft
review_required -> approved
review_required -> rejected
approved -> superseded
rejected -> draft, only by creating a new planning session revision
```

An approved planning session must not return to draft. Changes after approval
create a new revision and mark the previous approved contract `superseded` only
after the new revision is approved.

## Typed Schemas

The Planning Studio should reuse existing assurance schemas rather than create a
parallel truth model.

### Schema Reuse Map

| Artifact | Schema strategy | Canonical or derived |
| --- | --- | --- |
| Project intake | New `project-intake.schema.json`. | Canonical planning input |
| Config selection | New `project-config-selection.schema.json`, using existing config package refs/hashes where available. | Canonical planning input |
| Design questionnaire | New `project-design-questionnaire.schema.json`. | Derived from selected config |
| Design answers | New `project-design-answers.schema.json`. | Canonical planning input |
| Blueprint catalog | Reuse `fr-catalog.schema.json` with blueprint ID conventions and lineage metadata described in `docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`. | Canonical reusable config |
| Blueprint selection proposal | New `blueprint-selection-proposal.schema.json`, but accepted catalog mutations must be emitted as `config-update-proposal.schema.json`. | Proposal only |
| Blueprint decision log | New lightweight session/audit artifact, but not the catalog mutation mechanism. | Review/audit record |
| Project-specific requirements | Prefer `fr-catalog.schema.json` entries or `config-update-proposal.schema.json` operations; use a draft helper artifact only for unapproved session notes. | Proposal until applied |
| Resolved project planning contract | New `resolved-project-planning-contract.schema.json`. | Canonical approved planning contract |
| Project assurance contract | Derived projection that resolves into existing `fr-catalog`, `compliance-mapping-pack`, `scanner-compliance-mapping-pack`, `assurance-framework`, `assurance-instance` and evidence-policy artifacts. | Derived/exported cache |
| Design document manifest | New `project-design-document-manifest.schema.json`. | Derived/render manifest |
| Code Studio handoff | Target schema: `code-studio-handoff-pack.schema.json`. | Derived/exported handoff |
| Code Generator handoff | Target schema: `code-generator-handoff-pack.schema.json`. | Derived/exported handoff |

The resolved project planning contract is the source of truth for Planning
Studio approval. `project-assurance-contract.json` is a deterministic projection
and export bundle. If it diverges from the approved planning contract, the
planning contract wins and the derived artifact must be regenerated.

Blueprint catalog shape is not a new template-library schema in Phase 1. The
settled starting point is the "Option B" model from
`docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`: maintain a versioned reference FR
catalog shaped like `fr-catalog.schema.json`, with stable blueprint IDs and
lineage fields when instantiated into a project.

Minimum schema responsibilities:

| Schema | Required purpose |
| --- | --- |
| `project-intake.schema.json` | Project identity, mode, source repo if any, product intent, known constraints and stakeholder context. |
| `project-config-selection.schema.json` | Selected config package refs, versions, hashes, source of selection, unknowns and not-applicable choices. |
| `project-design-questionnaire.schema.json` | Questions generated from selected config, applicability conditions, answer types and required/optional markers. |
| `project-design-answers.schema.json` | User answers, skipped questions, unknowns, assumptions and provenance. |
| `blueprint-selection-proposal.schema.json` | Candidate blueprint FR/TBT chains with applicability rationale, confidence and source config refs. |
| `blueprint-decision-log.schema.json` | Session-level human decisions over candidates, tailoring deltas, reviewer attribution and reasons; catalog changes still go through config-update proposals. |
| `project-specific-requirements.schema.json` | Optional draft helper for bespoke notes before they are converted into FR/TBT config-update proposals. |
| `resolved-project-planning-contract.schema.json` | Deterministic resolved contract with all accepted planning inputs and section hashes. |
| `project-assurance-contract.schema.json` | Derived export bundle that contains or references the existing graph-ready assurance artifacts emitted for the Assurance Engine. |
| `project-design-document-manifest.schema.json` | Rendered design/SOW path, hash, source contract hash and sections rendered. |
| `code-studio-handoff-pack.schema.json` | Approved context Code Studio may use for technical design. |
| `code-generator-handoff-pack.schema.json` | Approved implementation constraints, tasks and gates Code Generator may use. |

All schemas named in this table currently exist in `data/schemas/`. Some are
minimal foundation schemas intended to prove the contract shape before the
full VibeGuide product implementation expands them.

The repository now uses Code Studio / Code Generator handoff schema names. Legacy
handoff vocabulary is retired and should not be reintroduced.

Schemas for SOW Studio, Code Studio, Code Generator and Governance Engine
artifacts beyond the handoff packs are owned by their respective product docs.
Planning Studio may reference those future artifacts, but it must not absorb
their product-specific schema responsibilities.

### Schema Evolution And Downstream Discovery

Planning Studio should be stable, but it should not pretend to predict every
future downstream need. The stable spine is:

- project identity and mode
- selected config package refs, versions and hashes
- user answers, assumptions and unknowns
- accepted, tailored, rejected and not-applicable blueprint decisions
- bespoke project requirements
- approval state, actor, timestamp and artifact hashes
- accepted planning contract hash

Downstream products may discover new required fields. Those changes must be
classified before changing schemas:

| Change belongs to | Rule |
| --- | --- |
| Planning Studio core | Add only when it changes user intent, accepted obligations, config selection, provenance, approval state or contract identity. |
| Product-owned handoff artifact | Add when it is specific to SOW Studio, Code Studio, Code Generator, Assurance Engine or Governance Engine execution. |
| Governance Engine | Add when it is an approval, waiver, compensating control, not-applicable decision, signature or audit lifecycle concern. |
| Assurance Generator / config update | Add when it changes FR/TBT/compliance/evidence obligations and therefore must flow through reviewed config-update proposals. |

Schema evolution must be explicit: update `schema_version`, add migration or
regeneration notes, preserve old artifact hashes for audit, and add fixtures
and tests before treating the new shape as accepted. The Planning Studio
contract is the stable spine; downstream handoff schemas are the controlled
extension points.

The resolved planning contract should include:

- selected config package refs, versions and hashes
- user answers and unknown/not-applicable decisions
- accepted blueprint lineage and tailoring decisions
- rejected/not-applicable blueprint decisions
- project-specific FRs and constraints
- architecture and governance decisions
- compliance regimes and mapping state using the states defined in
  `docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`: `mapped`,
  `mapping_required`, `project_only`, `not_applicable`, `mapped_elsewhere`
- expected evidence obligations
- deterministic gates and readiness rules
- downstream prompt fragments and handoff metadata
- section hashes and overall contract hash

Every schema must include:

- `schema_version`
- stable artifact ID
- source/provenance references
- created timestamp
- status where the artifact can be draft/reviewed/approved
- content hash or enough deterministic material to be hashable

## Prerequisites

Phase 1 depends on several companion-doc and existing-engine foundations:

| Dependency | Why it matters |
| --- | --- |
| FR/TBT `derived_from` lineage fields | Required to record accepted blueprint provenance. Defined in `docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`. |
| Canonical JSON hashing utility | Required for deterministic contract hashes and repeatable handoff manifests. Use the shared hashing approach from `docs/RUNTIME_GRAPH_ARCHITECTURE.md` and existing `scripts/artifact_hashing.py`. |
| Explicit compliance mapping states | Required so project-only and mapping-required FRs do not become ambiguous gaps. Defined in `docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`. |
| Config update proposal pipeline | Required so blueprint and bespoke FR/TBT acceptance uses the existing review-gated mutation path instead of a parallel approval system. |
| Existing-codebase discovery adapters | Required for onboarding mode. Wrap existing scanner/test/artifact discovery scripts before adding new discovery logic. |

These are prerequisites for a clean implementation, not optional polish.

## Config Package Role

Config packages should drive the planning process.

Examples:

| Package type | Planning contribution |
| --- | --- |
| Application type profile | Product-shape questions, default blueprint applicability hints. |
| Architecture profile | Allowed patterns, forbidden patterns, module boundaries, design questions. |
| Compliance ruleset | Candidate control scope, compliance mapping expectations. |
| Assurance framework | Gates, roles, approvals and process obligations. |
| Security profile | Security design questions, blueprint FR hints, evidence expectations. |
| Governance profile | review, approval, ownership and audit obligations. |
| Deployment profile | environment constraints, runtime evidence and operational requirements. |
| Agentic profile | autonomy limits, tool permissions and human approval rules. |
| Blueprint catalog | reusable FR/TBT chains and applicability metadata. |

The selected packages are not copied into the project by hand. They are resolved
into a deterministic planning contract with recorded source versions and hashes.

## Artifact Layout

For the first implementation, write planning artifacts under a report or project
planning directory rather than mutating application source.

Recommended file-backed layout:

```text
.asvs-scanner/planning/<planning-id>/
  intake.json
  config-selection.json
  questionnaire.json
  answers.json
  repository-analysis.json
  existing-evidence-mapping-proposal.json
  blueprint-proposal.json
  blueprint-decisions.json
  project-specific-requirements.draft.json
  config-update-proposal.json
  resolved-planning-contract.json
  project-assurance-contract.json
  design.md
  design-document-manifest.json
  code-studio-handoff.json
  code-generator-handoff.json
  audit-log.jsonl
```

When this moves into VibeGuide, the storage adapter can write the same logical
artifacts to the backend ledger/database while preserving exported JSON files
for audit, suitcase and proof workflows.

`config-update-proposal.json` is the artifact that proposes accepted blueprint
or bespoke FR/TBT changes to the project catalog. The decision log records the
Planning Studio session decision, but the catalog mutation still goes through
the existing proposal validation/review/apply pipeline.

## Blueprint And Bespoke Requirements

Blueprint FR/TBT chains are reusable candidate assurance obligations. They are
never accepted automatically.

Project-specific requirements are equally first-class. A project FR can be:

- accepted from a blueprint as-is
- tailored from a blueprint
- authored specifically for the project
- outside the selected compliance regime
- mapped to one or more compliance regimes
- deliberately marked not applicable for a given regime

This lets the Planning Studio raise the bar beyond a standard while keeping
standard-specific claims precise.

Decision vocabulary for blueprint candidates is defined authoritatively in
`docs/BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md`. The Planning Studio uses that
vocabulary in its session state and emits accepted/tailored decisions as
review-required config update proposals.

## Downstream Handoff

The Code Studio handoff should include:

- approved project intent and constraints
- selected architecture pattern and governance profile
- accepted FR/TBT catalog
- compliance and assurance framework scope
- expected evidence obligations
- deterministic gates
- rejected/not-applicable decisions that affect design
- open assumptions requiring user review
- contract hashes and source config refs

The Code Generator handoff should include only approved implementation-relevant
material:

- technical design produced by Code Studio
- implementation tasks
- architecture constraints
- accepted FR/TBT obligations
- test and scanner expectations
- gate commands and evidence requirements
- prompt/context hashes

Code Generator should not receive unapproved blueprint proposals as instructions.

## Code Studio Integration Contract

Code Studio should be updated after Planning Studio is implemented.

Required changes:

1. Add a Code Studio intake path that accepts the approved Code Studio handoff artifact.
2. Load the approved planning contract hash and display it in stage guidance.
3. Treat accepted FRs, TBTs, compliance scope, governance choices and
   architecture constraints as fixed inputs.
4. Allow Code Studio to propose technical refinements, but not to silently
   change accepted requirements or compliance scope.
5. Emit technical design artifacts that reference the planning contract hash.
6. Block Code Generator handoff if Code Studio output contradicts accepted
   planning constraints without an explicit reviewed decision.

This preserves the chain:

```text
approved planning contract
  -> code-facing design
  -> implementation
  -> evidence
```

## Assurance Engine Handoff

The Assurance Engine consumes accepted planning outputs as versioned config and
derived export bundles:

- project FR catalog
- TBT catalog and expected evidence
- compliance mapping packs
- scanner compliance mapping packs
- assurance framework/instance config
- waiver, decision and compensating-control records
- graph manifest commitments

The canonical assurance inputs remain the existing typed artifacts above.
`project-assurance-contract.json` may package or reference them for handoff, but
it must not become a second hand-authored assurance model.

Scans, tests and manual reviews then produce live observations against this
contract. The runtime graph resolves whether the implementation satisfies the
accepted obligations.

## Audit And Proof Requirements

To support assurance, audit and future zero-knowledge proof generation, the
Planning Studio must preserve:

- config package IDs, versions and hashes
- blueprint source IDs, versions and hashes
- accepted/tailored/rejected/not-applicable decisions
- user/agent rationale and reviewer attribution
- immutable approved contract hashes
- rendered document hashes
- downstream handoff hashes
- graph manifest linkage through the `planning_artifacts` commitment section

The verifier should be able to distinguish:

```text
The project accepted this obligation.
The project rejected this candidate obligation.
The selected compliance regime does not cover this project-only obligation.
The implementation produced evidence for this accepted obligation.
```

Those are different claims and must remain separate.

## MCP Packaging Strategy

The long-term VibeGuide workflow should be designed as seven independently
productisable bounded products from the outset. Each product may become its own
MCP server and commercial offering. Early deployment may still expose fewer MCP
façades while the implementation is settling, but the product names, schemas,
permissions and mutation boundaries should remain seven-shaped.

### Seven Product Boundaries

| Product / MCP boundary | Owns | Example tools | Outputs |
| --- | --- | --- | --- |
| Planning Studio | User-facing project intent and contract creation. | `create_project_intake`, `select_project_config`, `answer_planning_questions`, `recommend_blueprints`, `record_blueprint_decision`, `author_project_requirement`, `resolve_planning_contract`, `approve_planning_contract` | Intake, config selection, answers, blueprint decisions, resolved planning contract. |
| Assurance Generator | Translation from approved planning decisions into assurance-ready config. | `build_project_assurance_contract`, `generate_fr_catalog`, `generate_tbt_catalog`, `generate_compliance_mappings`, `validate_assurance_contract`, `propose_config_update`, `apply_approved_config_update` | FR catalog, TBTs, compliance mapping packs, expected evidence and ownership/governance config. |
| SOW Studio | User-facing review, editing and approval of human-readable design and procurement artifacts. | `render_design_document`, `render_sow`, `render_architecture_brief`, `render_governance_pack`, `approve_sow`, `export_code_studio_handoff` | Design/SOW document, architecture brief, governance pack and Code Studio handoff pack. |
| Code Studio | User-facing technical design under the approved planning/SOW contract. | `ingest_code_studio_handoff`, `generate_technical_design`, `propose_module_boundaries`, `propose_api_contracts`, `propose_data_model`, `validate_design_against_contract`, `approve_technical_design`, `export_code_generator_handoff` | Technical design, implementation plan and Code Generator handoff pack. |
| Code Generator | Source changes and assurance-test creation. | `implement_task`, `create_assurance_test`, `run_deterministic_gates`, `produce_change_manifest`, `validate_changes_against_handoff` | Code changes, assurance tests, change manifest and gate results. |
| Assurance Engine | Runtime verification, graph, dashboards, claims and proofs. | `run_scan`, `run_approved_tests`, `refresh_test_evidence`, `map_existing_tests`, `generate_missing_test_specs`, `build_runtime_graph`, `export_dashboard`, `export_assurance_claim`, `export_proof_bundle` | Evidence bundle, runtime graph, dashboard, assurance claim and proof bundle. |
| Governance Engine | Cross-cutting human decisions, approvals, waivers, compensating controls, signatures and audit events. | `record_review_decision`, `approve_contract`, `approve_test`, `record_waiver`, `record_compensating_control`, `record_not_applicable`, `export_audit_log` | Decision log, approval records, waiver/control records, signatures and audit trail. |

This naming follows a product rule:

- Studio: user-facing workspace where humans make choices, review
  recommendations and approve intent.
- Generator: service that produces structured artifacts from approved inputs.
- Engine: deterministic/runtime service that evaluates, verifies, enforces or
  governs.

The implementation can still deploy fewer MCP façades initially, for example a
single orchestrating façade or grouped Studio/Generator/Engine façades. That is
a deployment convenience only. It must not blur the seven product boundaries
internally.

### Artifact Exchange

MCP servers should communicate through typed artifacts rather than hidden
conversation memory:

```text
Planning Studio
  -> resolved-project-planning-contract.json

Assurance Generator
  -> project-assurance-contract.json
  -> fr-catalog.json
  -> mapping packs

SOW Studio
  -> project-design-document.json/md/docx
  -> code-studio-handoff.json

Code Studio
  -> technical-design.json
  -> code-generator-handoff.json

Code Generator
  -> change-manifest.json
  -> assurance-test-pack.json

Assurance Engine
  -> evidence-bundle.json
  -> graph-manifest.json
  -> assurance-claim.json
  -> assurance-proof-bundle.json

Governance Engine
  -> decision-log.json
  -> approvals.json
  -> waivers.json
```

### Mutation Boundaries

Each MCP server may propose changes, but only specific servers may mutate
accepted state:

- Planning Studio mutates approved planning contracts.
- Assurance Generator mutates generated assurance config only through reviewed
  config-update proposals.
- SOW Studio renders and proposes SOW/design artifacts; it must not silently
  change accepted assurance obligations.
- Code Studio mutates approved technical design and implementation plans.
- Code Generator mutates source code, assurance tests, implementation manifests
  and gate results.
- Assurance Engine mutates observed evidence and runtime graph artifacts.
- Governance Engine mutates approvals, waivers, compensating controls,
  not-applicable decisions, signatures and audit records.

This preserves auditability and keeps every accepted mutation attached to a
typed artifact, actor, timestamp and hash.

## Implementation Roadmap

### Phase 1: asvs-scanner Foundation And Handoff Closure

0. Finish or confirm the Assurance Engine prerequisites in this repository:
   lineage fields, graph vocabulary, scanner compliance mappings, direct
   scanner blocker semantics, evidence records, graph manifests, assurance
   claims, proof bundles and validation commands.
1. Confirm the file-backed planning-contract schemas and fixtures in this
   repository, using the schema reuse map above.
2. Keep `scripts/planning_studio/` modules limited to proof-of-contract helpers
   unless and until the work moves to VibeGuide.
3. Add or preserve backend tests proving blueprint decisions, config-update
   proposals, graph commitments and unapproved/draft boundaries.
4. Keep Code Studio / Code Generator handoff schema files, model names and
   artifact names aligned with the seven-product vocabulary.
5. Keep graph-manifest commitments for planning contract and handoff artifacts.
   Implemented as mandatory `planning_artifacts` commitments with a separate
   `planning_artifacts_hash`; graph nodes/edges for those planning artifacts
   remain a follow-up.

This phase is not a mandate to keep building a user-facing Planning Studio in
`asvs-scanner`. It is the closure checklist for making the Assurance Engine and
planning-contract artifacts safe to hand to VibeGuide.

### Phase 2: VibeGuide Planning Studio Implementation

1. Open a new Codex session rooted in VibeGuide and create a Planning Studio
   branch.
2. Copy or move the active docs from this repository into VibeGuide.
3. Use VibeGuide's existing agent workflow for typed Python atomic/workflow
   modules and gated quality checks.
4. Implement Planning Studio schemas, models, atomic modules and workflow
   modules one slice at a time.
5. Add Code Studio and Code Generator handoff ingestion once the Planning Studio
   contract is stable.
6. Make Code Studio output reference the planning contract hash.
7. Add contradiction checks between technical design and accepted planning
   constraints.
8. Add tests proving Code Studio cannot overwrite accepted FR/TBT/compliance
   scope without a reviewed config update.

### Phase 3: Product Boundary Expansion

Phase 3 is contingent on VibeGuide's current workflow, storage and MCP server
shape at the time of implementation.

1. Preserve the seven product boundaries: Planning Studio, Assurance Generator,
   SOW Studio, Code Studio, Code Generator, Assurance Engine and Governance
   Engine. Early deployment may still expose fewer MCP façades.
2. Move stable Planning Studio modules into VibeGuide workflow structure.
3. Replace file storage with VibeGuide ledger/database storage adapter.
4. Preserve JSON export for audit, suitcase and proof artifacts.
5. Add Planning Studio UI for config selection, questions, blueprint review and
   approval.
6. Wire approved handoff packs into VibeGuide SOW Studio, Code Studio and Code
   Generator surfaces.
7. Package Governance Engine independently when approval, waiver and
   compensating-control policy requires independent lifecycle ownership.

## Implementation Readiness Checklist

Before coding starts, the implementation is ready when:

- Assurance Engine prerequisites in this document are either implemented or
  explicitly accepted as the first Phase 1 task
- module package names and file layout are agreed
- schemas have minimum required fields and validation rules
- the schema reuse map is followed, with no parallel assurance truth model
- planning states and blueprint decisions are explicit
- draft/proposal/approved boundaries are enforced
- accepted FR/TBT mutations route through config-update proposals
- file-backed artifact layout is agreed
- downstream handoff contracts are named and hash-bound
- tests can prove unapproved proposals do not become accepted obligations

The current document defines the boundaries well enough to continue Phase 1.
The schema/backend foundation, first blueprint fixture, blueprint proposal
command, decision-to-config-update conversion and focused backend tests are in
place. Graph manifests now commit to planning artifacts separately from
accepted runtime config. Target Code Studio / Code Generator handoff schema
renames, richer handoff generation, UI and VibeGuide integration remain
deliberately deferred.

## First Test Plan

Phase 1 should ship with focused tests before UI work begins.

| Test area | Required proof |
| --- | --- |
| Schema validation | Every fixture validates against its schema; invalid enum/status values fail. |
| Deterministic resolution | Same intake, config, answers and decisions produce the same resolved contract hash. |
| Draft boundary | Draft intake/config/answers cannot produce Code Studio or Code Generator handoff packs. |
| Blueprint approval boundary | `pending_review`, `rejected` and `not_applicable` candidates do not appear as accepted FR/TBT obligations. |
| Tailoring provenance | `tailored` candidates preserve blueprint lineage plus recorded field deltas and rationale. |
| Project-only requirements | Bespoke FRs without compliance mappings remain in the project assurance contract with explicit mapping state. |
| Config proposal reuse | Accepted blueprint and bespoke FR/TBT decisions emit `config-update-proposal` operations rather than mutating catalogs directly. |
| Derived assurance contract | `project-assurance-contract.json` is reproducible from the approved planning contract and existing assurance schemas. |
| Existing-codebase mode | Repository analysis and existing test mapping proposals can be produced from discovery artifacts without accepting them as evidence. |
| Handoff integrity | Handoff packs include the approved planning contract hash and exclude unapproved proposals. |
| Assurance output | Project assurance contract can be loaded by the existing graph/evidence tooling without creating observed evidence. |
| Audit log | Approval, rejection, not-applicable and supersession events are written with actor, timestamp and artifact hashes. |

## Open Questions

1. Should Planning Studio live inside this repository initially, or be split
   once the schemas and workflows stabilize?
2. Should draft session state be file-backed first, database-backed first, or
   support both adapters?
3. Which VibeGuide config packages should be imported unchanged, and which
   should be re-authored as assurance-native packages?
4. What is the minimum blueprint set needed for the first greenfield demo?
5. What exact handoff shape does the current Code Studio MCP surface need to
   consume the approved planning contract cleanly?
