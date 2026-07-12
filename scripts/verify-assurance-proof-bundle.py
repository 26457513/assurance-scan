#!/usr/bin/env python3
"""Verify a selective-disclosure assurance proof bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from assurance_proof_bundles import verify_proof_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--report-dir", default=None, help="Optional report directory for recomputing the embedded claim.")
    parser.add_argument("--require-satisfied", action="store_true")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    errors = verify_proof_bundle(bundle_path, Path(args.report_dir) if args.report_dir else None)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    bundle = json.loads(bundle_path.read_text())
    claim = bundle["claim"]
    print(f"OK proof bundle: {claim['claim_result']} {claim['claim_type']} {claim['target']}")
    if args.require_satisfied and claim.get("claim_result") != "satisfied":
        print("ERROR: proof bundle is valid but claim is unsatisfied")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
