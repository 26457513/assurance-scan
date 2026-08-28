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

from artifact_hashing import file_sha256, write_hash_sidecar


SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}


def load_json(p: Path):
    try:
        if p.exists() and p.stat().st_size > 0:
            return json.loads(p.read_text(errors="replace"))
    except Exception:
        return None
    return None


def display_current_repo_path(value):
    if not value:
        return value
    legacy_root = Path("/Users/jd/Development/asvs-scanner")
    repo_root = Path(__file__).resolve().parents[1]
    try:
        path = Path(str(value))
        if path.is_absolute() and path.is_relative_to(legacy_root):
            return str(repo_root / path.relative_to(legacy_root))
    except (TypeError, ValueError):
        pass
    return value


def record_report_artifact(report_dir: Path, artifact: Path) -> None:
    manifest_path = report_dir / "evidence-manifest.json"
    if not manifest_path.exists() or not artifact.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
        rel = artifact.relative_to(report_dir)
        digest = file_sha256(artifact)
        write_hash_sidecar(report_dir, artifact)
        files = [item for item in manifest.get("evidence_files", []) if item.get("file") != str(rel)]
        files.append({"file": str(rel), "bytes": artifact.stat().st_size, "sha256": digest})
        manifest["evidence_files"] = sorted(files, key=lambda item: item.get("file", ""))
        manifest_path.write_text(json.dumps(manifest, indent=2))
    except Exception:
        return


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


def evidence_file_rows(evidence: dict, limit: int = 16, *, include_assurance_pack: bool = True) -> list[str]:
    files = evidence.get("evidence_files", []) or []
    if not include_assurance_pack:
        files = [item for item in files if not str(item.get("file", "")).startswith("generated-tests/")]
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


def source_report_rows(evidence: dict, *, include_assurance_pack: bool = True) -> list[str]:
    files = sorted({
        str(item.get("file", ""))
        for item in evidence.get("evidence_files", []) or []
        if item.get("file") and (include_assurance_pack or not str(item.get("file", "")).startswith("generated-tests/"))
    })
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


def load_fr_catalog_for_prompt(fr_catalog_path: str | None):
    if fr_catalog_path:
        try:
            from load_fr_catalog import load_fr_catalog
            return load_fr_catalog(Path(fr_catalog_path))
        except Exception:
            return None
    return None


def collect_prompt_deficiencies(fr_catalog, report_dir: Path, junit_xml_path: str | None = None) -> list[dict]:
    if not fr_catalog:
        return []
    try:
        from fr.deficiencies import collect_assurance_deficiencies
        from fr.framework_tab import (
            _compute_fr_evidence_status,
            _load_junit_index,
            _load_test_inventory,
            _tbts_by_fr,
        )
        test_index = _load_junit_index(report_dir, junit_xml_path)
        inventory_index = _load_test_inventory(report_dir)
        tbts_for_fr = _tbts_by_fr(fr_catalog)
        fr_evidence = {}
        for fr in getattr(fr_catalog, "frs", []) or []:
            fr_id = fr.get("id")
            if not fr_id:
                continue
            fr_evidence[fr_id] = _compute_fr_evidence_status(
                fr,
                tbts_for_fr.get(fr_id, []),
                report_dir,
                test_index,
                inventory_index,
            )
        return collect_assurance_deficiencies(fr_catalog, fr_evidence, limit=30)
    except Exception:
        return []


def render_prompt(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
    git_commit: str | None,
    fr_catalog_path: str | None = None,
) -> str:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    scanner_health = evidence.get("scanner_health", {})
    findings = evidence.get("findings_summary", {})
    assurance = evidence.get("assurance", {})

    secrets = top_secrets(report_dir / "reports" / "gitleaks.json")
    grype_vulns = top_vulns(report_dir / "reports" / "grype.json")
    top_trivy_findings(report_dir / "reports" / "trivy-fs.json")
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
    md.extend(source_report_rows(evidence, include_assurance_pack=False))
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
    md.extend(evidence_file_rows(evidence, include_assurance_pack=False))
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
    md.append("7. For FR/TBT/JSP-453 coverage, use the separate `assurance-assessment-prompt.md` instead of mixing assurance design into remediation.")
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


def render_assurance_prompt(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
    git_commit: str | None,
    fr_catalog_path: str | None = None,
) -> str:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    assurance = evidence.get("assurance", {})
    assurance_pack = evidence.get("assurance_test_pack") or {}
    test_evidence = evidence.get("test_evidence") or {}
    inventory = test_evidence.get("inventory") or {}
    junit = test_evidence.get("junit") or {}
    branch = evidence.get("git_branch") or git_branch_name(target_dir)
    original_source_repo = evidence.get("source_repo") or evidence.get("target_dir") or "not available"
    safe_scan_worktree = evidence.get("target_dir") or target_dir
    fr_catalog = load_fr_catalog_for_prompt(fr_catalog_path)
    junit_xml_path = None
    for candidate in (report_dir / "junit.xml", report_dir / "reports" / "junit.xml"):
        if candidate.exists():
            junit_xml_path = str(candidate)
            break
    assurance_deficiencies = collect_prompt_deficiencies(fr_catalog, report_dir, junit_xml_path)

    pack_summary = assurance_pack.get("summary") or {}
    md: list[str] = []
    md.append("# Assurance Assessment Prompt")
    md.append("")
    md.append("## Mission")
    md.append("")
    md.append("You are assessing whether the scanned project has observable evidence for its mapped TBT, FR, ASVS and JSP-453 requirements.")
    md.append("This is an assessment-first workflow. Do not start by generating large new test suites.")
    md.append("")
    md.append("**Primary objective:** classify existing and missing assurance evidence so the user can decide what to implement next.")
    md.append("")
    md.append("## Scan Context")
    md.append("")
    md.append(f"- **Original source repo:** `{display_current_repo_path(original_source_repo)}`")
    md.append(f"- **Safe scan worktree:** `{display_current_repo_path(safe_scan_worktree)}`")
    md.append(f"- **Branch:** `{branch}`")
    md.append(f"- **Run ID:** `{run_id}`")
    md.append(f"- **Git commit:** `{git_commit or 'not available'}`")
    md.append(f"- **Reports directory:** `{report_dir}`")
    md.append(f"- **ASVS assurance score:** `{assurance.get('asvs_traceability_pct', 0)}%`")
    md.append(f"- **Native test files discovered:** `{inventory.get('files', 0)}`")
    md.append(f"- **Native test cases discovered:** `{inventory.get('cases', 0)}`")
    md.append(f"- **JUnit present:** `{bool(junit.get('present'))}`")
    md.append(f"- **JUnit passed/failed/skipped:** `{junit.get('passed', 0)}/{junit.get('failed', 0)}/{junit.get('skipped', 0)}`")
    md.append("")
    md.append("## Inputs")
    md.append("")
    md.append("Read these first:")
    md.append("")
    md.append("1. `evidence-manifest.json`")
    md.append("2. `generated-tests/VG_TEST_FRAMEWORK/manifest.json`")
    md.append("3. `reports/test-inventory.json`")
    md.append("4. `fr-catalog.snapshot.json`, if present")
    md.append("5. `assurance-framework.snapshot.json`, if present")
    md.append("6. `assurance-instance.snapshot.json`, if present")
    md.append("7. Existing copied native tests under `generated-tests/VG_TEST_FRAMEWORK/imported/`")
    md.append("")
    md.append("## Operating Rules")
    md.append("")
    md.append("1. Do **not** edit the original source repo or safe scan worktree unless the user explicitly asks for a commit-ready test pack or a product-code fix.")
    md.append("2. Use `generated-tests/VG_TEST_FRAMEWORK/manifest.json` as the plan of record for copied, wrapped, planned, and proposed tests.")
    md.append("3. Existing native tests copied into `generated-tests/VG_TEST_FRAMEWORK/imported/` are review inputs. Assess them before claiming ASVS/JSP-453 evidence.")
    md.append("4. Do not generate broad new integration, e2e, or load tests by default. Stop at coverage assessment and proposed test specifications unless the user explicitly asks for implementation.")
    md.append("5. Tiny wrapper tests are allowed only where an existing copied test is already close and the wrapper does not invent product behaviour. Ask before writing wrapper code; otherwise describe the wrapper as a specification.")
    md.append("6. Every mapped or proposed test must trace back to `TBT-*`, `FR-*`, applicable ASVS rows, and any related JSP-453 gate or criterion.")
    md.append("7. Do not invent endpoints, APIs, roles, workflows, data models, or security behaviour that are not already present in the product or documented in the supplied artifacts.")
    md.append("8. Evidence is observed, not implemented. Produce test specifications capable of collecting evidence; only record pass/fail evidence from actual JUnit/scanner/runtime results.")
    md.append("9. Prefer manual evidence where the requirement is process, ceremony, approval, policy, or role-based rather than executable product behaviour.")
    md.append("10. TBT is the test-basis provenance identifier. Do not create a second identifier for the same thing in VG_TEST_FRAMEWORK.")
    md.append("11. If a wrapper or generated test is later approved, the TBT must appear in the manifest `tbt` field, file name, test title, and JUnit testcase name/classname.")
    md.append("")
    md.append("## VG_TEST_FRAMEWORK Summary")
    md.append("")
    if assurance_pack.get("present"):
        md.append(f"- **Manifest:** `{assurance_pack.get('path')}`")
        md.append(f"- **Mode:** `{assurance_pack.get('mode', 'ephemeral')}`")
        md.append(f"- **Copied native tests:** `{pack_summary.get('copied_native', 0)}`")
        md.append(f"- **Native tests needing wrapper/assessment:** `{pack_summary.get('wrapper_needed', 0)}`")
        md.append(f"- **Planned TBT entries needing assessment/specification:** `{pack_summary.get('planned_tbt', 0)}`")
        md.append("- **Note:** the evidence gap table may show only the highest-priority gaps; the full VG_TEST_FRAMEWORK manifest is authoritative.")
    else:
        md.append("No VG_TEST_FRAMEWORK pack was generated for this run.")
    md.append("")
    md.append("## Assurance Levels")
    md.append("")
    md.append("- **Level 1, always:** assess existing tests, map useful evidence, identify coverage gaps, and classify missing evidence. No new code.")
    md.append("- **Level 2, optional:** propose or create tiny wrappers under `tests/asvs/` only where copied existing tests are already close to proving a TBT/FR. Avoid inventing behaviour.")
    md.append("- **Level 3, explicit request only:** generate missing integration, e2e, or load tests under `tests/asvs/`. Do this only when the user asks for a commit-ready assurance pack.")
    md.append("")
    if assurance_deficiencies:
        md.append("## Assurance Evidence Gaps")
        md.append("")
        md.append("Assess these mapped FR/process/compliance expectations. Do not generate broad new test code unless the user explicitly asks for a commit-ready assurance pack. The full VG_TEST_FRAMEWORK manifest may contain additional TBT entries beyond this table.")
        md.append("")
        md.append("| Priority | FR | Evidence need | Gap | Assessment action |")
        md.append("|---|---|---|---|---|")
        for item in assurance_deficiencies:
            priority = item.get("severity", "medium")
            related = ", ".join(str(v) for v in item.get("related", [])[:4]) or "mapped assurance item"
            md.append(
                f"| {priority} | `{item.get('fr_id')}` {item.get('title', '')} | "
                f"`{item.get('test_type', 'test')}` | {item.get('gap', '').replace('_', ' ')} | "
                f"Assess existing coverage first. If evidence is missing, produce a proposed assurance test specification. Related: {related}. |"
            )
        md.append("")
    md.append("## Assessment Tasks")
    md.append("")
    md.append("1. Open the VG_TEST_FRAMEWORK manifest and group entries by `assessment`: `useful_with_wrapper`, `candidate_inspiration`, `needs_design`, and any existing `not_assurance_relevant` entries.")
    md.append("2. For copied native tests, inspect the imported file and decide whether it is `useful_as_is`, `useful_with_wrapper`, `candidate_inspiration`, or `not_assurance_relevant`.")
    md.append("3. For each planned TBT, classify the gap as `wrapper_required`, `existing_test_enhancement`, `new_test_recommended`, or `manual_evidence`.")
    md.append("4. Map useful tests to `tbt`, `frs`, `ruleset_rows`, and `assurance_gates` without inventing product behaviour.")
    md.append("5. Produce test specifications for missing evidence, including preconditions, observable behaviour, assertions, safe fixtures, required runtime inputs, and expected JUnit output.")
    md.append("6. Where evidence can be collected by running existing tests, provide the JUnit export command for the next scan using `--junit-xml <path>`.")
    md.append("7. Use this output table for each assessment row: `TBT | FR | Existing evidence | Assessment | Gap classification | Proposed next step | Blockers`.")
    md.append("")
    md.append("## Deliverables")
    md.append("")
    md.append("- Proposed manifest updates, or updates to the ephemeral manifest only if the user asks you to write changes. Use `tbt`, `frs`, `ruleset_rows`, `assurance_gates`, `assessment`, `runner`, `pack_path`, and a coverage classification.")
    md.append("- A coverage assessment describing which copied native tests are useful as-is, useful with a wrapper, not assurance-relevant, or candidate inspiration.")
    md.append("- Proposed assurance test specifications for missing evidence, not full generated suites by default.")
    md.append("- Tiny wrapper specifications by default. Write wrapper code under `tests/asvs/` only after explicit user approval and only when the existing copied test already proves most of the behaviour.")
    md.append("- A short runbook showing the containerized command that could produce JUnit XML.")
    md.append("- A list of TBT/FR entries still blocked by missing environment, credentials, product owner input, or unavailable runtime URLs.")
    md.append("")
    md.append("## When To Stop")
    md.append("")
    md.append("- Stop before generating large new test suites.")
    md.append("- Stop if product behaviour is unclear or undocumented.")
    md.append("- Stop if a test would need production credentials, destructive data mutation, or live external systems.")
    md.append("- Stop if a process/approval requirement needs human ceremony or role evidence rather than executable tests.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by ASVS Security Scanner. Use this separately from the remediation fix prompt.*")
    md.append("")
    return "\n".join(md)


def _config_prompt_gap_rows(fr_catalog) -> list[dict]:
    if not fr_catalog:
        return []
    tbts_by_fr: dict[str, list[dict]] = {}
    for tbt in getattr(fr_catalog, "tbts", []) or []:
        for fr_id in tbt.get("proves") or []:
            tbts_by_fr.setdefault(fr_id, []).append(tbt)
    rows: list[dict] = []
    for fr in getattr(fr_catalog, "frs", []) or []:
        fr_id = str(fr.get("id", ""))
        if not fr_id:
            continue
        tbts = tbts_by_fr.get(fr_id, [])
        compliance_rows = {
            (row.get("ruleset", ""), row.get("row", ""))
            for tbt in tbts
            for row in (tbt.get("compliance") or [])
            if row.get("ruleset") and row.get("row")
        }
        generic_tbts = [
            tbt for tbt in tbts
            if "test basis for" in str(tbt.get("title", "")).lower()
            or not (tbt.get("expected_evidence") or [])
        ]
        issues = []
        if not compliance_rows:
            issues.append("no_compliance_rows")
        if not tbts:
            issues.append("no_tbts")
        if generic_tbts:
            issues.append("generic_or_underdefined_tbts")
        if issues:
            rows.append({
                "fr_id": fr_id,
                "title": fr.get("title", ""),
                "gate": fr.get("gate") or fr.get("assurance_gate") or "",
                "code_refs": len(fr.get("implemented_by") or []),
                "tbts": [tbt.get("id", "") for tbt in tbts],
                "compliance_rows": len(compliance_rows),
                "issues": issues,
            })
    rows.sort(key=lambda item: (len(item["issues"]), item["code_refs"]), reverse=True)
    return rows[:40]


def render_config_update_prompt(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
    git_commit: str | None,
    fr_catalog_path: str | None = None,
    assurance_framework_path: str | None = None,
    assurance_instance_path: str | None = None,
    compliance_mapping_pack_path: str | None = None,
) -> str:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    branch = evidence.get("git_branch") or git_branch_name(target_dir)
    original_source_repo = evidence.get("source_repo") or evidence.get("target_dir") or "not available"
    safe_scan_worktree = evidence.get("target_dir") or target_dir
    fr_catalog = load_fr_catalog_for_prompt(fr_catalog_path)
    config_gaps = _config_prompt_gap_rows(fr_catalog)

    md: list[str] = []
    md.append("# FR Config Update Prompt")
    md.append("")
    md.append("## Mission")
    md.append("")
    md.append("You are helping maintain VibeGuide assurance configuration for the scanned project.")
    md.append("Review the project FR catalog, TBT records, compliance mapping packs, scanner-compliance mapping packs, assurance framework, dashboard payload and source references.")
    md.append("Produce proposed config updates that improve FR -> TBT -> evidence -> compliance/gate traceability.")
    md.append("")
    md.append("**Primary objective:** improve the quality and completeness of assurance config without changing product code, generating tests, or claiming unobserved evidence.")
    md.append("")
    md.append("## Scan Context")
    md.append("")
    md.append(f"- **Original source repo:** `{display_current_repo_path(original_source_repo)}`")
    md.append(f"- **Safe scan worktree:** `{display_current_repo_path(safe_scan_worktree)}`")
    md.append(f"- **Branch:** `{branch}`")
    md.append(f"- **Run ID:** `{run_id}`")
    md.append(f"- **Git commit:** `{git_commit or 'not available'}`")
    md.append(f"- **Reports directory:** `{report_dir}`")
    md.append("")
    md.append("## Config Inputs")
    md.append("")
    md.append(f"- **FR catalog:** `{display_current_repo_path(fr_catalog_path) or 'not supplied'}`")
    md.append(f"- **Compliance mapping pack:** `{display_current_repo_path(compliance_mapping_pack_path) or 'not supplied'}`")
    md.append(f"- **Assurance framework:** `{display_current_repo_path(assurance_framework_path) or 'not supplied'}`")
    md.append(f"- **Assurance instance:** `{display_current_repo_path(assurance_instance_path) or 'not supplied'}`")
    md.append("")
    md.append("Read these report artifacts first if present:")
    md.append("")
    md.append("1. `dashboard-payload.json`")
    md.append("2. `fr-catalog.snapshot.json`")
    md.append("3. `compliance-mapping-pack.snapshot.json`")
    md.append("4. `scanner-compliance-mapping-packs/`")
    md.append("5. `assurance-framework.snapshot.json`")
    md.append("6. `assurance-instance.snapshot.json`")
    md.append("7. `evidence-bundle.json`")
    md.append("8. `agent-prompt-plan.json`")
    md.append("9. `reports/test-inventory.json`")
    md.append("")
    md.append("## Non-Negotiable Rules")
    md.append("")
    md.append("1. Do **not** modify application source code.")
    md.append("2. Do **not** generate tests or wrappers. This prompt is for config authoring only.")
    md.append("3. Do **not** claim evidence exists unless it is observed in `evidence-bundle.json`, scanner outputs, JUnit XML, manual evidence files, or explicit report artifacts.")
    md.append("4. Do **not** invent product behaviour, endpoints, roles, data models, ceremonies, or compliance obligations.")
    md.append("5. Treat all new mappings as `review_status: proposed` unless the supplied config already contains a reviewed/accepted source basis.")
    md.append("6. Every proposed mapping must include `source_basis`, `rationale`, `confidence`, and enough provenance for a human reviewer to approve or reject it.")
    md.append("7. Keep TBT as the test-basis provenance identifier. Do not create parallel IDs for the same test obligation.")
    md.append("8. Separate config updates from evidence updates: config may say what evidence is expected; evidence status must come only from observed artifacts.")
    md.append("9. If a mapping is plausible but not certain, put it under `uncertain_mappings`, not under ready-to-apply updates.")
    md.append("10. Do not mark scanner-only evidence sufficient unless the compliance mapping policy explicitly allows scanner-only sufficiency for that row.")
    md.append("")
    md.append("## What To Improve")
    md.append("")
    md.append("- FR catalog quality: precise FR text, precise TBTs, expected evidence, and clear TBT-to-FR provenance.")
    md.append("- Compliance mapping packs: regime rows such as ASVS/NIST mapped to relevant FRs and TBTs with sufficiency rules.")
    md.append("- Scanner-compliance mapping packs: scanner rule IDs/patterns mapped to compliance rows or domains only where a reviewed scanner finding genuinely supports or blocks that compliance signal.")
    md.append("- Assurance framework or instance mappings: JSP-453 gates/criteria connected to FRs, TBTs, ruleset rows, manual evidence, approvals, and roles.")
    md.append("- Manual evidence checklist structure: process or ceremony requirements should remain manual evidence, not fake automated tests.")
    md.append("")
    if config_gaps:
        md.append("## High-Priority Config Gaps From This Catalog")
        md.append("")
        md.append("| FR | Title | Code refs | TBTs | Compliance rows | Issues |")
        md.append("|---|---|---:|---|---:|---|")
        for item in config_gaps:
            md.append(
                f"| `{item['fr_id']}` | {str(item['title']).replace('|', '/')} | "
                f"{item['code_refs']} | `{', '.join(item['tbts']) or '-'}` | "
                f"{item['compliance_rows']} | `{', '.join(item['issues'])}` |"
            )
        md.append("")
        md.append("Use this table as a triage starter only. Re-check the underlying config and source references before proposing changes.")
        md.append("")
    md.append("## Required Output")
    md.append("")
    md.append("Return a single JSON document. Do not wrap it in prose. Use this shape:")
    md.append("")
    md.append("The output must validate against `data/schemas/config-update-proposal.schema.json`.")
    md.append("Before applying any proposal, run `scripts/validate-config-update-proposal.py` with the current FR catalog, ruleset and assurance framework where available.")
    md.append("Render a human review brief with `scripts/review-config-update-proposal.py proposal.json --output proposal-review.md` before accepting changes.")
    md.append("Apply only explicitly reviewed entries with `scripts/apply-config-update-proposal.py proposal.json --select section:index --reviewed-by <name> ... --*-out <reviewed-file>`.")
    md.append("")
    md.append("```json")
    md.append("{")
    md.append('  "schema_version": 1,')
    md.append('  "mode": "config_update_proposal",')
    md.append('  "project": "project-name",')
    md.append('  "run_id": "scan-run-id",')
    md.append('  "source_inputs": [')
    md.append('    {"path": "dashboard-payload.json", "sha256": "if known", "used_for": "traceability context"}')
    md.append("  ],")
    md.append('  "fr_catalog_updates": [')
    md.append("    {")
    md.append('      "operation": "update_tbt",')
    md.append('      "fr_id": "FR-019",')
    md.append('      "tbt_id": "TBT-019",')
    md.append('      "review_status": "proposed",')
    md.append('      "proposed_fields": {')
    md.append('        "title": "Precise test-basis title",')
    md.append('        "type": "integration",')
    md.append('        "evidence_policy": "automated_required",')
    md.append('        "expected_evidence": []')
    md.append("      },")
    md.append('      "source_basis": [{"type": "source_file", "ref": "path:line or config path"}],')
    md.append('      "rationale": "Why this TBT proves the FR",')
    md.append('      "confidence": "low|medium|high"')
    md.append("    }")
    md.append("  ],")
    md.append('  "compliance_mapping_pack_updates": [')
    md.append("    {")
    md.append('      "operation": "add_mapping",')
    md.append('      "ruleset": "ASVS",')
    md.append('      "ruleset_version": "5.0.0",')
    md.append('      "row_id": "v5.0.0-x.y.z",')
    md.append('      "fr_refs": ["FR-019"],')
    md.append('      "tbt_refs": ["TBT-019"],')
    md.append('      "sufficiency": {"scanner_only_sufficient": false, "manual_review_required": false},')
    md.append('      "review_status": "proposed",')
    md.append('      "source_basis": [{"type": "ruleset_row", "ref": "ruleset path or report artifact path"}],')
    md.append('      "rationale": "Why this row is satisfied by these FR/TBT records",')
    md.append('      "confidence": "low|medium|high"')
    md.append("    }")
    md.append("  ],")
    md.append('  "assurance_framework_or_instance_updates": [')
    md.append("    {")
    md.append('      "operation": "add_decision",')
    md.append('      "target": {"kind": "gate", "id": "G3"},')
    md.append('      "review_status": "proposed",')
    md.append('      "proposed_fields": {')
    md.append('        "id": "DEC-G3",')
    md.append('        "readiness_status": "manual_review",')
    md.append('        "notes": "Gate decision needs named human approval evidence"')
    md.append("      },")
    md.append('      "source_basis": [{"type": "assurance_framework", "ref": "assurance-framework path or dashboard payload"}],')
    md.append('      "rationale": "Why this project instance needs a gate decision, waiver, role assignment or criterion mapping",')
    md.append('      "confidence": "low|medium|high"')
    md.append("    }")
    md.append("  ],")
    md.append('  "manual_evidence_updates": [],')
    md.append('  "uncertain_mappings": [],')
    md.append('  "review_required": [')
    md.append('    {"item": "FR-019", "question": "Which ASVS/NIST rows should a human assessor approve?", "why": "Ambiguous source basis"}')
    md.append("  ]")
    md.append("}")
    md.append("```")
    md.append("")
    md.append("## Review Checklist Before Returning")
    md.append("")
    md.append("- All new/changed mappings are `review_status: proposed`.")
    md.append("- Every proposal cites source basis and rationale.")
    md.append("- Evidence expectations are stated, but pass/fail evidence is not invented.")
    md.append("- TBTs are precise enough that an assessment prompt could later decide wrapper/enhancement/new-test/manual-evidence.")
    md.append("- Compliance sufficiency policy says whether scanner evidence is supporting only, strong enough, or requires manual review.")
    md.append("- JSP-453/process items that map criteria to FR/TBT/manual artifacts, role assignments, gate decisions or waivers belong in assurance instance updates; reusable framework structure changes remain review-only.")
    md.append("- Ambiguous items are parked in `uncertain_mappings` or `review_required`.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("*Generated by ASVS Security Scanner. Use this before remediation or test-generation prompts when FR/TBT/compliance traceability is weak.*")
    md.append("")
    return "\n".join(md)


def build_config_update_proposal_template(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
) -> dict:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    project = evidence.get("repository") or Path(target_dir).name or "target-project"
    generated_at = evidence.get("generated_at")
    source_inputs = []
    for path, used_for in (
        ("dashboard-payload.json", "Traceability graph, node state and unresolved evidence gaps"),
        ("fr-catalog.snapshot.json", "Current project FR and TBT records"),
        ("compliance-mapping-pack.snapshot.json", "Current compliance row to FR/TBT mappings"),
        ("scanner-compliance-mapping-packs", "Current scanner finding to compliance row/domain mappings"),
        ("assurance-framework.snapshot.json", "Current gate, criterion and role model"),
        ("assurance-instance.snapshot.json", "Current project gate mappings and decisions"),
        ("evidence-bundle.json", "Observed evidence records for this scan"),
        ("agent-prompt-plan.json", "Structured deficiencies and recommendations"),
        ("reports/test-inventory.json", "Discovered native project test inventory"),
    ):
        if (report_dir / path).exists():
            source_inputs.append({"path": path, "kind": "report_artifact", "used_for": used_for})

    if not source_inputs:
        source_inputs.append({
            "path": str(report_dir),
            "kind": "report_directory",
            "used_for": "Scan report context",
        })

    template = {
        "schema_version": 1,
        "mode": "config_update_proposal",
        "project": project,
        "run_id": run_id,
        "source_inputs": source_inputs,
        "fr_catalog_updates": [],
        "compliance_mapping_pack_updates": [],
        "assurance_framework_or_instance_updates": [],
        "manual_evidence_updates": [],
        "uncertain_mappings": [],
        "review_required": [
            {
                "item": "config-authoring",
                "question": "Replace this template item with proposed config updates or explicit review questions before validation.",
                "why": "The template is a starting artifact and intentionally does not claim mappings, evidence or product behaviour.",
            }
        ],
    }
    if generated_at:
        template["generated_at"] = generated_at
    return template


def build_agent_prompt_plan(
    *,
    target_dir: str,
    run_id: str,
    report_dir: Path,
    fr_catalog_path: str | None = None,
    assurance_framework_path: str | None = None,
    assurance_instance_path: str | None = None,
) -> dict:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    scanner_health = evidence.get("scanner_health", {}) or {}
    fr_catalog = load_fr_catalog_for_prompt(fr_catalog_path)
    junit_xml_path = None
    for candidate in (report_dir / "junit.xml", report_dir / "reports" / "junit.xml"):
        if candidate.exists():
            junit_xml_path = str(candidate)
            break
    assurance_deficiencies = collect_prompt_deficiencies(fr_catalog, report_dir, junit_xml_path)
    affected_gates = _affected_gates_by_ref(
        assurance_framework_path=assurance_framework_path,
        assurance_instance_path=assurance_instance_path,
    )

    deficiencies: list[dict] = []
    assurance_recommendations: list[dict] = []
    for idx, item in enumerate(assurance_deficiencies, start=1):
        fr_id = str(item.get("fr_id", ""))
        related = [str(value) for value in item.get("related", []) if value]
        tbts = [str(value) for value in item.get("tbts", []) if value]
        rows = []
        for value in related:
            if " " in value:
                ruleset, _, row = value.partition(" ")
                if ruleset and row:
                    rows.append({"ruleset": ruleset, "row": row})
        gates = sorted({
            gate
            for ref in ([fr_id] + tbts)
            for gate in affected_gates.get(ref, [])
        })
        deficiency_id = f"DEF-FR-{idx:03d}"
        deficiencies.append({
            "id": deficiency_id,
            "severity": str(item.get("severity", "medium")),
            "type": "missing_evidence" if item.get("gap") != "failed_evidence" else "failed_evidence",
            "summary": f"{fr_id} needs observable assurance evidence for {item.get('title', 'mapped requirement')}.",
            "affected": {
                "frs": [fr_id] if fr_id else [],
                "tbts": tbts,
                "ruleset_rows": rows,
                "gates": gates,
            },
            "recommended_action": (
                "Assess existing tests first. Where evidence is still missing, produce a proposed "
                "assurance test specification rather than generating broad new tests by default."
            ),
        })
        assurance_recommendations.append({
            "id": f"REC-ASSURANCE-{idx:03d}",
            "type": "assess_existing_test",
            "summary": f"Assess existing or copied tests for {fr_id} before proposing new {item.get('test_type', 'test')} coverage.",
            "affected": {
                "frs": [fr_id] if fr_id else [],
                "tbts": tbts,
                "ruleset_rows": rows,
                "gates": gates,
            },
            "requires_explicit_test_generation_request": True,
        })

    fix_recommendations: list[dict] = []
    fix_idx = 0
    for scanner, info in sorted(scanner_health.items()):
        if not isinstance(info, dict) or info.get("status") != "FAIL":
            continue
        fix_idx += 1
        fix_recommendations.append({
            "id": f"REC-FIX-{fix_idx:03d}",
            "type": "fix",
            "summary": f"Investigate and remediate failing scanner {scanner}: {info.get('reason', 'failed')}",
            "affected": {},
            "prompt_text": f"Read the raw report for {scanner}, fix the source cause where safe, and rerun the affected scanner.",
            "requires_explicit_test_generation_request": False,
        })

    plan = {
        "schema_version": 1,
        "project": Path(target_dir).name or "target-project",
        "mode": "assessment_first",
        "deficiencies": deficiencies,
        "fix_recommendations": fix_recommendations,
        "assurance_recommendations": assurance_recommendations,
        "safety_rules": [
            "Do not invent product behaviour.",
            "Do not generate broad new tests unless explicitly requested.",
            "Evidence must be observed from scanner, JUnit, document, approval or manual review artifacts.",
            "Keep TBT as the provenance identifier for generated or proposed assurance tests.",
        ],
    }
    if evidence.get("generated_at"):
        plan["generated_at"] = evidence["generated_at"]
    return plan


def _affected_gates_by_ref(
    *,
    assurance_framework_path: str | None,
    assurance_instance_path: str | None,
) -> dict[str, set[str]]:
    if not assurance_framework_path or not assurance_instance_path:
        return {}
    try:
        framework = json.loads(Path(assurance_framework_path).read_text())
        instance = json.loads(Path(assurance_instance_path).read_text())
    except Exception:
        return {}

    criterion_to_gate: dict[str, str] = {}
    for process in framework.get("processes") or []:
        for gate in process.get("gates") or []:
            gate_id = gate.get("id")
            for criterion in gate.get("criteria") or []:
                criterion_id = criterion.get("id")
                if gate_id and criterion_id:
                    criterion_to_gate[criterion_id] = gate_id

    out: dict[str, set[str]] = {}
    for mapping in instance.get("criterion_mappings") or []:
        criterion = mapping.get("criterion")
        gate = criterion_to_gate.get(criterion)
        if not gate:
            continue
        for requirement in mapping.get("requirements") or []:
            ref = requirement.get("ref")
            if ref:
                out.setdefault(ref, set()).add(gate)
            evidence = requirement.get("evidence")
            if evidence:
                out.setdefault(evidence, set()).add(gate)
            if requirement.get("type") == "ruleset_row":
                ruleset = requirement.get("ruleset")
                row = requirement.get("row")
                if ruleset and row:
                    out.setdefault(f"{ruleset} {row}", set()).add(gate)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--git-commit", default="")
    ap.add_argument("--fr-catalog", default=None)
    ap.add_argument("--assurance-framework", default=None)
    ap.add_argument("--assurance-instance", default=None)
    ap.add_argument("--compliance-mapping-pack", default=None)
    args = ap.parse_args()

    report_dir = Path(args.report_dir)
    text = render_prompt(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
        git_commit=args.git_commit or None,
        fr_catalog_path=args.fr_catalog,
    )
    out = report_dir / "agent-investigation-prompt.md"
    out.write_text(text)
    record_report_artifact(report_dir, out)
    print(f"agent-investigation-prompt: written to {out.name}")
    assurance_text = render_assurance_prompt(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
        git_commit=args.git_commit or None,
        fr_catalog_path=args.fr_catalog,
    )
    assurance_out = report_dir / "assurance-assessment-prompt.md"
    assurance_out.write_text(assurance_text)
    record_report_artifact(report_dir, assurance_out)
    print(f"assurance-assessment-prompt: written to {assurance_out.name}")
    config_update_text = render_config_update_prompt(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
        git_commit=args.git_commit or None,
        fr_catalog_path=args.fr_catalog,
        assurance_framework_path=args.assurance_framework,
        assurance_instance_path=args.assurance_instance,
        compliance_mapping_pack_path=args.compliance_mapping_pack,
    )
    config_update_out = report_dir / "fr-config-update-prompt.md"
    config_update_out.write_text(config_update_text)
    record_report_artifact(report_dir, config_update_out)
    print(f"fr-config-update-prompt: written to {config_update_out.name}")
    config_template = build_config_update_proposal_template(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
    )
    config_template_out = report_dir / "fr-config-update-proposal.template.json"
    config_template_out.write_text(json.dumps(config_template, indent=2))
    record_report_artifact(report_dir, config_template_out)
    print(f"fr-config-update-proposal.template: written to {config_template_out.name}")
    plan = build_agent_prompt_plan(
        target_dir=args.target_dir,
        run_id=args.run_id,
        report_dir=report_dir,
        fr_catalog_path=args.fr_catalog,
        assurance_framework_path=args.assurance_framework,
        assurance_instance_path=args.assurance_instance,
    )
    plan_out = report_dir / "agent-prompt-plan.json"
    plan_out.write_text(json.dumps(plan, indent=2))
    record_report_artifact(report_dir, plan_out)
    print(f"agent-prompt-plan: written to {plan_out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
