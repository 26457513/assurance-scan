# Scan ingestion programme

Status: approved direction; WS6a–WS7c implemented and WS7d–WS7g pending —
2026-09-02

This folder is the authoritative plan for local scanning, GitHub Actions push
ingestion, GitHub-derived access and the replacement Setup experience. It
supersedes the former monolithic `plan-local-scan-upload.md` and
`plan-github-oidc-push-ingest.md` documents.

## Outcome

- GitHub is the authority for account identity, enabled repositories, teams and
  human access to projects and GitHub-origin scans.
- GitHub Actions pushes results using a short-lived OIDC identity. Assurance
  Scan does not poll runs, download artifacts or fetch repository source.
- Local scanning uses an Assurance Scan-issued account token. A local run is
  visible only to its submitting user and never contributes to shared results.
- Both origins use one versioned result contract, scanner release set, source-
  context contract, project identity and source-neutral ingestion workflow.
- `/setup` is rebuilt around one shared GitHub access foundation branching into
  shared Actions scans and private local scans.

## Document map

| Concern | Authoritative document |
|---|---|
| Project/run identity and visibility | [Shared identity and visibility](shared/identity-and-visibility.md) |
| Upload envelope, limits and idempotency | [Shared result contract](shared/result-contract.md) |
| Finding source context and redaction | [Shared source context](shared/source-context.md) |
| Accepted and rejected upload evidence | [Ingest attempts](shared/ingest-attempts.md) |
| Local user journey | [Local scan overview](local/README.md) |
| CLI bootstrap, updates and Docker trust | [Local bootstrap and trust](local/bootstrap-and-trust.md) |
| Local snapshot, Docker and outbox | [Local CLI runtime](local/cli-runtime.md) |
| Local tokens and upload API | [Local authentication and upload](local/authentication-and-upload.md) |
| GitHub installation and user access | [GitHub App access](github/app-access.md) |
| Webhooks and repository freshness | [Webhook and repository sync](github/webhook-and-repository-sync.md) |
| Actions workload authentication | [OIDC push ingestion](github/oidc-ingestion.md) |
| Standard repository YAML | [Standard workflow](github/standard-workflow.md) |
| New Setup information architecture | [Setup experience](setup/experience.md) |
| Setup states and transitions | [Setup state model](setup/state-model.md) |
| New capability placement in the existing module architecture | [Module architecture](delivery/module-architecture.md) |
| Remaining implementation order | [Workstreams](delivery/workstreams.md) |
| Existing-data migration | [Migration and data disposition](delivery/migration-and-data.md) |
| Production change and recovery | [Cutover and operations](delivery/cutover-and-operations.md) |
| Required validation | [Quality gates](delivery/quality-gates.md) |
| Already completed foundation | [Completed work](history/completed-work.md) |

## Precedence and change control

Each decision has one owning document. Other files link to it instead of
restating the contract. If two documents appear to conflict, the concern owner
in the table above wins and the conflict must be removed before implementation.

Runtime/API backward compatibility is not required. A migration-only GitHub
identity-linking action ships before cutover and is removed by the coordinated
server, frontend, workflow and public-CLI release. Rollback means restoring the
verified pre-cutover database and previous matching application set; there are
no dual-read, dual-write, poll fallback or legacy UI paths in the new release.
