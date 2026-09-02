# Local scanning

## User outcome

A developer with a linked GitHub identity and write-or-higher access to an
enabled repository can scan its current checkout from macOS or Linux:

```bash
assurance-scan scan
```

The logical command is a copyable wrapper around the public multi-architecture
container. No host Python package is required. It scans an immutable snapshot,
uploads the shared v2 bundle and opens the private run in Assurance Scan.

The run uses the same `Project.id` as GitHub Actions, but only the submitting
user can see its existence or content. Current GitHub project entitlement is
also required. See [shared visibility](../shared/identity-and-visibility.md).

## One-time machine setup

From the new Setup local lane, the user:

1. Creates an Assurance Scan `scans:upload` token labelled for the machine.
2. Copies the token once.
3. Runs the token-safe container login command; the token is entered at a hidden
   prompt and validated before storage.
4. Installs and verifies the `assurance-scan` wrapper using the command and
   checksum shown by Setup.
5. Runs the command from an enabled GitHub checkout.

A machine token is account-wide, not repository-specific. Create it once per
machine and reuse it for every enabled repository where the user retains GitHub
write access. The repository selected in Setup supplies only the first-scan
example.

Configuration is atomically stored at
`~/.config/assurance-scan/config.json` with directory mode `0700` and file mode
`0600`. The normal scan mounts it read-only. The file contains API URL, token,
label and a non-secret `cli_installation_id`; it never contains hardware IDs.
The token is an owner-readable plaintext bearer credential, not a device-bound
secret; filesystem protection and prompt-only entry are deliberate first-release
tradeoffs. See [Bootstrap and trust](bootstrap-and-trust.md).

## Commands

```text
auth login --url URL    validate and store token from hidden prompt
auth status             show server/account/label/expiry without token
auth logout             remove credentials, preserve CLI installation ID
doctor                  verify platform, Docker, mounts and registry access
scan                     snapshot, scan and upload
scan --no-upload         retain a private local bundle only
upload --retry UUID      resend the exact outbox bundle without rescanning
cache list|prune         inspect/remove retained sensitive bundles
version                  show CLI/build/image/scanner release provenance
```

## Scope

Supported first release: Docker Desktop/Engine on `linux/amd64` and
`linux/arm64`, including macOS Docker Desktop hosts. Scanning without Docker,
automatic project creation from local uploads, and complete-source upload are
non-goals.

Bootstrap/security details: [Bootstrap and trust](bootstrap-and-trust.md).
Runtime details: [CLI runtime](cli-runtime.md). Token/API details:
[authentication and upload](authentication-and-upload.md).
