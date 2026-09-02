# Assurance Scan

Security scanning and compliance assurance for codebases, centred on a hosted
dashboard. Scans run on GitHub Actions or through the public local CLI; the
server receives their results and serves a team UI with findings, FR catalogues, and compliance workflows
built around the OWASP **ASVS** standard.

**The model in one picture:**

```
org repos ──push──▶ GitHub Actions ──scan──▶ artifact ──poll──┐
   ▲ workflow_dispatch                                       │
   │                                                         ▼
  UI "Scan now" ◀────────────────────────────── hosted server + UI
                                                             ▲
local checkout ──public container CLI──scan + token upload───┘
```

One central instance serves multiple GitHub organisations. Each org
registers once (a PAT in Settings); its repos add a stub; everything else
is automatic. **All scanning runs on the target org's own GitHub compute**
— this instance never executes scans on behalf of a repo.

- **CI tier** — repos with a stub scan every push and PR; results appear in
  GitHub (Step Summary, PR comment, deep link) *and* the UI.
- **On demand** — *Scan now* dispatches the repo's own workflow (needs the
  stub; repos without it are refused with setup guidance).

## Architecture

| Piece | What it is |
|---|---|
| `backend/` | FastAPI service, atomic/workflow/shared modules, resources, scripts, and tests |
| `frontend/` | SvelteKit UI (served by the server container) |
| `backend/app/modules/` | VibeGuide modules grouped under `atomic/`, `workflows/`, and `shared/` |
| `backend/Dockerfile.ci` | Slim scanner orchestrator (glue only; scanners run as stock public images) |
| `backend/Dockerfile.cli` | Public local-scan container CLI; no hosted server or frontend |
| `Dockerfile` | Full app image (server + built frontend) |
| `compose.yaml` | Local + cloud deployment (identical containers) |
| `assurance-scan-ci` (public repo) | Reusable CI workflow + vendored template for any org |
| `backend/scripts/ci-scan.py` | Standalone scanner CLI (no server, no DB) |
| `backend/resources/templates/assurance-scan.yml` | Vendored stub for repos outside the home org |

The backend module boundaries are documented in
[`docs/module-architecture.md`](docs/module-architecture.md). The approved
push-only GitHub, local scan, access, Setup and delivery designs are indexed in
[`docs/plans/README.md`](docs/plans/README.md).

Operators releasing the public local CLI or enabling local ingest must follow
the [local scan rollout and rollback runbook](docs/runbooks/local-scan-rollout.md).

## Local deployment

Prerequisites: Docker.

```bash
cp .env.example .env     # fill in GITHUB_POLL_TOKEN (required)
docker compose up -d --build
open http://localhost:8742
```

Auth is off locally unless you set the auth vars. Data (SQLite) persists in
the `assurance-data` volume. Local-folder scans work through the mounted
docker socket and `~/Development`.

### Development

Work on `develop`, test locally (`docker compose up -d --build` picks up the
working tree), and merge to `main` only after the quality gate passes. A main
build publishes an immutable candidate; production deployment remains an
operator-reviewed maintenance-window action. Backend tests: `cd backend && python3 -m pytest tests/ -q`; frontend:
`cd frontend && npx svelte-check`.

## Droplet deployment (DigitalOcean)

One-time:

1. **Droplet**: Docker marketplace image, ≥1 GB RAM (2 GB comfortable), 15 GB
   disk. Add 2 GB swap if small (`fallocate -l 2G /swapfile && chmod 600
   /swapfile && mkswap /swapfile && swapon /swapfile` + fstab entry).
2. **DNS**: A record `scan → <droplet IP>` at your registrar.
3. **On the droplet**:
   ```bash
   git clone https://<token>@github.com/26457513/assurance-scan && cd assurance-scan
   ```
   Create `.env` (see below), then:
   ```bash
   docker login ghcr.io -u <github-user>    # classic PAT with read:packages
   DOMAIN=scan.yourdomain.com docker compose --profile public up -d
   ```
   Caddy obtains the Let's Encrypt cert on first request.
4. **Data carry-over** (optional; CI runs rehydrate from GitHub regardless):
   ```bash
   scp ~/.assurance-scan/db.sqlite droplet:/tmp/
   docker cp /tmp/db.sqlite assurance-scan-server-1:/data/db.sqlite
   docker compose restart server
   ```

### Droplet `.env`

```
GITHUB_POLL_TOKEN=<fine-grained PAT: home-org owner, Contents:Read, Actions:Read+Write>
GITHUB_ORG=26457513            # home org; others are registered in the UI
DOMAIN=scan.yourdomain.com
GOOGLE_CLIENT_ID=<OAuth client>        # auth: Google Workspace login
GOOGLE_CLIENT_SECRET=<...>
GOOGLE_DOMAIN=yourdomain.com
SESSION_SECRET=<random 32+ chars>
PUBLIC_BASE_URL=https://scan.yourdomain.com
TOKEN_ENCRYPTION_KEY=<random 32+ chars>   # encrypts user + org tokens
SCAN_TOKEN_CREATION_ENABLED=false        # enable only for reviewed account canaries
LOCAL_INGEST_ENABLED=false               # enable only for reviewed repository canaries
# APP_AUTH_USER / APP_AUTH_PASSWORD      # optional Basic Auth fallback
```

Local ingest requires the complete Google/session configuration above; it
stays unavailable in auth-off and Basic-only deployments. Users create a
one-time `asu_v1_...` upload token in **Settings → Scan tokens**. The v1 API
exposes authenticated capabilities, identity validation, multipart upload and
request-status endpoints under `/api/v1/ingest`. Upload, concurrency, storage
and payload ceilings can be lowered with the `LOCAL_INGEST_*` variables shown
in `.env.example`; compiled ceilings cannot be raised by configuration.

### Google login setup

Google Cloud console (Workspace account): OAuth consent screen → User type
**Internal** → Credentials → OAuth Client (Web application) → redirect URI
`https://<host>/auth/callback`. Only `@<your-domain>` accounts can sign in;
an already-logged-in browser gets one silent redirect. `/auth/logout` signs
out. Basic Auth (the two `APP_AUTH_*` vars) remains valid for curl/API use.

### Deploying updates

Merging `develop → main` builds, signs, attests, and publicly verifies an
immutable `assurance-scan-app` candidate. It does not mutate `latest` or deploy
production. Record the matching app, CI, and CLI digests, then use the
[local scan rollout and rollback runbook](docs/runbooks/local-scan-rollout.md)
for the maintenance-window backup, migration, exact-digest cutover, canary,
and rollback procedure. Small droplets must never build locally.

**Backup**: the SQLite file in the `assurance-data` volume is the only copy
of catalogues, registry, and waivers — schedule a daily `docker cp` + copy
off-box.

## Adding CI scanning to a repo

Add the self-contained `backend/resources/templates/assurance-scan.yml` as
`.github/workflows/assurance-scan.yml` in the repository. The same workflow
scans pull requests and the configured default branch and directly pulls the
public `ghcr.io/26457513/assurance-scan-ci:latest` image. No GHCR grant or
secret is required.

`latest` advances only after the image passes its release checks. Repositories
that require a fixed scanner version can replace `:latest` with
`:sha-<full-git-commit>`, or use the qualified `@sha256:<digest>` shown in the
release evidence for a content-addressed immutable pin.

Each run produces a Step Summary (per-tool severity matrix, runtimes, deep
link to the hosted UI) and an `assurance-scan-results` artifact (SARIF,
CycloneDX SBOM, `findings.json`). Repos with a root `Dockerfile` also get a
Trivy image scan of the build. Scans never fail the workflow.

## Running a local scan

Local and GitHub Actions scans use the same canonical `owner/repo` project.
Branch, commit, dirty-working-tree state and origin remain separate run
provenance, so a local feature-branch scan does not create a duplicate project.

Create a token in **Settings → Scan tokens** and enroll this installation once.
The hidden prompt keeps the token out of shell history and Docker environment
metadata. The CLI validates the account and label before atomically saving an
owner-only `0600` config file:

```bash
mkdir -p "$HOME/.config/assurance-scan" "$HOME/.cache/assurance-scan" && \
  chmod 700 "$HOME/.config/assurance-scan" "$HOME/.cache/assurance-scan"
docker run --rm -it --pull=always \
  --user "$(id -u):$(id -g)" \
  -v "$HOME/.config/assurance-scan:/config" \
  ghcr.io/26457513/assurance-scan-cli:stable \
  auth login --url https://scan.example.com
```

Then run this from the Git repository root:

```bash
docker run --rm -it --pull=always --init \
  --user "$(id -u):$(id -g)" --group-add 0 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
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

The command above is for macOS Docker Desktop. On Linux, replace
`--group-add 0` with
`--group-add "$(stat -c '%g' /var/run/docker.sock)"`. The CLI retains the host
user's identity for owner-only config/cache files while receiving only the
supplemental group needed to reach the Docker socket. Native Windows and WSL 2
are not v1 targets; use a supported host rather than adapting the command.
The exact copyable commands are also available under
**Setup → My account → Local scanner**.

`--pull=always` is the update check; unchanged layers are reused. For controlled
environments, replace `stable` with an immutable version or registry digest.
Use `scan --no-upload` to retain a bundle locally, `upload --retry REQUEST_ID`
to retry without rescanning, and `cache list`/`cache prune` to manage retained
bundles. The default outbox policy is seven days and 1 GiB. Revoking the token
in Settings prevents future uploads; `auth logout` removes local credentials
while preserving the non-secret installation ID.

The CLI uploads repository metadata, normalized findings, SARIF, and the
CycloneDX SBOM—not the source snapshot or absolute host paths. The upload token
stays in the outer CLI and is never passed to scanner containers. Semgrep,
Gitleaks, and Syft run with Docker networking disabled; Trivy, Grype, and
OSV-Scanner use bridge networking so they can refresh vulnerability databases.
The server retains raw artifacts for
30 days, normalized runs/findings for 365 days, and inactive-token audit data
for 400 days. Deleting a run or project removes its scan data; a content-free
request tombstone may remain for 30 days to prevent unsafe idempotency-key reuse.

## Adding another organisation

The instance polls the home org (`GITHUB_ORG`) plus every organisation
registered in **Settings → GitHub organisations**. An org's complete
onboarding:

1. **Register the org** (Settings → GitHub organisations): org name + a
   fine-grained PAT owned by that org (Contents:Read; Actions:Read — plus
   Actions:Write if the org's repos should support the UI's *Scan now*
   button). Verified and stored encrypted on save; the poller picks up its
   repos on the next cycle.
2. **Per repo**: copy `templates/assurance-scan.yml` into
   `.github/workflows/`, keep `ASSURANCE_SCAN_URL` pointing at this
   instance, set the default branch in `push.branches`. The scanner image is
   public — no GHCR grants or secrets needed.
3. Runs appear in the shared UI within a minute; deep links work the same
   as for the home org. Identity is org-qualified (`github:{owner}/{repo}`),
   so projects never collide across orgs.

Auth today is the home org's Google Workspace; external users use the Basic
Auth fallback until multi-tenant SSO arrives. The scanner image
(`assurance-scan-ci`) is public; the **app image** (`assurance-scan-app`)
stays private to the product owner.

## On-demand scans from the UI

*Scan now* on any project page (repo prefilled, any `owner/repo` accepted,
optional branch/SHA) dispatches the repo's own `assurance-scan` workflow —
the run executes on that repo's compute. Every scan runs on the target
repo's own Actions minutes; this instance never executes scans.

**Token requirements** — workflow dispatch needs a token with
**Actions: Read and write** on the target repo. Resolution order:

1. the signed-in user's personal token (**Settings**, encrypted at rest),
2. the target org's registered token (if it was granted Actions:Write),
3. the home-org token (`GITHUB_POLL_TOKEN` — grant it Actions:Read+Write
   in the fine-grained token editor to make the button work org-wide).

A `503/502 … 403 Forbidden` from the button means the resolved token is
read-only: widen it per the list above (editing a PAT's permissions
doesn't change its value — the server picks it up immediately).

Repos without the stub are refused with setup guidance (copy
`templates/assurance-scan.yml` from the public
`assurance-scan-ci` repo; delete the `push`/`pull_request` triggers for a
manual-only variant that costs nothing until clicked).

## Scanner set

| Tier | Scanners |
|---|---|
| Always | semgrep (code), gitleaks (secrets), trivy-fs + grype + osv-scanner (dependencies), trivy-config (IaC/Dockerfile), syft (SBOM) |
| With a Dockerfile | trivy-image (built image) |

All run as reviewed stock public images pinned by immutable multi-architecture
digests. GitHub Actions and the public local CLI consume the same scanner
release-set manifest; a promoted CLI release advances the tested set.

## MCP server

The server exposes an MCP endpoint (`/mcp`) with scan management, catalogue
and mapping tools, and agent workflows (`generate-fr-catalogue`,
`scan-and-propose-fixes`, …) — the bridge for agentic workflows.
