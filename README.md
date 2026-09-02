# Assurance Scan

Assurance Scan gives teams one project history for security scans produced by GitHub Actions and by developers working locally.

## Operating model

GitHub is the identity and repository-authorization authority:

- people sign in with the Assurance Scan GitHub App;
- an installation administrator selects the organisations or repositories covered by the App;
- the UI shows a person only projects that GitHub currently lets that person access;
- expiring GitHub user authorization is refreshed server-side and reverified by numeric user ID;
- GitHub Actions scans the default branch after a direct push or merged pull request;
- Actions pushes results directly to Assurance Scan with GitHub-issued OIDC identity;
- the server never polls Actions, downloads result artifacts, or stores a PAT;
- local scan uploads use Assurance Scan tokens and remain visible only to the uploader.

Feature branches are normally scanned locally. Pull-request branches are not scanned by the shared workflow; merging a pull request creates the default-branch push that is scanned.

## Repository layout

- `backend/app/modules/atomic` — small framework-free policy and transformation modules
- `backend/app/modules/workflows` — application workflows composed from atomic modules
- `backend/app/modules/shared` — contracts shared across workflows
- `backend/app/infrastructure` — database, GitHub and runtime adapters
- `backend/app/api` — thin HTTP adapters
- `frontend` — SvelteKit UI
- `backend/resources` — scanner, workflow and policy assets
- `docs/plans` — active delivery design

## Local development

```bash
cp .env.example .env
mkdir -p .secrets
# Save the development GitHub App private key as .secrets/github-app.pem.
docker compose up -d --build
```

The development GitHub App needs this callback URL:

```text
http://localhost:8742/auth/github/callback
```

Set `GITHUB_APP_ACCESS_ENABLED=true` only after the App ID, client credentials, slug, private key, public URL and token-encryption key are configured. `GITHUB_ADMIN_USER_IDS` is a comma-separated list of immutable GitHub numeric user IDs; those accounts receive the protected `admin` role on first sign-in.

Open [http://localhost:8742/setup](http://localhost:8742/setup), continue with GitHub, then install or update the App for the selected repositories.

## Local scans

After signing in and gaining upload access to at least one installed repository:

1. Open Setup and create a machine-labelled local scan token.
2. Follow the copyable bootstrap command shown there to save the token locally.
3. Run the copyable scan command from a checkout.

The public CLI container resolves a signed release, runs the pinned scanner images against the checkout, captures bounded source context, and uploads the normalized result to the same project identity used by GitHub Actions.

## GitHub Actions

Setup serves the standard workflow for an installed repository. It triggers only for pushes to that repository's default branch and uses GitHub OIDC to upload results; no Assurance Scan token is added to repository secrets.

The GitHub App production callback is:

```text
https://scan.squease.ai/auth/github/callback
```

Webhook delivery is configured separately at:

```text
https://scan.squease.ai/api/v2/github/webhook
```

## Production configuration

The manual production deployment uses the protected GitHub Environment named `production`. It refuses to stop the service unless all required configuration validates, then installs a root-only runtime release under `/root/assurance-scan-runtime` and mounts the private key read-only.

Environment secrets:

- `APP_CLIENT_SECRET`
- `APP_PRIVATE_KEY_B64`
- `APP_SESSION_SECRET`
- `APP_TOKEN_ENCRYPTION_KEY`
- `APP_WEBHOOK_SECRET`
- `APP_MCP_TOKEN` (optional)

Environment variables:

- `APP_CLIENT_ID`, `APP_ID`, `APP_SLUG`
- `APP_PUBLIC_BASE_URL=https://scan.squease.ai`
- `APP_DOMAIN=scan.squease.ai`
- `APP_ADMIN_GITHUB_IDS`
- `APP_ACCESS_ENABLED`
- `APP_WEBHOOK_ENABLED`
- `APP_OIDC_INGEST_ENABLED`
- `APP_LOCAL_INGEST_ENABLED`
- `APP_SCAN_TOKEN_CREATION_ENABLED`
- `APP_LOG_LEVEL=INFO`, `APP_PARALLELISM=4`

`DEPLOY_SSH_KEY` remains a repository or environment secret used only to reach the deployment host. Runtime secrets are never committed and the Droplet's legacy `.env` is not used by the deployment.

## Quality gate

```bash
QUALITY_GATE_PYTHON=backend/.venv/bin/python backend/scripts/quality-gate.sh
```

The gate runs backend and frontend tests, Ruff, Mypy, Semgrep, builds, migration checks and container validation. See `docs/plans/delivery/quality-gates.md` for release evidence.
