# Assurance Scan

Security scanning and compliance assurance for codebases, centred on a hosted
dashboard. Scans run on GitHub Actions compute; the server polls results in
and serves a team UI with findings, FR catalogues, and compliance workflows
built around the OWASP **ASVS** standard.

**The model in one picture:**

```
GitHub repos  ──push──▶  GitHub Actions  ──scan──▶  artifact (SARIF/SBOM/findings)
     ▲                                                    │
     │ workflow_dispatch / scan-remote runner             │ poll (60s)
     │                                                    ▼
  UI "Scan now"  ◀────  droplet (server + UI + SQLite)  ── poller
```

- **CI tier** — repos with a 6-line stub scan every push and PR; results
  appear in GitHub (Step Summary, PR comment, deep link) *and* the UI.
- **Instant tier** — *Scan now* in the UI scans any repo your GitHub token
  can read, with zero footprint on that repo.

## Architecture

| Piece | What it is |
|---|---|
| `server/` | FastAPI app: projects registry, scans/findings, FR catalogues, poller, auth |
| `frontend/` | SvelteKit UI (served by the server container) |
| `Dockerfile.ci` | Slim scanner orchestrator (glue only; scanners run as stock public images) |
| `Dockerfile` | Full app image (server + built frontend) |
| `compose.yaml` | Local + cloud deployment (identical containers) |
| `.github/workflows/scan.yml` | Reusable CI workflow used by org repos |
| `.github/workflows/scan-remote.yml` | Runner for on-demand scans of external repos |
| `scripts/ci-scan.py` | Standalone scanner CLI (no server, no DB) |

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
GITHUB_POLL_TOKEN=<fine-grained PAT: org owner, Actions+Contents read>
GITHUB_ORG=26457513
DOMAIN=scan.yourdomain.com
GOOGLE_CLIENT_ID=<OAuth client>        # auth: Google Workspace login
GOOGLE_CLIENT_SECRET=<...>
GOOGLE_DOMAIN=yourdomain.com
SESSION_SECRET=<random 32+ chars>
PUBLIC_BASE_URL=https://scan.yourdomain.com
TOKEN_ENCRYPTION_KEY=<random 32+ chars>   # encrypts user GitHub tokens
RUNNER_PULL_TOKEN=<random 24+ chars>      # shared with scan-remote.yml
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

One-time org setup: (1) `assurance-scan` repo → Settings → Actions → Access →
"Accessible from repositories in \<org\>"; (2) Actions policy → allow all;
(3) after the first `publish-ci-image` run, grant repos access to the
`assurance-scan-ci` GHCR package (package settings → Manage Actions access →
role Read).

Then add `.github/workflows/assurance-scan.yml` to the repo:

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
  packages: read       # scanner image from org GHCR
  actions: write
  pull-requests: write
jobs:
  scan:
    uses: 26457513/assurance-scan/.github/workflows/scan.yml@main
```

Each run produces a Step Summary (per-tool severity matrix, runtimes, deep
link to the hosted UI) and an `assurance-scan-results` artifact (SARIF,
CycloneDX SBOM, `findings.json`). Repos with a root `Dockerfile` also get a
Trivy image scan of the build. Scans never fail the workflow.

## Running assurance-scan for another organisation (self-hosted)

Each organisation runs its own instance — findings, tokens, and code never
leave that organisation's infrastructure. Their complete setup:

1. **Deploy their instance**: follow the droplet recipe above with their own
   values — `GITHUB_ORG`, their GitHub PAT (fine-grained, org-owned,
   Actions+Contents read; Actions **write** too if they want *Scan now*),
   their Google Workspace domain for login, their `DOMAIN`/DNS.
2. **Per repo**: copy `templates/assurance-scan.yml` into
   `.github/workflows/`, set `ASSURANCE_SCAN_URL` to their instance, and set
   the default branch in `push.branches`. The scanner image is public — no
   GHCR grants or secrets needed.
3. Runs appear in their UI within a minute (their poller, their org); deep
   links in PR comments point at their instance.

The scanner image (`assurance-scan-ci`) is public glue over open-source
scanners. The **app image** (`assurance-scan-app`, the server + UI) stays
private to the product owner — other organisations get access to run it
under licence, or build from source access. That's the commercial surface,
not a technical one.

## On-demand scans from the UI

*Scan now* on any project page (repo prefilled, any `owner/repo` accepted,
optional branch/SHA). Repos with the stub dispatch it directly; everything
else runs through `assurance-scan-remote` in the assurance-scan repo, which
pulls the target's code from the server's tarball proxy — user GitHub tokens
(encrypted at rest, added in **Settings**) never enter GitHub Actions, and
the target repo sees nothing.

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
