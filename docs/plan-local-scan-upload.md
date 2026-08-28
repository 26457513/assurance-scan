# Plan: local scan runner and authenticated result upload

Status: WSQ/WS0/WS1/WS2/WS3/WS4 complete; WS5 implementation complete and production rollout pending operator execution — 2026-08-28

The repository-readiness gate in **WSQ** passed before feature implementation
began. The structural refactor and initial quality cleanup exposed the remaining
boundaries; the documented adapter rules, release reproducibility and
end-to-end quality automation are enforced in code throughout the remaining
workstreams rather than treated as intentions.

## Objective

Let a developer run one command from the root of any registered,
GitHub-linked checkout on a supported machine:

```bash
assurance-scan scan
```

This is the user-facing logical command supplied as a copyable shell
function/wrapper. The distributed implementation remains the public container;
the documented raw `docker run` command is always available and no host Python
package is required.

The command pulls the public `assurance-scan-cli` image, scans the current
checkout with Docker, and uploads the resulting `findings.json`, SARIF, and
SBOM to the hosted Assurance Scan API using a bearer token held on the
developer's machine.

A GitHub Actions scan and a local scan of the same repository must belong to
the same Assurance Scan project. Runs remain distinct by origin, branch,
commit, and (for local runs) working-tree state.

## Existing components to reuse

The repository already contains the core of this feature:

- `.github/workflows/publish-ghcr.yml` publishes the public slim image as
  `ghcr.io/26457513/assurance-scan-ci`.
- `backend/Dockerfile.ci` and `backend/scripts/ci-scan.py` run the portable scanner subset and
  emit `findings.json`, `assurance.sarif`, and `sbom.cyclonedx.json`.
- `backend/app/modules/workflows/github_result_ingest/` validates and converts
  that result format into `Run`, `ScanJob`, `ScannerRun`, `ScannerArtifact`,
  and `Finding` rows through an explicit persistence port.
- `Run.git_branch` and `Run.commit_sha` already preserve revision identity.
- `Project.github_repo` already links a registered project to `owner/repo`.
- `Project.id` already provides the durable identity that local and GitHub
  runs should share once `Run.project_id` is added.

Local scanning should therefore use the CI result contract. It should not
introduce another scanner implementation or upload the full report produced by
`backend/scripts/run-local.sh`.

## Repository readiness before feature work

The existing codebase must be in tip-top condition before local-scan schema,
API, CLI or UI behavior is added. A green feature test is not sufficient if an
older validation path, migration, build or static-analysis gate is failing.

The current baseline has 316 passing backend tests, clean Ruff and Mypy runs,
zero Semgrep findings/errors, clean Svelte diagnostics, successful production
and container builds, and passing schema-fixture validation. Preserve that
baseline while completing these remaining structural and operational items:

- finish the promised infrastructure boundaries: atomic capability services
  must not import SQLAlchemy models/repositories directly; database, filesystem,
  HTTP and Docker implementations belong in private adapters behind explicit
  ports;
- remove workflow dependencies on legacy `app.worker` implementations by
  extracting or adapting the parser and tribal-check capabilities;
- extend architecture tests to enforce the full dependency direction, not only
  the current shared-layer restrictions;
- add a single deterministic quality-gate entrypoint and CI job that runs the
  same checks developers run locally;
- pin the quality-tool/runtime versions used by CI, including the Semgrep image
  and rules configuration, while retaining an optional latest-rules audit;
- add migration dry-run/forward tests against a copied representative SQLite
  database, verify foreign keys/indexes/data projection, and exercise backup
  restore as the rollback mechanism;
- establish a frontend component-test harness before relying on UI behavior
  tests in WS1/WS4;
- resolve or explicitly pin the current SvelteKit/Svelte compatibility notices
  so a successful build is also warning-free;
- remove generated caches from review inputs and keep root-level files limited
  to genuine repository entrypoints/configuration.

No feature migration, upload route, scan token, local CLI or origin UI should
land before WSQ acceptance. Any newly discovered baseline failure is fixed at
its source; it is not added to an allowlist merely to unblock feature work.

## Clean cutover policy

Backward compatibility is not a requirement. The server, frontend, GitHub
scanner contract and local CLI move to the new model as one coordinated
release:

- no compatibility exports, deprecated import paths, dual-read/dual-write
  repositories or legacy API response shapes;
- no runtime fallback from `project_id` to paths, basenames, run-ID prefixes or
  nullable legacy identity;
- `Run.project_id` is mandatory after the one-time migration and
  `Run.project_path` is removed once its data has been projected into the new
  canonical project/provenance records;
- old CLI/ingest schema versions are rejected with an explicit upgrade error
  rather than translated indefinitely;
- the frontend and server API types change atomically, and the supported GitHub
  workflow/image is promoted with the same release;
- rollback means restoring the pre-migration database backup and redeploying
  the matching previous application set, not running mixed versions or keeping
  permanent downgrade/compatibility code.

Historical data is preserved only where it maps unambiguously to the new
identity model. The migration produces a dry-run report and aborts on ambiguous
or unresolved rows. An operator must explicitly resolve or export/drop those
rows before the cutover; the running application never carries a null-project
compatibility path.

## User experience

### One-time setup

In **Settings → Local scan tokens**, the signed-in user chooses a recognizable
label such as `laptop` or `workstation` and creates a token. The token belongs
to that Assurance Scan user, has only the `scans:upload` scope, and is shown
once in the UI for copying. The server stores the label and token hash, never
the plaintext token.

The token is entered at the CLI's hidden prompt and written to a host
configuration directory mounted into the CLI container:

```bash
mkdir -p "$HOME/.config/assurance-scan" "$HOME/.cache/assurance-scan" && \
  chmod 700 "$HOME/.config/assurance-scan" "$HOME/.cache/assurance-scan"
docker run --rm -it --pull=always \
  --user "$(id -u):$(id -g)" \
  -v "$HOME/.config/assurance-scan:/config" \
  ghcr.io/26457513/assurance-scan-cli:stable \
  auth login --url https://scan.example.com
```

Before saving, `auth login` calls an authenticated validation endpoint and
shows the account and token label it received, for example `alice@example.com
(laptop)`. It then atomically writes `/config/config.json` with mode `0600`.
This maps to `~/.config/assurance-scan/config.json` on the host and contains:

```json
{
  "api_url": "https://scan.example.com",
  "token": "asu_v1_...",
  "token_label": "laptop",
  "installation_id": "random-local-uuid"
}
```

`installation_id` is a non-secret random identifier generated by the CLI. It
helps distinguish installations in audit data without collecting a hostname,
serial number, MAC address, or other hardware fingerprint.

Mode `0600` means only the owning host user can read or replace the file. The
file itself should not be forced to mode `0400`: login, logout, server changes,
and token rotation need to replace it. During normal scans the directory is
mounted into the container with `:ro`, which is the useful read-only boundary.
Login refuses symlinked, wrongly owned or group/world-writable config paths and
uses a same-directory `0600` temporary file, `fsync` and atomic rename.
`installation_id` survives token rotation and logout; logout removes credentials
without pretending the installation itself changed.

Environment variables can override configuration for automation, but the
documented interactive flow does not put the token in shell history, a project
file, or Docker container environment metadata:

```bash
export ASSURANCE_SCAN_URL=https://scan.example.com
export ASSURANCE_SCAN_TOKEN=asu_xxxxxxxxxxxxxxxxx
```

This override is automation-only and prints a warning in interactive use:
process and container inspection may expose environment variables. It is not
presented as equivalent to the owner-only configuration-file flow.

The CLI accepts HTTPS API origins only. Plain HTTP is rejected except for an
explicit development opt-in limited to loopback hosts. The upload client does
not forward bearer credentials across an origin-changing redirect. Custom CA
bundles may be mounted/configured without disabling certificate validation.

Tokens must never be written into the project, `.assurance-scan.yml`, Docker
environment variables in the normal interactive flow, scan artifacts, or
command output. The CLI container can read the token only because `/config` is
mounted; it must not forward the token to any sibling scanner container.
`auth login` runs with the host UID/GID so it does not leave a root-owned
configuration file on Linux. The scan command may retain the image's default
user so it can access the Docker socket; it mounts the configuration read-only.

### Scan

From the target repository:

```bash
docker run --rm -it --pull=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD:ro" \
  -v "$HOME/.config/assurance-scan:/config:ro" \
  -v "$HOME/.cache/assurance-scan:$HOME/.cache/assurance-scan" \
  -e ASSURANCE_SCAN_CACHE_DIR="$HOME/.cache/assurance-scan" \
  -e ASSURANCE_SCAN_HOST_UID="$(id -u)" \
  -e ASSURANCE_SCAN_HOST_GID="$(id -g)" \
  -w "$PWD" \
  ghcr.io/26457513/assurance-scan-cli:stable scan
```

This is one command and requires no language runtime or locally installed CLI.
The first release requires invocation from the Git repository root. Its
qualified matrix is Ubuntu 22.04/24.04 rootful Docker on `linux/amd64`, Ubuntu
24.04 rootful Docker on `linux/arm64`, and the two current Docker Desktop
releases on Intel and Apple-silicon macOS. Each signed release descriptor lists
the exact versions exercised. Native Windows, WSL2, rootless Docker,
SELinux-enforcing bind mounts, Podman and remote Docker contexts are explicitly
unsupported in v1 rather than implied to work.
`--pull=always` asks the registry whether `stable` changed on every run. Docker
reuses existing layers, so an unchanged version is effectively a metadata
check and an update downloads only changed layers.

For frequent use, the Setup page can also provide a copyable shell function
named `assurance-scan`. It pulls `stable`, resolves the returned repository
digest, and runs that exact digest with `--pull=never`, eliminating a tag race
and recording precise CLI provenance. When the registry is unavailable it may
use the last resolved digest with a visible warning unless
`ASSURANCE_SCAN_REQUIRE_FRESH=1`. The function is convenience/update glue only;
the public container remains the entire application and the raw `docker run`
form remains supported with nullable registry-digest provenance.

The outer container runs with `--init`, a read-only root filesystem, a
`nosuid,nodev,noexec` temporary filesystem, all capabilities dropped and
`no-new-privileges`. These flags reduce ordinary container attack surface but
do not neutralize the Docker socket: the CLI remains root-equivalent to the
Docker host and is treated as a signed high-trust release.

Useful initial flags:

```text
--no-upload          run the image and keep results locally
--branch NAME        override branch detection for a detached HEAD
--project OWNER/REPO override remote-based repository detection
--target-image TAG   additionally scan an application image visible to Docker
--output DIR         retain a result bundle in a mounted host directory
--url URL            override the configured API URL
```

`--no-upload` writes the owner-only result bundle into the mounted cache and
prints the corresponding host path; it must not leave the only copy inside the
`--rm` container. `--output` is restricted to a path below the mounted cache by
default. If an arbitrary output directory is supported, the generated command
must add a same-path host bind mount explicitly. The retry interface is a
single unambiguous top-level command:

```text
assurance-scan upload --retry REQUEST_ID
```

It reuses the stored payload and request ID and never rescans source.

The command prints the hosted run URL after a successful upload and exits
non-zero for runner or upload failures. Findings themselves do not make the
command fail in the first release, matching GitHub Actions behavior.

Stable exit codes are `0` success/valid bundle (including findings and partial
scanner warnings), `2` usage/configuration, `3` Docker/Git/snapshot/platform
preflight, `4` no valid scanner result, `5` permanent upload rejection with
bundle retained, `6` retryable queued upload, and `130` interruption after
best-effort cleanup.

## Local runner design

Publish a dedicated public container,
`ghcr.io/26457513/assurance-scan-cli`, rather than installing an executable on
the host. Add `backend/Dockerfile.cli` and a Python standard-library entry point such as
`backend/scripts/local-cli.py`. The image contains the existing CI orchestration code
and Docker CLI, so its `scan` subcommand can call the same `run_scanners()` and
result builders used by `backend/scripts/ci-scan.py`.

Do not make the CLI container launch `assurance-scan-ci` as another container.
The CLI container is the orchestrator: it scans the mounted repository by
launching the existing stock scanner images through the Docker socket, writes
results to an internal temporary directory, and uploads them itself. This
removes a redundant container layer while keeping scanner behavior identical
to Actions.

Conceptually the user's invocation is:

```bash
docker run --rm --pull=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$REPO_ROOT:$REPO_ROOT:ro" \
  -v "$HOME/.config/assurance-scan:/config:ro" \
  -v "$HOME/.cache/assurance-scan:$HOME/.cache/assurance-scan" \
  -e ASSURANCE_SCAN_CACHE_DIR="$HOME/.cache/assurance-scan" \
  -e ASSURANCE_SCAN_HOST_UID="$(id -u)" \
  -e ASSURANCE_SCAN_HOST_GID="$(id -g)" \
  -w "$REPO_ROOT" \
  ghcr.io/26457513/assurance-scan-cli:stable scan
```

The repository must be mounted at the same absolute path inside the
orchestrator container. `DockerRunner` launches sibling scanner containers
through the host Docker socket, so a synthetic `/workspace` path would not be
mountable by the host daemon on Docker Desktop.

The cache mount serves two purposes: a stable source snapshot that sibling
scanner containers can bind-mount by the same absolute host path, and an upload
outbox that survives an interrupted CLI container. Cache content is owner-only;
the CLI uses the supplied host UID/GID to ensure persisted files are not left
root-owned on Linux. The token remains in the CLI process and is not passed to
sibling scanner containers.

Publish these tags:

```text
stable        tested automatic-update channel used by the documented command
v0.1.0        immutable release for controlled environments
<git-sha>     immutable build provenance
```

The CLI reports its version, OCI build revision and Docker image ID in uploaded
metadata. It reports a registry digest only when inspecting its running
container/image resolves one unambiguously; a container cannot otherwise
reliably infer the digest of the tag used to start it. A missing registry digest
is represented as null, never guessed from the image ID.
Users who require change control replace `stable` with `v0.1.0` and omit
`--pull=always`. Update behavior should rely on Docker rather than custom
self-update code inside the application.

The release publishes a multi-architecture manifest for `linux/amd64` and
`linux/arm64`. The Setup page also shows a pinned digest command for controlled
environments and a version-tag/`--pull=missing` alternative for offline use.
An unavailable registry must produce an actionable message; `--pull=always`
does not guarantee fallback to a cached image.

Because the CLI container receives the Docker socket, publishing it is a
high-trust supply-chain operation. The release workflow must run tests before
moving `stable`, generate an SBOM and provenance attestation, sign the image,
and document digest pinning. The image should contain only the CLI/orchestrator
and required Docker client—not the hosted server or frontend.

Plain `docker run` does not verify a Cosign signature, so the automatic
`stable` flow explicitly trusts the GHCR publisher and protected release
workflow. Environments requiring local signature enforcement use an
organisation-provided wrapper/policy or the pinned digest command.

The scanner catalog in
`backend/app/modules/atomic/scanning/scanner_catalog/` currently uses mutable
`:latest` tags. Replace these with a shared, reviewed version/digest manifest
used by both GitHub Actions and the local CLI. A CLI `stable` release therefore
identifies one tested set of Semgrep, Gitleaks, Trivy, Syft, Grype and OSV
Scanner images. The CLI pulls missing pinned images before the scan; moving the
`stable` CLI tag is what advances the scanner set. This avoids a locally cached
`:latest` image producing different results from a fresh Actions runner.

The initial release-set inputs inspected on 2026-08-28 are locked as follows;
implementation consumes the index digest, not the discovery tag:

| Scanner | Tool version | Multi-architecture index digest |
|---|---:|---|
| Semgrep | 1.174.0 | `semgrep/semgrep@sha256:f1f7b71861c7b28b6e0f661225a2c4f58a484f5d0f182465c6d6b3b22f972ade` |
| Gitleaks | 8.30.1 | `zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f` |
| Trivy | 0.74.0 | `aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969` |
| Syft | 1.51.1 | `anchore/syft@sha256:95fe0835e5bebc6f8b1f8acef68d47d63d594ef4c0f25c097ff853b23cbac74c` |
| Grype | 0.118.0 | `anchore/grype@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7` |
| OSV-Scanner | 2.5.1 | `ghcr.io/google/osv-scanner@sha256:8108ae94eadea5a02c9bec6e646909d5b790b44bd62d7f5b7f0b1d6d0ffc7734` |

All six indexes contain `linux/amd64` and `linux/arm64` manifests. Release
qualification still pulls and smokes both platform manifests before promotion.
The manifest also pins a vendored, reviewed Semgrep rules bundle; `--config
auto` is removed because an immutable executable with mutable remote rules is
not reproducible. Vulnerability databases remain intentionally time-sensitive:
the scan refreshes them when older than 24 hours and records database
version/timestamp/digest, so comparisons disclose rather than hide data drift.
The same orchestration path applies `.scannerignore` for Actions and local
scans and uploads its content hash plus retained/removed counts; it filters
source/config findings without silently removing dependency inventory.

The reusable workflow in `26457513/assurance-scan-ci` currently controls the
Actions execution path. The release contract must therefore make the manifest
in this repository the source of truth and make that workflow consume an
immutable published CI-orchestrator digest from the same tested release set.
Pinning only the reusable-workflow commit while it pulls a mutable image is not
reproducible. Promotion moves `stable` to an already tested digest and never
rebuilds it. The release checklist verifies that the GHCR package is public,
all third-party Actions use full commit SHAs, and SBOM/provenance/signature
artifacts refer to the promoted digest.

`backend/Dockerfile.cli` must install Git; the existing `backend/Dockerfile.ci` contains the
Docker client but not Git. Git metadata commands inside the container must use
the mounted repository as an explicit Git safe directory. Host-owned files
otherwise trigger Git's
"dubious ownership" protection when the scan container runs as root.

Before scanning, the CLI records:

```text
repository: canonical owner/repo parsed from remote.origin.url
branch:     git symbolic-ref --short HEAD, or null for detached HEAD
commit:     git rev-parse HEAD
dirty:      git status --porcelain is non-empty
request_id: locally generated UUID used for idempotent retries
```

The CLI then creates
`~/.cache/assurance-scan/runs/<request-id>/source` using tracked files plus
non-ignored untracked files (`git ls-files --cached --others
--exclude-standard`). Scanners read this immutable snapshot rather than the
live checkout. Deleted files stay absent; symlinks are copied without following
targets outside the repository. Submodule handling must be explicit and tested:
initialized submodule working trees are recursively snapshotted, while missing
submodules produce a warning.

Git LFS behavior is explicit: the snapshot contains the bytes present in the
working tree and records whether tracked LFS pointers or hydrated LFS objects
were observed. The CLI records a pre/post repository fingerprint and aborts
with a retryable source-changed error if files mutate while the snapshot is
being assembled. It checks free space before copying, bounds individual and
aggregate snapshot growth, and removes partial snapshots after failure.
The v1 bounds are 500,000 entries, 1 GiB per regular file and 5 GiB total,
with estimated free space plus a 1 GiB reserve. Sockets, devices, FIFOs,
absolute/traversal/NUL paths, duplicate normalized paths and hardlink surprises
are rejected. `.git`, `.assurance-scan` and configured cache/outbox paths are
always excluded; scanner-specific dependency exclusions live in the shared
manifest so Actions and local execution remain aligned.

`source_content_hash` is required for local uploads and is SHA-256 over a
canonical, path-sorted sequence of snapshot entries containing relative path,
file mode/type, symlink target where applicable, and file-content hash. The
canonical manifest format is versioned as `source_manifest_version` in upload
metadata so it can evolve without changing the
meaning of historical runs.

Results and request metadata are written to an owner-only outbox before upload.
The source snapshot is deleted as soon as scanning finishes. After confirmed
upload the outbox bundle is also deleted. If upload fails or the response is
interrupted, only the result bundle remains and `upload --retry REQUEST_ID` reuses the
same request ID without rescanning. The default configurable retention is seven
days with a 1 GiB total outbox quota; every command performs a safe prune that
skips active request locks. `cache list` and `cache prune` make retained
sensitive data visible and removable. Successful uploads retain only a small
receipt; no background daemon is introduced in v1.

Scanner stdout/stderr is streamed to bounded files rather than accumulated
without limit in process memory. Sibling scanner containers are read-only with
respect to the snapshot, carry a request-specific label/name, and are removed
on normal exit, signal handling and the next cache-prune/recovery pass. CLI
logs never print the host snapshot bind source, bearer token or unredacted
scanner output.

The shared scanner manifest supplies per-scanner user, read-only filesystem,
temporary filesystem, capability, `no-new-privileges`, network, timeout, CPU,
memory and cache/database policy. Cleanup selects the exact request label/name,
never a broad Compose label. Target-image scanning does not give the Docker
socket to the third-party Trivy container: the trusted outer orchestrator saves
the selected image to a bounded temporary archive and mounts that archive
read-only, recording the target image ID/digest.

Both SSH and HTTPS remotes normalize to the same `owner/repo` value:

```text
git@github.com:26457513/assurance-scan.git
https://github.com/26457513/assurance-scan.git
                     -> 26457513/assurance-scan
```

Do not upload the developer's absolute local filesystem path.

Release qualification records the exact Docker Desktop/Engine, OS and
architecture combinations exercised against the matrix above. An unqualified
combination fails `doctor` with an explicit unsupported/best-effort message;
it is never silently represented as tested.

## Project identity

Add `Run.project_id` as the mandatory foreign key to `Project.id` and use it as
the canonical identity for every run. During the one-time migration,
`Run.project_path` may be read only as an input to deterministic resolution;
it is removed at cutover after path-keyed catalogue and compliance data is
projected onto `project_id`. `CatalogueSnapshot`, `ComplianceMapping`,
`ComplianceMappingSnapshot` and `ProjectCheckout` likewise receive mandatory
project foreign keys and stop using `project_path` as identity; checkout paths
remain user-specific locator data only. Project pages and scan APIs join/filter
only by `project_id`; they never infer identity from a path, repository basename
or run-ID prefix.

Also add nullable `Project.github_repository_id`, populated from GitHub's
immutable numeric repository ID when a project is registered or polled. The
existing canonical spelling remains:

```text
github:{owner}/{repo}
```

The project migration also makes `Project.local_path` nullable: a GitHub-only
registered project does not have a meaningful server-local checkout. Preserve
the display spelling in `github_repo`, add a normalized lowercase
`github_repo_key` with a unique index, and make `github_repository_id` a unique
indexed `BIGINT` where non-null. Existing path-dependent catalogue, compliance,
version, trend, project-deletion and scan queries migrate to `project_id`
before nullable local paths are accepted. Project deletion remains a tombstone
operation and deletes/cascades run data by `project_id`, not by reconstructing
path aliases.

The local upload endpoint resolves the submitted `owner/repo` to a visible
`Project` and stores both its `Project.id` and canonical GitHub project path.
GitHub ingest performs the same resolution. A locally executed scan must not be
stored under `/Users/alice/code/repo`, because that creates a second logical
project and leaks machine-specific information.

The GitHub poller preserves the API repository's immutable numeric `id` and
current `full_name`, resolves a visible registered project before downloading
artifacts, and treats GitHub API run/revision data as authoritative. The shared
result bundle contains scanner status/findings/durations/artifacts only;
GitHub-specific repository, run URL, actor, event and revision fields move out
of the current `ci_payload()` body into a versioned GitHub provenance envelope.
Payload copies are validated against authoritative API data, never preferred
silently. The matching Actions workflow/image and server are promoted in the
same cutover.

The migration populates `Run.project_id` where a registered project's
`local_path` or `github_repo` matches. For existing derived `github:` runs, it
creates or resolves a non-hidden registry row using a collision-safe tag.
It refuses to complete while any retained run lacks a project ID.

The migration is deterministic and produces an audit report containing matched,
created, ambiguous and unresolved rows. It never guesses by repository
basename. Ambiguous normalized repositories or duplicate immutable GitHub IDs
abort the cutover for explicit operator resolution/export/drop rather than
silently selecting a project. Migration tests cover GitHub repository
rename/transfer, same-basename repositories, hidden tombstones and backup/
restore recovery.

The projection covers every project-scoped legacy path, not only the tables
named above: `Fr` derives its project through `CatalogueSnapshot`; `TestResult`,
`Evidence` and `FrState` derive it through `Run`; `Waiver` and
`FindingAcceptance` receive mandatory project IDs; `AgentAction` receives a
nullable project ID; and `ProjectCheckout` replaces `user_email/project_path`
with mandatory `user_id/project_id`. A run cannot reference a catalogue
snapshot owned by another project. The preflight also aborts on unmapped
checkout emails, hidden tombstones and conflicting current mappings.

Resolution rules:

1. A supplied `--project owner/repo` wins.
2. Otherwise parse and normalize `remote.origin.url`.
3. The API finds a visible `Project` by immutable GitHub repository ID when
   available, otherwise by normalized `github_repo`.
4. If no registry row exists, return `409 project_not_registered` with an
   onboarding URL. Do not silently create projects from an authenticated local
   upload in v1.

Repository names should be compared case-insensitively while preserving the
GitHub spelling returned by the registered project.

Forks are intentionally distinct projects. A developer whose `origin` points
to a personal fork uses `--project owner/upstream-repo` only when they are
deliberately uploading the checkout to the registered upstream project; the
override is included in audit metadata.

### Project authorization

Authentication alone is insufficient. After resolving the project, the ingest
endpoint must verify that the token's user can upload to it. The current
application has no tenant, membership or user-active model. The v1 rule is
therefore precise and explicitly single-tenant: any active authenticated `User`
row holding a non-expired,
non-revoked token with `scans:upload` may upload to any non-hidden, registered
project in this Assurance Scan instance. Hidden and unknown projects are
rejected. This rule lives in one authorization helper so a future tenant,
`ProjectMembership` or account-state policy can replace it without changing the
ingest contract.

`User.disabled_at` provides the v1 offboarding switch. A disabled user cannot
authenticate a scan token or create new tokens; disabling does not erase the
historical submitter audit reference.

## Run identity and provenance

Add explicit run provenance instead of inferring it from the run ID prefix.
The recommended migration adds these fields to `runs`:

```text
project_id              integer not null FK projects.id
origin                  varchar(24) not null
repository_full_name_at_scan varchar(256) null
git_object_format       varchar(8) null
working_tree_dirty      boolean null
source_content_hash     char(64) null
source_manifest_version varchar(64) null
submitted_by_user_id   integer null FK users.id
submitting_token_id    integer null FK api_tokens.id
payload_hash            char(64) null
client_provenance_json text null
```

`client_provenance_json` has a strict versioned contract and stores the
installation ID, CLI version, OCI build revision, Docker image ID, optional
resolved CLI registry digest, LFS/snapshot facts and explicit branch/project
override audit fields. Each `ScannerRun` gains its executed image reference,
manifest digest, tool version and optional database-version metadata. These
fields are returned only where the API/UI needs them; `options_json` is not the
new provenance system of record.

Branch storage is widened from the current 64 characters to 512 and the API
applies the same bound. Commit validation accepts lowercase SHA-1 only as 40
hexadecimal characters and SHA-256 only as 64 hexadecimal characters with the
matching `git_object_format` value.

Allowed origins initially are:

```text
github-actions | local | server
```

`source_content_hash` is required for local runs and distinguishes dirty working
trees at the same commit. The UI still labels dirty runs because reproducing one
requires the preserved content rather than the commit alone.

The hash is client-attested provenance: the server cannot independently verify
it because source code is intentionally not uploaded.

The migration must backfill provenance instead of allowing the new default to
mislabel history:

```text
run_id gh-* or options.source=github-actions -> github-actions
existing server queue/orchestrator runs      -> server, dirty state null unless proven
new authenticated uploads                    -> local
```

Run IDs remain globally distinct and are generated independently of the
client's idempotency key:

```text
gh-{github_run_id}
local-{uuid}
{existing server-generated id}
```

Use a dedicated `ingest_requests` table rather than overloading the globally
unique run ID:

```text
id, submitted_by_user_id FK users.id, client_request_id varchar(36),
project_id FK projects.id, payload_hash varchar(80), state, run_id FK runs.run_id,
lease_expires_at, created_at, updated_at
UNIQUE(submitted_by_user_id, client_request_id)
```

After streaming validation and payload hashing, ingestion atomically claims
this key. A completed matching claim returns the existing run; repository or
payload mismatch returns `409 idempotency_conflict`; an in-progress claim
with different repository/revision data does likewise. A matching in-progress
claim returns `202 idempotency_in_progress`, a status URL and `Retry-After`;
the five-minute lease is heartbeated and may be reclaimed only when no run was
committed.
The run ID is a separate server-generated `local-{uuid}` so two accounts using
the same client UUID cannot collide. Token rotation works because the claim is
bound to the user, while `submitting_token_id` remains immutable audit
provenance. Run, scanner rows, artifacts and findings commit together; no claim
is marked completed until that transaction succeeds. The outbox retains the
client request ID across restarts.

The header is an unquoted canonical lowercase UUIDv4 and must equal
`metadata.request_id`. A completed matching replay returns the original run
with `replayed: true`. Completed claims live with their run; after run deletion
a content-free tombstone rejects reuse with `410` for 30 days.

`payload_hash` is SHA-256 over canonical validated metadata plus the ordered
name/size/byte-hash tuple of every uploaded artifact and is stored on both the
claim and completed run.

Branch is metadata, not identity. The commit SHA identifies committed source;
`working_tree_dirty` and `source_content_hash` distinguish local
modifications. A detached HEAD is valid and stores a null branch unless the
user supplies `--branch`.

GitHub provenance stores both the API-reported head SHA and the checkout SHA
actually scanned, since pull-request merge runs can legitimately differ.
Historical server runs display working-tree state as `Unknown`; they are never
backfilled to clean merely because the legacy schema lacked the field.

## API

### Authentication

Introduce scan-upload tokens rather than treating Basic Auth or browser
cookies as CLI credentials. Add an `api_tokens` table containing:

```text
id UUID, user_id FK users.id, label, token_selector, token_hash BLOB(32),
scope, token_version, expires_at, created_at, last_used_at, revoked_at
```

Tokens have the form `asu_v1_<selector>.<random-secret>`. The selector is 12
random bytes and the secret is 32 random bytes, both unpadded base64url. The
unique indexed selector locates one row without scanning all token hashes; only a SHA-256 hash
of the high-entropy secret is stored and comparison is constant-time. The
plaintext is displayed once. The initial required scope is
`scans:upload`. The Settings UI lists token label, creation, expiry, last use,
and revocation state, but can never reveal the token again. Revocation takes
effect on the next API request. API tokens are soft-revoked, not hard-deleted,
so historical runs retain their submitting-token audit reference.

The secret contains at least 256 bits from a cryptographically secure random
source; the selector is independently random and non-secret. Authentication
uses the same generic `401` response for unknown selectors and invalid,
expired or revoked secrets, never logs the Authorization header, and applies a
per-origin/per-selector failure rate limit. Token creation returns
`Cache-Control: no-store`, `Pragma: no-cache` and `Referrer-Policy: no-referrer`.
Labels are NFKC-normalized, control-free, 1–64 characters and case-insensitively
unique among a user's active tokens. Expiry defaults to 90 days, the UI offers
30/90/180 days, the hard maximum is 365 days, and each user may hold five
active tokens. `last_used_at` updates are throttled to once per hour and
best-effort so every upload does not create unnecessary SQLite write
contention.

Unknown selectors perform the same dummy digest comparison as known selectors.
Malformed, unknown, expired, revoked and disabled-user credentials all receive
the same generic `401` with `WWW-Authenticate: Bearer`.

The label `laptop` is descriptive metadata, not proof that the bearer token is
being used by one physical machine. Anyone who copies a bearer token can use
it until it expires or is revoked. That is acceptable for the first release
when combined with narrow scope, strong random tokens, owner-only local
storage, expiry, last-used visibility, and easy revocation.

If cryptographic device binding becomes a requirement, replace bearer-only
enrollment with a one-time UI token: the CLI generates a local key pair,
redeems the one-time token to register the public key, and signs each upload.
Do not imply that a user-entered label or hardware fingerprint provides this
binding.

Add a small validation endpoint used before local storage:

```http
GET /api/v1/ingest/whoami
Authorization: Bearer asu_v1_...
```

It returns the account, token label, scopes and expiry. This prevents a typo,
wrong server URL or revoked token from being persisted as a successful login.

Use a FastAPI authentication dependency on every `/api/v1/ingest/*` route so token
validation is enforced even when browser/Basic Auth middleware is disabled.
Where global middleware would otherwise reject the request, it may allow an
ingest bearer request to reach the route, but the route dependency remains
authoritative. It validates format, hash, expiry, revocation and scope, updates
`last_used_at`, and supplies the user/token principal to project authorization.
The upload route accepts only this bearer dependency and never falls back to a
browser cookie, Basic credential, GitHub token, MCP token or global service
token. CORS remains same-origin/exact-allowlist and never combines wildcard
origins with credentials.
Do not broaden or migrate the existing MCP token. Scan upload receives its own
new token in the UI, and MCP/global tokens are never accepted by ingest.

Initial token management endpoints are required before CLI delivery:

```http
POST   /api/users/me/scan-tokens
GET    /api/users/me/scan-tokens
DELETE /api/users/me/scan-tokens/{id}
```

The creation response contains the plaintext once. Hosted Google-session users
are supported in v1. Basic-Auth-only deployments must either map the Basic user
to a real `User` row or explicitly disable account-bound token creation until
that mapping exists.

The v1 choice is to disable local-scan token management and local ingest in a
Basic-Auth-only or auth-off deployment. Basic Auth is an outer deployment gate,
not an account identity; it is never synthesized into a shared `User`. Enabling
the feature therefore requires Google-session account identity and a session
secret. Browser token-management requests use exact-origin validation plus a
signed double-submit `X-CSRF-Token` bound to the session for creation and
revocation. API-token foreign keys use restrictive/soft-delete semantics so
historical submitter and token audit records cannot be orphaned.

### Result upload

Add:

```http
POST /api/v1/ingest/local-scans
Authorization: Bearer asu_v1_...
Idempotency-Key: <request UUID>
Content-Type: multipart/form-data

metadata=<JSON>
findings=<findings.json>
sarif=<assurance.sarif, optional>
sbom=<sbom.cyclonedx.json, optional>
```

The request contains exactly one `metadata` and one `findings` part and at most
one `sarif` and `sbom` part. Unknown or duplicate parts, duplicate JSON keys,
unknown schema fields, excessive nesting and archives are rejected. Filenames
are ignored as authority; validated part names/content determine meaning.
Every limit is enforced while streaming/spooling, not only from
`Content-Length`.

Metadata:

```json
{
  "schema_version": 1,
  "request_id": "canonical-uuid-v4",
  "repository": "26457513/assurance-scan",
  "branch": "feature/local-scan",
  "commit": "0123456789abcdef...",
  "git_object_format": "sha1",
  "working_tree_dirty": true,
  "source_content_hash": "lowercase-sha256-hex",
  "source_manifest_version": "assurance-snapshot-v1",
  "installation_id": "random-local-uuid",
  "cli_version": "0.1.0",
  "cli_build_revision": "git-sha",
  "cli_image_id": "sha256:...",
  "cli_image_digest": null,
  "project_override": null,
  "scanner_image_digests": {
    "semgrep": "sha256:...",
    "gitleaks": "sha256:..."
  }
}
```

Success returns `201`; an idempotent retry returns `200`:

```json
{
  "run_id": "local-...",
  "project_id": 123,
  "repository": {
    "provider": "github",
    "full_name": "26457513/assurance-scan"
  },
  "run_url": "https://scan.example.com/scans/local-...",
  "status": "completed"
}
```

`metadata` and `findings.json` each have a checked-in JSON Schema identified by
`schema_version`. The contract defines required/optional fields,
permitted scanner kinds and statuses, artifact-to-scanner relationships,
maximum string/path lengths, normalized repository-relative paths, duplicate
scanner handling and whether unknown fields are rejected. JSON parsing rejects
duplicate object keys and excessive nesting. Multipart filenames are ignored;
the protocol part name and validated content determine meaning.

All ingest failures use `application/problem+json` with the RFC 9457 fields
plus stable application extensions:

```json
{
  "type": "https://scan.example.com/problems/project-not-registered",
  "title": "Project is not registered",
  "status": 409,
  "detail": "Human-readable summary",
  "instance": "/api/v1/ingest/local-scans",
  "code": "project_not_registered",
  "retryable": false,
  "request_id": "server-correlation-id",
  "limits": {}
}
```

The CLI retries only network failures, `408`, `429` (respecting `Retry-After`)
and selected `5xx` responses with bounded exponential backoff. Validation,
authorization, project and idempotency conflicts remain in the outbox but are
not automatically retried. Unsupported payload schema returns `422
unsupported_schema_version` with supported versions; `426` is reserved for a
server policy that requires a newer CLI release.

The stable status mapping is: `400` malformed/duplicate/missing idempotency;
`401` invalid, expired, revoked or disabled principal; `403` valid principal
without scope; `404` hidden/unauthorized project; `409` authorized but
unregistered repository or idempotency conflict; `413` byte limit; `415` media
type; `422` schema; `429` rate/concurrency; `507` retained storage; and `503`
feature disabled/capacity. Error bodies never echo token or payload content.

Set explicit upload limits and validate before inserting:

- authenticated token with `scans:upload` scope;
- known repository identity;
- `findings.json` schema version and bounded finding count;
- commit format and optional branch length;
- maximum size for each artifact;
- client metadata must not contain `origin`/`source`; the server assigns
  `local`;
- scanner kinds and statuses must use the same constraints as CI ingest.

Shipping configurable ceilings are 32 MiB total wire size, 64 KiB metadata,
10 MiB `findings.json`, 16 MiB SARIF, 16 MiB SBOM, 64 MiB parsed/decompressed
aggregate, 20,000 normalized findings, 32 scanner results and JSON depth 20.
Paths are at most 1,024 characters and messages 8,192; source snippets are not
accepted in v1. The 4.7 KiB checked-in scanner fixture is deliberately small,
so release qualification additionally records real-project p50/p95/max bundle
sizes without weakening these ceilings.

The server permits 10 upload attempts per token per hour and 100 per user per
day, with one in-flight request per token, two per user and four per instance.
Authentication failures are limited to 20 per IP and 10 per selector in ten
minutes; token creation is limited to five per user per hour. Retained raw
artifacts are capped at 1 GiB per user and 5 GiB per instance, with 500 MiB of
accepted upload bytes per user per day. `429` carries `Retry-After`; a request
that exceeds its byte ceiling returns `413`, while retained-storage exhaustion
returns `507 storage_quota_exceeded`. Database indexes cover token selectors,
ingest request claims,
`Run.project_id`, and scan-list access patterns `(project_id, started_at)`,
`(project_id, origin, started_at)` and `(project_id, commit_sha)`. Scan APIs use
stable cursor pagination rather than increasing the existing recent-run query
indefinitely.

Enforce total request size at the TLS proxy and application boundary, then
enforce per-part limits while streaming/spooling multipart data. A
`Content-Length` check alone is insufficient. Reject unsupported
`schema_version` with the machine-readable response above and advertise
supported versions from a small capabilities endpoint. Pinned CLI releases
therefore fail clearly rather than corrupting or silently dropping new fields.

```http
GET /api/v1/ingest/capabilities
```

Server-supplied metadata is authoritative: assign `local`, use the authenticated
principal for submitter identity, and reject conflicting repository, request or
revision data rather than silently rewriting it. A run is `completed` when the
orchestrator produced a valid bundle even if individual `ScannerRun` children
failed; it is `failed` when orchestration or bundle validation fails or no valid
scanner result is available. Apply the same rule to Actions and local ingestion.

For very large artifacts, direct object-storage uploads can replace multipart
later. The current application stores compressed artifacts in SQLite, so a
simple multipart request is consistent with the existing design.

## Data handling and redaction

The onboarding UI must state that source code is scanned locally, while the
normalized findings, SARIF and SBOM are uploaded. Those artifacts can still
contain file paths, dependency names, source snippets and secret material.
It must also disclose that third-party scanner containers have outbound network
access for rules and vulnerability databases; scanners must not receive the API
token or Git credentials.

Before enabling local upload:

- remove secret values and prefixes from the Gitleaks parser;
- strip or bound source snippets and environment-specific absolute paths from
  normalized findings and SARIF;
- never upload raw scanner stdout unless its format has a reviewed redactor;
- document server retention and deletion behavior;
- keep outbox/result files owner-only and delete them after confirmed upload;
- make `--no-upload` prominent for users who need a local-only review.

Redaction is defence in depth. The CLI redacts before writing the upload
bundle, and the server independently validates and re-redacts before any
artifact, normalized finding or error text is persisted. The same shared
redaction capability is applied to GitHub ingestion so the two origins do not
develop different disclosure rules. SARIF URIs and SBOM references are made
repository-relative where possible; source snippets are removed or tightly
bounded; secret matches retain only non-reversible fingerprints/locations
needed for deduplication. Scanner stderr is never persisted without a reviewed
redactor.

The API token, host path, hostname, hardware identifiers and Git credentials
must never enter results, logs or scanner-container environments. Tests should
scan fixtures containing canary secrets and assert that neither API payloads nor
logs contain the canaries.

Raw uploaded SARIF/SBOM/findings blobs are retained for 30 days; normalized
runs/findings for 365 days; and token audit metadata for 400 days after
revocation/expiry. Completed idempotency claims live with their run, followed
by the 30-day content-free tombstone described above. A run or project deletion
immediately hides it and rejects new access/upload, then purges blobs and
normalized findings within 24 hours while retaining only the minimal audit and
idempotency tombstone. Retention overrides are explicit, time-bounded and
audited—there is no implicit indefinite SQLite policy or unaudited legal hold
in v1. The scheduled cleanup job is idempotent, observable and tested.

## VibeGuide module architecture

The behavior-preserving structural refactor has established the VibeGuide
`atomic`, `workflows`, and `shared` parent packages. Before adding local-scan
behavior, WSQ completes the remaining dependency boundaries so the implemented
code matches the documented topology rather than merely matching its folder
names.

```text
backend/app/
  modules/
    atomic/
      access/
        scan_token/
          __init__.py
          models.py
          service.py
        project_authorization/
          __init__.py
          models.py
          service.py

      ingestion/
        bundle_validator/
          __init__.py
          models.py
          service.py
        finding_normalizer/
          __init__.py
          models.py
          service.py
        idempotency_guard/
          __init__.py
          models.py
          service.py
        result_persister/
          __init__.py
          models.py
          service.py

      provenance/
        repository_identity/
          __init__.py
          models.py
          service.py
        source_snapshot/
          __init__.py
          models.py
          service.py
        content_hasher/
          __init__.py
          models.py
          service.py

      scanning/
        scanner_catalog/
          __init__.py
          models.py
          service.py
        scanner_runner/
          __init__.py
          models.py
          service.py
          _adapters.py
        result_builder/
          __init__.py
          models.py
          service.py

      platform/
        docker_port/
          __init__.py
          models.py
          service.py
          _adapters.py
        outbox_storage/
          __init__.py
          models.py
          service.py
          _adapters.py
        upload_client/
          __init__.py
          models.py
          service.py
          _adapters.py

    workflows/
      github_scan_execution/
      github_result_ingest/
      local_result_ingest/
      local_scan_execution/
      token_enrollment/

    shared/
      contracts/
        ingest.py
        findings.py
        provenance.py
      errors.py
      hashing.py
      constants.py
```

The structure follows these dependency rules:

```text
API routes / CLI entrypoint
          ↓
       workflows
          ↓
    atomic modules
          ↓
        shared
```

- Atomic modules must not import workflows, API routes or CLI entrypoints.
- Workflows coordinate multiple atomic capabilities and own use-case sequencing.
- Shared contains only stable cross-module contracts and deterministic
  primitives; it must not become a miscellaneous helper directory.
- Database, Docker, filesystem and HTTP implementations sit behind atomic
  platform ports/adapters.
- Atomic `service.py` files contain domain/capability behavior and may depend
  only on their models, explicit ports and shared contracts; they do not import
  SQLAlchemy, FastAPI, concrete repositories or subprocess/network clients.
- Workflows receive ports/unit-of-work abstractions and do not reach into
  legacy `app.worker` implementations or concrete database repositories.
- Every atomic capability exposes its public API through `__init__.py`.
- `models.py` contains input/output contracts and domain types, not behavior.
- `service.py` contains the capability behavior.
- `_adapters.py` contains replaceable infrastructure implementations and is
  private to the module.
- Existing API routes and scripts become thin entrypoints into workflows.
- Old import paths are removed in the cutover. Callers and tests move in the
  same change; no compatibility-export layer remains.
- Do not copy unrelated `doc2context` concepts such as LLM ports or clearance
  decorators unless assurance-scan independently requires them.

Architecture tests parse imports and fail on reverse-layer dependencies,
atomic-to-infrastructure imports, workflow-to-legacy-worker imports, shared
framework dependencies and dependency cycles. Architecture tests also reject
the removed import roots so compatibility wrappers cannot reappear.

### Existing-code extraction map

The pre-feature architecture cutover maps the former code to these current
responsibilities:

| Existing code | Target responsibility |
|---|---|
| Removed `backend/app/ci_ingest.py` | `backend/app/modules/workflows/github_result_ingest/` plus atomic validator, normalizer, idempotency and persister modules |
| `backend/scripts/ci-scan.py` | Thin Actions entrypoint into `backend/app/modules/workflows/github_scan_execution/` and atomic result-building capabilities |
| Removed `backend/app/worker/sarif.py` | `backend/app/modules/atomic/scanning/result_builder/` and shared findings/ingest contracts |
| Removed `backend/app/worker/scanners.py` | `backend/app/modules/atomic/scanning/scanner_catalog/`; digest pinning remains a later feature workstream |
| Removed `backend/app/worker/runner.py` | `backend/app/modules/atomic/platform/docker_port/` |
| `backend/app/api/routes/projects.py` | Thin routes plus atomic repository identity and project authorization |
| Bearer logic in `backend/app/main.py` | Atomic scan-token service exposed through route dependencies |
| New `backend/scripts/local-cli.py` | Thin container entrypoint into `local_scan_execution` and `token_enrollment` workflows |

The common source-neutral ingest capability remains conceptually:

```text
ingest_result_bundle(unit_of_work, bundle, provenance, principal) -> run_id
```

It is composed from atomic modules by both workflows:

- `github_result_ingest` supplies `origin=github-actions`, `gh-{id}`, GitHub
  timestamps and run URL.
- `local_result_ingest` supplies `origin=local`, `local-{uuid}`, authenticated
  user, dirty state, source hash and CLI/scanner image digests.

This keeps finding normalization, scanner status creation, artifact storage and
transaction behavior identical between origins. The entire upload commits in
one database transaction. Invalid or partial uploads must not leave a completed
`Run` with missing findings. Idempotency lookup/insertion must be safe under
concurrent SQLite requests and must not return a run belonging to another user
or project.

## Frontend

Expose these fields from `backend/app/api/schemas/scan.py` and
`backend/app/api/routes/scans.py`:

```text
project_id
origin
working_tree_dirty
submitted_by
commit_sha (already present on detail; add to summary)
```

Update `frontend/src/lib/types.ts` and the project/scan views to show:

- `Local` or `GitHub Actions` origin badge;
- branch and short commit;
- a `Dirty working tree` warning for local modified-source scans;
- the GitHub run link only when origin is `github-actions`;
- uploader identity on scan detail where available.

The scans table must make origin a first-class column rather than relying on
run-ID prefixes or subtle badges. Its minimum row layout is:

| Origin | Branch | Commit | Working tree | Submitted by | Status/findings |
|---|---|---|---|---|---|
| GitHub Actions | `main` | `a84c913` | Clean | Workflow | Existing status/count |
| Local | `main` | `a84c913` | Dirty | `alice · laptop` | Existing status/count |
| Local | `feature/auth` | `e91d024` | Clean | `alice · workstation` | Existing status/count |

Add an origin filter with `All`, `Local`, and `GitHub Actions`, alongside the
existing project/branch selection. The token label is shown as the submitting
device label for local runs; it remains descriptive metadata, not proof of
cryptographic device binding.

Local and Actions runs are never rendered as separate projects. Within one
project, rows sharing a commit SHA should be visually related or offer a
`Compare origins` action. The comparison shows finding-count/status differences,
scanner-image digests, dirty state and source-content hash. A dirty local run at
the same commit must not be presented as source-equivalent to the clean Actions
run.

Even a clean local run is labelled “same commit” rather than “identical source”
unless both origins provide the same versioned source-content hash. LFS
hydration, submodule state and scanner database/network state can otherwise
produce legitimate differences. The comparison explains these limits instead
of implying false reproducibility.

Remove origin inference based on `run_id.startswith("gh-")` from
`backend/app/api/routes/scans.py`. Project pages should match scans by canonical
`project_id`, not by comparing only the final folder/repository name. Scan list
and detail responses require `project_id`; the migration must resolve or
explicitly remove every incompatible historical row before the application is
started.

Add scan-token creation, listing, and revocation to Settings. Token values are
shown only at creation.

WSQ first adds a maintained frontend test harness (component tests plus a small
browser-level smoke path). WS1/WS4 UI acceptance cannot rely only on
`svelte-check` and a successful bundle build.

## Delivery sequence

### WSR — VibeGuide structural foundation (substantially complete)

1. Capture the current GitHub ingestion, scanner payload, project registry,
   authentication and API behavior with characterization tests.
2. Create `backend/app/modules/atomic`, `backend/app/modules/workflows`, and
   `backend/app/modules/shared` with documented dependency rules.
3. Move contracts and deterministic transformations first, then platform
   adapters and workflow orchestration.
4. Move callers and tests directly to the new imports in the same cutover.
5. Keep structural/move commits separate from feature or schema changes.
6. Delete obsolete packages/wrappers and make repository-wide import checks
   reject their reintroduction.

Quality gate:

- no API, database schema, payload, normalized-finding or UI behavior changes;
- existing tests pass unchanged;
- extracted atomic modules have focused unit tests;
- GitHub CI payload fixtures remain byte/semantically equivalent as applicable;
- no circular dependencies or reverse imports from atomic/shared into workflows;
- no FastAPI, browser-session or database-session dependencies in shared;
- the extraction map and public module APIs are documented.

Acceptance: the existing application behaves identically, while GitHub ingest
and scanner execution enter through thin workflows composed from independently
testable atomic modules. Local-scan development can add adapters/workflows
without duplicating existing behavior.

WSR created the target folders and extracted the first capabilities. Its final
boundary checks are deliberately completed in WSQ; folder placement alone does
not satisfy acceptance.

### WSQ — repository hardening and quality-gate closure

1. Move concrete SQLAlchemy/repository use out of atomic services and behind
   private adapters/ports; give ingest workflows an explicit unit-of-work port.
2. Extract/adapt parser and tribal-check behavior so workflows no longer import
   legacy `app.worker` implementations.
3. Expand static architecture tests to enforce every documented layer rule and
   prevent removed import roots or compatibility wrappers from reappearing.
4. Add migration dry-run/forward-projection and backup/restore tests using a
   copied representative DB, then add a deterministic local/CI quality gate.
5. Add the frontend component-test harness, resolve dependency compatibility
   notices, and make check/build warning-free.
6. Pin the CI quality environment, Semgrep image/config and all external Actions.
7. Run and record the entire clean baseline before creating feature migrations.
8. Review and commit the structural/hardening baseline separately from all
   local-scan feature work, preserving an independently reversible checkpoint.

Mandatory gate:

```text
Ruff                              0 findings
Mypy                              0 errors
Backend pytest                    all tests pass (currently 330)
Architecture tests                all dependency rules pass
Schema/fixture validators         pass
Migration dry-run/upgrade          pass on empty and representative copied DBs
Backup/restore rollback            restores the matching pre-cutover stack
Semgrep                           0 findings and 0 processing errors
Frontend diagnostics/tests        0 errors and 0 warnings
Frontend dependency audit         0 known vulnerabilities
Frontend production build         pass without compatibility notices
Python compile + shell syntax      pass
Dockerfile/Compose validation      pass
Existing app/CI image smoke tests  pass
git diff --check                  pass
```

The gate is implemented as one version-controlled command used by both local
development and CI. Suppressions must be narrow, rule-specific and justified
next to the code; there is no baseline file for unexplained findings. Generated
content and an unavoidable parser exclusion may use an explicit alternative
check documented by the gate.

Acceptance: the repository is fully green, architecture rules are enforced by
tests, migrations are recoverable, and the same gate runs locally and in CI.
Only then may WS0/WS1 feature work begin.

WSQ verification on 2026-08-28: the version-controlled gate passed with Ruff
clean, Mypy clean across 158 files, 324 backend tests, 15 Semgrep rules across
301 targets with zero findings, seven frontend tests, zero frontend diagnostics
or dependency advisories, clean production and container builds, both image
smokes, migration/backup/restore checks, and source hygiene across 520 files.
The structural checkpoint was reviewed and committed as `7fc8e40` before WS0
contract work began.

### WS0 — contracts and threat model

1. Check in the locked v1 metadata/findings schemas and exact multipart/error
   contract described above.
2. Add canary-secret, oversized, duplicate-key, path-leak, idempotency and
   incompatible-version fixtures before changing persistence.
3. Encode the selected token, Basic/Auth-off, CSRF, rate, concurrency, quota,
   retention, deletion and single-tenant project authorization decisions as
   constants/config contracts with boundary tests.
4. Check in the initial scanner release-set manifest and validate both required
   platform manifests, tool versions, vendored policy digest and database-age
   policy.
5. Record real-project bundle measurements and the exact release qualification
   OS/Docker versions without relaxing the approved ceilings.

Acceptance: security, product and engineering agree what leaves the laptop,
who may upload it, how long it persists, how abuse is bounded, which platforms
are supported, and how old clients are rejected with an upgrade path. Decisions
are checked into this plan; none remain as “implementation must choose”
branches.

WS0 verification on 2026-08-28: the v1 metadata and source-neutral findings
schemas, valid/adversarial fixtures, shared limits/retention/token constants and
the initial scanner release-set (including both platform digests) are checked
in. Contract, duplicate-key, oversized, incompatible-version and path-leak
tests pass. The canary-secret fixture is intentionally schema-valid and becomes
the mandatory redaction test vector in WS2. Release promotion remains gated on
recording exact qualified OS/Docker versions and real-project bundle
measurements; those observations cannot change the locked ceilings silently.

### WS1 — identity, provenance and token lifecycle

1. Add nullable `Project.local_path`, normalized/immutable GitHub identity,
   `Run.project_id`, provenance, per-scanner image metadata, `ingest_requests`
   and API-token migrations, including deterministic audited backfills.
2. Add token repository/service helpers, route-level scoped bearer
   authentication and project authorization.
3. Ship the minimum Settings UI and API for token creation, one-time display,
   listing and revocation.
4. Migrate runs, catalogue/compliance records, checkout mappings, deletion and
   scan list/detail queries to indexed mandatory `project_id`; add canonical
   GitHub repository parsing/resolution and remove path-identity columns.
5. Replace scan API responses and frontend types atomically with required
   `project_id`, `origin`, commit and provenance fields, behind a
   disabled-by-default local-ingest feature flag.

Acceptance: a user can create/revoke a labelled token, and GitHub and synthetic
local runs for the same repository resolve to one `Project.id`, with origin and
branch independently visible.

WS1 verification on 2026-08-28: migration `0021` performs a deterministic,
forward-only identity preflight and removes persisted path identity across the
project-scoped graph. GitHub resolution uses immutable repository IDs first and
the normalized full name only as a bootstrap key. Scan APIs, MCP tools,
workflow templates and the frontend use mandatory numeric `project_id`; local
checkout paths remain locators only. Labelled scan-upload tokens use one-time
`asu_v1` plaintext, stored secret digests, scoped bearer authentication,
expiry/revocation/disabled-user enforcement, an active-token limit, exact
origin plus signed double-submit CSRF for browser mutation, and a Settings UI.
The scan table renders explicit GitHub Actions, Local and Server origins and
branch provenance. A boundary test proves synthetic local and GitHub runs for
the same repository share one project ID. `LOCAL_INGEST_ENABLED` defaults to
false. The WS1 quality gate passed: Ruff, Mypy (169 files),
396 backend tests, schema fixtures, compilation, shell syntax, Semgrep (15
rules, 317 targets, zero findings), frontend audit/check/15 tests/build,
Dockerfile/Compose validation, both image builds and entrypoint/import smokes,
diff whitespace and source hygiene.

### WS2 — source-neutral, atomic ingest API

1. Generalize the existing port-driven `github_result_ingest` composition into
   a source-neutral ingest workflow shared by explicit GitHub and local
   adapters; replace the GitHub-specific workflow name in the same cutover.
2. Add `/api/v1/ingest/local-scans`, capabilities and whoami endpoints with strict
   versioned schemas, uniform errors and streaming application/proxy limits.
3. Add durable leased idempotency claims, client/server redaction, rate/storage
   quotas, schema negotiation and atomic rollback tests.
4. Cut the GitHub poller over to registered-project resolution, immutable
   repository IDs and the source-neutral bundle plus GitHub provenance envelope.

Acceptance: an authenticated fixture bundle creates one local run, scanner
runs, artifacts, and findings; resubmitting the same idempotency key creates
nothing new.

Completed in WS2. GitHub and local adapters now share the source-neutral
`result_ingest` workflow, while `local_scan_ingest` coordinates registered
project resolution, the explicit single-tenant authorization rule, serialized
quota reservation, fenced leased claims and one-transaction graph/claim
persistence. The authenticated capabilities, whoami, multipart upload and
request-status endpoints use uniform problem details, streamed application
limits and a validated Caddy hard cap. Payload, rate, concurrency and retained
storage ceilings can only be configured downward. Failed bearer attempts and
token creation are bounded; redaction runs before either GitHub or local data
is persisted; Gitleaks secret prefixes are no longer copied into findings.

Migration `0022_local_ingest_claims` adds token/byte attribution, random lease
fencing and 30-day content-free tombstones. Manual deletion and the observable
six-hour cleanup loop share the tombstone transition; raw artifacts retain for
30 days, normalized runs for 365 days, and unreferenced inactive token audits
for 400 days. End-to-end tests prove that a valid authenticated fixture creates
exactly one local run, claim, scanner graph, artifact and finding, while replay
returns that run without duplicates. The complete WS2 gate passed: Ruff, Mypy
(188 files), 446 backend tests, schema fixtures, compilation, shell syntax,
Semgrep (15 rules, 336 targets, zero findings), frontend audit/check/15 tests/
build, Dockerfile/Compose/Caddy validation, both image builds and smokes,
tracked-diff whitespace and source hygiene (575 text files).

### WS3 — public container CLI

1. Add `backend/Dockerfile.cli` with Git and implement container-based
   config/auth, Git metadata detection, Docker preflight, immutable snapshot
   creation, scanner execution, persistent outbox/retry, and multipart upload.
2. Replace mutable scanner tags with a shared pinned image manifest, then
   publish `stable`, immutable version, and Git-SHA CLI tags; record the CLI OCI
   identity, optional resolved registry digest and scanner manifest digests in
   each upload.
3. Add `--no-upload`, detached-HEAD support, actionable Docker errors, and
   bounded streaming, mutation/disk checks, signal-safe scanner cleanup and
   cleanup of temporary results.
4. Add a tested multi-architecture (`linux/amd64`, `linux/arm64`) release
   workflow with SBOM, provenance, signing, and promotion of a passing version
   to `stable`; verify every pinned scanner image on both architectures.

Acceptance: on a clean checkout and a dirty feature branch, one command runs
the auto-updating public container and each result appears under the existing
GitHub project with correct provenance. Re-running without a new release reuses
the local image layers; publishing a new stable release updates on the next
run. Killing the CLI after server commit and before response can be recovered
from the outbox without rescanning or duplicating the run.

Completed on 2026-08-28. The public CLI is composed from atomic config,
enrollment, Git metadata, immutable snapshot, scanner runtime, outbox and HTTP
upload capabilities plus the `local_scan_execution` workflow and a thin
container entrypoint. It validates a copied token before an owner-only atomic
save; preserves a non-secret installation ID; normalizes GitHub SSH/HTTPS
remotes; handles detached/dirty branches; creates bounded mutation-checked
snapshots; executes request-labelled pinned scanners with bounded files and
signal-safe cleanup; redacts before outbox persistence; and retries the exact
request bundle with request-status recovery after response loss.

The CLI and Actions paths consume one content-addressed six-scanner release
manifest and vendored Semgrep policy. `backend/Dockerfile.cli` builds the
server-free public image. The release workflow gates version tags, verifies
both scanner and CLI architectures, produces SBOM/provenance attestations,
keyless-signs the tested digest, verifies anonymous pull and promotes `stable`
by digest retag without rebuilding. User login, scan, retry and cache commands
are documented in the README. The final VibeGuide gate passed Ruff, Mypy (220
source files), 500 backend tests, schema/compile/shell checks, Semgrep (15 rules,
371 targets, zero findings), frontend audit/check/15 tests/build, Dockerfile and
Compose validation, all three image builds/smokes, diff whitespace and
source hygiene (622 text files).

### WS4 — UI and onboarding

1. Add origin/dirty badges and commit display.
2. Complete token audit/expiry presentation started in WS1.
3. Add the Origin column/filter and same-commit local-versus-Actions comparison.
4. Add platform-specific copyable login/scan instructions to project setup.
5. Document token revocation, uploaded-data retention and local outbox cleanup.

Acceptance: a new user can go from the project page to a visible local scan
without manually constructing Docker or HTTP commands. In the scans table they
can immediately distinguish Local from GitHub Actions, filter by origin, and
compare runs for the same branch/commit without seeing duplicate project rows.

Completed on 2026-08-28. The project scan view now presents explicit Local and
GitHub Actions origin badges and filtering, branch and short/full commit
provenance, dirty-working-tree state, and an accessible same-commit comparison
that opens either run while remaining scoped to the existing numeric project.
Token management presents the server audit contract, including upload scope,
created/expiry/last-used/revoked timestamps, authoritative lifecycle state and
a near-expiry warning, with owner-confirmed revocation and one-time secret
handling.

Setup now contains a copyable token-to-first-scan runbook using the current
instance origin and exact hardened public-container commands for supported
macOS and Linux hosts. It also covers automatic image update checks, retry and
outbox cleanup, revocation/logout, upload boundaries, scanner networking and
the 30/365/400-day server retention policy; project registration links directly
to that flow and explains the shared local/Actions identity. A visual breakpoint
check exposed and fixed the application shell at phone width by collapsing the
sidebar without losing navigation labels. The final VibeGuide gate passed Ruff,
Mypy (220 source files), 500 backend tests, schema/compile/shell checks, Semgrep
(15 rules, 377 targets, zero findings), frontend dependency audit, zero Svelte
diagnostics, 23 frontend tests and production build, Dockerfile/Compose
validation, all three image builds/smokes, diff whitespace and source hygiene
(628 text files).

### WS5 — staged rollout and operations

Implementation completed on 2026-08-28. Token creation and local ingest now
fail closed behind independent global and canary allowlist controls; disabled
token creation still permits recovery-safe listing and revocation. The HTTP and
retention paths emit bounded JSON operational signals containing only
allowlisted machine codes, timings and counts, with tests proving that secrets,
host paths, repositories and account identities are absent. The Setup UI shows
the effective token-creation rollout state instead of inviting a request that
the server will reject.

Recoverable SQLite operator tooling now provides read-only identity/schema/
retention preflight, verified online backup plus manifest, backup verification,
and guarded dry-run/execute restore with fresh stopped-writer evidence, exact
digest-bound confirmation, race checks and a recoverable original copy. App and
CI workflows publish signed, attested immutable candidates without changing
`latest` or deploying; CLI canary and stable promotion use the same tested
digest with evidence and stale-baseline gates. The operator runbook ties the
matching app/CI/CLI digest set to maintenance, canary, monitoring, kill-switch,
cleanup and rollback procedures.

The repository implementation and full quality gate are complete. Production
backup/migration/deployment, public candidate publication, macOS/Linux canary
qualification, stable promotion and a real recovery exercise remain explicitly
pending the reviewed maintenance window. Until those actions are performed and
their sanitized evidence is recorded, the operational acceptance criterion
below is not claimed as complete.

1. Enter a maintenance window, stop writers, take and verify a database backup,
   run the migration dry-run, resolve every ambiguity, apply the clean-cutover
   migration and deploy the matching server/frontend/GitHub contract together.
   Rollback restores the backup and complete previous application set.
2. Keep local ingest/token creation disabled while verifying projected counts,
   required foreign keys, removed legacy columns and indexes; then enable token
   management for administrators/test users and ingest for a canary project.
3. Enforce rate/storage limits and retention cleanup during the canary, then
   publish immutable CLI/CI digests, verify public pull/signature/provenance and
   run automated plus manual macOS/Linux end-to-end scans.
4. Promote the already tested digest to `stable`, monitor authentication
   failures, upload rejection reasons, bytes, redaction counts, ingest latency,
   idempotency conflicts/retries and cleanup failures.
5. Document the kill switch, rollback, token revocation, cache cleanup and
   server artifact deletion procedures.

Acceptance: the feature can be disabled without reverting migrations, canary
and stable digests are identical, operational signals contain no secrets or
host paths, and rollback/recovery has been exercised.

## Tests

Add or extend:

- Architecture tests: enforce `entrypoints -> workflows -> atomic -> shared`,
  reject circular/reverse imports, atomic concrete-infrastructure imports,
  workflow legacy-worker imports, and ensure shared modules remain free of
  FastAPI and database-session dependencies.
- Characterization fixtures: pre-refactor and post-refactor GitHub payloads,
  findings, scanner statuses and project responses remain equivalent.
- `backend/tests/phase1/test_ci_ingest.py`: the cutover GitHub adapter produces
  the new mandatory project/provenance contract.
- `backend/tests/phase1/test_local_ingest.py`: auth, identity, branch, dirty state,
  findings/artifacts, unknown/unauthorized project, limits, exact supported
  schema version and explicit rejection of old/unknown versions,
  concurrent idempotency and rollback.
- `backend/tests/phase1/test_project_registry.py`: local-upload and GitHub runs fold
  into the same registered project without basename guessing, including rename,
  transfer and same-basename repositories.
- Migration tests: empty and copied representative databases dry-run and
  upgrade; historical GitHub origins/project IDs, nullable project checkout
  paths, repository transfers and tombstones resolve correctly; ambiguous or
  unresolved rows abort the cutover. Backup restoration is verified with the
  matching pre-cutover application version.
- Token tests: selector lookup, constant-time secret verification, ownership,
  scope, expiry, revocation, last-used audit and Basic-Auth-only behavior.
- CLI unit tests: SSH/HTTPS remote normalization, detached HEAD, dirty state,
  forks/override audit, canonical snapshot hashing, ignored/untracked files,
  Git LFS, symlinks/submodules, source mutation, free-space/size bounds, config
  precedence, TLS/redirect behavior, token/path redaction and outbox retry.
- CLI integration test with a stub HTTP server and mocked Docker executable,
  including server-commit/response-loss recovery and source mutation during the
  scan.
- Payload redaction tests containing canary secrets and absolute host paths.
- Streaming/abuse tests: chunked requests without `Content-Length`, per-part and
  total limits, excessive JSON depth, duplicate keys, rate/concurrency/storage
  quotas, stale idempotency leases and response-loss recovery.
- Container smoke tests on `linux/amd64` and `linux/arm64`, including paths with
  spaces, Docker socket access, host-owned cache files and pinned scanner pulls.
- Frontend tests: one project containing local and Actions runs renders one
  project identity, explicit origin cells, origin filters, device labels, dirty
  warnings and a same-commit comparison without basename matching.
- Release tests: the reusable Actions workflow and local CLI consume the same
  immutable scanner manifest; promoted `stable` is the tested digest; GHCR is
  anonymously pullable and SBOM/provenance/signature verification succeeds.

An automated compose/stub end-to-end test and one manual qualified-platform
test should scan this repository from a feature branch,
upload it, and confirm that both its GitHub Actions and local runs appear under
the same project and remain filterable by branch and origin.

## Explicit non-goals for the first release

- Running scans on a machine without Docker.
- Uploading the heavy full report produced by `backend/scripts/run-local.sh`.
- Automatically creating projects from arbitrary local uploads.
- Failing builds or local commands because findings exist.
- Reproducing external scanner database/network state beyond the recorded CLI
  and scanner image digests.
- Replacing GitHub polling with push ingest.
