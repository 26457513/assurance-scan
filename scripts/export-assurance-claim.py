#!/usr/bin/env python3
"""Export a typed assurance claim from a report runtime graph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from artifact_hashing import file_sha256, write_hash_sidecar
from assurance_claims import build_claim, default_output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir")
    parser.add_argument("--claim-type", required=True, choices=[
        "fr_satisfied",
        "tbt_satisfied",
        "compliance_row_satisfied",
        "no_blocking_scanner_evidence",
        "selected_scope_satisfied",
    ])
    parser.add_argument("--target", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--require-satisfied", action="store_true")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    try:
        claim = build_claim(report_dir, args.claim_type, args.target)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    out_path = Path(args.out) if args.out else default_output_path(report_dir, args.claim_type, args.target)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(claim, indent=2) + "\n")
    write_hash_sidecar(report_dir, out_path)

    print(f"claim: {claim['claim_result']} {args.claim_type} {args.target}")
    print(f"artifact: {out_path}")
    print(f"hash: {file_sha256(out_path, prefixed=True)}")
    if args.require_satisfied and claim["claim_result"] != "satisfied":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
