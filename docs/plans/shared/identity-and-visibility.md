# Shared identity and visibility

## Canonical project identity

`Project.id` is the internal identity for every run and project-scoped record.
`Project.github_repository_id` is the immutable external repository identity;
`github_repo` and normalized `github_repo_key` are display/bootstrap metadata.
Paths, basenames and run-ID prefixes are never identity.

An active GitHub App installation is the repository-enablement boundary. A
project may be created or bound only from immutable owner/repository IDs inside
that installation's all-or-selected repository scope. A local upload cannot
create a project.

Repository rename with the same numeric repository and owner IDs updates
display metadata. Transfer changes the owner ID: disable uploads, require an
active installation under the new owner, then perform an audited rebind while
preserving project history.

Installation add idempotently creates or reactivates a project by numeric
repository ID. Removal or suspension disables uploads and hides the project
without deleting history. Archive disables uploads while retaining entitled
read access. Exact legacy disposition is defined in
[Migration and data disposition](../delivery/migration-and-data.md).

## Canonical run identity

Origins are `github-actions`, `local` and retained historical `server`.

- GitHub uniqueness: `(github_repository_id, github_run_id, run_attempt)`.
- GitHub public ID: `gh-{repository_id}-{run_id}-{run_attempt}`.
- GitHub display label: `#{run_number} · assurance-scan`, with attempt shown
  when greater than one.
- Local public ID: server-generated `local-{uuid}`.
- Branch is provenance, not identity.

Historical `server` runs are labelled legacy, remain read-only under current
project entitlement and never participate in current latest-run pointers,
trends or compliance aggregates.

GitHub stores signed checkout SHA/ref plus PR head metadata when applicable.
Local stores commit, branch/null detached state, dirty flag, source-content hash
and source-manifest version.

Use qualified names throughout: `github_installation_id` is GitHub's numeric
installation; `cli_installation_id` is the local CLI's random UUID. The v2
payload must not use ambiguous `installation_id`.

## Human visibility

GitHub-origin project/run visibility is the intersection of:

```text
active GitHub App installation repository scope
AND current affiliated repository access for the linked GitHub user
AND active, non-hidden Assurance Scan project
```

Affiliated access is ownership, explicit collaboration or organisation/team
access. Generic public readability is insufficient.

```text
read/triage or higher    view project and GitHub-origin runs
write/maintain or higher view plus upload a private local run
repository admin         manage repository scan settings
organisation owner       manage installation scope on GitHub
```

Local content adds an exact ownership predicate. A local run and its findings,
statuses, artifacts, contexts, exports and derived counts require both current
project entitlement and `submitted_by_user_id == current_user.id`. Another
repository user receives no existence, count, branch, timing or token-label
signal. Shared trends, compliance and latest-run pointers use GitHub-origin
runs only; the owner may privately overlay their own local runs.

Loss of GitHub project access hides historical local and GitHub data from that
user. Restoring the same immutable GitHub identity and repository entitlement
restores retained history. This fail-closed rule is deliberate.

Application admin/superuser flags do not bypass project or private-local
authorization in product APIs. Operational database access is separate and
audited.

## Query boundary

Authorization is applied in database queries before lookup, pagination,
aggregation and ordering for dashboard, project, scan, trend, finding, source,
export, search and MCP endpoints. Post-query filtering is forbidden.

The existing `ProjectMembership` table is retained and migrated as the single
expiring GitHub-entitlement projection with `source=github_app`; ordinary
manual project grants and admin bypasses are removed. Its authoritative inputs
remain GitHub App user access and installation scope.
