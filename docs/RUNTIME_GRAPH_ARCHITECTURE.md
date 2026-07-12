# Runtime Assurance Graph Architecture

## Purpose

This document captures the target architecture for the VibeGuide Assurance
Engine after the move to a graph-centric runtime model. It is an implementation
contract and roadmap, not a statement that every described capability is already
complete.

The core principle is:

```text
versioned config + live observations -> deterministic runtime graph -> UI, audit and proof artifacts
```

Versioned config remains the auditable source material. Scanner results,
test results, manual approvals and document evidence are the live observations.
The target state is that the runtime graph is the single source of truth for the
dashboard and the runtime state used by compliance, assurance and audit claims.
The current implementation is part-way through that migration: graph data
exists and is validated, but some dashboard views still use view-specific
payloads that must be collapsed into graph projections.

Zero-knowledge or trustless verification is not based on the graph alone. It is
based on a committed graph plus committed raw/private evidence, deterministic
derivation rules, known config versions and explicit trust assumptions about how
the evidence was produced.

## Relationship To Live Docs

This document is authoritative for the runtime graph, evidence provenance,
audit/export and future proof-generation direction.

[Framework Cockpit Design](FRAMEWORK_COCKPIT_DESIGN.md) is the live companion
document for assurance frameworks, routes, gates, criteria, roles and process
cockpit UX. This document references that model where framework/gate status
depends on graph evidence.

[Planning Studio](ASSURANCE_PLANNING_STUDIO.md) is the live upstream
design-contract model. It defines how user intent, selected config packages,
blueprint FR/TBT recommendations, bespoke requirements and approvals become the
accepted project contract that this runtime graph later consumes.

[Blueprint FRs and Project Assurance](BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md)
defines reusable blueprint FR/TBT catalogs, project-only requirements and
explicit compliance-mapping states.

This document is self-contained for runtime graph architecture.

Superseded or historical design docs are kept in `docs/archive/` and may also
exist in generated runtime mirrors for older reports. They are not authoritative
for new runtime graph, cockpit, schema, audit or proof work.

## Implementation Status

| Area | Status | Notes |
|---|---|---|
| Versioned FR/TBT, ruleset, mapping and assurance config | Partial | Schemas, loaders, shared definitions and graph-manifest accepted-config commitments exist with review/signature summaries; remaining cleanup is broader content-addressed config usage across every scan path. |
| Evidence bundle and scanner/test observations | Partial | Evidence records exist; stronger raw artifact commitments, trust basis and retention metadata are still needed. |
| Runtime graph | Partial | The graph exists and is validated; shared vocabulary exists, while identity rules and projection coverage still need tightening. |
| Scanner-to-compliance mappings | Partial | Versioned scanner compliance mapping packs exist; direct failed scanner evidence now blocks mapped compliance rows and appears as first-class graph evidence. Claims and mapped gates/criteria are scanner-blocker aware; remaining work is broader scanner exception policy and UI projection polish. |
| Dashboard views as graph projections | Partial | `scripts/graph_projection.py` now derives overview, Project FR, scanner-evidence and assurance summaries from the runtime graph; more view-specific payloads still need migration. |
| Assurance framework gate rollups | Partial | Gate and criterion graph nodes inherit resolved FR/TBT/compliance-row status and mapped scanner blockers when framework criteria or assurance-instance mappings connect them to the assurance chain. Gate/criterion decisions and approved controls now participate in rollups; remaining work is richer policy configuration and UI explanation. |
| Graph manifest and graph root hash | Partial | `graph-manifest.json` is emitted and validated with graph root and artifact commitments; scanner/test runner versions and signature metadata remain. |
| Canonical JSON and deterministic hashing | Partial | `scripts/artifact_hashing.py` provides shared canonical JSON and SHA-256 helpers for graph manifests, report validation, evidence/report writers, scanner rule hashes, claim artifacts and proof bundles; broader accepted-config freezing remains. |
| Typed proof claims and zero-knowledge proof generation | Partial | Typed assurance claim export and selective-disclosure proof bundle export are implemented as hash-bound audit artifacts; full zero-knowledge circuit/proof generation remains target architecture. |

## Architectural Stance

The target application should not maintain separate truth models for Project
FRs, Compliance Regime, Industry Framework, Evidence Files and Traceability
Graph. Those views should be filtered projections over the same normalized
graph.

The graph is rebuilt from immutable or versioned inputs:

- FR/TBT catalog
- compliance rulesets
- compliance mapping packs
- scanner compliance mapping packs
- assurance framework definitions
- assurance instance/project process config
- scanner rule catalogs
- scanner outputs
- executable test results
- manual evidence records
- generated assurance test-pack manifests

Dashboard-specific arrays, counts and cards may exist as cached projections,
but they must be derivable from the graph.

## Runtime Flow

| Step | Status | Target behavior |
|---|---|---|
| 0. Accept planning contract | Target | Consume the approved Planning Studio contract, including config refs, blueprint decisions, bespoke requirements, architecture/governance choices and handoff hashes. |
| 1. Load versioned config | Partial | Load FR catalog, TBT definitions, expected evidence, compliance rulesets, compliance mapping packs, scanner compliance mapping packs, assurance framework and assurance instance config. |
| 2. Load live observations | Partial | Load scanner outputs, JUnit or test runner results, manual/document evidence, approvals, waivers and decisions. |
| 3. Normalize evidence | Partial | Parse raw artifacts, preserve artifact hashes, attach scanner/test runner versions, attach source commit/report id and map findings through accepted versioned mappings. |
| 4. Build deterministic graph | Partial | Create typed nodes and edges, calculate status rollups, preserve derivation/provenance and emit graph plus graph manifest. Current graph construction exists, but rollups and identity rules are not yet complete. |
| 5. Project views | Target | Render Project FRs, Compliance Regime, Industry Framework, Traceability Graph, Evidence Files and prompts as graph projections. Current dashboard generation still includes view-specific payloads. |
| 6. Optional proof layer | Target | Create typed claims over graph state and prove them from committed private inputs without exposing source or raw evidence. |

## Source Of Truth Boundaries

### Versioned Config

Config defines what should be true.

Examples:

- `FR-016` exists and means session timeout and re-authentication.
- `TBT-016-ASVS-A` is required evidence for expired JWT rejection.
- ASVS `v5.0.0-7.1.1` maps to `FR-016` and `TBT-016-ASVS-A`
  through a compliance mapping pack.
- a Semgrep rule maps directly to ASVS `v5.0.0-7.1.1`.
- a JSP-453 gate criterion requires selected FR/TBT evidence.

Config must be versioned, reviewable and traceable. Agent-authored config is
proposal material until a human accepts it.

### Live Observations

Observations define what was seen in this run.

Examples:

- a JUnit testcase for `TBT-016-ASVS-A` passed
- a scanner finding mapped to ASVS `v5.0.0-7.1.1` failed
- a required manual approval is present
- a document evidence artifact is missing

Observations do not change config. They become evidence nodes in the graph.

### Runtime Graph

The graph defines what the application currently believes at runtime.

It should answer:

- which FRs are satisfied, partial, failed or missing evidence
- which TBTs have required evidence
- which compliance rows are satisfied or blocked
- which scanner results directly affect compliance rows
- which scanner results are general inventory/risk signals
- which assurance gates are blocked and why

## Scanner Evidence Model

Scanner findings have three mapping levels.

### Direct Compliance Row Mapping

Use when a scanner rule or finding maps explicitly to a specific compliance
rule/control.

```text
scanner result -> scanner compliance mapping -> compliance row -> FR/TBT chain
```

If the mapped scanner result fails and the mapping says it is blocking, that is
valid failing evidence for the mapped compliance row even if a bespoke TBT test
passed. The UI must show both pieces of evidence rather than hiding the
contradiction.

This distinction matters:

- the scanner result can block the mapped compliance row
- the scanner result can block a gate or claim that depends on that compliance
  row
- the scanner result does not automatically fail a bespoke TBT unless that TBT's
  expected evidence explicitly includes the scanner result

For example, `TBT-016-ASVS-A` may have passing JUnit evidence for expired JWT
rejection while a scanner result mapped to ASVS `v5.0.0-7.1.1` fails. The graph
must preserve both facts:

```text
TBT-016-ASVS-A -> observed JUnit evidence -> passed
ASVS v5.0.0-7.1.1 -> mapped scanner evidence -> failed/blocking
```

The compliance row or framework gate may remain blocked even though the bespoke
TBT passed.

### Compliance Domain Mapping

Use when scanner output is relevant to a broader ruleset domain or family but
not precise enough to prove or fail a specific row.

```text
scanner result -> compliance domain/category
```

This is useful risk context, not sufficient FR/TBT proof.

### General Or Unmapped Scanner Evidence

Use when scanner output is valuable but not traceable to the selected compliance
regime.

```text
scanner result -> scanner inventory/risk group
```

These findings should still appear in the graph, grouped by scanner/type/status
where necessary. They should be clearly marked as `unmapped`, `inventory_only`
or equivalent, and they should not be forced into FR/TBT paths.

## Required Graph Properties

The runtime graph must be:

- typed: every node and edge has a stable type
- identifiable: every node has a stable id, and every edge has either a stable
  id or a deterministic identity derived from `source + target + type + key`
- deterministic: same inputs produce the same graph
- traceable: every derived status has a provenance path
- version-aware: config, tool and mapping versions are recorded
- hashable: graph and evidence commitments can be reproduced
- inspectable: UI views are projections over graph state
- conservative: missing, failed and contradictory evidence must remain visible

## Node Categories

The central graph vocabulary should cover at least:

- assurance framework
- process/route/profile
- gate
- criterion
- role
- compliance ruleset
- compliance domain/category
- compliance row/control
- FR
- TBT
- scanner rule/check
- executable test
- manual/document/approval obligation
- observed evidence
- scanner result
- grouped scanner inventory result
- waiver
- compensating control
- decision

## Edge Categories

The central edge vocabulary should cover at least:

- requires
- maps_to
- proves
- satisfies
- evidences
- produced_by
- implements
- assigned_to with a `responsibility` property for RACI roles
- applies_to
- blocks
- derived_from
- approved_by
- waived_by
- depends_on_process

The exact names should live in one shared contract used by schemas, graph
builders, validators, dashboard code and future proof tooling.

## Assurance Framework Join Rule

Assurance frameworks such as JSP-453 are part of the runtime graph as process
context, but they do not automatically prove or depend on project FR/TBT
evidence.

Reusable framework nodes are always allowed to exist as isolated process
structure:

```text
assurance framework -> process -> gate -> criterion -> role
```

They join the assurance/proof chain only through explicit typed requirements:

```text
gate criterion
  -> requires -> ruleset row
    -> satisfies -> FR
      -> requires -> TBT
        -> evidences -> evidence
```

or through a project assurance-instance mapping:

```text
gate criterion
  -> requires -> FR / TBT / evidence / approval / waiver / compensating control / decision
```

If a JSP-453 criterion has no accepted framework requirement or assurance
instance mapping, it remains visible in framework/gate projections but does not
connect to ASVS, NIST, FRs, TBTs or evidence and must not be counted as
assurance proof. This keeps process context from becoming implicit compliance
evidence.

## Vocabulary Reconciliation

The architecture terms above are target concepts. The shared vocabulary now
lives in `data/schemas/defs.schema.json` and `scripts/graph_vocabulary.py`.
Use this table to distinguish intended concepts from runtime names that still
need design attention.

| Architecture concept | Current dashboard schema enum | Current graph builder examples | Disposition |
|---|---|---|---|
| Compliance ruleset | `compliance` | compliance/ruleset nodes | Keep concept; standardize naming in shared vocabulary. |
| Compliance row/control | `ruleset_row` | ruleset row nodes | Prefer `ruleset_row` as the stable machine type; use "compliance row" as UI language. |
| Compliance domain/category | `domain` | domain nodes for scanner domain signals | Keep, but define domain id format and rollup semantics. |
| FR | `fr` | FR nodes | Keep. |
| TBT | `tbt` | TBT nodes | Keep. |
| Executable test | `test`, `unit`, `integration`, `e2e`, `load` | generated/native test nodes | Decide whether `unit`/`integration` are node types or `test` nodes with a subtype. |
| Scanner result | `scanner` or `evidence` | scanner evidence nodes | Split clearly into scanner tool/check/result/evidence types. |
| Observed evidence | `evidence` | evidence nodes | Keep, with explicit evidence type and result status. |
| Assurance process/gate/criterion/role | `process`, `gate`, `criterion`, `role` | framework graph nodes | Keep and align with the framework cockpit model. |
| Waiver / compensating control / decision | `waiver`, `compensating_control`, `decision` | assurance-instance records now materialize as graph nodes | Complete rollup semantics before using in proof claims. |
| RACI responsibility | older payloads allowed `owner`, `accountable`, `approver`, `reviewer`, `contributor`, `consulted`, `informed` as edge types | role and assignment edges | Use `assigned_to` edges with a `responsibility` property. RACI values are edge metadata, not relationship types. |
| `supports` edge | not currently canonical | `supported_by` appears in schema | Pick one direction per relationship and make inverse display-only. |
| `blocks` edge | `blocks` | blocker edges/signals | Keep, but define status rollup consequences. |
| Edge identity | `key` is optional | current de-duplication can collapse same source/target/type edges | Require stable `id` or deterministic `source + target + type + key` identity before proof/audit use. |

This table should shrink as remaining runtime aliases are removed and each UI
view becomes a projection over the same graph vocabulary.

## Status And Evidence Semantics

Statuses should distinguish the object definition from runtime evidence.

TBT lifecycle examples:

- planned
- generated
- ready_to_run
- executed
- deprecated

This richer lifecycle is a target reconciliation. The FR catalog currently uses
a smaller TBT lifecycle, while the assurance test-pack uses additional execution
states. The shared graph vocabulary should make this explicit: catalog TBTs
describe assurance obligations; test-pack entries describe implementation and
execution readiness.

Evidence result examples:

- passed
- failed
- partial
- missing
- manual_review
- waived
- compensating_control
- not_observed

Scanner evidence effect examples:

- blocking_if_finding
- supporting_signal
- review_signal
- inventory_only

A scanner signal can support or block a compliance row, but it must not silently
replace required FR/TBT evidence unless the accepted config explicitly allows
that sufficiency rule.

The deterministic status resolver now treats normalized `scanner_result`
evidence with `result_status: failed` and direct `ruleset_refs` or
`mapping_refs` as blocking evidence for the mapped compliance row. Raw scanner
finding ingestion through scanner-compliance mapping packs is already represented
in the graph builder and now feeds the resolver for accepted direct
`compliance_row` mappings. Domain and general scanner findings remain advisory
or inventory projections until an accepted project/compliance policy promotes
them into a concrete row-level effect.

## Waivers And Compensating Controls

Waivers, compensating controls and reviewed decisions must be first-class graph
objects, not comments hidden in status text.

First-class means each record has a stable identifier, a typed graph node,
explicit graph edges to the thing it affects, review/provenance metadata,
status-effect semantics and visibility in UI projections, audit exports and
future proof manifests.

Target semantics:

- a waiver does not turn failed or missing evidence into passing evidence
- a compensating control does not make the original evidence pass
- both can change the rollup outcome from `failed` or `missing` to a reviewed
  non-pass state such as `waived` or `compensating_control`
- both require reviewer identity, decision timestamp, rationale, scope,
  expiry/review date where applicable and signature or approval metadata
- both must link to the exact FR, TBT, compliance row, gate criterion or
  evidence record they affect
- both must remain visible in UI, audit exports and proof manifests

Runtime foundation now materializes assurance-instance waiver, compensating
control and decision records as graph nodes. Each node links to its target with
`applies_to`, links to supporting artifacts with `evidences`, and links to
approval/signature references with `approved_by`.

The deterministic status resolver consumes approved waiver and compensating
control records for TBT, FR and compliance-row targets. Approved records produce
explicit non-pass statuses (`waived` or `compensating_control`) and pending
records are reported as pending assurance-control review. Gate and criterion
rollups also consume target decisions and approved gate/criterion controls:
they can clear a hard scanner blocker from the process path, but they do not
turn the underlying evidence into a pass.

Graph shape:

```text
waiver / compensating-control / decision
  -> applies_to -> FR, TBT, compliance row, gate criterion or evidence
  -> evidences -> supporting artifact or decision record
  -> approved_by -> approval/signature reference
```

Rollup rule: a reviewed waiver or compensating control may satisfy a policy that
allows non-pass outcomes, but it must remain distinguishable from `passed` in
every UI and proof claim.

## Zero-Knowledge Proof Direction

Typed claim export, deterministic claim verification and v1 selective-disclosure
proof bundle export are implemented as the first audit/proof foundation. Full
zero-knowledge proof generation remains target architecture.

The proof layer should prove precise typed claims over a deterministic graph. It
should not try to prove vague claims such as "the application is secure".

Example claim:

```text
Against source commit 7214daec910d, using ASVS 5.0.0 and the accepted
config hashes listed in the manifest, TBT-016-ASVS-A has observed passing
test evidence and no blocking scanner evidence mapped to ASVS v5.0.0-7.1.1.
```

Private inputs may include:

- source code
- raw scanner logs
- raw test logs
- screenshots
- manual review notes
- internal file paths
- private graph labels or evidence summaries that would reveal sensitive paths,
  component names, user data or implementation details

Public inputs may include:

- source commit hash
- config artifact hashes
- scanner/test runner versions
- evidence artifact hashes
- normalized evidence hashes
- graph root hash
- selected claim type and target ids
- public/redacted graph labels where disclosure is acceptable

The contract should support both aggregate commitments and selective-disclosure
commitments:

- aggregate commitments such as `config_manifest_hash`,
  `evidence_bundle_hash` and `graph_root_hash`
- per-artifact commitments for raw evidence, normalized evidence and selected
  config artifacts when a verifier needs narrower disclosure

The claim verifier can currently check:

- the claim schema is valid
- the claim references the current graph manifest hash
- the public inputs match graph-manifest commitments
- the graph root and accepted-config hashes match the manifest
- the claim type is supported by the committed runtime config roles
- the claim result follows from graph nodes, edges and statuses

Future proof tooling still needs to check private artifact openings and
zero-knowledge proof material without disclosing source, raw scanner logs, raw
test logs or manual review notes.

### Typed Claim Shape

Claims are explicit data structures, not prose.
`data/schemas/assurance-claim.schema.json` is the current implemented aggregate
claim shape. It contains:

```json
{
  "schema_version": 1,
  "mode": "assurance_claim",
  "claim_type": "tbt_satisfied",
  "target": "TBT-016-ASVS-A",
  "claim_result": "satisfied",
  "graph_manifest": {
    "path": "graph-manifest.json",
    "sha256": "sha256:...",
    "graph_root_hash": "sha256:...",
    "accepted_config_hash": "sha256:..."
  },
  "public_inputs": {
    "graph_root_hash": "sha256:...",
    "evidence_bundle_hash": "sha256:...",
    "evidence_manifest_hash": "sha256:...",
    "accepted_config_hash": "sha256:..."
  },
  "evaluation": {
    "target_node_id": "test:TBT-016-ASVS-A",
    "target_status": "passed",
    "satisfied": true,
    "reasons": ["TBT-016-ASVS-A has sufficient passing evidence."],
    "evidence_refs": ["EVD-TBT-016-ASVS-A"],
    "scanner_blockers": []
  }
}
```

The example above is the aggregate claim form. The implemented
selective-disclosure proof bundle keeps the aggregate public commitments and
adds per-evidence commitments plus optional disclosed artifact openings:

```json
{
  "mode": "assurance_proof_bundle",
  "bundle_type": "selective_disclosure_v1",
  "claim": {"mode": "assurance_claim"},
  "claim_hash": "sha256:...",
  "public_commitments": {
    "graph_root_hash": "sha256:...",
    "accepted_config_hash": "sha256:...",
    "evidence_bundle_hash": "sha256:..."
  },
  "evidence_commitments": [
    {
      "id": "EVD-TBT-016-ASVS-A",
      "type": "test_result",
      "result_status": "passed",
      "record_hash": "sha256:...",
      "artifact_hashes": [{"path": "reports/junit.xml", "sha256": "sha256:..."}]
    }
  ],
  "openings": [
    {"path": "reports/junit.xml", "sha256": "sha256:...", "encoding": "base64", "content": "..."}
  ]
}
```

That lets a verifier check selected evidence commitments and optional disclosed
artifacts without receiving the whole evidence bundle or source repository.

Initial claim types should be narrow:

- `tbt_satisfied`
- `fr_satisfied`
- `compliance_row_satisfied`
- `no_blocking_scanner_evidence`
- `selected_scope_satisfied`

Each claim type must define its required graph path, acceptable statuses,
blocking statuses, required config inputs and public/private fields.

Implemented commands:

```text
asvs-scanner export-assurance-claim <report-dir> --claim-type <type> --target <id>
asvs-scanner verify-assurance-claim <claim.json> --report-dir <report-dir>
asvs-scanner export-assurance-proof-bundle <claim.json> --report-dir <report-dir> [--open <report-relative-artifact>]
asvs-scanner verify-assurance-proof-bundle <bundle.json> [--report-dir <report-dir>]
```

Report validation also verifies claim artifacts under `claims/*.json` and proof
bundles under `proof-bundles/*.json`. A stale or tampered claim or bundle fails
`asvs-scanner validate-report --strict` because it no longer matches the current
`graph-manifest.json`, `dashboard-payload.json`, `evidence-bundle.json` or hash
sidecar.

### Proof Chain

The intended proof chain is:

```text
versioned config artifacts
  -> config artifact hashes
  -> live evidence artifacts
  -> raw evidence hashes
  -> normalized evidence records
  -> normalized evidence hashes
  -> deterministic graph build
  -> graph root hash
  -> typed assurance claim
  -> proof
  -> verifier checks public inputs and proof
```

The proof does not need to reveal source code, raw scanner logs, raw test logs or
manual review notes. It proves that private artifacts matching the public
commitments produce a graph in which the selected claim is true.

There should be one canonical graph model with multiple projections. The
operator dashboard projection can include useful private labels and summaries.
The proof export projection should allow redacted labels, committed private
labels or label hashes when node names, file paths, scanner messages or evidence
summaries are sensitive.

### Trust Boundary

A proof can show that committed private artifacts support a graph claim. It does
not, by itself, prove that a scanner or test runner was honestly executed.

The system must therefore record one of the following trust bases for evidence:

- local operator trust: the report producer is trusted to run tools honestly
- reproducible execution: the verifier can rerun the same command/container
- CI attestation: a CI system signs the run output
- runner attestation: a trusted runner signs tool versions, inputs and outputs
- external assessor attestation: a reviewer signs or approves the artifact

The chosen trust basis must be explicit in the manifest and evidence records.

## Compliance, Assurance, Provenance And Audit Chains

The graph should support four related chains. They overlap, but they answer
different questions.

### Compliance Chain

Question: does the project satisfy a selected external rule or control?

```text
compliance ruleset
  -> compliance row/control
  -> compliance mapping pack entry
  -> FR/TBT obligation
  -> required evidence policy
  -> observed evidence
  -> compliance row status
```

Direct scanner mappings attach to the compliance row side of this chain.

Rollup rule: a blocking scanner result directly mapped to a compliance row makes
that compliance row `failed` or `blocked` unless a reviewed waiver or
compensating control applies. Passing FR/TBT evidence should remain visible, but
it does not override the blocking scanner evidence for the compliance row.

This behavior is implemented for compliance-row status: direct failed scanner
evidence from accepted scanner-compliance mapping packs is materialized as graph
evidence and blocks the mapped row unless a reviewed waiver or compensating
control applies. Remaining work is to finish gate-specific exception policy and
claim-specific scanner blocker rules.

### Assurance Chain

Question: can the project make a defensible assurance claim about its own
requirements?

```text
FR
  -> TBT
  -> expected evidence
  -> observed evidence
  -> TBT status
  -> FR status
```

Scanner evidence affects this chain only when a TBT or sufficiency policy
requires that scanner evidence.

### Framework/Gate Chain

Question: can a process gate, such as a JSP-453 gate, be passed?

```text
assurance framework
  -> process/route
  -> gate
  -> criterion
  -> required roles, approvals, compliance rows, FRs or TBTs
  -> observed evidence and decisions
  -> gate readiness
```

Gate status should preserve the exact blocker: missing role, missing approval,
failed compliance row, missing TBT evidence, failed scanner evidence or manual
review.

Framework gates and criteria do not maintain an independent assurance truth
model. When a typed framework requirement or project assurance-instance mapping
points at an FR, TBT or compliance row, gate readiness is derived from the same
resolved graph status used by Project FR, Compliance Regime, claims and scanner
evidence projections. A direct scanner blocker on a mapped compliance row
therefore blocks the dependent criterion/gate until a reviewed policy exception
applies.

### Provenance/Audit Chain

Question: why does the system believe this, and can that belief be reproduced?

```text
source commit
  -> config artifact versions and hashes
  -> tool/container versions
  -> raw artifact hashes
  -> parser/normalizer version
  -> normalized evidence hash
  -> graph builder version
  -> graph node/edge/status
  -> reviewer/waiver/approval records
  -> report manifest
```

Audit views should expose this path. Proof tooling should commit to this path.

## Requirements Imposed On Config Models

To support audit and future proof generation, config models need:

1. Stable identifiers for every FR, TBT, ruleset row, scanner mapping, evidence
   record and graph node, plus stable or deterministically derived edge
   identities.
2. Canonical JSON serialization so equivalent inputs hash identically.
3. Explicit config version, ruleset version and mapping version metadata.
4. Immutable accepted mappings once used in a proof or audit record.
5. Public/private field classification for evidence-bearing schemas.
6. Strong provenance fields for every evidence record.
7. Deterministic graph-build inputs and ordering.
8. A proof/graph manifest emitted per report.
9. Typed claim schemas for assurance assertions.
10. Conservative rollup rules that preserve missing, failed and contradictory
    evidence.

## Graph Manifest

Each report should emit a graph/proof manifest containing:

- report id
- source repository identity
- source commit hash
- graph builder version
- graph vocabulary version
- graph schema version
- claim schema version
- dashboard payload schema version
- FR catalog hash
- ruleset hash
- compliance mapping pack hashes
- scanner compliance mapping pack hashes
- assurance framework hash
- assurance instance hash
- accepted runtime config commitments and `accepted_config_hash`
- planning artifact commitments and `planning_artifacts_hash`
- evidence bundle hash
- raw artifact hash inventory
- raw artifact retention policy and retrieval location, if retained
- scanner versions
- test runner versions
- evidence trust basis for each evidence source
- reviewer/signature metadata for approvals, waivers, compensating controls and
  accepted config
- graph root hash
- supported claim types

This manifest becomes the bridge between the operational dashboard and later
trustless verification.

`graph schema version` and `dashboard payload schema version` may initially be
the same because the graph is embedded in the dashboard payload. They should be
listed separately because the target architecture separates the graph contract
from dashboard-specific cached projections.

## Scale And Graph Materialization

Current graph rendering uses pragmatic caps and slices to keep the static
dashboard usable. The target architecture should treat the full graph as a
runtime data product and render filtered projections from it.

Target posture:

- build the full normalized graph once per report/run
- materialize a graph manifest and graph root for the full graph
- generate dashboard projections from the full graph, not by rebuilding partial
  truth models per view
- paginate or filter large projections in the UI layer
- aggregate high-volume scanner findings by scanner, rule, severity, status and
  mapping level, with drill-down to raw/normalized evidence records
- keep complete graph views explorable through focused entry points rather than
  rendering every node at once by default

Incremental updates are a future optimization. The initial proof/audit posture
should prefer a deterministic full rebuild per report because it is easier to
hash, reproduce and verify. That rebuild cost is accepted as a deliberate
tradeoff for deterministic hashing; revisit it if report latency becomes a
constraint on large projects with high-volume scanner findings.

## Versioning And Migration

Audit and proof records must remain verifiable after graph builders and schemas
evolve.

Target rules:

- each report records graph builder version, graph vocabulary version, graph
  schema version, dashboard payload schema version and claim schema version
- old reports are verified with the versions recorded in their manifest
- new graph builders do not silently reinterpret old proof claims
- migrations create a new graph version and record source/target hashes
- compatibility windows are explicit; absence of compatibility means the old
  verifier/builder must be retained
- accepted config used in an audit or proof should be frozen by content hash and
  review metadata, not only by mutable file path or version label

This requires content-addressable config references and a canonical JSON
serialization utility. Both are target implementation tasks.

## Query And Projection Layer

Graph-centric UI requires a query/projection contract rather than ad hoc
dashboard assembly.

Target shape:

```text
full graph
  -> graph query/projection layer
  -> Project FRs projection
  -> Compliance Regime projection
  -> Industry Framework projection
  -> Traceability Graph projection
  -> Evidence Files projection
  -> Agent/runner prompt projection
```

The first implementation can be a small in-process query module, not a server.
It should provide stable selectors such as:

- node by id
- incoming/outgoing edges by type
- FR assurance chain
- TBT evidence chain
- compliance row evidence chain
- gate readiness chain
- applicable waivers, compensating controls and decisions for a node or rollup
- scanner findings by mapping level/status
- provenance path for a node, edge or status
- blocker explanation for a rollup

Dashboard payload arrays should be treated as cached projection outputs. They
are not independent truth.

## Non-Goals

The architecture deliberately does not claim to:

- prove that an application is generally secure
- treat agent recommendations as accepted config
- expose private source code or raw evidence to external verifiers
- treat scanner inventory findings as compliance proof without an accepted
  mapping
- hide contradictory evidence for the sake of a simpler status
- let dashboard-only state become audit truth
- treat a passing bespoke TBT as overriding a blocking mapped scanner result
- prove absence of vulnerabilities beyond the scoped tools, mappings, evidence
  policies and trust assumptions

## Outstanding Implementation Tasks

### 1. Make the graph the runtime contract

Move remaining dashboard views to query/projection code over the normalized
graph. Keep view-specific payloads as cached projections only.

### 2. Define graph vocabulary centrally

Implemented foundation: `data/schemas/defs.schema.json` defines the shared graph
node, edge and responsibility vocabulary, and `scripts/graph_vocabulary.py` is
the runtime bridge used by graph construction and validators. Remaining work is
to make every UI projection consume that vocabulary directly rather than keeping
small local label maps.

### 3. Add graph/proof manifest

Implemented foundation: report generation emits `graph-manifest.json`, validated
by `data/schemas/graph-manifest.schema.json`, with report/config artifact hashes,
accepted-config commitments, accepted-config review/signature summaries,
evidence artifact hashes, graph root hash, source commit when available, graph
builder identity, supported claim types and unsupported-claim reasons when
required runtime config roles are not committed. Remaining work is to enrich it
with scanner versions, test runner versions and selective disclosure proof
bundles.

### 4. Strengthen evidence commitments

Ensure every scanner, test and manual evidence record has raw artifact hash,
normalized evidence hash, tool version, source commit, mapping refs and
provenance chain.

### 5. Implement canonical JSON and hashing

Implemented foundation: `scripts/artifact_hashing.py` provides shared canonical
JSON serialization, canonical JSON SHA-256, file SHA-256, `sha256:` prefix
normalization and report hash-sidecar naming. Report/evidence writers and
scanner rule-hash generation now use this shared utility. Remaining work is to
extend graph-node coverage and zero-knowledge claim circuits beyond the current
canonical artifact commitments.

### 6. Freeze accepted config by content address

Implemented foundation: `graph-manifest.json` now includes an `accepted_config`
section. Each runtime config input is committed by role, path, `sha256:` hash,
schema hint, schema version where available, a `content_addressed` immutable
freeze marker and a compact review summary when the source config contains
accepted/proposed review status, approval status, reviewers, approvers,
decision makers or signature references. The manifest also records
`accepted_config_hash`. Claim readiness is now derived from the committed config
roles: unsupported proof claims name the missing roles instead of being
advertised as available. Dashboard refreshes discover report-local or bundled
scanner-compliance mapping packs by default so scanner-evidence claims remain
bound to content-addressed mapping config. Claim and proof-bundle exporters
verify the selected claim against the current report before writing output, so
unsupported or stale claims fail closed.

Planning and blueprint artifacts are committed separately from accepted runtime
config. `graph-manifest.json` now includes a mandatory `planning_artifacts`
section and `planning_artifacts_hash`; this binds project intake/config
selection, blueprint proposal/decision logs, planning contracts, assurance
contract exports and downstream handoff packs without treating those artifacts
as accepted runtime config or observed evidence.

### 7. Model public/private proof fields

Implemented foundation: `data/schemas/assurance-claim.schema.json` defines the
first public claim artifact and `data/schemas/assurance-proof-bundle.schema.json`
defines the v1 selective-disclosure wrapper. `scripts/export-assurance-claim.py`
exports a typed claim with public graph/config/evidence commitments copied from
`graph-manifest.json`, plus a compact graph-derived evaluation.
`scripts/export-assurance-proof-bundle.py` wraps that claim with per-evidence
record commitments and optional base64 artifact openings. The artifacts do not
expose source code or raw scanner/test logs unless the caller deliberately opens
specific report artifacts with `--open`. Remaining work is full zero-knowledge
proof generation over these committed public and private inputs.

### 8. Add typed assurance claims

Implemented foundation: `asvs-scanner export-assurance-claim` supports the first
typed claim export flow. It refuses unsupported claim types when the graph
manifest says required config roles are missing. It can also fail closed with
`--require-satisfied` when the selected claim is supported but false. Supported
claim names are:

- FR satisfied
- TBT satisfied
- compliance row satisfied
- no blocking scanner evidence
- selected scope satisfied

Current evaluation is intentionally conservative and graph-state based:
satisfied claims require a target graph node already marked `passed`,
`satisfied`, `waived` or `compensating_control`. Unsatisfied claims can still be
exported as audit artifacts, but they are not proof of compliance.

### 9. Enforce scanner rollup semantics

Implemented foundation: the status engine now merges scanner-result evidence and
accepted scanner-compliance mapping matches into compliance-row scanner
blockers. Direct failed scanner evidence blocks the mapped compliance row unless
a reviewed waiver or compensating control applies. The graph projection layer
also exposes scanner evidence categories: direct blockers, mapped signals,
domain signals and unmapped inventory. Typed claim evaluation is also
scanner-blocker aware: an FR claim fails when any compliance row claimed by that
FR has direct scanner blockers, while a TBT claim remains scoped to the TBT's
own expected evidence. This preserves the important distinction that a bespoke
test can pass while the broader FR or compliance row remains blocked by
independent scanner evidence. Dependent gate and criterion nodes now inherit
scanner blockers from mapped FR/TBT/compliance-row status, while approved
controls and explicit process decisions can create reviewed non-pass process
outcomes. Remaining work is richer policy configuration for when those
exceptions are allowed.

### 10. Represent unmapped scanner findings cleanly

Keep non-FR/TBT-relatable findings in the graph as grouped scanner evidence
nodes, marked as unmapped or inventory-only. Implemented foundation:
`scripts/fr/graph.py` emits grouped scanner inventory nodes and
`scripts/graph_projection.py` reports `unmapped_inventory_count` separately from
direct mapped evidence.

### 11. Add waiver, compensating-control and decision rollup semantics

Waivers, compensating controls and decisions now have first-class
assurance-instance schema records and runtime graph nodes. The status resolver
now applies approved waiver and compensating-control records to TBT, FR and
compliance-row targets as reviewed non-pass outcomes. Gate/criterion graph and
process-flow rollups now consume approved gate/criterion controls and explicit
decisions. Remaining work is richer policy configuration, expiry handling and UI
explanation.

### 12. Complete assurance-framework joins

Implemented foundation: framework criteria use typed `requirements` and project
assurance instances use `criterion_mappings` to create the only traceability
edges from JSP-453-style gates into compliance rows, FRs, TBTs, evidence,
approvals, waivers, compensating controls and decisions. Unmapped framework
nodes remain process context and do not participate in assurance rollups.

### 13. Improve complete graph UI

Rethink the complete graph overview so scanner evidence, grouped unmapped
findings, FR/TBT chains and compliance paths are inspectable without a dense
unreadable map.

### 14. Collapse remaining view-specific payloads

Remove any remaining parallel truth models in dashboard generation. Views should
be projections from graph state.

### 15. Add a graph query/projection layer

Create stable in-process graph selectors for FR chains, TBT evidence chains,
compliance row chains, gate readiness, scanner findings, provenance paths and
blocker explanations.

### 16. Add scale and materialization strategy

Build and hash the full graph per report, then paginate, filter or aggregate
large UI projections without changing graph truth.

### 17. Continue shared schema cleanup

Initial shared definitions now live in `data/schemas/defs.schema.json` and are
used for high-drift enums such as review status, confidence, evidence
type/result/strength and graph node/edge vocabulary. Continue migrating
remaining duplicated `$defs` and keep validators wired to the shared schema so
enum drift becomes hard to reintroduce.

### 18. Add deterministic graph build checks

Add tests proving graph node ids, edge ids, ordering, statuses and hashes are
reproducible from the same inputs.

### 18. Prepare the proof path

Do not build full zero-knowledge proofs yet. First shape the data:

- canonical JSON
- deterministic hashes
- graph root
- claim schema
- proof manifest
- public/private field classification

## Review Questions

- Which graph claim types should be supported first?
- Which fields should be public commitments versus private evidence?
- Should scanner-domain evidence affect readiness, or only appear as risk
  context?
- What is the minimum graph manifest required for a useful first audit export?
- Should complete graph visualization show every evidence node, or aggregate
  repeated scanner findings by default with drill-down on demand?
