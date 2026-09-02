# Local bootstrap and trust

Status: binding distribution and Docker trust contract.

## Wrapper installation

Setup provides one POSIX wrapper for supported macOS and Linux hosts. The user
saves it as `~/.local/bin/assurance-scan`, verifies the displayed SHA-256, and
makes it executable. The wrapper contains no token, account, repository or
machine-specific value.

The wrapper owns Docker invocation and has a versioned protocol independent of
the CLI image. `GET /api/v2/cli/releases/latest` returns a signed manifest with
wrapper minimum version, CLI version, OCI index digest, supported platforms and
signature identity. The wrapper refuses an incompatible server/CLI combination
and directs the user to the replacement command.

## Verified update

`latest` remains the convenient channel, but it is discovery only:

1. resolve `ghcr.io/26457513/assurance-scan-cli:latest` to an OCI digest;
2. require that digest to equal the signed release manifest;
3. verify its Cosign certificate against the exact GitHub Actions workflow
   identity and `https://token.actions.githubusercontent.com` issuer using a
   separately pinned verifier image;
4. run only `ghcr.io/26457513/assurance-scan-cli@sha256:...` with
   `--pull=never`;
5. abort without executing the CLI when resolution, signature, platform or
   provenance verification fails.

The verifier image digest and expected signing identity are pinned in the
wrapper. Version- and digest-pinned modes use the same verification. Update
checks occur once per 24 hours and may be forced with `assurance-scan update`;
the last verified digest remains usable during a registry outage until the
manifest's seven-day maximum age.

## Docker trust boundary

Docker daemon control is host-equivalent privilege. The verified Assurance Scan
orchestrator is the only project container allowed the socket; third-party
scanner and upload-only containers never receive it. The CLI prints this trust
boundary during installation and `doctor` reports daemon/rootless status.

The wrapper accepts only the active local Docker context. It rejects SSH/TCP
and otherwise remote daemons because bind sources belong to the daemon host.
On Linux it adds only the discovered socket GID when necessary; rootless Docker
is supported through its active Unix socket. It never changes host group
membership or socket permissions.

## Sibling mounts

The wrapper resolves and validates explicit host paths before launching the
orchestrator:

```text
checkout  absolute current repository path, mounted /workspace:ro
config    $XDG_CONFIG_HOME/assurance-scan, mounted /config as required
run cache $XDG_CACHE_HOME/assurance-scan/runs/<uuid>, mounted /cache/run:rw
```

It passes the validated run-cache host path separately as
`ASSURANCE_SCAN_HOST_RUN_CACHE`. The orchestrator may give sibling scanners
only `<host-run-cache>/source` read-only and their dedicated cache/output
subdirectories. It rejects a path outside the owner-only Assurance Scan cache,
a symlink component, a mismatched request UUID or a remote daemon. Authentication
files are never below the shared run path.

Login mounts config read-write; ordinary scan/status commands mount it
read-only. Cleanup selects the exact request UUID and verified sibling IDs,
never an arbitrary label supplied by repository content.
