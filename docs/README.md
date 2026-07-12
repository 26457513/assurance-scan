# Documentation

## Active Architecture Docs

- [Planning Studio](ASSURANCE_PLANNING_STUDIO.md) is the current upstream model for config-driven project planning, blueprint selection, typed design contracts and downstream handoff to SOW Studio, Code Studio, Code Generator and the Assurance Engine.
- [Runtime Assurance Graph Architecture](RUNTIME_GRAPH_ARCHITECTURE.md) is the current runtime model for graph-centric assurance, audit provenance and future proof generation.
- [Framework Cockpit Design](FRAMEWORK_COCKPIT_DESIGN.md) is the current assurance-framework and gate/process design reference.
- [Blueprint FRs and Project Assurance](BLUEPRINT_FR_AND_PROJECT_ASSURANCE.md) is the current model for reusable security FR/TBT blueprints, project-only assurance requirements and explicit compliance-mapping states.

The intended product chain is:

```text
Planning Studio
  -> Assurance Generator
  -> SOW Studio
  -> Code Studio
  -> Code Generator
  -> Assurance Engine

Governance Engine governs approvals, waivers, decisions and audit across all stages.
```

The Planning Studio creates the approved planning/design contract. The
Assurance Generator derives the graph-ready FR/TBT/compliance assurance config
from that approved contract. The Assurance Engine verifies implementation
evidence against those accepted artifacts.

## Canonical User Journey

The intended end-to-end journey is:

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

The important boundary is that downstream code generation does not invent its
own assurance model. Assurance Generator, SOW Studio, Code Studio, Code
Generator and the Assurance Engine all consume the same approved Planning
Studio contract and its immutable hashes.

## MCP Packaging Direction

The product boundaries should be seven-shaped from the outset:

```text
Planning Studio
  -> Assurance Generator
  -> SOW Studio
  -> Code Studio
  -> Code Generator
  -> Assurance Engine

Governance Engine governs approvals, waivers, decisions and audit across all stages.
```

Studio means user-facing choice, review and approval. Generator means artifact
production from approved inputs. Engine means deterministic/runtime evaluation,
verification, enforcement or governance.

Early deployment may expose fewer MCP façades, but internal packages, schemas,
permissions and mutation boundaries should remain independently productisable.
The full MCP packaging strategy is defined in
[Planning Studio](ASSURANCE_PLANNING_STUDIO.md).

## Repository Handoff Plan

Current work should finish in this `asvs-scanner` repository only where it
belongs to the Assurance Engine foundation or the file-backed planning contract
boundary:

- keep schemas, graph vocabulary, evidence, claims, proof bundles and scanner
  mappings coherent and validated
- keep blueprint lineage and config-update proposal paths working
- keep docs self-contained and explicit about what is implemented, target and
  deferred
- keep tests focused on backend/schema/graph guarantees rather than UI polish

Planning Studio product work should then move to a new VibeGuide branch, using
VibeGuide's existing typed Python atomic/workflow module pattern and gated
quality checks. The active docs in this folder should be copied or moved into
VibeGuide at that point as the implementation contract for the new product
boundary.

Do not start a separate greenfield project unless VibeGuide's workflow proves
to block the desired module, schema and gate structure. The preferred path is:

```text
finish asvs-scanner Assurance Engine foundation
  -> move active docs into VibeGuide
  -> create VibeGuide Planning Studio branch
  -> build one product boundary at a time with typed Python modules and gates
```

## Archive

Older planning and pivot documents live in [archive/](archive/). They are useful historical context, but they should not be treated as the current implementation contract when they conflict with the active architecture docs.
