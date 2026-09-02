# Quality gates

Status: mandatory for every implementation slice.

## Design gate

- The slice maps to an approved contract and workstream.
- Trust boundaries, authorization point, failure behavior, and data ownership are explicit.
- Atomic, workflow, shared, transport, and infrastructure responsibilities are separated.
- No compatibility shim, polling fallback, or duplicate provider-specific ingest logic is introduced.

## Backend gate

Run the repository-standard commands for:

- Ruff formatting and linting;
- Mypy strict type checking;
- pytest unit, integration, contract, migration, and architecture suites;
- Semgrep security rules;
- schema and generated-client drift checks.

New tests must cover happy path, malformed input, unauthorized and stale entitlement, cross-account isolation, idempotent replay, OIDC replay, quota boundaries, transaction rollback, audit emission, and correlation IDs where applicable.

## Frontend gate

Run the repository-standard commands for:

- formatting and linting;
- TypeScript/Svelte checking;
- unit and component tests;
- production build;
- dependency audit.

Setup additionally requires keyboard-only navigation, 360 px and desktop viewport checks, WCAG AA contrast, reduced-motion behavior, stable loading layout, copy/revoke feedback, and specific recovery states.

## Security gate

- Verify JWT algorithm, issuer, audience, expiry, event policy, workflow path, and replay protection.
- Verify token secrets are never logged, returned after creation, or stored in plaintext.
- Verify source context redaction and HTML escaping.
- Verify all list, detail, trend, export, and aggregate queries authorize before pagination or aggregation.
- Verify all containers run without a privileged user and unnecessary writable
  mounts. The one documented exception is the signed local CLI orchestrator's
  active local Docker Unix socket; prove no scanner/upload container receives
  it, remote contexts fail, and sibling host paths remain inside the validated
  run cache.
- Review third-party Actions by immutable commit and container releases by immutable digest.
- Verify webhook HMAC, replay, size/action allowlists, secret rotation and
  reconciliation fixtures.
- Verify `latest` resolution cannot execute a digest that fails signed-manifest,
  signature, provenance, platform or compatibility checks.

## Release gate

- Build and scan backend, frontend, and scanner images.
- Run local and GitHub scans from the same fixture and compare normalized output.
- Smoke-test a direct default-branch push, a merged pull request's resulting
  default-branch push, rejection of every non-push event, absence of uploads
  from unmerged branches, local upload, token revocation, App suspension, and
  a denied viewer.
- Run `git diff --check` and review the final diff for generated files, secrets, unrelated changes, and stale polling references.
- Record commands, versions, counts, known limitations, migration duration, and image digests in the release evidence.

A slice is not complete because its code exists; it is complete when all applicable gates pass and the evidence is recorded.
