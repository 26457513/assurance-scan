# Setup state model

Status: binding interaction contract for the Setup controller.

## Selection

Setup never keeps an implicit server-side “active repository”. The selected
numeric repository ID is represented in the URL:

```text
/setup?github_repository_id=123456
```

`GET /api/v2/setup?github_repository_id=123456` validates the selection against
the current user's entitlement. An absent parameter means no selection. An
ineligible or stale value is removed with `history.replaceState`, announced,
and replaced by the repository picker—not silently substituted.

## States and actions

| State | Evidence | Primary action | Scan lanes |
|---|---|---|---|
| Signed out | no session | Sign in with GitHub | hidden |
| GitHub connected | user token, no installation | Install GitHub App | locked |
| Approval pending | verified GitHub request state | View request on GitHub | locked |
| Installed, no repositories | active installation, empty scope | Manage repository access | locked |
| Repository selection | eligible repositories | Choose repository | preview only |
| Repository ready | selected enabled repository | Copy workflow | Actions enabled |
| Repository ready + write | selected repository with write access | Set up local scanning | both enabled |
| Access stale | expired entitlement | Retry access check | mutation locked |
| Installation suspended | verified suspension | Manage GitHub App | locked |

Authentication begins at the branded `/auth/login` page and hands credential
entry to GitHub through `/auth/github/start`; authenticated users do not see a
misleading “Connect GitHub” action. Accounts are created only from immutable
GitHub user identity; there is no email merge or legacy linking flow.

## Local token interaction

Machine tokens are bearer credentials labelled for human recognition; the
label and `cli_installation_id` do not bind a token cryptographically to a
device. Setup says this explicitly. Creating a token requires at least one
enabled repository with current write access; copying scan commands additionally
requires an active eligible repository.

The secret appears once in a modal-free inline reveal with Copy, concise secure-
storage instructions and Done. Leaving the state destroys the browser-held
plaintext; the UI never downloads it to a file. Dismissal offers immediate
revocation and replacement. Revoke uses
the same compact table row, confirmation naming the label, and an `aria-live`
result.

Setup offers macOS/Linux POSIX installation and command variants. Commands
never interpolate the token; `auth login` reads it from a hidden terminal
prompt. The wrapper checksum and Docker trust explanation appear immediately
beside installation, not behind help text.

## Readiness and failures

Actions readiness comes from the latest project-bound `ingest_attempt`:

- no authenticated attempt: `No scan received`;
- accepted/replayed: `Last upload accepted` with run link;
- rejected/failed internal: safe code, time, correlation ID and recovery link.

Pre-authentication attempts never appear. Local readiness uses only attempts
owned by the current user. Loading preserves the topology dimensions, and each
lane swaps evidence in place so selection never causes whole-page flicker.

The controller models every state as a discriminated union. Impossible
combinations fail schema parsing and render `SetupFailure`; presentation
components do not infer state from missing optional properties.
