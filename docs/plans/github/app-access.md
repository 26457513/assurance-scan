# GitHub App access plane

Implementation status: durable installation/repository records, independent
single-use installation state, fixed-origin GitHub API adapter, App JWT and
installation-token exchange, atomic numeric-identity repository projection and
setup-return HTTP flow are complete in candidate code. The setup route remains
behind `GITHUB_APP_ACCESS_ENABLED=false`. The independently gated signed
webhook boundary is also complete; webhook mutation processing and query-time
entitlement refresh are later WS7c slices.

## Exact app configuration

The public Assurance Scan GitHub App uses:

- repository permission: `Metadata: read` only;
- account permissions: none beyond GitHub's basic authorized-user identity;
- repository selection: GitHub's `all` or `selected` installation choice;
- webhooks: `installation`, `installation_repositories`, `repository` and
  `installation_target`;
- expiring user authorization tokens enabled;
- request user authorization during install disabled;
- exact OAuth callback URL: `${PUBLIC_BASE_URL}/api/v2/github/callback`;
- exact setup URL: `${PUBLIC_BASE_URL}/api/v2/github/setup-return`;
- redirect on installation update enabled;
- wildcard callback matching disabled.

It has no Contents, Actions, Administration or organisation Members permission.
It cannot inspect workflow files, list workflow runs, download artifacts, read
source or edit repository selection.

## Separate user and installation flows

**GitHub sign-in/authorization** is an OAuth web flow using a random state plus PKCE S256. It
links immutable GitHub user ID after explicit confirmation; email/login never
links accounts. The callback consumes state once and stores encrypted expiring
user/refresh tokens server-side only.

OAuth and installation state use separate 256-bit random values, stored only as
server-side hashes, bound to the initiating browser session and consumed once
within ten minutes. Return paths are a fixed internal allowlist. Browser sessions
use rotated opaque server-side IDs with `Secure`, `HttpOnly`, `SameSite=Lax` and
`Path=/` cookies, a 12-hour idle limit and seven-day absolute limit. Logout,
disconnect, role change and account disable revoke active sessions. Browser
mutations retain exact-origin and CSRF validation.

**Install/Manage repositories** is GitHub's installation flow using setup URL
return. The returned `github_installation_id` is untrusted. Assurance Scan uses
the already-connected user token to prove the user can access that installation
before persisting it. GitHub alone presents all/selected repository controls.

Installation owners and repository administrators act according to GitHub's
own organisation policies. Users without authority may request approval; Setup
shows `Approval requested` without implying installation succeeded.

## Repository and user entitlement

Installation scope is loaded using an installation token and GitHub's
installation repositories endpoint. User scope is loaded using the GitHub App
user token through:

```text
GET /user/installations
GET /user/installations/{github_installation_id}/repositories
```

The returned repository permission flags map through the shared visibility
rules. `Metadata: read` is the complete permission set for this access check.
Generic public repositories outside explicit owner/collaborator/organisation
affiliation are excluded.

Entitlement projections expire five minutes after verification. Refresh at
login, installation/setup return, repository selection, project-list access
when stale and every direct sensitive request when expired. Local upload
requires a verification no older than 60 seconds. An expired projection plus a
GitHub outage fails closed.

Verified installation webhooks immediately invalidate installation/repository scope.
Because the minimal app does not subscribe to team/member events, team and
collaborator changes propagate within the five-minute entitlement TTL rather
than being described as instantaneous.

Webhook verification, repository refresh and missed-delivery repair follow
[Webhook and repository sync](webhook-and-repository-sync.md). Webhook payloads
are invalidation hints; sensitive requests revalidate through GitHub when their
contract requires fresher evidence.

## Persistence

```text
github_accounts
  user_id, github_user_id UNIQUE, login_at_last_verify,
  encrypted_user_token, encrypted_refresh_token, token_expires_at,
  linked_at, verified_at, disconnected_at

github_app_installations
  github_installation_id UNIQUE, github_owner_id, owner_login_at_last_verify,
  account_type, repository_selection, suspended_at, created_at, updated_at

github_installation_repositories
  github_installation_id, github_repository_id, project_id,
  repository_full_name, github_owner_id, default_branch, visibility,
  archived, disabled, repository_verified_at, enabled_at, removed_at

project_memberships
  user_id, project_id, source=github_app,
  effective_permission, verified_at, expires_at
```

OAuth state/PKCE verifier and webhook delivery IDs are bounded and single-use/
idempotent. Encrypt credentials with rotation and never place them in browser
storage or logs.

## Account lifecycle

GitHub authorization is the primary interactive sign-in. Existing authenticated
accounts enter a one-time explicit linking flow; no email-based automatic merge
occurs. Collision on immutable GitHub user ID stops for operator resolution.

Disconnect revokes GitHub authorization and every active local scan token,
expires memberships and hides projects/runs. Reconnecting the same immutable
identity restores retained entitled history, but the user creates new local
tokens. Installation suspension/removal rejects OIDC and human access without
deleting history.

Assurance Scan has no ordinary developer-group or manual-project-grant UI.
GitHub teams are the group system. Platform operations live separately and do
not grant project-content access.
