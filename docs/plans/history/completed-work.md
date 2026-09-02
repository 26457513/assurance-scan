# Completed work

This file is a compact historical record. Current design decisions live in the other plan folders and take precedence.

## WSQ — codebase quality baseline

Completed the backend/frontend restructuring, architecture boundaries, lint and type cleanup, security findings, and root-folder reduction. The recorded checkpoint was commit `7fc8e40`. The quality run covered Ruff, Mypy, pytest, Semgrep, frontend tests, checks, and build.

## WS1 — local scan domain contracts

Added canonical repository identity, local run identity, branch and dirty-worktree metadata, token records, and contract tests. Historical verification recorded 396 backend tests and Mypy coverage across 169 files.

## WS2 — local authentication and upload

Added machine-token issuance, hashing, revocation, expiry, upload authorization, idempotency, quotas, and audit behavior. Historical verification recorded 446 backend tests and Mypy coverage across 188 files.

## WS3 — scanner container and CLI runtime

Added the public container workflow, local configuration, repository discovery, scanner orchestration, result bundling, retries, recovery, and release automation. Historical verification recorded 500 backend tests and Mypy coverage across 220 files.

## WS4 — local scan UI integration

Added local-origin run display, compact issued-token management, branch and dirty-state presentation, and navigation/access refinements. Historical verification recorded 500 backend tests, Mypy across 220 files, and 23 frontend tests.

## WS5 — initial rollout preparation

Completed the original rollout implementation and local end-to-end exercise. Subsequent design decisions replaced GitHub polling with the GitHub App and OIDC push-only model, so any polling-era rollout detail is obsolete and intentionally omitted here.

Historical counts are evidence from their checkpoints, not the current expected test totals. The current release must pass [Quality gates](../delivery/quality-gates.md).
