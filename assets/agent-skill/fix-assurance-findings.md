---
description: Read the latest assurance-scan findings, plan fixes, and open PRs
allowed-tools: Read, Edit, Write, Bash, Grep, Glob, TaskCreate, TaskUpdate
---

# Fix assurance-scan findings

You are working in the user's repo. Assurance-scan has just published a `findings.json` from a prior scan. Your job is to read it, summarise it, plan fixes, get the user's approval, implement, test, and open PR(s) — without ever committing the report files themselves.

## Step 1 — Locate the findings file

Resolve in this order:
1. `.assurance-scan/findings.latest.json` (preferred — written by every publish)
2. Otherwise: `find .assurance-scan/reports -maxdepth 2 -name findings.json | sort | tail -1 | xargs cat`

If neither exists, tell the user to run the scanner with `--publish-findings` first, and stop.

## Step 2 — Read and summarise

Read the JSON. Surface exactly these blocks to the user, in this order:

```
Scan: <run_id> on branch <git_branch> @ <git_commit>
Total findings: N across D files
Severity:  C critical | H high | M medium | L low | U unknown
Strategy:  A auto | S assisted | M manual
PR plan:   <single> or <themed: N themes>
Scanner:   semgrep N | gitleaks N | trivy-config N
Themes:    <list each theme with its count>
```

Then in 3–5 bullets, name the dominant problem classes (e.g. "eval sinks in src/auth/", "hardcoded credentials in tests/", "insecure TLS in 2 Dockerfiles"). Be concrete with paths.

## Step 3 — Propose the fix plan

- If `summary.pr_strategy == "single"`: propose ONE PR covering all findings. Group the work by theme even though it ships as one PR.
- If `summary.pr_strategy == "themed"`: propose ONE PR per theme, sequenced by severity-weighted count (highest first).

For each PR, list:
- Title (e.g. "fix(security): eliminate eval sinks in auth module")
- Finding IDs covered (use the `id` field from findings.json)
- Files touched
- Approach (one sentence per finding — what's the root-cause fix?)

**Manual findings:** never auto-pursue `fix_strategy == "manual"`. Surface them in a separate "Needs human action" block. Document what the human must do (e.g. rotate a credential, rewrite history). Only proceed with them after explicit user confirmation in chat.

**Assisted findings:** propose, but flag in the plan that they need user judgement (e.g. major version bumps, TLS version choices, Dockerfile USER changes).

## Step 4 — Ask for approval

Do not edit anything until the user approves the plan. Ask which PR(s) to proceed with. Suggested phrasing:

> Plan ready. Shall I proceed with PR #1 (`<title>`) covering N findings? Reply "yes" / "yes all" / "no" / "modify".

## Step 5 — Implement

For each approved PR, in order:

1. **Create a branch:** `git checkout -b fix/<theme>` from the user's current branch (don't branch from main unless that's where they are).
2. **Implement minimal diffs.** Follow these rules strictly:
   - Fix the root cause, not the symptom. No suppressions, `// noqa`, `# nosec`, or rule-level disables unless the finding is a false positive (and then document why in the PR body).
   - No refactoring beyond what the fix requires. No drive-by renames. No "while I'm here" changes.
   - One commit per finding (or per logical unit if findings are tightly related). Commit messages: `fix(<scope>): <rule_id> — <one-line>`.
3. **Test:** discover the project's test command and run it (`pytest`, `npm test`, `yarn test`, `go test ./...`, `cargo test`, etc.). Look at `package.json`, `pyproject.toml`, `go.mod`, `Makefile`. If tests fail, fix the implementation — do not skip the tests.
4. **Verify git state:** run `git status --porcelain`. Confirm NOTHING under `.assurance-scan/` is staged. If it is, unstage it — those files are gitignored and must never be committed.
5. **Push and open PR:**
   ```
   git push -u origin fix/<theme>
   gh pr create --title "<title>" --body "<body>"
   ```
   PR body must include:
   - Summary (2–3 lines)
   - Findings fixed (bullet list of `id` + `rule_id` + `file:line`)
   - Test command run + result
   - Any `assisted` judgement calls the reviewer should confirm

## Step 6 — Report back

For each PR opened, post:
- PR URL
- Findings covered (count + IDs)
- Anything the reviewer must confirm (manual/assisted items)

## Hard rules

- Never commit anything under `.assurance-scan/`.
- Never push without explicit user approval.
- Never attempt git history rewrites, force-pushes, or `gh pr edit` on existing PRs without confirmation.
- If the scanner emitted zero findings: tell the user "clean scan, nothing to fix" and stop.
- If a finding references a file the agent can't find at the reported path (path drift between runs), surface it and ask — don't guess.
