# Assurance Scan

Assurance Scan is a portable security scan and evidence bundle generator for application codebases. It runs source, dependency, container image, runtime URL, TLS, header, and uploaded-file checks through Docker, then produces a compact dashboard, raw evidence files, a manual evidence checklist, and an agent-ready fix prompt.

The scanner is built around the **Application Security Verification Standard (ASVS)** — an OWASP standard that lists security requirements an application should satisfy. Automated checks produce the evidence they can; manual ASVS evidence remains visible and trackable alongside them. The tool is designed for repeatable assurance work, not as a magic compliance stamp.

> **Image location placeholder:** commands below use `<dockerhub-user>/assurance-scan`. Substitute your Docker Hub username or org name when you copy them.

## Quick Start

```bash
# One-time per machine: authenticate + pull the image
docker login
docker pull <dockerhub-user>/assurance-scan:latest

# Scan a project
cd /path/to/project
git switch branch-to-scan
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest scan "$PWD"

# Open the dashboard (path is printed at the end of the scan)
open "<worktree-path>/.assurance-scan/runtime/reports/$(ls -t <worktree-path>/.assurance-scan/runtime/reports | head -1)/dashboard.html"
```

First scan in a project downloads vulnerability databases (Trivy / Grype / OSV), so expect it to be slower. Subsequent scans reuse the cache.

### Where to find the docs

- This README is also rendered on the Docker Hub image page (`hub.docker.com/r/<dockerhub-user>/assurance-scan`) once you link the source repo under Repository → General → Description.
- Runtime graph architecture and proof-direction notes live in `docs/RUNTIME_GRAPH_ARCHITECTURE.md`.
- Inside a terminal, `<dockerhub-user>/assurance-scan:latest help` prints the supported subcommands and key flags.
- The README is baked into the image at `/opt/assurance-scan/README.md`. Extract it without a browser:
  ```bash
  docker run --rm --entrypoint cat <dockerhub-user>/assurance-scan:latest /opt/assurance-scan/README.md
  ```
- Source, issues, and release notes live at `https://github.com/26457513/assurance-scan`.

## GitHub Actions CI Scanning (SARIF)

Scans can run on GitHub Actions compute and report findings in the run's Step Summary plus a downloadable SARIF artifact (the GitHub-native Security-tab upload needs GHAS, which free-plan private orgs don't have). Design notes: `docs/plan-github-actions-sarif.md`.

### One-time setup (organization)

Tested on a free-plan org with private repos (`26457513`). Skipping any of these surfaces as a confusing `workflow was not found` or `Not Found` error in the run:

1. **Tool-repo sharing:** `assurance-scan` → Settings → Actions → General → *Access* → **"Accessible from repositories in \<org\>"**. Without this, sibling repos can't see the reusable workflow at all.
2. **Actions policy:** same page, top section → **Allow all actions and reusable workflows** (the workflow uses marketplace actions like `actions/checkout`).
3. **Fine-grained PAT:** Settings → Developer settings → Fine-grained tokens → generate. **Resource owner must be the org** — left on the personal account, org repos never appear in the repository picker. Scope: Only select repositories → `assurance-scan`. Permissions: Contents → Read-only.
4. **Org PAT policy** (org → Settings → Personal access tokens): allow fine-grained tokens, do not require administrator approval.
5. **Secret:** free-plan orgs can't scope an org secret to all private repos (the option is greyed out), so add the token as a **repository secret** in each consuming repo: repo → Settings → Secrets and variables → Actions → `ASSURANCE_SCAN_TOKEN`.

### Add scanning to a repo

Create `.github/workflows/assurance-scan.yml` in the target repo:

```yaml
name: assurance-scan
on:
  pull_request:
    types: [opened, synchronize]   # skip redundant rescan on reopen
  push:
    branches: [<default branch>]   # scans each commit exactly once
permissions:
  contents: read
  actions: write        # build layer cache
  pull-requests: write  # findings comment on PRs
jobs:
  scan:
    uses: 26457513/assurance-scan/.github/workflows/scan.yml@main
    secrets: inherit   # passes ASSURANCE_SCAN_TOKEN
```

Pin to the branch carrying the reusable workflow while it's under development (currently `@target-schema-implementation`), `@main` once merged — and the reusable workflow's internal scanner checkout must be pinned to match.

Each run produces a GitHub Step Summary (severity counts + top findings) and an `assurance-scan-results` artifact containing the SARIF plus a CycloneDX SBOM (`sbom.cyclonedx.json`). When the repo has a root `Dockerfile`, the workflow builds it and adds a Trivy image scan of the built image. Scans never fail the workflow; scanner failures are listed in the summary instead.

### Run the same scan locally

```bash
python3 scripts/ci-scan.py /path/to/project --sarif out.sarif
# optional: scan a locally built image too
python3 scripts/ci-scan.py /path/to/project --sarif out.sarif --image app:local
```

Needs Docker; no server, no DB.

## Prerequisites

- **Docker Desktop** (or `docker` + `docker compose`) running on the host. Every scanner executes in its own container.
- **Access to the image.** The image is private on Docker Hub, so each user needs credentials with read access. Run `docker login` once per machine.
- **Internet access** on first run, to pull scanner images and seed vulnerability databases. Later scans are offline-tolerant.
- **Disk:** budget ~5 GB for caches plus the size of any built scan images.
- For target repos with uncommitted changes you want scanned: **commit or stash first.** The scanner creates a safe worktree from the current branch and only committed files end up in the scan.
- **Lockfile auto-injection.** Gitignored lockfiles (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`) that sit next to a discovered Dockerfile are copied into the safe worktree and force-committed before image build, so `npm ci` and similar commands don't fail with `EUSAGE`. The list of injected files is written to `.assurance-scan/runtime/injected-lockfiles.json` in the worktree. Set `ASSURANCE_SCAN_INJECT_LOCKFILES=0` to disable.

## What It Produces

Each run creates a report directory containing:

| File | Purpose |
|---|---|
| `dashboard.html` | Compact interactive report for triage and evidence review |
| `dashboard-payload.json` | Normalised machine-readable payload used by the dashboard |
| `agent-investigation-prompt.md` | Prompt for an AI coding agent to investigate and fix scanner findings |
| `assurance-assessment-prompt.md` | Separate Codex prompt for assessment-first FR/TBT/ASVS/JSP-453 evidence coverage |
| `fr-config-update-prompt.md` | Separate Codex prompt for proposing FR/TBT/compliance/gate config updates without product-code changes |
| `fr-config-update-proposal.template.json` | Schema-valid starting artifact for agent-authored config update proposals |
| `agent-prompt-plan.json` | Structured deficiencies, fix recommendations, and assurance recommendations |
| `evidence-manifest.json` | Machine-readable run metadata, scanner status, hashes, and scores |
| `evidence-bundle.json` | Target-schema evidence records produced by declared TBTs |
| `generated-tests/VG_TEST_FRAMEWORK/manifest.json` | Ephemeral assessment-first test-pack plan using TBT, FR, ruleset row and assurance gate references |
| `scanner-run-summary.txt` | Terminal-friendly summary |
| `manual-evidence-required.md` | Human evidence checklist |
| `reports/` | Raw scanner outputs |
| `sbom/` | CycloneDX SBOMs |
| `hashes/` | SHA-256 hashes for generated evidence |

The scanner creates a safe Git worktree beside your repo (sibling directory) and writes outputs inside it:

```text
<project-parent>/
  your-project/                                              ← your repo, untouched
  your-project-assurance-scan-<RUN_ID>/                           ← safe worktree (created by the scan)
    .assurance-scan/runtime/reports/<RUN_ID>/                  ← dashboard + all outputs
```

`<RUN_ID>` has the format `<UTCstamp>_<sha8>` (e.g. `20260702T104215Z_3e675e29`) — the same string the dashboard shows as "Run ID", so you can grep for it on disk.

Target-schema artifacts can be checked after a run:

```bash
docker run --rm -it \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest validate-report \
  "<worktree-path>/.assurance-scan/runtime/reports/<RUN_ID>" \
  --strict
```

Agent-authored config update proposals should be validated before review or application:

```bash
assurance-scan validate-config-update proposal.json \
  --fr-catalog /path/to/project.fr-catalog.enriched.json \
  --ruleset data/fixtures/target-schemas/ruleset.example.json \
  --assurance-framework /path/to/jsp453-framework.json
```

Then render a human review brief:

```bash
assurance-scan review-config-update proposal.json \
  --output proposal-review.md
```

After human review, selected entries can be applied to explicit output files:

```bash
assurance-scan apply-config-update proposal.json \
  --list

assurance-scan apply-config-update proposal.json \
  --select fr_catalog_updates:1 \
  --reviewed-by "assessor-name" \
  --fr-catalog /path/to/project.fr-catalog.enriched.json \
  --fr-catalog-out /path/to/project.fr-catalog.reviewed.json

assurance-scan apply-config-update proposal.json \
  --select assurance_framework_or_instance_updates:1 \
  --reviewed-by "assessor-name" \
  --assurance-instance /path/to/project.assurance-instance.json \
  --assurance-instance-out /path/to/project.assurance-instance.reviewed.json \
  --assurance-framework /path/to/jsp453-framework.json
```

Automatic apply currently covers `fr_catalog_updates`, `compliance_mapping_pack_updates`, `native_test_mapping_updates` that update the assurance test-pack manifest, `assurance_framework_or_instance_updates` that target project instance mappings, gate decisions and waivers, plus manual evidence targeted at FRs, TBTs, criteria, and sufficiently-specified gate/role instance records. Reusable framework-structure changes and scanner-compliance mapping curation remain review-only until a human edits the relevant catalog deliberately.

assurance-owned executable tests and wrappers live under `tests/asvs/` in the generated pack or dedicated assurance branch/worktree. Existing native project tests stay in their original source paths; report-local imported copies are provenance/review inputs, not a second source of truth.

### Worked Config Update Example

Use this when the dashboard shows FR/TBT gaps that are really config gaps, for example a project FR has a planned TBT but no accepted expected evidence, compliance row mapping, gate decision or waiver.

1. Generate a proposal with Codex or another agent using the report's `fr-config-update-prompt.md`. Start from `fr-config-update-proposal.template.json`, and save the returned JSON as `proposal.json`.

2. Validate the proposal against the current config and standards context:

```bash
assurance-scan validate-config-update proposal.json \
  --fr-catalog "$PWD/tapestry-mono.fr-catalog.enriched.json" \
  --ruleset "$PWD/data/fixtures/target-schemas/ruleset.example.json" \
  --assurance-framework "$PWD/jsp-453.assurance-framework.draft.json"
```

3. Render the human review brief:

```bash
assurance-scan review-config-update proposal.json \
  --output proposal-review.md
```

4. List selectable proposal entries and approve only the entries you have reviewed:

```bash
assurance-scan apply-config-update proposal.json \
  --list
```

5. Apply selected entries to explicit reviewed outputs. This is transactional: if any selected output fails validation, none of the reviewed outputs are replaced.

```bash
assurance-scan apply-config-update proposal.json \
  --select fr_catalog_updates:1 \
  --select assurance_framework_or_instance_updates:1 \
  --reviewed-by "assessor-name" \
  --fr-catalog "$PWD/tapestry-mono.fr-catalog.enriched.json" \
  --fr-catalog-out "$PWD/tapestry-mono.fr-catalog.reviewed.json" \
  --assurance-test-pack "$PWD/generated-tests/VG_TEST_FRAMEWORK/manifest.json" \
  --assurance-test-pack-out "$PWD/generated-tests/VG_TEST_FRAMEWORK/manifest.reviewed.json" \
  --assurance-instance "$PWD/tapestry-mono.assurance-instance.json" \
  --assurance-instance-out "$PWD/tapestry-mono.assurance-instance.reviewed.json" \
  --assurance-framework "$PWD/jsp-453.assurance-framework.draft.json"
```

6. Rerun the scan with the reviewed config files:

```bash
docker run --rm -it \
  -e ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM=2 \
  -e ASSURANCE_SCAN_PARALLELISM=4 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  assurance-scan:latest scan "$PWD" \
  --fr-catalog "$PWD/tapestry-mono.fr-catalog.reviewed.json" \
  --assurance-framework "$PWD/jsp-453.assurance-framework.draft.json" \
  --assurance-instance "$PWD/tapestry-mono.assurance-instance.reviewed.json"
```

After rerun, validate the fresh report with `assurance-scan validate-report <report-dir> --strict`, then inspect Project FRs, Compliance Regime, Industry Framework and Traceability Graph to confirm the gap moved from "missing config" to a real pass, fail, manual review, waiver or missing evidence state.

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

## Local Development Checks

```bash
python3 -m unittest tests/test_config_update_workflow.py
python3 scripts/validate-target-schema-fixtures.py
```

## Running The Scanner

The scanner creates a fresh branch and worktree from your currently checked-out branch, scans the safe copy, and writes outputs inside it. Your main checkout is untouched.

```bash
cd /path/to/project
git switch branch-to-scan

docker run --rm -it \
  -e ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM=2 \
  -e ASSURANCE_SCAN_PARALLELISM=4 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest scan "$PWD"
```

### Common Variations

| Situation | Add to `scan "$PWD"` |
|---|---|
| Source-only scan (skip image scanners) | `--no-auto-build-images` |
| Scan a specific prebuilt image | `--image app:tag` (disables auto-build) |
| Scan a running local web app | `--url http://host.docker.internal:3000` |
| Full scan | `--image app:local --url https://staging.example.com --uploads "$PWD/sample-uploads"` |
| Add project FR/TBT traceability | `--fr-catalog "$PWD/fr-catalog.json"` |
| Add compliance sufficiency mappings | `--compliance-mapping-pack "$PWD/asvs-mapping-pack.json"` |
| Add scanner-to-compliance mappings | `--scanner-compliance-mapping-pack "$PWD/data/scanner-mappings/asvs/5.0.0"` |
| Add an assurance gate framework | `--assurance-framework "$PWD/assurance-framework.jsp-453.json"` |
| Add project gate mappings and roles | `--assurance-instance "$PWD/assurance-instance.jsp-453.json"` |
| Import existing test execution evidence | `--junit-xml "$PWD/reports/junit.xml"` |

When an FR catalog is supplied, the scanner treats `FR-*` entries as project-owned functional requirements and `TBT-*` entries as the test-basis records that prove them. Observed evidence is emitted into `evidence-bundle.json`; missing evidence remains visible as gaps rather than being counted as a pass.

### Why the mount incantation?

`"$(dirname "$PWD"):$(dirname "$PWD")"` mounts your project's **parent directory** at the same absolute path inside the scanner container. The scanner launches other Docker containers through the host Docker socket, and those sibling containers need host-visible paths for the safe worktree, scripts, reports, and upload samples. Mounting only `$PWD` would break the sibling-worktree creation.

### Pulling updates

`docker run` uses the local image cache and will not auto-pull newer versions. When you publish or pull a new `latest`, refresh explicitly:

```bash
docker pull <dockerhub-user>/assurance-scan:latest
```

## Image Scan Workflow

By default, `scan` looks for Dockerfiles in the safe worktree and builds scan images automatically before running image scanners. Discovery checks:

- `Dockerfile`
- `services/*/Dockerfile`
- `apps/*/Dockerfile`
- `packages/*/Dockerfile`

Images are tagged with commit-stable local names like `repo-service:assurance-v1-1a2b3c4d5e6f`, then passed to Trivy image, Syft image, and Grype image. Later scans of the same commit reuse those images instead of rebuilding them. Set `ASSURANCE_SCAN_FORCE_IMAGE_BUILD=1` when you deliberately want to rebuild.

Image scans default Trivy to vulnerability scanning only (`TRIVY_IMAGE_SCANNERS=vuln`) because source secrets are already covered by Gitleaks and image secret scanning can be slow on package-manager caches. Set `TRIVY_IMAGE_SCANNERS=vuln,secret` when you explicitly want Trivy to search images for embedded secrets too.

### Safe Image-Build Worktree

Some repos need temporary Dockerfile or build-system changes before they can be scanned. The `safe-image-worktree` subcommand creates a separate Git worktree and branch for those changes — without switching your main checkout or dirtying your working tree.

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(dirname "$PWD"):$(dirname "$PWD")" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest safe-image-worktree "$PWD"                              # auto branch name
  <dockerhub-user>/assurance-scan:latest safe-image-worktree "$PWD" assurance/image-scan-my-check   # specific branch
```

That prints the new worktree path and branch name. Then `cd` into it, add whatever temporary build files you need, commit, and run the normal `scan` command from there.

## Scanner Databases

Database setup is automatic. Assurance Scan keeps scanner databases in persistent Docker named volumes, so they survive normal `docker run --rm` scans.

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
| `ASSURANCE_SCAN_DB_REFRESH_TTL_HOURS=24` | Default daily refresh window |
| `ASSURANCE_SCAN_DB_REFRESH_TTL_HOURS=0` | Check/download fresh databases on every scan |
| `ASSURANCE_SCAN_AUTO_PREFETCH=0` | Skip automatic database setup entirely |
| `assurance-scan prefetch` | Force a refresh immediately |

Warm a laptop ahead of time:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest prefetch
```

Or refresh selected databases:

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD:$PWD" \
  -w "$PWD" \
  <dockerhub-user>/assurance-scan:latest prefetch --only trivy,grype,osv,clamav
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
- Tune parallelism with `ASSURANCE_SCAN_PARALLELISM` (scanner containers) and `ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM` (image builds). Set either to `1` for sequential troubleshooting.

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
| `<user>/assurance-scan:latest` | You want every merged change to main, accepts some churn |
| `<user>/assurance-scan:stable` | You want only intentional releases — only advances when you cut a `v*` tag |
| `<user>/assurance-scan:<version>` | You want to pin a specific release (e.g. `:1.2.3`) for reproducibility |
| `<user>/assurance-scan:<short-sha>` | You want to pin a specific commit, e.g. for incident forensics |

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
  -t <dockerhub-user>/assurance-scan:latest \
  -t <dockerhub-user>/assurance-scan:"$(git rev-parse --short=8 HEAD)" \
  --push .
```

### Tarball handoff (airgapped machines)

For airgapped machines or skipping the registry entirely:

```bash
docker buildx build --platform linux/amd64 -t <dockerhub-user>/assurance-scan:amd64 --load .
docker save <dockerhub-user>/assurance-scan:amd64 -o assurance-scan-amd64.tar

docker buildx build --platform linux/arm64 -t <dockerhub-user>/assurance-scan:arm64 --load .
docker save <dockerhub-user>/assurance-scan:arm64 -o assurance-scan-arm64.tar
```

Colleagues load a tarball with:

```bash
docker load -i assurance-scan-amd64.tar
```

### Granting pull access

Docker Hub private images require each user to authenticate. Either:

- Add colleagues as **collaborators** on the image repo (per-user, simplest for small teams), or
- Move the image to a **Docker Hub org** and add a **team** with read access (better for groups, supports member turnover).

Colleagues then run `docker login` once with their own Docker Hub creds to pull.
