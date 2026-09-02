# Module architecture

Status: binding implementation structure.

## Backend

New backend work follows the established module boundaries:

```text
backend/app/modules/
  atomic/
    access/
      github_identity/
      github_installation/
      repository_entitlement/
      scan_token/              # existing token capability, extended
    ingestion/
      envelope_contract/      # frozen JCS/hash primitive, currently disabled
      ingest_attempt/
      source_context/
      result_persister/        # existing persistence boundary, extended
    provenance/
      repository_identity/     # existing identity capability, extended
    operations/
      identity_migration_preflight/ # read-only WS7b inventory and blockers
    scanning/                  # existing parsers/builders, extended
    local_cli/                 # existing CLI capabilities, extended
  workflows/
    github_app_access/
    github_app_webhook/
    github_oidc_ingest/
    local_scan_ingest/         # existing workflow, extended
    result_ingest/             # existing common workflow, extended
    result_ingest_v2_contract/ # disabled cross-part contract coordinator
    setup_bootstrap/
  shared/
    contracts/                 # existing source-neutral contracts
    paths.py                   # existing deterministic path primitives
```

Atomic modules own one domain capability and expose small typed interfaces. Workflow modules coordinate atomic modules and transactions. Shared modules contain genuinely cross-cutting code only; they may not become a miscellaneous utility folder.

HTTP controllers validate transport data, call one workflow, and serialize its result. They do not contain authorization, GitHub policy, persistence queries, or scanner-specific normalization.

## Ports and adapters

Domain and workflow code depend on ports for:

- GitHub OAuth, App, installation, and repository APIs;
- OIDC discovery and JWKS verification;
- clocks, identifiers, and hashing;
- persistence and object storage;
- scanner execution and result parsing.

Concrete clients and repositories live at the infrastructure boundary. Tests use narrow fakes at the same ports.

The current structural rules and module inventory in
[`docs/module-architecture.md`](../../module-architecture.md) remain the
repository-wide authority. This document assigns only new programme capabilities
within that taxonomy; it does not create a second module system.

## Shared ingestion seam

GitHub Actions and local CLI uploads enter through different authentication adapters, then converge on one source-neutral scan-bundle workflow:

```text
GitHub OIDC ----\
                 -> validate bundle -> authorize project -> normalize -> persist -> publish
Local ASU token-/
```

The common seam implements [Result contract](../shared/result-contract.md) and [Source context](../shared/source-context.md). Provider-specific identity and visibility remain outside it.

## Frontend

Frontend feature code is grouped by user workflow rather than API endpoint. Setup uses the component boundary in [Setup experience](../setup/experience.md). API clients are typed, controller state is explicit, and presentation components remain side-effect free.

## Dependency rules

- Atomic modules do not import workflows.
- Workflows may coordinate atomic and shared modules.
- Shared code must not import a workflow or UI route.
- Provider adapters do not leak GitHub response objects into domain models.
- Route modules do not query the database directly.
- Scan parsers do not decide authorization or visibility.
- Imports are enforced by architecture tests.
