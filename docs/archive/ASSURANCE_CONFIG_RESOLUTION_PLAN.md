# Assurance Config and Resolution Plan

## Purpose

This plan defines the next architecture step for VibeGuide Assurance Engine:
move from partially inferred FR/evidence relationships to an auditable model
where project Functional Requirements, TBT verification obligations,
compliance regimes, industry frameworks, scanner rules, tests, documents and
evidence artifacts are linked through explicit config and deterministic
resolution.

The core goal is:

```text
FR -> TBT -> scanner/test/manual/approval mechanism -> observed evidence -> assurance status
```

The dashboard should then explain every pass, partial, failure and gap from
that chain.

## Architectural Layers

### 1. Authoring Layer

Purpose: create and maintain assurance config up front.

Inputs:

- project FR catalog
- compliance regime snapshots, such as ASVS or NIST
- industry framework definitions, such as JSP-453 gated flows
- scanner rule catalogs and versions
- existing tests and generated VG_TEST_FRAMEWORK manifests
- manual/documentary evidence manifests

Agent role:

- propose config only
- identify likely mappings
- suggest missing TBTs
- suggest scanner/test/document evidence expectations
- identify stale scanner mappings
- produce review questions for ambiguous cases

Rules:

- all agent-authored mappings start as `review_status: proposed`
- accepted mappings become deterministic runtime input
- no hidden runtime agent judgement
- no compliance pass/fail conclusions from the agent
- review metadata is required before proposed config can become accepted

Prompt:

```text
backend/scripts/prompts/assurance-config-authoring.md
```

### 2. Validation Layer

Purpose: make config safe, complete and reviewable before runtime uses it.

Validation checks:

- every in-scope FR has at least one TBT
- every required TBT has `expected_evidence`
- every scanner mapping points to an existing TBT
- scanner mappings include scanner version or ruleset snapshot provenance
- compliance rows map to FR/TBT, manual review, or out-of-scope rationale
- framework criteria map to ruleset rows, FR/TBT, manual steps, roles or approvals
- evidence strength is explicit and conservative
- no orphan IDs
- no declared evidence source is counted as observed evidence
- no stale scanner rule references without review status
- no broad scanner "no findings" claim is treated as strong evidence unless allowed by policy

Output:

- accepted config packs
- warnings for proposed/stale/weak mappings
- blocking errors for broken references or missing required definitions

### 3. Resolution Layer

Purpose: deterministically link observed artifacts to TBTs.

Resolution order:

1. exact `fr_id` and `tbt_id` tags in manifests or metadata
2. accepted scanner rule mappings
3. test manifests and JUnit/result metadata
4. document manifests or frontmatter
5. framework approval and manual checklist records
6. weak path/pattern fallback only where config permits it

The resolver records why each link was made:

```text
artifact X satisfies/supports TBT Y because scanner rule Z matched accepted mapping M
```

It must distinguish:

- artifact declared but not observed
- scanner passed
- scanner found no issues
- scanner found issues
- scanner did not run
- scanner ran partially
- scanner output unavailable
- executable test passed
- executable test failed
- manual evidence present
- manual review required

### 4. Presentation Layer

Purpose: display the resolved assurance state consistently.

Views should consume the same normalized status model:

- Project FRs
- Compliance Regime
- Industry Framework
- Traceability Graph
- Evidence Files
- Agent Prompts

Graph chain:

```text
Compliance row / framework criterion / gate
-> FR
-> TBT
-> scanner control / executable test / manual evidence / approval
-> observed evidence artifact
```

Scanner evidence and executable test evidence must be visually distinct.

## Status Model

### TBT Status

| Status | Meaning |
|---|---|
| `passed` | Required evidence exists and satisfies the configured sufficiency policy. |
| `failed` | Required evidence exists and has a failing result. |
| `partial` | Supporting evidence exists but is not sufficient alone. |
| `missing` | Required evidence is absent. |
| `manual_review` | Human assessment or approval is required before status can pass. |
| `waived` | A reviewed waiver exists; this is not equivalent to passed. |
| `compensating_control` | A reviewed compensating control exists; this is not equivalent to passed. |
| `out_of_scope` | TBT is not required for the selected catalog/profile/regime. |

### Rollup

TBT status rolls up to:

- FR assurance status
- compliance row status
- industry framework criterion status
- gate status

Rollup must preserve reasons. A row should say whether the problem is:

- missing FR mapping
- missing TBT
- missing evidence
- failed evidence
- supporting-only evidence
- manual review required
- waived or compensating control
- out of scope

## Config Responsibilities

### FR Catalog

Defines project intent:

- FRs
- top-level TBTs owned by the catalog
- `TBT.proves` as the canonical relationship to one or more FRs
- `expected_evidence` per TBT
- project scope and selected strictness/profile metadata

FR views may display `FR -> TBT`, but that relationship is derived from
top-level `tbts[].proves`. It must not be maintained as a second source of
truth inside each FR.

### Compliance Mapping Pack

Defines compliance regime interpretation:

- ruleset row/control to FR/TBT mappings
- selected levels or families
- sufficiency rules per row/control
- manual/out-of-scope rationale

Compliance mappings should be separate from the FR catalog. The FR catalog is
project-owned and mostly ruleset-agnostic; compliance mapping packs decide how
ASVS, NIST, CIS, ISO, PCI or another regime interprets the same FR/TBT set.
Small convenience links may be denormalised into report payloads, but accepted
source config should keep regime-specific sufficiency rules in the mapping pack.

### Industry Framework Pack

Defines gated process interpretation:

- flows
- gates
- criteria
- roles
- manual steps
- approvals
- links to compliance rows and FR/TBT obligations

### Scanner Mapping Pack

Defines scanner interpretation:

- scanner name
- scanner version/ruleset snapshot
- rule IDs or patterns
- mapped TBTs
- evidence strength
- pass/fail/no-run interpretation
- limitations

This is distinct from a scanner rules catalog. A scanner rules catalog records
what rules exist; a scanner mapping pack records which accepted scanner rules
support which TBTs, at what evidence strength, for a versioned scanner/ruleset
snapshot.

### Declared Evidence Sources

Defines where non-scanner evidence is expected to come from:

- document paths or manifests
- approval record locations
- manual checklist locations
- required metabackend/resources/frontmatter
- provenance expectations

Declared evidence sources do not affect status until evidence is observed,
collected or reviewed.

### Observed Evidence Bundle

Defines observed evidence artifacts:

- scanner outputs
- executable test results
- VG_TEST_FRAMEWORK manifest entries
- reviewed manual documents
- approvals
- provenance and file paths

## Evidence Strength

Use explicit strength labels:

| Strength | Meaning |
|---|---|
| `strong` | Can satisfy the TBT when passing and policy permits it. |
| `supporting` | Useful evidence, but insufficient alone. |
| `weak` | Context only; requires review or stronger evidence. |
| `manual_review` | Human decision required. |
| `not_sufficient` | Related but cannot satisfy the TBT. |

Scanner "no findings" should usually be `supporting`, not `strong`, unless
the TBT is specifically a scanner/configuration obligation.

## Review And Acceptance

Agent output is not authoritative until reviewed. Accepted config objects
should include:

- `review_status`: `proposed`, `accepted`, `rejected` or `stale`
- `reviewed_by`
- `reviewed_at`
- `review_decision`
- `review_notes`
- optional `review_signature` or accepted-object hash

New agent output must never set `review_status: accepted`.

## Pack Versioning And Provenance

Every config pack should include:

- `schema_version`
- `pack_id`
- `pack_version`
- `created_at`
- `updated_at`
- `generator`
- `input_artifacts[]`
- `source_hash` or content hash where applicable
- scanner name/version and scanner ruleset snapshot hash for scanner mapping packs

This allows scanner drift, stale mappings and project-local overrides to be
detected before scan/report generation.

## Precedence And Conflicts

When multiple config sources could apply:

1. project-local accepted override
2. project-local proposed mapping, shown only as review input
3. global accepted mapping pack
4. global proposed/stale mapping, shown only as review input

The selected compliance regime and industry framework sufficiency policy still
constrain the final result. A project override cannot make scanner-only
evidence sufficient where the selected regime requires executable or manual
evidence.

## Vertical Slice

Implement the architecture first with a narrow proof path:

1. Choose one FR from `tapestry-mono`.
2. Define two or three top-level TBTs that prove that FR:
   - one executable test expectation
   - one scanner expectation
   - one manual/document expectation
3. Map one ASVS row to the FR/TBTs.
4. Map one JSP-453 gate criterion to the same obligations.
5. Add one scanner mapping with version/snapshot provenance.
6. Add one sample evidence artifact.
7. Add one missing-evidence case, one failed-evidence case and one supporting-only scanner case.
8. Run the resolver.
9. Show the chain in the dashboard:

```text
ASVS row + JSP-453 criterion -> FR -> TBT -> scanner/test/manual -> evidence
```

This proves success, failure, partial/supporting-only and missing states before
scaling to all FRs and all mappings.

## Implementation Sequence

### Step 1: Finalize Schemas

- update/add FR catalog schema with first-class TBTs and evidence expectations
- align the FR catalog schema on top-level `tbts[]`, `TBT.proves` and `expected_evidence`
- add scanner mapping pack schema
- add compliance mapping pack schema and keep regime sufficiency rules out of the FR catalog
- add declared evidence source schema if needed
- update evidence bundle schema for artifact kind/source/status/provenance/TBT refs
- update fixtures

### Step 2: Extend Validator

- add cross-file checks for FR/TBT/evidence/scanner/compliance/framework joins
- add stale scanner rule detection where snapshots are present
- add warnings for weak/supporting-only evidence overclaims
- add conflict/precedence checks for global packs and project overrides
- block declared-but-unobserved evidence from contributing to assurance status

### Step 3: Build Resolver

- deterministic evidence-to-TBT linking
- reason capture
- evidence strength handling
- no-run/partial-run scanner interpretation

### Step 4: Build Status Engine

- TBT status
- FR status
- compliance row status
- framework criterion/gate status
- gap reasons
- waiver and compensating-control status without collapsing them into passed

### Step 5: Upgrade Tapestry Catalog

- ensure every in-scope FR has one or more TBTs
- add conservative `expected_evidence`
- add explicit ASVS/JSP-453 mappings where justified

### Step 6: Update Dashboard

- Project FRs shows FR and TBT assurance state
- Compliance Regime rows show gap reasons
- Industry Framework gates consume resolved statuses
- Traceability Graph shows the explicit chain
- Evidence Files shows artifact type/source/provenance and linked TBTs

### Step 7: Update Runtime Flags

Support passing:

- FR catalog
- compliance mapping pack(s)
- industry framework pack/instance
- scanner mapping pack(s)
- declared evidence source pack(s)
- evidence manifest(s), where needed

## Design Guardrails

- Config is authoritative; runtime is deterministic.
- Agent output is proposed until accepted.
- All accepted mappings must be explainable.
- Accepted config requires review metadata.
- Scanner rule drift must be visible.
- Do not treat missing scanner findings as proof of runtime behaviour.
- Do not count copied tests as evidence until execution evidence exists.
- Do not count declared evidence sources as evidence until observed or reviewed.
- Do not infer document sufficiency from filename alone.
- Waivers and compensating controls are explicit states, not passes.
- UI must explain status using the same resolved model as the graph.

## Open Questions

- Should scanner mapping packs be global defaults, project-local overrides, or both?
- Should accepted agent config require a separate review signature field?
- What is the minimum required provenance for project-local documents?
- Should strictness profiles live only in compliance mapping packs, or can project catalogs declare a default desired profile?
- How should multiple compliance regimes combine when an industry framework references more than one?
- What review signature mechanism is sufficient for accepted config in local-only workflows?
