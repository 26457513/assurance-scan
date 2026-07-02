#!/usr/bin/env python3
"""Generate the manual-evidence-required.md checklist.

These are ASVS controls that cannot be automated by local/runtime scanning.
Each item is seeded with PENDING status. A human reviewer fills in evidence
and flips status to COMPLETE / NOT_APPLICABLE / WAIVED.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ITEMS = [
    {
        "title": "Manual ASVS code review",
        "description": "Targeted code review against ASVS v4.0.x verification requirements not covered by SAST.",
        "why_required": "SAST catches common patterns but misses business-logic, authorisation bypass, and race conditions.",
        "evidence_expected": "Review notes, findings register, reviewer name and date, ASVS control references.",
    },
    {
        "title": "Authentication review",
        "description": "Verify authentication mechanisms against ASVS V2 (Authentication).",
        "why_required": "Authentication flaws are top-3 causes of breach and are not fully automatable.",
        "evidence_expected": "Auth flow diagram, credential storage review, session management review, MFA verification.",
    },
    {
        "title": "RBAC / ABAC review",
        "description": "Review role and attribute-based access control implementation.",
        "why_required": "Authorisation logic is application-specific and cannot be validated by generic scanners.",
        "evidence_expected": "Role catalogue, capability matrix, ABAC policy review, negative-path tests.",
    },
    {
        "title": "SSO configuration review",
        "description": "Verify SSO provider configuration (OIDC, SAML, claims mapping).",
        "why_required": "Misconfigured SSO can grant unintended access or leak identity data.",
        "evidence_expected": "Provider config screenshots, claims policy, group-mapping rules, redirect URI list.",
    },
    {
        "title": "TLS configuration verification",
        "description": "Confirm production TLS configuration matches tested baseline (cert chain, minimum version, cipher suite).",
        "why_required": "testssl.sh checks the URL supplied locally; production may differ (load balancer, CDN).",
        "evidence_expected": "Production scan report, cert chain validation, OCSP stapling evidence.",
    },
    {
        "title": "Audit logging verification",
        "description": "Verify security-relevant events are logged with required fields (actor, action, target, time).",
        "why_required": "Audit-log completeness is a compliance control that no scanner can verify.",
        "evidence_expected": "Log schema, sample event capture, retention policy, tamper-protection evidence.",
    },
    {
        "title": "Splunk ingest validation",
        "description": "Confirm application audit logs are reaching the SIEM with expected schema and volume.",
        "why_required": "Operational assurance that audit pipeline is functional end-to-end.",
        "evidence_expected": "SIEM search results showing recent events, schema-mapping doc, alert status.",
    },
    {
        "title": "CIS / OpenSCAP validation",
        "description": "Run host-level CIS or OpenSCAP benchmark against production infrastructure.",
        "why_required": "Container scanners check images, not the underlying host OS hardening.",
        "evidence_expected": "CIS scan report, exemption list with justifications, remediation ticket backlog.",
    },
    {
        "title": "Infrastructure review",
        "description": "Review cloud infrastructure (network, IAM, secrets, storage) for the deployment.",
        "why_required": "Cloud-config drift is invisible to local scanners.",
        "evidence_expected": "IaC scan output (tfsec / checkov), IAM permission matrix, network diagram, secrets inventory.",
    },
    {
        "title": "Deployment review",
        "description": "Review deployment pipeline, signing, and gating controls.",
        "why_required": "CI/CD pipeline tampering is a real supply-chain attack vector.",
        "evidence_expected": "Pipeline config, signing keys/digests, gate policy, deployment audit log.",
    },
    {
        "title": "Secrets management review",
        "description": "Verify production secrets are stored, rotated, and accessed through approved tooling.",
        "why_required": "Local scanners find leaked secrets in code; production secret-store hygiene is separate.",
        "evidence_expected": "Secret manager inventory, rotation policy evidence, access audit, blast-radius analysis.",
    },
    {
        "title": "Backup and recovery verification",
        "description": "Confirm backups exist, are encrypted, and have been restore-tested.",
        "why_required": "Operational resilience control; not detectable by security scanners.",
        "evidence_expected": "Backup schedule doc, restore-test report, encryption evidence, RTO/RPO alignment.",
    },
    {
        "title": "Monitoring and alerting verification",
        "description": "Verify security-relevant alerts fire on the right events with correct routing.",
        "why_required": "Detection coverage gaps are operational, not code, issues.",
        "evidence_expected": "Alerting rules, on-call rotation, recent incident retrospectives, dashboard screenshots.",
    },
    {
        "title": "Penetration test evidence",
        "description": "Independent third-party penetration test of the deployed application and infrastructure.",
        "why_required": "Required by ASVS V14 and most regulated release policies.",
        "evidence_expected": "Pen-test report, severity-ranked findings, remediation evidence for any HIGH/CRITICAL items.",
    },
]


def render(target_dir: str, run_id: str) -> str:
    lines = []
    lines.append("# Manual Evidence Required")
    lines.append("")
    lines.append(f"Target: `{target_dir}`  ")
    lines.append(f"Run ID: `{run_id}`  ")
    lines.append(f"Items: **{len(ITEMS)}**  ")
    lines.append(f"Status legend: `PENDING` `IN_PROGRESS` `COMPLETE` `NOT_APPLICABLE` `WAIVED`")
    lines.append("")
    lines.append("> This checklist complements the automated Evidence Bundle. Each item covers "
                 "ASVS controls that cannot be satisfied by local or runtime scanning. Update the "
                 "Status line as evidence is produced; the evidence-bundle generator counts non-PENDING "
                 "items toward the ASVS Traceability percentage.")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, item in enumerate(ITEMS, start=1):
        lines.append(f"## {idx}. {item['title']}")
        lines.append("")
        lines.append(f"- **Description:** {item['description']}")
        lines.append(f"- **Why required:** {item['why_required']}")
        lines.append(f"- **Evidence expected:** {item['evidence_expected']}")
        lines.append(f"- **Status:** PENDING")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    output = Path(args.output)
    output.write_text(render(args.target_dir, args.run_id))
    print(f"manual-evidence-required: {len(ITEMS)} items written to {output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
