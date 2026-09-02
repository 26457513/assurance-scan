# Standard GitHub Actions workflow

## Supported behavior

Setup generates one complete `.github/workflows/assurance-scan.yml` for an
enabled repository. GitHub receives the `push` event, but the scan job runs only
when `github.ref == format('refs/heads/{0}', github.event.repository.default_branch)`.
It therefore scans only:

- pushes to the repository's default branch.

A merged pull request naturally creates a push to the default branch and is
therefore scanned after merge. There is no `pull_request` trigger and no upload
from an unmerged PR branch. Developers scan those branches locally before
merge. Direct pushes and merge pushes follow the same authenticated path.

Minimum permissions:

```yaml
permissions:
  contents: read
  id-token: write
```

The default workflow writes the GitHub job summary and uploads the bounded
diagnostic artifacts using GitHub's first-party upload-artifact action pinned
to a full reviewed commit SHA. It does not request pull-request permissions or
post pull-request comments.

## Container policy

The copyable default uses
`ghcr.io/26457513/assurance-scan-ci:latest`. The release workflow moves `latest`
only to a fully tested signed digest. The job pulls `latest`, resolves its
repository digest, requires it to match the signed release manifest, verifies
the expected Cosign workflow identity, runs that exact digest and records it in
provenance. Verification tooling is itself pinned by digest.

Setup also offers immutable `vX.Y.Z` and digest variants for controlled
environments. All scanner images and rules inside the producer use the shared
immutable release manifest. Third-party Actions use full commit SHAs.

## Bundle and upload

Scan an immutable checkout snapshot using the same result/source-context
contracts as local execution. `findings.json` contains normalized findings plus
scanner statuses/durations; there is no separate scanner-status multipart part.
Strip incidental snippets and redact before persistence/upload.

Checkout uses the signed event SHA with persisted credentials disabled. The
producer rejects a workspace whose HEAD or source-content hash changes during
the scan. Repository-controlled build scripts are not executed by the upload
step.

After the bundle is complete and hashed, use the secure runner-to-container OIDC
transport in `oidc-ingestion.md`. The workflow never contains an Assurance Scan
secret, PAT or GitHub token beyond GitHub's ephemeral job/OIDC mechanisms.

## Readiness semantics

Because Assurance Scan has no Contents or Actions-read permission, it never
claims to detect whether the YAML exists. Setup states are exactly:

```text
No scan received yet
Last upload accepted <time>
Last upload rejected <safe reason/time>
```

The first accepted OIDC upload is the only workflow-readiness proof. Actions
link derives from signed run identity; Assurance Scan does not query it.
