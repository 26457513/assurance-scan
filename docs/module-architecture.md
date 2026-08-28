# Module architecture

Assurance Scan uses a VibeGuide module topology for newly extracted and new
capabilities:

```text
backend/
  app/
    api/                  # transport entrypoints
    modules/
      atomic/             # independently testable capabilities
      workflows/          # use-case orchestration
      shared/             # stable contracts and deterministic primitives
  resources/              # schemas, catalogues, mappings, prompts, templates
  scripts/                # operational and CI entrypoints
  tests/                  # backend test suites and fixtures
```

```text
entrypoints (API routes, scripts, CLI)
                |
                v
            workflows
                |
                v
             atomic
                |
                v
             shared
```

- `backend/app/modules/atomic` contains independently testable capabilities.
- `backend/app/modules/workflows` coordinates capabilities into use cases.
- `backend/app/modules/shared` contains stable contracts and deterministic
  primitives used across capabilities.
- API routes and command entrypoints translate transport errors and inputs;
  domain services do not depend on FastAPI or another entrypoint.
- Atomic and shared modules cannot import workflows or API routes.
- Shared modules cannot import atomic modules.
- Atomic `service.py` modules cannot import SQLAlchemy, concrete repositories,
  filesystem/network clients, or subprocess APIs. They depend on explicit ports;
  concrete implementations live in private `_adapters.py` modules or the
  infrastructure layer and are injected by composition code.
- Workflows cannot import legacy worker implementations or concrete database
  repositories. They coordinate atomic public APIs and explicit unit-of-work
  ports.
- Atomic modules expose their supported surface through `__init__.py`.
- Capability contracts live in `models.py`, behavior in `service.py`, and
  replaceable infrastructure implementations in optional `_adapters.py` files.
- `result_ingest` is the source-neutral GitHub/local persistence workflow,
  `local_scan_ingest` owns authenticated upload sequencing, and
  `github_scan_execution` owns the GitHub Actions scanner loop. The CI script
  is only responsible for command arguments and output files.

The completed pre-feature extraction is:

| Responsibility | Current module |
|---|---|
| Source-neutral result ingest orchestration | `app.modules.workflows.result_ingest` |
| Authenticated local upload orchestration | `app.modules.workflows.local_scan_ingest` |
| Idempotency, quotas and redaction | `app.modules.atomic.ingestion.{idempotency_guard,usage_quota,data_redactor}` |
| GitHub scanner execution | `app.modules.workflows.github_scan_execution` |
| Finding parsers | `app.modules.atomic.scanning.finding_parser` |
| JUnit/test-result parsing | `app.modules.atomic.scanning.test_result_parser` |
| Tribal assurance checks | `app.modules.atomic.scanning.tribal_checks` |
| Scanner catalog | `app.modules.atomic.scanning.scanner_catalog` |
| SARIF/result construction | `app.modules.atomic.scanning.result_builder` |
| Docker execution port | `app.modules.atomic.platform.docker_port` |
| Ingest persistence contract/adapter | `app.modules.atomic.ingestion.result_persister` |

The former `app.ci_ingest` and `app.worker` parser, scanner, runner, SARIF and
tribal-check roots are deliberately unsupported and must not be recreated as
facades.

This project uses a clean cutover. Old import paths and compatibility wrappers
are removed when a capability moves; application callers and tests change in
the same workstream. Architecture tests reject the removed roots so new code
cannot quietly rebuild a compatibility layer.

Python commands run with `backend/` as the working directory (or on
`PYTHONPATH`), so application imports use `app.*`; the old `server.*` package
name is no longer part of the supported layout.

The initial project registry extraction retained basename-based GitHub alias
merging and application-wide project access. The local-scan clean cutover
replaces that behavior with mandatory durable project IDs and removes the
basename fallback rather than supporting both identity systems at runtime.
