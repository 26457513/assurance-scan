# Assurance Scan

Security scanning and compliance assurance for codebases, centred on a hosted
dashboard. Scans run on GitHub Actions compute; the server polls results in
and serves a team UI with findings, FR catalogues, and compliance workflows
built around the OWASP **ASVS** standard.

**The model in one picture:**

```
org repos ──push──▶ GitHub Actions ──scan──▶ artifact (SARIF/SBOM/findings)
   (any org)             │                              │
   ▲ workflow_dispatch   │ reusable workflow (home org) │ poll (60s, all orgs)
   │                     │ or vendored stub (any org)   ▼
   │                                             droplet (server+UI+SQLite)
  UI "Scan now"  ◀──────────────────────────────────────  poller
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
| `server/` | FastAPI app: projects registry, scans/findings, FR catalogues, poller, auth |
| `frontend/` | SvelteKit UI (served by the server container) |
| `Dockerfile.ci` | Slim scanner orchestrator (glue only; scanners run as stock public images) |
| `Dockerfile` | Full app image (server + built frontend) |
| `compose.yaml` | Local + cloud deployment (identical containers) |
| `assurance-scan-ci` (public repo) | Reusable CI workflow + vendored template for any org |
| `scripts/ci-scan.py` | Standalone scanner CLI (no server, no DB) |
| `templates/assurance-scan.yml` | Vendored stub for repos outside the home org |

Design notes live in `docs/plan-*.md`.

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
working tree), merge to `main` when happy — merges deploy automatically (see
below). Tests: `python3 -m pytest tests/ -q`; frontend:
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
GITHUB_POLL_TOKEN=<fine-grained PAT: home-org owner, Actions+Contents read>
GITHUB_ORG=26457513            # home org; others are registered in the UI
DOMAIN=scan.yourdomain.com
GOOGLE_CLIENT_ID=<OAuth client>        # auth: Google Workspace login
GOOGLE_CLIENT_SECRET=<...>
GOOGLE_DOMAIN=yourdomain.com
SESSION_SECRET=<random 32+ chars>
PUBLIC_BASE_URL=https://scan.yourdomain.com
TOKEN_ENCRYPTION_KEY=<random 32+ chars>   # encrypts user + org tokens
# APP_AUTH_USER / APP_AUTH_PASSWORD      # optional Basic Auth fallback
```

### Google login setup

Google Cloud console (Workspace account): OAuth consent screen → User type
**Internal** → Credentials → OAuth Client (Web application) → redirect URI
`https://<host>/auth/callback`. Only `@<your-domain>` accounts can sign in;
an already-logged-in browser gets one silent redirect. `/auth/logout` signs
out. Basic Auth (the two `APP_AUTH_*` vars) remains valid for curl/API use.

### Deploying updates

Merging `develop → main` and pushing: `publish-app-image` builds and pushes
`ghcr.io/26457513/assurance-scan-app`, then the deploy job SSHes the droplet
(`DEPLOY_SSH_KEY` repo secret) to `git pull && docker compose pull && up -d`.
A 5-minute cron on the droplet is the safety net; `@daily docker system
prune` keeps the disk clear. Small droplets must never build locally.

**Backup**: the SQLite file in the `assurance-data` volume is the only copy
of catalogues, registry, and waivers — schedule a daily `docker cp` + copy
off-box.

## Adding CI scanning to a repo

Add `.github/workflows/assurance-scan.yml` to the repo — the same stub for
every org, home or external (the referenced repo and image are public):

```yaml
name: assurance-scan
on:
  workflow_dispatch:
  pull_request:
    types: [opened, synchronize]
  push:
    branches: [<default branch>]
permissions:
  contents: read
  actions: write
  pull-requests: write
jobs:
  scan:
    uses: 26457513/assurance-scan-ci/.github/workflows/scan.yml@main
```

Orgs whose Actions policy blocks external references use the self-contained
copy at `github.com/26457513/assurance-scan-ci` → `templates/assurance-scan.yml`.
No GHCR grants or secrets are needed — the scanner image is public.

Each run produces a Step Summary (per-tool severity matrix, runtimes, deep
link to the hosted UI) and an `assurance-scan-results` artifact (SARIF,
CycloneDX SBOM, `findings.json`). Repos with a root `Dockerfile` also get a
Trivy image scan of the build. Scans never fail the workflow.

## Adding another organisation

The instance polls the home org (`GITHUB_ORG`) plus every organisation
registered in **Settings → GitHub organisations**. An org's complete
onboarding:

1. **Register the org** (Settings → GitHub organisations): org name + a
   fine-grained PAT owned by that org (Actions+Contents read on its repos).
   Verified and stored encrypted on save; the poller picks up its repos on
   the next cycle.
2. **Per repo**: copy `templates/assurance-scan.yml` into
   `.github/workflows/`, keep `ASSURANCE_SCAN_URL` pointing at this
   instance, set the default branch in `push.branches`. The scanner image is
   public — no GHCR grants or secrets needed.
3. Runs appear in the shared UI within a minute; deep links and *Scan now*
   (via any user token that can write Actions there) work the same as for
   the home org. Identity is org-qualified (`github:{owner}/{repo}`), so
   projects never collide across orgs.

Auth today is the home org's Google Workspace; external users use the Basic
Auth fallback until multi-tenant SSO arrives. The scanner image
(`assurance-scan-ci`) is public; the **app image** (`assurance-scan-app`)
stays private to the product owner.

## On-demand scans from the UI

*Scan now* on any project page (repo prefilled, any `owner/repo` accepted,
optional branch/SHA) dispatches the repo's own `assurance-scan` workflow —
the run executes on that repo's compute. Token resolution: the signed-in
user's token (**Settings**, encrypted at rest) → the org's registered
token → the home-org token; dispatch needs Actions:Write. Repos without
the stub are refused with setup guidance (copy
`templates/assurance-scan.yml`; delete the `push`/`pull_request` triggers
for a manual-only variant that costs nothing until clicked).

## Scanner set

| Tier | Scanners |
|---|---|
| Always | semgrep (code), gitleaks (secrets), trivy-fs + grype + osv-scanner (dependencies), trivy-config (IaC/Dockerfile), syft (SBOM) |
| With a Dockerfile | trivy-image (built image) |

All run as their stock public images via the docker socket — always current
at run time. Local equivalent: `python3 scripts/ci-scan.py <path> --sarif
out.sarif [--image app:local]` (needs Docker; no server, no DB).

## MCP server

The server exposes an MCP endpoint (`/mcp`) with scan management, catalogue
and mapping tools, and agent workflows (`generate-fr-catalogue`,
`scan-and-propose-fixes`, …) — the bridge for agentic workflows.
