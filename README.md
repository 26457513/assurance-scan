# ASVS Scanner

ASVS Scanner is a portable security scan and evidence bundle generator for application codebases. It runs source, dependency, container image, runtime URL, TLS, header, and uploaded-file checks through Docker, then produces a compact dashboard, raw evidence files, a manual evidence checklist, and an agent-ready fix prompt.

The scanner is built around the **Application Security Verification Standard (ASVS)** — an OWASP standard that lists security requirements an application should satisfy. Automated checks produce the evidence they can; manual ASVS evidence remains visible and trackable alongside them. The tool is designed for repeatable assurance work, not as a magic compliance stamp.

## Quick Start

```bash
cd /path/to/asvs-scanner
chmod +x run-local.sh scripts/*.sh
./run-local.sh /path/to/project
open reports/$(ls -t reports | head -1)/dashboard.html
```

First run downloads scanner images and vulnerability databases (a few GB), so expect it to be slow. Subsequent runs reuse the cache.

## Prerequisites

- **Docker Desktop** (or `docker` + `docker compose`) running on the host. Every scanner executes in its own container.
- **Internet access** on first run, to pull scanner images and seed Trivy / Grype / OSV / ClamAV databases. Later scans are offline-tolerant.
- **Disk:** budget ~5 GB for caches plus the size of any built scan images.
- For target repos with uncommitted changes you want scanned: **commit or stash first.** The Docker scan path only copies committed files into the safe worktree (see below).

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

The location of the report directory depends on how you run the scanner — see [Two Ways To Run](#two-ways-to-run).

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

## Two Ways To Run

There are two entry points. **They behave differently** — pick the one that matches your workflow.

| | Option A: `run-local.sh` | Option B: Docker image (`asvs-scanner scan`) |
|---|---|---|
| Where it scans | Your target directory **in place** | A **safe Git worktree** created beside your repo |
| Where reports land | `asvs-scanner/reports/<run-id>/` | `<worktree>/.asvs-scanner/runtime/reports/<run-id>/` |
| Affects your working tree | No (read-only scan) | No (separate worktree and branch) |
| Best for | Iterating on the scanner itself, quick local scans | Repeatable scans on a clean commit; sharing the image with colleagues |

Both eventually invoke the same scanner containers, so coverage is identical — only the source-snapshot and report-location behavior differs.

### Option A: `run-local.sh`

Best for development or local modification of the scanner. Reports land inside this repo.

```bash
cd /path/to/asvs-scanner
./run-local.sh /path/to/project
```

Optional surfaces:

```bash
./run-local.sh /path/to/project \
  --image app:local \
  --url http://host.docker.internal:3000 \
  --uploads /path/to/upload-samples
```

Use `host.docker.internal` for apps running on the laptop, because the runtime scanners run inside Docker containers.

### Option B: Docker image (`asvs-scanner scan`)

Best for repeatable scans of a clean commit. Builds a distributable image once, then runs it against any checkout. The scanner creates a fresh branch and worktree from your currently checked-out branch, and scans that safe copy — your main checkout is untouched.

Build the image (see [Distributable Image Builds](#distributable-image-builds) for multi-arch / tarball variants):

```bash
docker build -t asvs-scanner:latest .
```

Run a scan from inside the project you want to scan:

```bash
cd /path/to/project
git switch branch-to-scan

docker run --rm -it \
  -e ASVS_IMAGE_BUILD_PARALLELISM=2 \
  -e ASVS_PARALLELISM=4 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  asvs-scanner:latest scan "$PWD"
```

The scan creates a branch like `asvs/scan-1a2b3c4d` and a timestamped sibling worktree:

```text
../project-asvs-scan-20260702-104215Z-1a2b3c4d/
  .asvs-scanner/runtime/reports/<run-id>/    ← dashboard.html and other outputs
```

**Why the mount incantation?** `"$(dirname "$PWD"):$(dirname "$PWD")"` mounts your project's **parent directory** at the same absolute path inside the scanner container. The scanner launches other Docker containers through the host Docker socket, and those sibling containers need host-visible paths for the safe worktree, scripts, reports, and upload samples. Mounting only `$PWD` would break the sibling-worktree creation.

## Docker Workflow

Once you have the image built, one subcommand covers the common cases: `scan`. It auto-discovers Dockerfiles, builds scan images, and runs the appropriate scanners. Use the flags to opt in to optional surfaces or to disable auto-build.

### Decision Table

| Your situation | Command |
|---|---|
| Dockerfiles in standard locations, want everything | `scan "$PWD"` (auto-builds and scans images) |
| Source-only scan | `scan "$PWD" --no-auto-build-images` |
| Scan a specific prebuilt image | `scan "$PWD" --image app:tag` (disables auto-build) |
| Scan a running local app | `scan "$PWD" --url http://host.docker.internal:3000` |
| Full scan | `scan "$PWD" --image app:local --url https://staging.example.com --uploads "$PWD/sample-uploads"` |
| Repo needs temporary Dockerfile/build changes | Run `safe-image-worktree` first (see below) |

### Automatic Image Discovery

By default, `scan` looks for Dockerfiles in the safe worktree and builds scan images before running image scanners. Discovery checks:

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
  asvs-scanner:latest safe-image-worktree "$PWD"           # auto branch name
asvs-scanner:latest safe-image-worktree "$PWD" asvs/image-scan-my-check   # specific branch
```

That prints the new worktree path and branch name. Then `cd` into it, add whatever temporary build files you need, and run the normal `scan` command from there.

### Distributable Image Builds

Build for the laptop you are on:

```bash
docker build -t asvs-scanner:latest .
```

Build for both Intel and ARM laptops:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-registry/asvs-scanner:latest \
  --push .
```

For a local tarball handoff instead of a registry:

```bash
docker buildx build --platform linux/amd64 -t asvs-scanner:amd64 --load .
docker save asvs-scanner:amd64 -o asvs-scanner-amd64.tar

docker buildx build --platform linux/arm64 -t asvs-scanner:arm64 --load .
docker save asvs-scanner:arm64 -o asvs-scanner-arm64.tar
```

Colleagues can load a tarball with:

```bash
docker load -i asvs-scanner-amd64.tar
```

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
  asvs-scanner:latest prefetch
```

Or refresh selected databases:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD" \
  -w "$PWD" \
  asvs-scanner:latest prefetch --only trivy,grype,osv,clamav
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
