# Local CLI runtime

## Distribution and update

Publish `ghcr.io/26457513/assurance-scan-cli` as:

```text
latest        default tested channel; moved only after release qualification
vX.Y.Z        immutable version
sha-<git-sha> immutable build provenance
```

The wrapper treats `latest` as discovery, verifies the resolved release and runs
the exact digest with `--pull=never`. Controlled environments select a version
or digest but use the same verification. Bootstrap, protocol compatibility and
signature policy are defined in [Bootstrap and trust](bootstrap-and-trust.md).
The image contains only the CLI/orchestrator, Git and Docker client—not the
server or frontend. Publish signed `linux/amd64` and `linux/arm64` manifests with
SBOM and provenance. An unverified tag or digest is never executed.

## Host mounts and privilege boundary

The generated command mounts:

- current checkout read-only at `/workspace`;
- config read-only at `/config`;
- owner-only cache/outbox read-write at `/cache`;
- the active local Docker Unix socket for the verified outer orchestrator only.

Run as host UID/GID and add only the discovered socket GID when required so
persisted files are not root-owned. Reject remote Docker contexts, symlinked,
wrongly owned or group/world-writable config paths. Never pass the Assurance
Scan token or Git credentials to scanner containers.

The wrapper passes the validated absolute host run-cache path separately so the
orchestrator can mount `<host-run-cache>/source` into sibling scanners. It never
uses `/cache` as a daemon-side bind source. See [Bootstrap and trust](bootstrap-and-trust.md).

Third-party scanners receive an immutable snapshot read-only, request-specific
name/labels, no-new-privileges, dropped capabilities, bounded CPU/memory/time,
and the network/cache policy in the release manifest. Target-image scanning
uses an image archive capped at 10 GiB created by the trusted orchestrator; the Trivy
container never receives the Docker socket.

## Repository discovery and snapshot

Record canonical GitHub `owner/repo`, branch/null detached state, commit, dirty
flag and client request UUID. Normalize SSH/HTTPS remotes; never upload absolute
host paths. `--project owner/repo` is an audited override and cannot bypass
server-side installation or entitlement checks.

Create `/cache/runs/<request-id>/source` from tracked plus non-ignored untracked
files. Scanners and source-context extraction read this exact snapshot.

- deleted files remain absent;
- symlinks are copied without following outside targets;
- initialized submodules are recursively snapshotted; missing ones warn;
- working-tree LFS pointer/hydrated state is recorded;
- pre/post fingerprint mismatch aborts with retryable source-changed error;
- `.git`, `.assurance-scan`, cache and outbox are always excluded.

Reject devices/FIFOs/sockets, traversal/absolute/NUL/duplicate-normalized paths
and hardlink surprises. Bounds: 500,000 entries, 1 GiB/file, 5 GiB total, plus
1 GiB free-space reserve. Delete partial snapshots after failure.

`source_content_hash` is SHA-256 over the versioned canonical, path-sorted entry
manifest including relative path, mode/type, symlink target and content hash.

## Scanner release set

Actions and local execution consume one reviewed manifest containing immutable
multi-architecture image digests, vendored Semgrep rules, ignore policy,
resource/network rules and database-age policy. Mutable scanner `latest` tags
and Semgrep `--config auto` are forbidden.

The initial qualified tools remain Semgrep, Gitleaks, Trivy, Syft, Grype and
OSV-Scanner. Vulnerability databases may refresh when older than 24 hours;
record version/timestamp/digest so comparisons disclose data drift.

## Outbox and recovery

Write redacted metadata/results to an owner-only outbox before upload. Delete
the source snapshot after scanning. Delete the bundle after confirmed upload,
retaining only a small receipt. Response loss uses request-status recovery and
the same UUID; retry never rescans or creates a duplicate.

Default outbox retention is seven days and 1 GiB. Every command prunes safely
while respecting active locks. Stream scanner output to bounded files; logs
never contain tokens, absolute snapshot paths or unredacted scanner output.
Request-labelled sibling containers are cleaned on exit, signal and recovery;
cleanup never selects a broad Compose label.
