# Plan: GitHub-centric UI (Phase 3)

Status: draft for review — 2026-08-18
Follows: `plan-github-actions-sarif.md` (phase 1), `plan-github-polling-ingest.md`
(phase 2) — both shipped.

## Objective

The UI treats GitHub repos as the primary project kind: the org's repos are
listed as projects, each repo shows the scans pulled from GitHub, and each
scan renders findings VS Code-SARIF-viewer-style — anchored to the actual
source lines. Local-folder projects remain as a second mode, untouched.

## Model

- GitHub Actions runs are the **source of truth**; the local DB is an
  index/cache over them. Deleting scans locally and re-polling repopulates
  them — accepted behavior (see caveat below).
- Caveat to respect later: waivers/finding-acceptances are run-scoped today;
  delete-and-repoll would destroy them. Don't surface "delete + repoll" as a
  promoted flow, and re-key enrichment to fingerprints when it matters.

## Design

### 1. Org repos as projects

- New env `GITHUB_ORG` (default `26457513`). The poller drops its repo list:
  it resolves repos from `GET /orgs/{org}/repos` (cached ~1h); `POLL_REPOS`
  remains as an optional manual override.
- New endpoint `GET /api/github/repos` — org repos (name, pushed_at), merged
  client-side with local-path projects from `/api/projects`. GitHub repos
  with no scans yet still appear (empty until their first CI run is polled).
- Projects page: GitHub section (repo cards/rows) + local section. Selecting
  a GitHub repo opens the existing project view parameterized with
  `github:{owner}/{repo}` — the scans tab already works against that key.

### 2. Scans per repo

No new backend work: `Run.project_path = "github:{owner}/{repo}"` +
`listScans` filtering already delivers this. Only wiring in the projects
page (slug ⇄ `github:owner/repo` encoding).

### 3. Source peek (the one new server capability)

- `GET /api/github/source?repo=&commit=&path=&line=` →
  server fetches `GET /repos/{repo}/contents/{path}?ref={commit}` with the
  poll token (private repos readable), returns a window of lines around
  `line` (default ±3) as text plus the highlight range.
- Response is sha-keyed and immutable → in-memory LRU cache, no DB storage.
- 404/403 (file gone, path moved) degrades to "source unavailable" in the
  UI; findings still render without code context.

### 4. Findings view, SARIF-inspector style

- The run detail findings list gains: severity/scanner filters (mostly
  exists), and each finding row expands to a code-context strip — the peeked
  lines with the offending line highlighted, plus a `file:line` link.
- This augments the existing findings UI; no replacement of ScanDetail.

## Non-goals

- No fix/edit flows, no PR comments from the UI, no webhook realtime.
- Local scan flow (MCP, catalogues, FRs) unchanged.
- No storage of file contents in the DB (peek is cached, not persisted).

## Verification

1. Unit: source-peek parsing (window slicing, highlight range) with a
   fixture; poller org-discovery resolution.
2. E2E: projects page lists org repos; doc2context shows its scans; open a
   finding → code context renders with the correct line highlighted against
   the run's commit; a moved/deleted path degrades gracefully.

## Decisions (resolved at review, 2026-08-18)

1. `GITHUB_ORG` is a `.env` variable (documented in `.env.example`);
   unset → no GitHub section, local projects unaffected.
2. Code window stays ±3 lines.
3. Projects page shows **both** kinds from day one: local folders and
   GitHub repos.
