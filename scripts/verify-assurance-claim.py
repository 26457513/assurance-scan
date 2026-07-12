#!/usr/bin/env python3
"""Verify a typed assurance claim against report artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify_assurance_claim import verify_claim


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("claim")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--require-satisfied", action="store_true")
    args = parser.parse_args()

    claim_path = Path(args.claim)
    report_dir = Path(args.report_dir)
    errors = verify_claim(claim_path, report_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    claim = json.loads(claim_path.read_text())
    print(f"OK assurance claim: {claim['claim_result']} {claim['claim_type']} {claim['target']}")
    if args.require_satisfied and claim.get("claim_result") != "satisfied":
        print("ERROR: claim is valid but unsatisfied")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
