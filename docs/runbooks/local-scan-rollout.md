# Local scan rollout and rollback

Status: operator procedure. This document does not assert that a production
rollout, public package publication, signature, canary, or platform
qualification has occurred.

Use this runbook for the first local-ingest cutover and subsequent CLI stable
promotions. The database migrations are forward-only. Application rollback
therefore restores the matching pre-migration database backup; it does not run
an Alembic downgrade.

## Evidence and safety rules

- Schedule a maintenance window and name one release operator, one reviewer,
  and one rollback operator.
- Record immutable application and CLI digests, not mutable tags. Never paste a
  token, `.env`, database, scanner output, absolute workstation path, or raw log
  into an Actions input, issue, or release note.
- GitHub evidence inputs must be sanitized URLs under this repository. Manual
  evidence records contain OS/architecture, Docker version, CLI version,
  candidate digest, request ID, expected outcome, and pass/fail only.
- Configure required reviewers on the `cli-stable` GitHub environment before
  using the promotion job.
- Keep `LOCAL_INGEST_ENABLED=false` until the database, matching server image,
  and one-account canary are ready.

Create a private operator record with at least:

```text
window_start_utc:
operator:
reviewer:
previous_app_digest:
candidate_app_digest:
candidate_app_revision:
candidate_app_build_run_url:
candidate_ci_digest:
candidate_ci_revision:
candidate_ci_build_run_url:
previous_cli_stable_digest:
candidate_cli_digest:
candidate_version:
database_backup_checksum:
identity_preflight_summary:
cli_tag_build_run_url:
macos_evidence_url:
linux_evidence_url:
rollback_decision_deadline_utc:
```

Do not store this record in a public issue if it contains infrastructure names
or paths. Publish only a sanitized evidence comment for workflow inputs.

## 1. Build the immutable matching release set

1. Confirm the release commit passed the repository quality gate and the
   application/CI/CLI/scanner release set is the intended matching set.
2. On `main`, the `publish-app-image` and `publish-ci-image` workflows build
   immutable `sha-<full revision>` candidates. Each must attach SBOM and SLSA
   provenance and keyless-sign the digest. The private app candidate must be
   verified with registry authentication; the public CI candidate must also be
   anonymously retrievable. The CI workflow moves both `candidate` and the
   user-facing `latest` tag to the verified digest without rebuilding. The app
   workflow changes only `candidate`; neither workflow deploys the application.
3. Record each workflow URL, full source revision, and immutable app/CI digest.
   Verify the chosen revisions contain the intended matching scanner release
   set and API contract. Mutable `candidate` and `latest` tags are discovery
   and convenience metadata only; use the digest in rollout records and pinned
   repository workflows.
4. Push one canonical CLI tag such as `v1.2.3`. Do not reuse or move a release
   tag. The `publish-cli-image` tag workflow must:
   - build `linux/amd64` and `linux/arm64` once;
   - attach SBOM and SLSA provenance;
   - keyless-sign the resulting index digest;
   - verify anonymous public retrieval, both platform manifests, signature,
     attestations, and architecture smokes;
   - move `canary` to that exact verified digest without rebuilding;
   - leave `stable` unchanged.
5. Record the CLI workflow URL, immutable digest, and summary. A workflow that
   fails any step is not a candidate. Do not open the maintenance window until
   the reviewer has approved the complete app/CI/CLI digest tuple.

The tag workflow's architecture smokes are automated evidence, not a substitute
for the host-level Docker Desktop/Engine qualification below.

## 2. Stop writers and take the cutover backup

Announce the maintenance window. Stop the application before copying SQLite so
GitHub polling, browser writes, MCP writes, and local ingestion are all fenced:

```bash
docker compose stop server
```

Resolve and record the exact Compose data volume. Do not guess a volume or use a
wildcard in backup/restore commands:

```bash
docker compose config --volumes
docker volume inspect EXACT_ASSURANCE_DATA_VOLUME >/dev/null
```

Set these shell variables to values already recorded by the operator. Do not
enable shell tracing:

```bash
set +x
umask 077
export DATA_VOLUME=EXACT_ASSURANCE_DATA_VOLUME
export PREVIOUS_APP_REF='ghcr.io/26457513/assurance-scan-app@sha256:...'
export CANDIDATE_APP_REF='ghcr.io/26457513/assurance-scan-app@sha256:...'
export CANDIDATE_CI_REF='ghcr.io/26457513/assurance-scan-ci@sha256:...'
export CANDIDATE_CLI_REF='ghcr.io/26457513/assurance-scan-cli@sha256:...'
export ROLLOUT_EVIDENCE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/assurance-rollout.XXXXXX")"
export CUTOVER_TOOL=/opt/assurance-scan/backend/scripts/local-cutover.py
chmod 700 "$ROLLOUT_EVIDENCE_DIR"
```

Validate each digest before continuing:

```bash
case "$PREVIOUS_APP_REF$CANDIDATE_APP_REF$CANDIDATE_CI_REF$CANDIDATE_CLI_REF" in
  *[!A-Za-z0-9./:@_-]*) exit 2 ;;
esac
docker image inspect "$PREVIOUS_APP_REF" >/dev/null
docker buildx imagetools inspect "$CANDIDATE_APP_REF" >/dev/null
docker buildx imagetools inspect "$CANDIDATE_CI_REF" >/dev/null
docker buildx imagetools inspect "$CANDIDATE_CLI_REF" >/dev/null
```

Run the candidate's cutover preflight against the stopped database. The command
opens SQLite in read-only mode, runs integrity and foreign-key checks, records
the schema revision and safe row counts, performs a retention dry run, and
reuses the deterministic 0021 identity preflight when the database is at
revision `0020_snapshot_source_branch`. Its report can contain private local
paths, so keep it in the operator directory:

```bash
docker run --rm --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" preflight --database /data/db.sqlite \
  > "$ROLLOUT_EVIDENCE_DIR/cutover-preflight.json"
chmod 600 "$ROLLOUT_EVIDENCE_DIR/cutover-preflight.json"
```

Stop if `database.integrity` is not `ok`,
`database.foreign_key_violations` is non-zero, or `identity_cutover.status` is
`blocked`. At revision 0020, identity status must be `ready`; at a later schema
it is `not-applicable`. If the database is older than revision 0020, stop and
exercise the intermediate upgrade to 0020 on a verified copy before changing
production. Review the private blocker report rather than inferring identity
from a repository basename.

Create the backup through SQLite's online backup API. Both destination paths
must be new, explicit absolute paths inside the private evidence mount. The
tool verifies source and backup integrity, foreign keys, size and SHA-256,
records the matching application reference and schema revision, atomically
publishes each artifact, and makes the backup and manifest owner-read-only:

```bash
docker run --rm --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" backup \
  --database /data/db.sqlite \
  --backup /evidence/db.sqlite.pre-cutover \
  --manifest /evidence/db.sqlite.pre-cutover.json \
  --application-revision "$PREVIOUS_APP_REF" \
  > "$ROLLOUT_EVIDENCE_DIR/backup-create-report.json"
chmod 600 "$ROLLOUT_EVIDENCE_DIR/backup-create-report.json"

docker run --rm --read-only \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" verify-backup \
  --backup /evidence/db.sqlite.pre-cutover \
  --manifest /evidence/db.sqlite.pre-cutover.json \
  > "$ROLLOUT_EVIDENCE_DIR/backup-verify-report.json"
chmod 600 "$ROLLOUT_EVIDENCE_DIR/backup-verify-report.json"
```

Record `backup_sha256` from the verified manifest as
`database_backup_checksum`. Copy both the backup and its manifest to encrypted
off-host storage according to the deployment's backup policy before applying
migrations. The manifest is verification metadata, not encryption and not a
substitute for the off-host copy.

## 3. Run deterministic preflight and apply migrations

Use the verified `cutover-preflight.json`, backup manifest and
`backup-verify-report.json` produced in section 2. Resolve/export/drop any
specific ambiguous data reported by identity preflight, then rerun preflight
and create a new backup/manifest pair; never reuse a report or guess by
repository basename.

With writers still stopped and `LOCAL_INGEST_ENABLED=false` in `.env`, apply
the matching migration set exactly once:

```bash
docker run --rm \
  --env-file .env \
  -e ASSURANCE_SCAN_DB_PATH=/data/db.sqlite \
  -v "$DATA_VOLUME:/data" \
  -w /opt/assurance-scan/backend \
  --entrypoint /opt/venv/bin/alembic "$CANDIDATE_APP_REF" \
  -c /opt/assurance-scan/backend/alembic.ini upgrade head
```

Do not start an older server against the migrated database.

## 4. Deploy the matching server with ingest disabled

Tag the already-pulled immutable application digest to the Compose image name;
do not rebuild on the host:

```bash
docker image tag "$CANDIDATE_APP_REF" ghcr.io/26457513/assurance-scan-app:latest
docker compose up -d --no-deps --pull never server
```

Confirm the running container image ID/digest matches the operator record, the
health endpoint succeeds, the migration head is current, existing GitHub scans
remain visible, and local-ingest capabilities return the documented disabled
response. Do not enable the canary if any existing project/run count or origin
breakdown is unexpected.

## 5. Verify release-set evidence

Authenticate to GHCR and verify the private application candidate first:

```bash
docker login ghcr.io
docker buildx imagetools inspect "$CANDIDATE_APP_REF"
cosign verify "$CANDIDATE_APP_REF" \
  --certificate-identity 'https://github.com/26457513/assurance-scan/.github/workflows/publish-app-image.yml@refs/heads/main' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect "$CANDIDATE_APP_REF" \
  --format '{{ json .SBOM.SPDX }}' > "$ROLLOUT_EVIDENCE_DIR/app-sbom.json"
docker buildx imagetools inspect "$CANDIDATE_APP_REF" \
  --format '{{ json .Provenance.SLSA }}' > "$ROLLOUT_EVIDENCE_DIR/app-provenance.json"
```

BuildKit attaches its generated SBOM and provenance to the platform manifest;
they are not separately published Cosign attestations. Confirm that the saved
SBOM has `SPDXID: SPDXRef-DOCUMENT` and a non-empty `packages` array, and that
the provenance has a non-empty `buildDefinition.buildType` and
`runDetails.builder.id`. Compare its `build-arg:REVISION`,
`build-arg:VERSION`, and builder identity with the recorded application build.

Then remove cached GHCR credentials and prove that CI and CLI are public:

```bash
docker logout ghcr.io
docker buildx imagetools inspect "$CANDIDATE_CI_REF"
docker buildx imagetools inspect "$CANDIDATE_CLI_REF"
cosign verify "$CANDIDATE_CI_REF" \
  --certificate-identity 'https://github.com/26457513/assurance-scan/.github/workflows/publish-ghcr.yml@refs/heads/main' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
docker buildx imagetools inspect "$CANDIDATE_CI_REF" \
  --format '{{ json .SBOM.SPDX }}' > "$ROLLOUT_EVIDENCE_DIR/ci-sbom.json"
docker buildx imagetools inspect "$CANDIDATE_CI_REF" \
  --format '{{ json .Provenance.SLSA }}' > "$ROLLOUT_EVIDENCE_DIR/ci-provenance.json"
cosign verify "$CANDIDATE_CLI_REF" \
  --certificate-identity-regexp '^https://github.com/26457513/assurance-scan/.github/workflows/publish-cli-image.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
for platform in linux/amd64 linux/arm64; do
  suffix=${platform//\//-}
  docker buildx imagetools inspect "$CANDIDATE_CLI_REF" \
    --format "{{ json (index .SBOM \"$platform\").SPDX }}" \
    > "$ROLLOUT_EVIDENCE_DIR/cli-sbom-$suffix.json"
  docker buildx imagetools inspect "$CANDIDATE_CLI_REF" \
    --format "{{ json (index .Provenance \"$platform\").SLSA }}" \
    > "$ROLLOUT_EVIDENCE_DIR/cli-provenance-$suffix.json"
done
```

Apply the same structural and recorded-build comparisons to the CI evidence
and to both CLI platform files. The automated candidate workflows perform
these checks in full; this independent inspection proves the recorded rollout
references still expose that evidence before deployment or promotion.

Before expanding the cohort, pin every CI workflow participating in this
release to `CANDIDATE_CI_REF`; do not consume `candidate` or `latest`. Confirm
the deployed application digest and the CI/CLI digests exactly match the
reviewed tuple in the private operator record.

Verify the immutable version tag and `canary` both resolve to the recorded
candidate digest. Do not use `stable` for qualification.

## 6. Enable and qualify the canary

Edit `.env` to set `LOCAL_INGEST_ENABLED=true`, retain the complete Google
session configuration, and restart only the candidate server:

```bash
docker compose up -d --no-deps --pull never --force-recreate server
```

Create one short-lived upload token for a dedicated canary account/machine and
one registered test repository. The token is entered only at the CLI hidden
prompt. Run the copyable Setup commands with the image reference changed from
`stable` to the recorded candidate digest.

Capture both automated and manual evidence:

| Evidence | Required checks |
|---|---|
| Automated tag workflow | quality gate, public pull, signature, SBOM, provenance, amd64/arm64 manifest and smoke |
| Supported macOS host | login, clean scan, dirty scan, upload, same project ID as GitHub, branch/commit/dirty provenance, retry after response loss, cache prune |
| Supported Linux host | the same checks using the qualified Docker Engine/architecture |
| Server boundary | invalid/revoked token, oversized/invalid schema, duplicate request, redaction canary, quota response, no partial run after injected failure |

Native Windows and WSL 2 are unsupported in v1 and are not qualifying evidence.
Record Docker/OS/architecture versions and pass/fail, but never scanner payloads,
tokens, host paths, or raw logs. Put sanitized evidence in GitHub Actions runs or
issue comments under this repository so the promotion workflow can validate the
URL shape.

## 7. Promote the exact canary digest

Before dispatch, record the current stable digest:

```bash
docker buildx imagetools inspect \
  ghcr.io/26457513/assurance-scan-cli:stable \
  --format '{{.Manifest.Digest}}'
```

Run `publish-cli-image` manually with:

```text
promotion_mode=promote_canary
source_digest=<candidate sha256 digest>
source_version=<immutable vX.Y.Z tag>
automated_evidence_url=<successful tag workflow run URL>
macos_evidence_url=<sanitized Actions run or issue/comment URL>
linux_evidence_url=<sanitized Actions run or issue/comment URL>
previous_stable_digest=<digest observed immediately above, or none>
qualification_complete=true
```

The protected job refuses stale stable state, a tag/digest mismatch, a canary
mismatch, failed/wrong automated evidence, invalid evidence URLs, missing
acknowledgement, or missing signature/attestations. It moves `stable` with
`imagetools create`; it does not rebuild.

After completion, independently require:

```bash
test "$(docker buildx imagetools inspect ghcr.io/26457513/assurance-scan-cli:stable --format '{{.Manifest.Digest}}')" = '<candidate digest>'
test "$(docker buildx imagetools inspect ghcr.io/26457513/assurance-scan-cli:canary --format '{{.Manifest.Digest}}')" = '<candidate digest>'
```

## 8. Monitor and expand

Keep the initial token/project cohort small through the rollback decision
deadline. Review sanitized counts at 15 minutes, one hour, and the next business
day:

- upload created/replayed/in-progress/rejected by stable error code;
- authentication failures, revocations, quota/capacity responses, and latency;
- stale idempotency leases, duplicate runs, retained bytes, and cleanup errors;
- run/scanner/artifact/finding count consistency and transaction rollbacks;
- GitHub polling health and existing UI/API behavior;
- CLI retry/outbox reports from canary operators.

Never paste raw request bodies or full logs into release evidence. Pause cohort
expansion for unexplained `5xx`, partial persistence, redaction failures,
cross-project identity, sustained capacity errors, or scanner supply-chain
drift.

Generate a read-only retention report at each review point. It reports eligible
row counts only; it does not delete artifacts, runs, tombstones or token audit
records:

```bash
docker run --rm --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" retention-report --database /data/db.sqlite \
  > "$ROLLOUT_EVIDENCE_DIR/retention-report.json"
chmod 600 "$ROLLOUT_EVIDENCE_DIR/retention-report.json"
```

## Kill switch and user cleanup

To stop new local uploads, set `LOCAL_INGEST_ENABLED=false` and recreate the
server using the same pinned application image. This does not disable GitHub
polling or delete historical scans.

For a compromised or retired machine:

1. Revoke its token under **Setup → My account**; the next request fails.
2. Run `auth logout` to remove the local secret while preserving the non-secret
   installation ID.
3. Run `cache list`, then `cache prune`; remove a specific retained request only
   through the CLI-supported cache operation when available—never a broad
   recursive deletion.
4. Delete a run/project through the application only when its server-side scan
   data should be removed. Raw artifacts retain for 30 days by policy,
   normalized history for 365 days, and inactive-token audit for 400 days unless
   explicit deletion/retention controls apply. A content-free request tombstone
   may remain for 30 days to prevent unsafe request-ID reuse.

## Rollback

### Before database migration

Keep local ingest disabled, deploy the previously recorded application digest,
and leave CLI `stable` unchanged.

### After database migration or server deployment

1. Activate the kill switch and stop all writers:

```bash
docker compose stop server
```

2. Validate `DATA_VOLUME`, the backup manifest/digest, and the previous
   application digest against the operator record.
3. Capture fresh stopped-writer evidence bound to the exact current target and
   run a guarded restore dry run. The restore tool preserves the current failed
   database as the recovery copy; do not make an unverified overwrite.
4. Execute the exact dry-run plan only after reviewer approval.
5. Tag the previous immutable application image as the Compose `latest` image
   and restart with `--pull never` and `LOCAL_INGEST_ENABLED=false`.
6. Verify SQLite integrity, health, project/run counts, GitHub polling, and that
   local ingest remains disabled.

First prove that Compose has no running server writer and retain the private
command output. Do not manufacture this evidence while a worker, poller,
retention loop or API process can still write the volume:

```bash
docker volume inspect "$DATA_VOLUME" >/dev/null
test -z "$(docker compose ps --status running -q server)"
docker compose ps --all > "$ROLLOUT_EVIDENCE_DIR/compose-stopped.txt"
chmod 600 "$ROLLOUT_EVIDENCE_DIR/compose-stopped.txt"

docker run --rm \
  --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  -c 'import datetime,hashlib,json,pathlib; p=pathlib.Path("/data/db.sqlite"); digest=hashlib.file_digest(p.open("rb"),"sha256").hexdigest(); e={"schema":"assurance-scan-stopped-writers-v1","target_path":"/data/db.sqlite","target_sha256":digest,"writers_stopped":True,"service_state":"stopped","observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"evidence":"docker compose ps reported no running server writer; see private compose-stopped.txt"}; out=pathlib.Path("/evidence/stopped-writers.json"); out.write_text(json.dumps(e,sort_keys=True)+"\n"); out.chmod(0o600)'
```

Verify the backup again and derive the exact confirmation from its manifest.
The target in the confirmation is the resolved in-container target recorded in
the stopped-writer evidence, not a host guess:

```bash
docker run --rm --read-only \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" verify-backup \
  --backup /evidence/db.sqlite.pre-cutover \
  --manifest /evidence/db.sqlite.pre-cutover.json \
  > "$ROLLOUT_EVIDENCE_DIR/rollback-backup-verify.json"

export BACKUP_SHA256="$(docker run --rm --read-only \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  -c 'import json; print(json.load(open("/evidence/rollback-backup-verify.json"))["backup_sha256"])')"
export RESTORE_CONFIRMATION="RESTORE ${BACKUP_SHA256} TO /data/db.sqlite"

docker run --rm --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" restore \
  --backup /evidence/db.sqlite.pre-cutover \
  --manifest /evidence/db.sqlite.pre-cutover.json \
  --target /data/db.sqlite \
  --stopped-writer-evidence /evidence/stopped-writers.json \
  --confirm "$RESTORE_CONFIRMATION" \
  > "$ROLLOUT_EVIDENCE_DIR/restore-dry-run.json"
```

Omitting `--execute` is intentional: a successful result has status
`verified-dry-run` and names the recovery path. The command refuses stale or
mismatched evidence, a changed target, any `-wal`/`-shm` sidecar, an existing
recovery path, or an inexact confirmation. Do not delete a sidecar or weaken a
guard to continue; investigate and take a new backup/evidence set. Stopped-
writer evidence expires after 15 minutes. If review exceeds that window or the
target changes, recreate the evidence and repeat the dry run.

After the reviewer checks the dry-run report, repeat the same command with the
single additional `--execute` flag:

```bash
docker run --rm --read-only \
  -v "$DATA_VOLUME:/data" \
  -v "$ROLLOUT_EVIDENCE_DIR:/evidence:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" restore \
  --backup /evidence/db.sqlite.pre-cutover \
  --manifest /evidence/db.sqlite.pre-cutover.json \
  --target /data/db.sqlite \
  --stopped-writer-evidence /evidence/stopped-writers.json \
  --confirm "$RESTORE_CONFIRMATION" \
  --execute \
  > "$ROLLOUT_EVIDENCE_DIR/restore-result.json"

docker run --rm --read-only \
  -v "$DATA_VOLUME:/data:ro" \
  --entrypoint /opt/venv/bin/python "$CANDIDATE_APP_REF" \
  "$CUTOVER_TOOL" preflight --database /data/db.sqlite \
  > "$ROLLOUT_EVIDENCE_DIR/post-restore-preflight.json"

docker image tag "$PREVIOUS_APP_REF" ghcr.io/26457513/assurance-scan-app:latest
docker compose up -d --no-deps --pull never server
```

The restore result records the exact `recovery_path` retained beside the
database in the data volume and its SHA-256. Copy that recovery database and
the restore/preflight reports to encrypted off-host storage before any later
cleanup. This procedure specifies the recovery mechanism; it does not claim a
production recovery has been exercised.

Never run Alembic downgrade for revisions 0021/0022.

### CLI stable rollback

Dispatch `publish-cli-image` with `promotion_mode=rollback_previous`, the
previously qualified immutable version/digest as `source_*`, the current stable
digest as `previous_stable_digest`, that release's successful automated and
macOS/Linux evidence URLs, and `qualification_complete=true`. Protected review,
tag/digest, signature, attestation, public-pull, and stale-baseline checks still
apply. The job restores `stable` without rebuilding; `canary` remains available
for investigation.

Record the rollback reason and both before/after digests. Do not claim recovery
complete until the same monitoring checks above pass.
