# Migration and data disposition

Status: required before WS7g production cutover.

## Preflight inventory

Run a read-only, repeatable preflight against a restored production database
and then the stopped production database. It emits counts and opaque row IDs,
never tokens or findings, for:

- users with and without a confirmed immutable GitHub identity;
- projects with one numeric repository identity, no identity or conflicting
  identity;
- manual and GitHub-derived memberships;
- GitHub runs with sufficient repository/run provenance to migrate;
- historical `server` runs and local runs;
- duplicate future run keys and broken foreign-key references.

Any conflict blocks migration. Basename, repository text, email and local path
are never used to guess identity.

Run the frozen preflight against each database copy with:

```text
backend/.venv/bin/python backend/scripts/identity-migration-preflight.py <database.sqlite>
```

It opens the exact regular file read-only, emits only counts, internal row IDs,
allowlisted blocker codes and a content checksum, and exits `2` when blocked.
Two independent copies of the same frozen production-like snapshot must produce
the same transformed counts and state checksum. The stopped production database
gets its own preflight checksum after the additive migration is installed; that
exact checksum binds the production transformation. A legacy email-keyed GitHub
token never counts as a linked immutable GitHub identity.

## Account linking window

Before the atomic product cutover, ship a migration-only **Link GitHub** action
inside the existing authenticated application. A user must prove both the
existing session and the GitHub authorization in one short-lived transaction.
The immutable GitHub user ID is then attached to the existing `User.id`, so
local-run ownership and audit history remain intact.

This action is removed at cutover and is not a compatibility path in the new
application. Users who do not link are disabled at cutover, their active local
tokens are revoked, and their data remains retained but inaccessible. Later
recovery requires operator-assisted proof of both identities; email equality
never merges accounts.

## Project and run disposition

- One verified GitHub repository ID: retain `Project.id`, refresh metadata and
  bind it to the active installation.
- No numeric repository ID/local-only project: mark `legacy_unbound`, hide it,
  export its opaque inventory for operator review and never accept new uploads.
- Conflicting repository IDs: block the cutover until explicitly resolved.
- Manual memberships: expire at cutover; rebuild GitHub App projections for
  linked users before opening the service.
- Existing GitHub Actions runs: preserve rows and migrate public run IDs and all
  dependent foreign keys transactionally to the new composite identity.
- Historical `server` runs: retain read-only under current project entitlement,
  label as legacy, and exclude from current latest-run pointers and trends.
- Local runs: retain exact owner and project predicates; revoke pre-cutover
  tokens so users create fresh GitHub-backed credentials.

Enabling an installation repository idempotently creates or reactivates its
project by numeric repository ID. Removing/suspending access disables uploads
and hides the project from users without deleting history. Archive disables
uploads but retained entitled history remains readable. Product-level `hidden`
is a repository-admin display setting and does not alter identity.

## Migration mechanics

Delivery is split into four gated slices without changing the atomic cutover:

1. read-only inventory/checksum and ambiguity blockers — complete;
2. additive GitHub identity, OAuth-state and server-session foundations —
   complete in dormant storage/domain code; the live sign-in path is unchanged;
3. migration-only explicit account linking plus the deterministic, expiring
   GitHub App membership projection adapter — complete in feature-gated
   candidate code; WS7c supplies the installation entitlements used to populate
   that projection;
4. journalled data transformation and final logical-switch tooling — complete in
   candidate code; two independent production-like rehearsals remain an
   operational acceptance gate.

The forward migration adds the disposition fields and a journal table without
activating the new product path. The cutover tool records each transaction's
phase, input checksum, state checksum, counts and completion time. It transforms
data, updates composite GitHub run IDs and dependent foreign keys, validates the
result, and stops before the logical switch unless the operator supplies the
explicit switch confirmation. Legacy fields and tables are not dropped until
the rollback window closes.

The rehearsal records duration, required free space and checksums. Production
must have twice the database size plus 2 GiB free before starting. Every phase
is restart-safe before the final schema switch; after the switch, failure enters
the documented rollback path rather than attempting an ad hoc partial rerun.

## Rehearsal and production commands

First upgrade each stopped copy to the additive migration head. Capture the
preflight JSON and use its `checksum` verbatim:

```text
backend/.venv/bin/python backend/scripts/identity-migration-preflight.py <copy.sqlite>
backend/.venv/bin/python backend/scripts/identity-migration-cutover.py <copy.sqlite> \
  --expected-preflight-checksum <checksum> \
  --cutover-at <fixed-ISO-8601-time> > rehearsal-1.json
```

Repeat against a second independent copy of the same frozen snapshot, using the
same fixed cutover time, then compare the reports:

```text
backend/.venv/bin/python backend/scripts/identity-migration-compare-rehearsals.py \
  rehearsal-1.json rehearsal-2.json
```

The comparator requires both copies to have reached `validated` and requires
identical preflight checksum, transformed counts and state checksum. It excludes
duration and filesystem free-space metrics from equality. Any mismatch blocks
production. On the stopped production database, upgrade to the additive head,
run a fresh preflight, and execute the cutover with that checksum and
`--confirm-switch`. Reusing a rehearsal checksum against changed production data
fails closed.

## Repository workflow rollout

Before maintenance, inventory every enabled production repository as
`updated`, `scheduled`, or `owner_action_required`. Only repositories with the
new default-branch push workflow can produce results after cutover. Pilot
repositories are updated and committed before the rehearsal; other projects
remain visible but show `No scan received` until their owners install the new
workflow.
