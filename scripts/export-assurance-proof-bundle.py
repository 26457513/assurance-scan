#!/usr/bin/env python3
"""Export a selective-disclosure assurance proof bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from artifact_hashing import file_sha256, write_hash_sidecar
from assurance_proof_bundles import build_proof_bundle, default_bundle_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("claim")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--open", action="append", default=[], help="Report-relative artifact path to disclose as a base64 opening. May be repeated.")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    claim_path = Path(args.claim)
    try:
        bundle = build_proof_bundle(report_dir, claim_path, openings=args.open)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    out_path = Path(args.out) if args.out else default_bundle_path(report_dir, claim_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2) + "\n")
    write_hash_sidecar(report_dir, out_path)
    print(f"proof bundle: {out_path}")
    print(f"claim: {bundle['claim']['claim_result']} {bundle['claim']['claim_type']} {bundle['claim']['target']}")
    print(f"hash: {file_sha256(out_path, prefixed=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
