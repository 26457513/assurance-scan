#!/usr/bin/env python3
"""Generate an agent-ready investigation/fix prompt.

The prompt distils the actual findings from a completed scan bundle into an
ordered investigation plan. An agent (Claude Code, GPT, etc.) can pick up the
prompt and start fixing issues without re-reading every raw report.

Output: <report_dir>/agent-investigation-prompt.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from textwrap import dedent


SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}


def load_json(p: Path):
    try:
        if p.exists() and p.stat().st_size > 0:
            return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None
    return None


def top_secrets(gitleaks_path: Path, limit: int = 10) -> list[dict]:
    """Return the most actionable leaked-secret findings.

    Heuristic: prefer secrets in source code over those in .env files (which
    are typically local-only), and group by file.
    """
    data = load_json(gitleaks_path)
    if not isinstance(data, list):
        return []
    findings = []
    for f in data:
        path = f.get("File", "?")
        rule = f.get("RuleID", "?")
        line = f.get("StartLine", "?")
        # Don't leak the actual secret value into the prompt — mask it.
        secret = f.get("Secret", "") or ""
        masked = secret[:6] + "…" + secret[-4:] if len(secret) > 12 else "（redacted）"
        path_upper = path.upper()
        is_creds_file = (
            ".ENV" in path_upper
            or "CREDS" in path_upper
            or "SECRETS" in path_upper
            or path_upper.endswith((".PEM", ".KEY", ".PFX", ".P12"))
        )
        category = "creds-file" if is_creds_file else "source"
        findings.append({
            "path": path,
            "line": line,
            "rule": rule,
            "category": category,
            "masked": masked,
        })
    # Sort: source code secrets first, then by path
    findings.sort(key=lambda x: (x["category"] != "source", x["path"]))
    return findings[:limit]


def top_vulns(grype_path: Path, limit: int = 10) -> list[dict]:
    """Return the most actionable Grype matches (CRITICAL first)."""
    data = load_json(grype_path)
    if not data:
        return []
    out = []
    for m in data.get("matches", []) or []:
        v = m.get("vulnerability") or {}
        a = m.get("artifact") or {}
        sev = (v.get("severity") or "UNKNOWN").upper()
        out.append({
            "id": v.get("id", "?"),
            "severity": sev,
            "pkg": a.get("name", "?"),
            "version": a.get("version", "?"),
            "fixed_in": ", ".join(
                (v.get("fix") or {}).get("versions") or []
            ) or "（no fix listed）",
            "description": (v.get("description") or "").strip().split("\n")[0][:200],
        })
    out.sort(key=lambda x: SEVERITY_RANK.get(x["severity"], 99))
    return out[:limit]


def top_trivy_findings(trivy_path: Path, limit: int = 10) -> list[dict]:
    data = load_json(trivy_path)
    if not data:
        return []
    out = []
    for r in data.get("Results", []) or []:
        for v in r.get("Vulnerabilities", []) or []:
            sev = (v.get("Severity") or "UNKNOWN").upper()
            out.append({
                "id": v.get("VulnerabilityID", "?"),
                "severity": sev,
                "pkg": v.get("PkgName", "?"),
                "version": v.get("InstalledVersion", "?"),
                "fixed_in": v.get("FixedVersion") or "—",
                "target": r.get("Target", "?"),
            })
    out.sort(key=lambda x: SEVERITY_RANK.get(x["severity"], 99))
    return out[:limit]


def top_trivy_misconfigs(trivy_config_path: Path, limit: int = 10) -> list[dict]:
    data = load_json(trivy_config_path)
    if not data:
        return []
    out = []
    for r in data.get("Results", []) or []:
        for m in r.get("Misconfigurations", []) or []:
            sev = (m.get("Severity") or "UNKNOWN").upper()
            out.append({
                "id": m.get("ID", "?"),
                "severity": sev,
                "title": m.get("Title") or (m.get("Description") or "").strip().split("\n")[0][:80],
                "target": r.get("Target", "?"),
            })
    out.sort(key=lambda x: SEVERITY_RANK.get(x["severity"], 99))
    return out[:limit]


def semgrep_summary(semgrep_path: Path, limit: int = 8) -> list[tuple[str, int]]:
    data = load_json(semgrep_path)
    if not data:
        return []
    rules = Counter()
    for run in data.get("runs", []) or []:
        for r in run.get("results", []) or []:
            rules[r.get("ruleId", "?")] += 1
    return rules.most_common(limit)


def compact_list(value) -> str:
    if isinstance(value, list):
        clean = [str(v) for v in value if v]
        if not clean:
            return "not supplied"
        return ", ".join(clean)
    return str(value or "not supplied")


def git_branch_name(target_dir: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", target_dir, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        branch = result.stdout.strip()
        if branch:
            return branch
        result = subprocess.run(
            ["git", "-C", target_dir, "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        short = result.stdout.strip()
        return f"detached@{short}" if short else "not available"
    except Exception:
        return "not available"


def scanner_status_rows(scanner_health: dict) -> list[str]:
    rows = ["| Scanner | Status | Signal |", "|---|---|---|"]
    for name, info in sorted(scanner_health.items()):
        status = info.get("status", "UNKNOWN")
        reason = str(info.get("reason", "")).replace("\n", " ")[:180]
        rows.append(f"| `{name}` | `{status}` | {reason or '—'} |")
    return rows


def evidence_file_rows(evidence: dict, limit: int = 16) -> list[str]:
    files = evidence.get("evidence_files", []) or []
    rows = ["| File | Size | SHA-256 |", "|---|---:|---|"]
    for item in files[:limit]:
        rows.append(
            f"| `{item.get('file', '—')}` | {item.get('bytes', 0)} | `{str(item.get('sha256', ''))[:12]}` |"
        )
    if len(files) > limit:
        rows.append(f"| ... | ... | {len(files) - limit} more files in `evidence-manifest.json` |")
    return rows


def describe_evidence_file(path: str) -> str:
    name = Path(path).name
    if name == "gitleaks.json":
        return "Leaked secrets detail"
    if name == "grype.json":
        return "Dependency CVEs from SBOM"
    if name.startswith("grype-image"):
        return "Container image CVEs"
    if name == "trivy-fs.json":
        return "Filesystem vulnerabilities and secrets"
    if name.startswith("trivy-image"):
        return "Container image OS/package findings"
    if name == "trivy-config.json":
        return "Dockerfile/IaC misconfigurations"
    if name == "semgrep.sarif":
        return "SAST findings"
    if name == "sbom.cyclonedx.json":
        return "Source SBOM"
    if name.startswith("image-sbom") and name.endswith(".cyclonedx.json"):
        return "Image SBOM"
    if name == "zap-baseline.json":
        return "Runtime web scan"
    if name == "security-headers.json":
        return "Runtime HTTP header scan"
    if name.startswith("testssl"):
        return "TLS configuration scan"
    if name.startswith("clamav"):
        return "Uploads/malware scan"
    if "osv" in name:
        return "OSV dependency scan"
    return "Generated scanner evidence"


def source_report_rows(evidence: dict) -> list[str]:
    files = sorted({str(item.get("file", "")) for item in evidence.get("evidence_files", []) or [] if item.get("file")})
    rows = ["| Evidence file | Use it for |", "|---|---|"]
    for path in files:
        rows.append(f"| `{path}` | {describe_evidence_file(path)} |")
    if not files:
        rows.append("| `evidence-manifest.json` | No individual evidence files listed in manifest |")
    return rows


def skipped_surface_lines(scanner_health: dict) -> list[str]:
    skipped = []
    for name, info in sorted(scanner_health.items()):
        if info.get("status") == "SKIPPED":
            reason = str(info.get("reason", "not requested")).replace("\n", " ")
            skipped.append(f"- `{name}` skipped: {reason}")
    return skipped


def render_prompt(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
    git_commit: str | None,
) -> str:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    scanner_health = evidence.get("scanner_health", {})
    findings = evidence.get("findings_summary", {})
    assurance = evidence.get("assurance", {})

    secrets = top_secrets(report_dir / "reports" / "gitleaks.json")
    grype_vulns = top_vulns(report_dir / "reports" / "grype.json")
    trivy_vulns = top_trivy_findings(report_dir / "reports" / "trivy-fs.json")
    misconfigs = top_trivy_misconfigs(report_dir / "reports" / "trivy-config.json")
    semgrep_top = semgrep_summary(report_dir / "reports" / "semgrep.sarif")

    n_critical = assurance.get("critical_findings", 0)
    n_secrets = findings.get("gitleaks", 0)
    recommendation = assurance.get("release_recommendation", "—")
    auto_pct = assurance.get("automated_assurance_pct", 0)
    asvs_pct = assurance.get("asvs_traceability_pct", 0)
    manual_total = assurance.get("manual_items_total", 0)
    manual_done = assurance.get("manual_items_completed", 0)
    branch = evidence.get("git_branch") or git_branch_name(target_dir)
    images = compact_list(evidence.get("image_scanned"))
    urls = compact_list(evidence.get("url_scanned"))
    uploads = compact_list(evidence.get("uploads_scanned"))
    passed = assurance.get("passed", 0)
    warned = assurance.get("warned", 0)
    failed = assurance.get("failed", 0)
    skipped = assurance.get("skipped", 0)

    md = []
    md.append("# Agentic Fix Prompt")
    md.append("")
    md.append("## Mission")
    md.append("")
    md.append("You are assisting the user with a security remediation pass for the scanned codebase.")
    md.append("Use the report artifacts below as the source of truth, make the smallest safe fixes first,")
    md.append("and keep a clear audit trail of what changed, what was verified, and what still needs human approval.")
    md.append("")
    md.append("**Primary objective:** reduce exploitable risk and improve the ASVS assurance score without hiding, suppressing, or hand-waving findings.")
    md.append("")
    md.append("## Scan Context")
    md.append("")
    md.append(f"- **Target project:** `{target_dir}`")
    md.append(f"- **Branch:** `{branch}`")
    md.append(f"- **Run ID:** `{run_id}`")
    md.append(f"- **Git commit:** `{git_commit or 'not available'}`")
    md.append(f"- **Reports directory:** `{report_dir}`")
    md.append(f"- **Images scanned:** `{images}`")
    md.append(f"- **Runtime URLs scanned:** `{urls}`")
    md.append(f"- **Uploads scanned:** `{uploads}`")
    md.append(f"- **Automated assurance:** `{auto_pct}%`  •  **ASVS assurance score:** `{asvs_pct}%`")
    md.append(f"- **Manual ASVS evidence:** `{manual_done}/{manual_total}`")
    md.append(f"- **Release recommendation:** **`{recommendation}`**")
    md.append("")
    md.append("## Operating Rules")
    md.append("")
    md.append("1. Start by reading `evidence-manifest.json`, then the raw report for the phase you are working on.")
    md.append("2. Treat generated bundles, `dist/`, `node_modules/`, and image-only artifacts carefully; fix source causes where possible rather than editing build output.")
    md.append("3. Do not commit, print, or move real secret values. Mask secrets in notes and ask the user before rotating production credentials.")
    md.append("4. Ask before destructive git operations, force pushes, history rewrites, production secret rotation, or CI/CD changes.")
    md.append("5. Prefer small batches: fix one class of issue, run targeted tests, rerun the scanner or affected scanner, then continue.")
    md.append("6. For each finding class, decide: **fix**, **waive with evidence**, **false positive**, or **needs owner input**.")
    md.append("7. Leave the report artifacts intact. Regenerate reports by rerunning the scanner, not by editing raw scanner output.")
    md.append("")
    md.append("## Current Scanner State")
    md.append("")
    md.append(f"- **Passed:** `{passed}`  **Warned:** `{warned}`  **Failed:** `{failed}`  **Skipped:** `{skipped}`")
    md.append("")
    md.extend(scanner_status_rows(scanner_health))
    md.append("")
    md.append("## Source Reports")
    md.append("")
    md.append("Only files produced by this run are listed here. Do not assume optional image, runtime, TLS, or uploads reports exist unless they appear below.")
    md.append("")
    md.extend(source_report_rows(evidence))
    md.append("")
    md.append("Always read `evidence-manifest.json` for machine-readable summary, hashes, scanner status, and run metadata.")
    skipped_lines = skipped_surface_lines(scanner_health)
    if skipped_lines:
        md.append("")
        md.append("**Skipped or unavailable surfaces:**")
        md.append("")
        md.extend(skipped_lines)
    md.append("")
    md.append("**Generated evidence files:**")
    md.append("")
    md.extend(evidence_file_rows(evidence))
    md.append("")
    md.append("## Recommended Work Order")
    md.append("")
    md.append("Work in this order unless a finding is clearly a false positive or the user gives a different priority:")
    md.append("")
    md.append("1. Secret exposure and credential rotation.")
    md.append("2. Critical/high dependency and image CVEs with available fixes.")
    md.append("3. Container/IaC hardening and runtime web/header issues.")
    md.append("4. High-signal SAST issues with direct exploit paths.")
    md.append("5. SBOM/lockfile completeness and residual license/compliance work.")
    md.append("6. Manual ASVS evidence collection and owner assignment.")
    md.append("")

    # ----- Phase 1: secrets ---------------------------------------------------
    md.append("## Phase 1 — Rotate leaked secrets (URGENT)")
    md.append("")
    md.append("**Why first:** Secrets in git history are the only finding with irreversible")
    md.append("external blast radius. Rotate before anything else; once a key is leaked, you")
    md.append("must assume it is compromised regardless of whether you also remove it from history.")
    md.append("")
    md.append(f"**Count:** {n_secrets} leaked secrets across gitleaks findings.")
    md.append("")
    if secrets:
        md.append("**Top findings (masked):**")
        md.append("")
        md.append("| File | Line | Type | Category |")
        md.append("|---|---:|---|---|")
        for s in secrets:
            md.append(f"| `{s['path']}` | {s['line']} | `{s['rule']}` | {s['category']} |")
        md.append("")
    md.append("**Suggested agent steps:**")
    md.append("")
    md.append("1. **Identify each unique secret** by reading `reports/gitleaks.json`. Group duplicates (same key in multiple files = one rotation).")
    md.append("2. **For each unique secret:**")
    md.append("   - Determine the affected service (AWS, Stripe, OpenAI, GitHub, GCP, Telegram, SSH keys, generic API keys).")
    md.append("   - **Rotate** via the provider's admin console or CLI (e.g., `aws iam create-access-key`, `stripe keys rotate`).")
    md.append("   - Update local `.env` / secret manager with the new value.")
    md.append("   - **Do not commit the new value.**")
    md.append("3. **Identify which secrets are in git history** (not just working tree):")
    md.append("   ```bash")
    md.append("   git log --all -p -S '<secret-fragment>' -- source/path")
    md.append("   ```")
    md.append("4. **Purge history** for tracked secrets using `git filter-repo` (preferred) or BFG Repo-Cleaner. `git rm --cached` alone does **not** remove history.")
    md.append("5. **Update `.gitignore`** to prevent recurrence (`.env*`, `*-CREDS.txt`, `DOCKER-SECRETS*`, `*.pem`, `*.key`).")
    md.append("6. **Move production secrets to a real secret manager** (Vault, AWS Secrets Manager, Doppler). Plaintext creds files in repos are an anti-pattern.")
    md.append("")
    md.append("**Verification:** re-run the scanner after rotation and source cleanup. `reports/gitleaks.json` should be empty or contain only documented false positives.")
    md.append("")

    # ----- Phase 2: critical CVEs --------------------------------------------
    md.append("## Phase 2 — Patch critical/high CVEs")
    md.append("")
    md.append("**Why next:** Dependency and image CVEs are usually reproducible, externally documented, and often have concrete fixed versions.")
    md.append("Group by package/image first so one upgrade can close many findings.")
    md.append("")
    md.append(f"**Critical findings across the bundle:** `{n_critical}`. See `reports/grype.json`, `reports/grype-image-*.json`, `reports/trivy-fs.json`, and `reports/trivy-image-*.json`.")
    md.append("")
    if grype_vulns:
        md.append("**Top critical / high CVEs (Grype):**")
        md.append("")
        md.append("| Severity | CVE | Package | Installed | Fixed in |")
        md.append("|---|---|---|---|---|")
        for v in grype_vulns:
            md.append(f"| {v['severity']} | `{v['id']}` | `{v['pkg']}` | `{v['version']}` | `{v['fixed_in']}` |")
        md.append("")
    md.append("**Suggested agent steps:**")
    md.append("")
    md.append("1. **Read** `reports/grype.json` and any `reports/grype-image-*.json`; group critical/high CVEs by package and target image.")
    md.append("2. **For each affected package:**")
    md.append("   - Identify the package manager (npm/yarn/pnpm/pip/maven/go/cargo).")
    md.append("   - Run the upgrade command (e.g., `npm install <pkg>@<fixed-version>`).")
    md.append("   - Verify the package's release notes for breaking changes before major-version bumps.")
    md.append("3. **For image findings:** identify whether the fix is in the base image, OS packages, bundled binaries, or app dependencies copied into the image.")
    md.append("4. **Resolve conflicting transitive versions** by inspecting `pnpm why <pkg>` / `npm ls <pkg>` / equivalent.")
    md.append("5. **Re-run the test suite and rebuild images** after each upgrade batch.")
    md.append("6. **Re-run the scanner** to verify the CVE is gone from filesystem and image reports.")
    md.append("")
    md.append("**Watch for:** runtime-exposed packages, bundled binaries such as `ffmpeg`, old base images, and repeated `stdlib` findings from embedded Go binaries.")
    md.append("")

    # ----- Phase 3: IaC misconfigurations -------------------------------------
    md.append("## Phase 3 — Fix container, IaC, and runtime findings")
    md.append("")
    md.append("**Why next:** These are often mechanical hardening fixes and can improve both source and image posture.")
    md.append("")
    if misconfigs:
        md.append("**Top Trivy Config findings:**")
        md.append("")
        md.append("| Severity | ID | Target | Title |")
        md.append("|---|---|---|---|")
        for m in misconfigs:
            md.append(f"| {m['severity']} | `{m['id']}` | `{m['target']}` | {m['title']} |")
        md.append("")
    md.append("**Common fixes:**")
    md.append("")
    md.append("- **`DS-0002` (Image user should not be 'root'):** Add `USER nonroot` (or equivalent non-root UID) to each production Dockerfile.")
    md.append("- **`DS-0026` (No HEALTHCHECK):** Add a `HEALTHCHECK` directive pointing at the app's health endpoint.")
    md.append("- **`no-new-privileges: true`** (Semgrep docker-compose rule): Add to `security_opt:` in each compose service.")
    md.append("- **`writable-filesystem-service`** (Semgrep): Add `read_only: true` to compose services, with explicit `tmpfs:` mounts for write paths.")
    md.append("- **Docker-socket exposure:** Remove `/var/run/docker.sock` mounts unless the service genuinely needs Docker-in-Docker.")
    md.append("- **Runtime headers:** Review `reports/security-headers.json` and add missing CSP, HSTS, frame, MIME, referrer, and permissions-policy headers where applicable.")
    md.append("- **ZAP findings:** Review `reports/zap-baseline.json`; prioritize exposed paths, missing anti-clickjacking/CSP controls, and information disclosure.")
    md.append("- **TLS:** If `testssl` was skipped, supply an HTTPS URL in the next scan so TLS controls can be assessed.")
    md.append("")
    md.append("**Verification:** re-run `./run-local.sh <target>`. Trivy Config and Semgrep docker-compose counts should drop.")
    md.append("")

    # ----- Phase 4: SAST findings --------------------------------------------
    md.append("## Phase 4 — Address high-signal SAST findings")
    md.append("")
    md.append("**Why next:** Semgrep noise is high — sort by rule and fix the recurring patterns")
    md.append("rather than chasing individual findings.")
    md.append("")
    if semgrep_top:
        md.append("**Top Semgrep rules:**")
        md.append("")
        md.append("| Count | Rule |")
        md.append("|---:|---|")
        for rule, count in semgrep_top:
            md.append(f"| {count} | `{rule}` |")
        md.append("")
    md.append("**Strategy:**")
    md.append("")
    md.append("- **Bulk-fix patterns** (e.g., one rule fired 60 times = one fix in 60 places, or a shared config).")
    md.append("- **Skip pure-secrets rules** (already covered in Phase 1).")
    md.append("- **Skip dependency-version rules** if a renovate/dependabot config exists.")
    md.append("- **Triage XSS/injection/PostMessage rules individually** — these can be real bugs.")
    md.append("")
    md.append("**Verification:** re-run scanner; check that the targeted rule counts dropped.")
    md.append("")

    md.append("## Fix Execution Template")
    md.append("")
    md.append("For each remediation batch, produce a short note with:")
    md.append("")
    md.append("- **Findings addressed:** scanner, rule/CVE/secret type, affected files or images.")
    md.append("- **Root cause:** source dependency, generated artifact, base image, config, runtime header, or manual control gap.")
    md.append("- **Change made:** exact package/config/code changes, with file paths.")
    md.append("- **Risk/compatibility:** any breaking-change risk or production dependency.")
    md.append("- **Verification:** tests run, build commands, scanner rerun, and remaining residual findings.")
    md.append("- **Waivers:** owner, expiry date, compensating control, and evidence path if a finding cannot be fixed now.")
    md.append("")

    # ----- Phase 5: SBOM & license ------------------------------------------
    md.append("## Phase 5 — SBOM completeness and license review")
    md.append("")
    md.append("**Why next:** Required for release certification in regulated contexts.")
    md.append("")
    md.append("1. Confirm `sbom/sbom.cyclonedx.json` has all expected components (cross-check against `package.json` / `requirements.txt`).")
    md.append("2. Add `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` to the repo if missing — this is why osv-scanner reported 'No lockfiles found'.")
    md.append("3. Once lockfiles exist, re-run scanner — osv-scanner will produce real findings.")
    md.append("4. Review license obligations for any non-permissive licenses (GPL, AGPL) if product policy requires.")
    md.append("")

    # ----- Phase 6: manual evidence -----------------------------------------
    md.append("## Phase 6 — Coordinate manual evidence")
    md.append("")
    md.append("**Why last:** These cannot be automated. The scanner generates the checklist;")
    md.append("a human must complete it.")
    md.append("")
    md.append("1. Open `manual-evidence-required.md`.")
    md.append("2. Assign each of the 14 items to a named owner with a due date.")
    md.append("3. Update Status from `PENDING` to `IN_PROGRESS` / `COMPLETE` as evidence is produced.")
    md.append("4. Store evidence references in a durable location (ticket, wiki, GRC system, or repo docs) rather than only checking the dashboard box.")
    md.append("5. The ASVS assurance score rises as manual evidence is completed.")
    md.append("")

    # ----- Closing -----------------------------------------------------------
    md.append("## When to stop and ask")
    md.append("")
    md.append("- Before rotating any production secret (confirm with the secret owner first).")
    md.append("- Before running `git filter-repo` on a shared branch (coordinate with the team).")
    md.append("- Before any change to CI/CD pipeline config (`.github/workflows/`, Jenkinsfile, etc.).")
    md.append("- Before force-pushing anywhere.")
    md.append("- If a finding looks like a false positive, document why and skip — don't `--no-verify` your way past it.")
    md.append("- If the safest fix requires product/security ownership input, stop after documenting options and recommended next action.")
    md.append("")
    md.append("## Done criteria")
    md.append("")
    md.append("- Secret values are rotated or formally accepted by the secret owner, and source leaks are removed.")
    md.append("- Filesystem and image reports have 0 unwaived CRITICAL findings.")
    md.append("- HIGH findings are fixed or have owner-approved waiver evidence with expiry.")
    md.append("- Container/IaC/runtime findings are fixed or tracked with clear owners.")
    md.append("- Tests/builds relevant to changed components pass.")
    md.append("- Scanner rerun shows improved counts and no new critical regressions.")
    md.append("- Manual ASVS checklist items are completed or assigned with evidence owners and due dates.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by ASVS Security Scanner. Re-run the scanner after each fix batch to refresh this prompt and dashboard.*")
    md.append("")

    return "\n".join(md)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--git-commit", default="")
    args = ap.parse_args()

    report_dir = Path(args.report_dir)
    text = render_prompt(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
        git_commit=args.git_commit or None,
    )
    out = report_dir / "agent-investigation-prompt.md"
    out.write_text(text)
    print(f"agent-investigation-prompt: written to {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
