# Setup experience

Status: implemented in the disabled WS7f candidate path. Production activation
and live GitHub state-transition verification remain part of WS7g.

## Purpose

Setup should answer one question: **how do I get trusted scan results into Assurance Scan and let the right people see them?** It presents GitHub Actions and local scanning as two paths built on one GitHub-backed access foundation.

```text
GitHub identity -> App installation -> enabled repository
                                      |-- GitHub Actions: team-visible
                                      `-- Local CLI: private to uploader
```

The current setup screen may be replaced without preserving its routes, tabs, component structure, or query parameters.

## Information architecture

The page has three persistent regions:

1. **Access topology** — a compact, live diagram of identity, installation, repository, and scan path.
2. **GitHub access foundation** — connect an identity, install or manage the GitHub App, and choose an enabled repository.
3. **Scan paths** — configure GitHub Actions or configure a local machine.

GitHub Actions remains the primary team workflow. Local scanning is a private developer workflow for feature branches and work in progress.

## GitHub access foundation

GitHub authentication and GitHub App installation are separate actions:

- **Sign in with GitHub** occurs at `/auth/login` using OAuth with PKCE; Setup shows
  the connected identity and offers reconnect only when authorization expires.
- **Install GitHub App** opens GitHub's installation page.
- **Manage repository access** opens the installation settings on GitHub; they are not embedded in an iframe.

After return, Assurance Scan refreshes the user's installations and eligible repositories. The installation selector supports multiple personal and organisation installations. The repository picker is searchable, keyboard accessible, grouped by installation, and cursor-paginated.

An installation summary says, for example, `3 enabled · selected repositories`. It never infers or displays a count of excluded repositories because GitHub does not expose that set reliably.

Repository access in the UI follows the entitlement rules in [Identity and visibility](../shared/identity-and-visibility.md). A user cannot manually grant Assurance Scan access that they do not have on GitHub.

## GitHub Actions path

For the active repository, show:

- whether any accepted GitHub scan has been received;
- the standard workflow YAML with copy and download actions;
- the default-branch push trigger, including pushes created by merged pull
  requests;
- a link to the repository's Actions page;
- the most recent project-bound accepted or rejected ingest attempt, when present.

The UI must not claim that the workflow is installed. Assurance Scan cannot reliably inspect repository contents with the selected App permissions. Valid readiness states are therefore:

- `No scan received`
- `Last upload accepted`
- `Last upload rejected`

The standard workflow is defined in [Standard workflow](../github/standard-workflow.md).

## Local path

The local path unlocks after the user selects an enabled repository for which they have at least GitHub `write` permission. It shows:

1. create or select a machine token;
2. copy the one-command container login;
3. copy the one-command local scan;
4. view the last private local upload for the active repository.

A machine token belongs to the account and machine label, not to the selected repository. The repository is used only to produce the first relevant command example. The token secret is shown once; the token table shows label, status, created date, expiry, last use, and revoke action in one compact row per token.

Local privacy must be explicit beside the command: `Only you can see local scan runs. Repository access is rechecked before every upload.`

## Bootstrap and API boundaries

The page controller owns loading and selection state. Child components receive typed data and callbacks; they do not issue competing bootstrap requests.

`GET /api/v2/setup?github_repository_id=...` returns:

- current GitHub identity and connection state;
- at most 10 installation summaries plus a cursor;
- the active installation and repository when still eligible;
- capabilities for the active repository;
- compact machine-token summaries;
- the latest local run for the active repository.

Repositories are loaded through:

`GET /api/v2/setup/repositories?github_installation_id=...&query=...&cursor=...&limit=25`

The repository parameter is optional and never inferred server-side. Selection,
eligibility and every interaction state follow [Setup state model](state-model.md).
The server caps repository `limit` at 50. Search is debounced, stale requests
are cancelled, and selections are reflected in controller state before dependent
content loads. A stable page skeleton reserves final layout space to prevent
flicker.

## Components

```text
frontend/src/lib/features/setup/
  models.ts
  api.ts
  controller.ts
  SetupExperience.svelte
  AccessTopology.svelte
  GithubAccessFoundation.svelte
  RepositoryPicker.svelte
  ActionsSetupLane.svelte
  LocalSetupLane.svelte
  SetupFailure.svelte
  SetupSkeleton.svelte
```

Shared primitives remain in the existing design system. Route files only compose the feature entry point.

## Visual direction

The page should feel like a security control surface, not a marketing dashboard.

- Palette: carbon `#0E0F11`, graphite `#16181C`, chalk `#E6E8EC`, GitHub blue `#58A6FF`, local amber `#FBBF24`, verified green `#4ADE80`.
- Typography: Geist for interface text and Geist Mono for repository names, permissions, commands, and status evidence.
- Signature element: the Access Topology visibly connects identity, installation, repository, and the two scan paths.
- Layout: strong horizontal hierarchy, restrained borders, no gradients, no decorative metric cards, and no card-per-step wizard.
- Motion: one short transition when the selected repository changes; respect `prefers-reduced-motion`.

The interface must work at 360 px without horizontal page scrolling. Commands may scroll within their own region. Focus order follows the visual flow, all status meaning has a text equivalent, contrast meets WCAG AA, and copy/revoke feedback is announced through an `aria-live` region.

## Navigation disposition

- `/setup` becomes this experience.
- GitHub App and machine-token configuration live in `/setup`; the old setup tabs and `run_id` query carry-over are removed.
- MCP configuration moves to `/integrations`.
- administrative account and system controls move to `/admin`.
- explanatory material moves to `/help`.

Standard users see Setup, Projects, Scans, and Trends. Administrative navigation remains capability-gated.

## Failure states

Every external boundary has a specific recovery action:

- OAuth failed: reconnect GitHub.
- Installation missing or suspended: install or manage the App.
- Repository no longer eligible: choose another repository and remove the stale selection.
- Entitlement refresh failed: retain the last visible selection but disable mutation and retry.
- Workflow upload rejected: show the request correlation ID and link to troubleshooting.
- Token secret dismissed: explain that it cannot be recovered and offer token rotation.
- Wrapper or image verification failed: do not run it; show the expected digest,
  safe troubleshooting path and update action.

No failure may silently fall back to polling, a stored GitHub PAT, or broader visibility.
