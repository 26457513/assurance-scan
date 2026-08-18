# Plan: assurance-scan on GitHub compute with SARIF results (Phase 1)

Status: draft for review — 2026-08-18

## Roadmap position

Three agreed phases; this doc covers phase 1 only:

1. **[this doc]** Scans run on GitHub Actions compute; results display in the
   GitHub UI (Security tab + inline PR annotations) via SARIF.
2. Push run results from CI to the assurance-scan API + deep link from the
   GitHub UI back to the run-detail page.
3. Local agent bridge (outbound connection) for UI-driven local scans and
   agentic workflows. Deferred until phase 2 proves demand.

## Objective

A GitHub Actions workflow in a target repo that:

- runs the assurance-scan scanner set against the checkout on GitHub-hosted
  compute (`ubuntu-latest`),
- emits one unified SARIF file, publishes a GitHub Step Summary
  (counts + top findings) and uploads the SARIF as a workflow artifact,
- is non-blocking: findings never fail the workflow; scanner failures are
  logged and skipped, matching current orchestrator semantics.

## Non-goals (phase 1)

- No catalogue / FR evaluation / project tests — those need the DB and stay
  server-side. SARIF carries scanner findings only.
- No push to the assurance-scan API, no deep links (phase 2).
- No fail-on-severity gating (add later only if wanted).
- No Actions caching of scanner DBs (add when runtimes actually hurt).

## What we already have (and reuse unchanged)

The scan execution path is already free of DB/server coupling:

- `server/worker/scanners.py` — declarative `ScannerConfig` per scanner
  (image, command, mounts, exit codes). Stdlib only.
- `server/worker/runner.py` — `DockerRunner` spawns scanner containers via
  the `docker` CLI. Ubuntu hosted runners ship docker preinstalled.
- `server/worker/parsers/*` — normalize each scanner's output to
  `ParsedFinding` (rule_id, severity, file_path, line, message, tags).
  Stdlib only.

Only `ScanOrchestrator` couples to the DB. Phase 1 bypasses it entirely —
nothing existing needs refactoring; we add one new entry script.

## Design

### 1. New script: `scripts/ci-scan.py`

Stdlib-only CLI (no pip install on the runner):

```
python3 scripts/ci-scan.py <project_path> --sarif out.sarif
```

Behavior:

- Run the **CI scanner subset** — all `CODE_SCANNERS` except `trivy-image` by
  default: semgrep, gitleaks, trivy-fs, trivy-config, syft (SBOM artifact),
  grype, osv-scanner. With `--image <tag>`, trivy-image runs against that
  image; the workflow builds it from the root Dockerfile when present
  (`ci_scanner_set()` in `server/worker/scanners.py`).
- Drive them with `DockerRunner` + `parser_for` exactly as the orchestrator
  does; collect `ParsedFinding` rows in memory (no DB).
- Emit one unified SARIF file and print a summary (counts by scanner and
  severity) to the log.
- Always exit 0 unless the script itself is broken. Scanner failures are
  logged with stderr context and counted in the summary.
- Constraint to hold in review: the import graph of `ci-scan.py` must never
  touch `server.db`, `server.api`, or `server.config` — if a parser grows a
  heavy import later, that's a regression against this plan.

### 2. SARIF shape (one tool, one run)

- `tool.driver.name = "assurance-scan"`; one `rules[]` entry per distinct
  `(scanner_kind, rule_id)`, falling back to the scanner kind when a finding
  has no rule id.
- `results[]` = one entry per finding:
  - `ruleId` → `{scanner_kind}/{rule_id}`
  - `level` → severity mapping below
  - `message.text` → finding message
  - `locations[0].physicalLocation` → repo-relative `file_path` +
    `region` (start/end line). Parsers already store repo-relative paths.
  - `partialFingerprints.primaryLocationLineHash` →
    `sha256(ruleId|file_path|line_start)[:16]` so GitHub tracks/dedups the
    same finding across commits and runs.
  - `properties` → scanner kind, theme, compliance tags (visible in the
    alert detail; harmless if GitHub ignores them).

Severity → SARIF level, plus `security-severity` on the rule for GitHub's
severity filters:

| our severity | SARIF level | security-severity |
|---|---|---|
| CRITICAL | error | 9.5 |
| HIGH | error | 8.0 |
| MEDIUM | warning | 5.0 |
| LOW / INFO / UNKNOWN | note | 2.0 |

### 3. Reusable workflow (lives in the assurance-scan repo)

`.github/workflows/scan.yml` in the assurance-scan repo, triggered by
`workflow_call`, holds all scanner invocation logic:

```yaml
on: [workflow_call]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4                      # caller's code
      - uses: actions/checkout@v4
        with:
          repository: 26457513/assurance-scan
          path: assurance-scan                          # scanner code
          # Private cross-repo checkout — caller's GITHUB_TOKEN can't read
          # sibling private repos, so callers pass the org secret via
          # `secrets: inherit`.
          token: ${{ secrets.ASSURANCE_SCAN_TOKEN }}
      - run: python3 assurance-scan/scripts/ci-scan.py . --sarif assurance.sarif
        # ci-scan.py also writes the GitHub Step Summary ($GITHUB_STEP_SUMMARY)
      - uses: actions/upload-artifact@v4
        with:
          name: assurance-sarif
          path: assurance.sarif
        if: always()
```

(In a reusable workflow, a bare `actions/checkout` checks out the **caller's**
repo — only the scanner code needs the explicit second checkout.)

## Adoption: how a project gets scanned

Per-repo opt-in. The user's entire setup is a stub in their repo:

```yaml
name: assurance-scan
on: [pull_request, push]
jobs:
  scan:
    uses: 26457513/assurance-scan/.github/workflows/scan.yml@main
    secrets: inherit   # provides ASSURANCE_SCAN_TOKEN
```

**One-time org setup (UI):** create a fine-grained PAT (Contents: Read-only,
scoped to the assurance-scan repo only) and add it as an org Actions secret
`ASSURANCE_SCAN_TOKEN` (org Settings → Secrets and variables → Actions →
available to all repositories). Without it the job can't check out the
private scanner repo. Note: anyone triggering the caller workflow also needs
read access to the assurance-scan repo to resolve the reusable workflow
reference — a non-issue while the org is just you.

Scanner updates propagate from the assurance-scan repo without touching
caller repos.

Not org-wide automatic, deliberately: GHAS licensing is per-private-repo,
blanket alerts create noise on repos that didn't ask, and org "required
workflows" are name-pattern blunt instruments. If enforcement is ever wanted,
org-level required workflows can mandate the same reusable workflow later.
Phase 2 note: once runs are pushed to the API, the server can auto-register
a project on first sight of an unknown repo — adoption tracking for free.

Runner behaviour to expect (fine for phase 1, noted so nobody's surprised):

- Docker cache volumes start empty each run → trivy/grype download their DBs
  and osv-scanner queries the OSV API on first scan. Expect roughly 5–10 min
  per cold run.
- `semgrep --config auto` works anonymously but is rate-limited;
  `SEMGREP_TOKEN` as an optional secret improves it.
- Gitleaks runs with `--no-git` (scans the working tree as-is) — correct for
  a checkout.

## Verification

1. Local: run `scripts/ci-scan.py . --sarif /tmp/out.sarif` against this
   repo; assert findings counts match a server-side scan of the same commit.
2. Validate the SARIF parses (`python3 -c "import json;json.load(open(...))"`
   plus schema spot-checks; a `@microsoft/sarif-multitool validate` run
   locally if we want to be strict).
3. Trial run on a private target repo in the org: Step Summary renders,
   artifact downloads, re-runs are stable (fingerprints present for the
   GHAS-enabled future).

## Open questions (decide at review)

1. **Events:** `pull_request` + `push` to main (no double-runs), or every
   branch push as the user originally said?
2. ~~GHAS~~ **Resolved (2026-08-18):** all repos private under org
   `26457513` on the free plan — no GHAS. Display = Step Summary + SARIF
   artifact (as now designed above). Revisit GHAS only if the native
   Security tab becomes a hard requirement.
3. **Versioning the reusable workflow:** pin callers to `@main` (always
   current) vs a moving tag like `@v1` (controlled rollouts). Recommend
   `@main` until more than a couple of repos consume it.
4. **Noise level:** do we ship all findings, or filter (e.g. drop LOW/INFO)
   in the SARIF to keep PR annotations focused? The UI keeps everything
   either way in phase 2.
