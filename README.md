# ASVS Scanner

ASVS Scanner is a portable security scan and evidence bundle generator for application codebases. It runs source, dependency, container image, runtime URL, TLS, header, and uploaded-file checks through Docker, then produces a compact dashboard, raw evidence files, a manual evidence checklist, and an agent-ready fix prompt.

The scanner is built around the **Application Security Verification Standard (ASVS)** — an OWASP standard that lists security requirements an application should satisfy. Automated checks produce the evidence they can; manual ASVS evidence remains visible and trackable alongside them. The tool is designed for repeatable assurance work, not as a magic compliance stamp.

> **Image location placeholder:** commands below use `<dockerhub-user>/asvs-scanner`. Substitute your Docker Hub username or org name when you copy them.

## Quick Start

```bash
# One-time per machine: authenticate + pull the image
docker login
docker pull <dockerhub-user>/asvs-scanner:latest

# Scan a project
cd /path/to/project
git switch branch-to-scan
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/asvs-scanner:latest scan "$PWD"

# Open the dashboard (path is printed at the end of the scan)
open "<worktree-path>/.asvs-scanner/runtime/reports/$(ls -t <worktree-path>/.asvs-scanner/runtime/reports | head -1)/dashboard.html"
```

First scan in a project downloads vulnerability databases (Trivy / Grype / OSV), so expect it to be slower. Subsequent scans reuse the cache.

### Where to find the docs

- This README is also rendered on the Docker Hub image page (`hub.docker.com/r/<dockerhub-user>/asvs-scanner`) once you link the source repo under Repository → General → Description.
- Inside a terminal, `<dockerhub-user>/asvs-scanner:latest help` prints the supported subcommands and key flags.
- The README is baked into the image at `/opt/asvs-scanner/README.md`. Extract it without a browser:
  ```bash
  docker run --rm --entrypoint cat <dockerhub-user>/asvs-scanner:latest /opt/asvs-scanner/README.md
  ```
- Source, issues, and release notes live at `https://github.com/jondowson/asvs-scanner`.

## Prerequisites

- **Docker Desktop** (or `docker` + `docker compose`) running on the host. Every scanner executes in its own container.
- **Access to the image.** The image is private on Docker Hub, so each user needs credentials with read access. Run `docker login` once per machine.
- **Internet access** on first run, to pull scanner images and seed vulnerability databases. Later scans are offline-tolerant.
- **Disk:** budget ~5 GB for caches plus the size of any built scan images.
- For target repos with uncommitted changes you want scanned: **commit or stash first.** The scanner creates a safe worktree from the current branch and only committed files end up in the scan.

## What It Produces

Each run creates a report directory containing:

| File | Purpose |
|---|---|
| `dashboard.html` | Compact interactive report for triage and evidence review |
| `agent-investigation-prompt.md` | Prompt for an AI coding agent to investigate and fix findings |
| `evidence-manifest.json` | Machine-readable run metadata, scanner status, hashes, and scores |
| `scanner-run-summary.txt` | Terminal-friendly summary |
| `manual-evidence-required.md` | Human evidence checklist |
| `reports/` | Raw scanner outputs |
| `sbom/` | CycloneDX SBOMs |
| `hashes/` | SHA-256 hashes for generated evidence |

The scanner creates a safe Git worktree beside your repo (sibling directory) and writes outputs inside it:

```text
<project-parent>/
  your-project/                                              ← your repo, untouched
  your-project-asvs-scan-<RUN_ID>/                           ← safe worktree (created by the scan)
    .asvs-scanner/runtime/reports/<RUN_ID>/                  ← dashboard + all outputs
```

`<RUN_ID>` has the format `<UTCstamp>_<sha8>` (e.g. `20260702T104215Z_3e675e29`) — the same string the dashboard shows as "Run ID", so you can grep for it on disk.

## Scanner Coverage

| Surface | Required Flag | Tools |
|---|---|---|
| Source code | _always on_ | Semgrep, Gitleaks, Trivy config |
| Dependencies and SBOM | _always on_ | Trivy FS, Syft, Grype, osv-scanner |
| Container images | `--image <image>` | Trivy image, Syft image, Grype image |
| Runtime URL | `--url <url>` | OWASP ZAP baseline, security header checks |
| HTTPS/TLS | `--url https://...` | testssl.sh |
| Uploaded files | `--uploads <dir>` | ClamAV |
| Manual ASVS evidence | _always generated_ | Checklist embedded in the dashboard |

When an optional surface is not supplied, its scanners are shown as `SKIPPED` in the dashboard with a reason.

## Running The Scanner

The scanner creates a fresh branch and worktree from your currently checked-out branch, scans the safe copy, and writes outputs inside it. Your main checkout is untouched.

```bash
cd /path/to/project
git switch branch-to-scan

docker run --rm -it \
  -e ASVS_IMAGE_BUILD_PARALLELISM=2 \
  -e ASVS_PARALLELISM=4 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/asvs-scanner:latest scan "$PWD"
```

### Common Variations

| Situation | Add to `scan "$PWD"` |
|---|---|
| Source-only scan (skip image scanners) | `--no-auto-build-images` |
| Scan a specific prebuilt image | `--image app:tag` (disables auto-build) |
| Scan a running local web app | `--url http://host.docker.internal:3000` |
| Full scan | `--image app:local --url https://staging.example.com --uploads "$PWD/sample-uploads"` |

### Why the mount incantation?

`"$(dirname "$PWD"):$(dirname "$PWD")"` mounts your project's **parent directory** at the same absolute path inside the scanner container. The scanner launches other Docker containers through the host Docker socket, and those sibling containers need host-visible paths for the safe worktree, scripts, reports, and upload samples. Mounting only `$PWD` would break the sibling-worktree creation.

### Pulling updates

`docker run` uses the local image cache and will not auto-pull newer versions. When you publish or pull a new `latest`, refresh explicitly:

```bash
docker pull <dockerhub-user>/asvs-scanner:latest
```

## Image Scan Workflow

By default, `scan` looks for Dockerfiles in the safe worktree and builds scan images automatically before running image scanners. Discovery checks:

- `Dockerfile`
- `services/*/Dockerfile`
- `apps/*/Dockerfile`
- `packages/*/Dockerfile`

Images are tagged with commit-stable local names like `repo-service:asvs-v2-1a2b3c4d5e6f`, then passed to Trivy image, Syft image, and Grype image. Later scans of the same commit reuse those images instead of rebuilding them. Set `ASVS_FORCE_IMAGE_BUILD=1` when you deliberately want to rebuild.

Image scans default Trivy to vulnerability scanning only (`TRIVY_IMAGE_SCANNERS=vuln`) because source secrets are already covered by Gitleaks and image secret scanning can be slow on package-manager caches. Set `TRIVY_IMAGE_SCANNERS=vuln,secret` when you explicitly want Trivy to search images for embedded secrets too.

### Safe Image-Build Worktree

Some repos need temporary Dockerfile or build-system changes before they can be scanned. The `safe-image-worktree` subcommand creates a separate Git worktree and branch for those changes — without switching your main checkout or dirtying your working tree.

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/asvs-scanner:latest safe-image-worktree "$PWD"                              # auto branch name
  <dockerhub-user>/asvs-scanner:latest safe-image-worktree "$PWD" asvs/image-scan-my-check   # specific branch
```

That prints the new worktree path and branch name. Then `cd` into it, add whatever temporary build files you need, commit, and run the normal `scan` command from there.

## Scanner Databases

Database setup is automatic. ASVS Scanner keeps scanner databases in persistent Docker named volumes, so they survive normal `docker run --rm` scans.

| Behavior | Default |
|---|---|
| First scan on a laptop | Downloads/seeds Trivy, Grype, and OSV databases before scanning |
| Upload scanning enabled | Also downloads/seeds ClamAV signatures |
| Later scans | Reuse cached Docker volumes |
| Automatic refresh cadence | At most once every 24 hours |
| Refresh marker storage | Persistent Docker metadata volume |
| Scanner image pull checks | Also skipped within the same 24-hour freshness window |

Tune the refresh policy with:

| Setting | Effect |
|---|---|
| `ASVS_DB_REFRESH_TTL_HOURS=24` | Default daily refresh window |
| `ASVS_DB_REFRESH_TTL_HOURS=0` | Check/download fresh databases on every scan |
| `ASVS_AUTO_PREFETCH=0` | Skip automatic database setup entirely |
| `asvs-scanner prefetch` | Force a refresh immediately |

Warm a laptop ahead of time:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD" \
  -w "$PWD" \
  <dockerhub-user>/asvs-scanner:latest prefetch
```

Or refresh selected databases:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD" \
  -w "$PWD" \
  <dockerhub-user>/asvs-scanner:latest prefetch --only trivy,grype,osv,clamav
```

## Ignoring Source Paths

Add `.scannerignore` to the target project root to filter noisy source/config findings:

```text
node_modules/
dist/
build/
.next/
test/fixtures/
**/fixtures/**
reports/
```

This applies to Semgrep, Gitleaks, and Trivy config. Dependency scanners still inspect the full filesystem so SBOM and dependency vulnerability coverage stays complete.

## Practical Notes

- The terminal output is intentionally compact. Full scanner output is saved in `run.log` beside the dashboard — start there when something fails.
- Image scans require the image to exist in the same Docker daemon, for example `docker build -t app:local .`.
- Runtime scans need a URL reachable from Docker containers. For apps running on the laptop, use `http://host.docker.internal:<port>`.
- HTTPS URLs trigger TLS checks; HTTP URLs skip testssl.sh by design.
- Upload scans need a folder of representative files mounted under the project path or another same-path bind mount.
- The ASVS score combines automated checks and manual evidence. Use the Manual KPI in the dashboard to track evidence completion during review.
- Tune parallelism with `ASVS_PARALLELISM` (scanner containers) and `ASVS_IMAGE_BUILD_PARALLELISM` (image builds). Set either to `1` for sequential troubleshooting.

## Local Configuration

Optional tokens can be placed in `scanner-config.yaml`, `.env`, or environment variables:

```yaml
github_token: ""
trivy_token: ""
semgrep_app_token: ""
zap_api_key: ""
scanner_timeout_default: 600
```

Configuration precedence is:

1. Command-line flags
2. Environment variables
3. `scanner-config.yaml`
4. `.env`
5. Built-in defaults

## Publishing A New Version (Maintainers)

The image is private on Docker Hub. Two paths:

### Automatic (recommended)

The `publish-image` GitHub Actions workflow (`.github/workflows/publish-image.yml`) handles everything. Build cache lives in the GitHub Actions cache (repository-scoped, not exposed on Docker Hub).

**Triggers and what each produces:**

| Trigger | Job | Tags published |
|---|---|---|
| Pull request | `validate` (build only, no push) | none |
| Push to `main` | `publish` | `latest`, `:<short-sha>` |
| `v*` git tag | `publish` | `:<version>`, `stable`, `:<short-sha>` |
| Manual dispatch (Actions tab) | `publish` | same as push to `main`, or same as a tag if dispatched from a tag |

**Tag policy for teams pulling the image:**

| Tag | Use when |
|---|---|
| `<user>/asvs-scanner:latest` | You want every merged change to main, accepts some churn |
| `<user>/asvs-scanner:stable` | You want only intentional releases — only advances when you cut a `v*` tag |
| `<user>/asvs-scanner:<version>` | You want to pin a specific release (e.g. `:1.2.3`) for reproducibility |
| `<user>/asvs-scanner:<short-sha>` | You want to pin a specific commit, e.g. for incident forensics |

To cut a release: `git tag v1.2.3 && git push --tags` — the workflow publishes `:1.2.3` plus advances `:stable`.

**Required GitHub secrets** (repo → Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub account with push access to the image repo |
| `DOCKERHUB_TOKEN` | Personal access token (hub.docker.com → Account Settings → Security) |

The image repo on Docker Hub must already exist (create it as private first).

### Manual

One-time setup on a maintainer machine:

```bash
docker buildx create --use --name asvs-builder   # enables multi-arch builds
docker login                                     # Docker Hub username + access token
```

Build for both Intel and ARM, tag with `latest` plus a commit-stable sha, push in one go:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t <dockerhub-user>/asvs-scanner:latest \
  -t <dockerhub-user>/asvs-scanner:"$(git rev-parse --short=8 HEAD)" \
  --push .
```

### Tarball handoff (airgapped machines)

For airgapped machines or skipping the registry entirely:

```bash
docker buildx build --platform linux/amd64 -t <dockerhub-user>/asvs-scanner:amd64 --load .
docker save <dockerhub-user>/asvs-scanner:amd64 -o asvs-scanner-amd64.tar

docker buildx build --platform linux/arm64 -t <dockerhub-user>/asvs-scanner:arm64 --load .
docker save <dockerhub-user>/asvs-scanner:arm64 -o asvs-scanner-arm64.tar
```

Colleagues load a tarball with:

```bash
docker load -i asvs-scanner-amd64.tar
```

### Granting pull access

Docker Hub private images require each user to authenticate. Either:

- Add colleagues as **collaborators** on the image repo (per-user, simplest for small teams), or
- Move the image to a **Docker Hub org** and add a **team** with read access (better for groups, supports member turnover).

Colleagues then run `docker login` once with their own Docker Hub creds to pull.
