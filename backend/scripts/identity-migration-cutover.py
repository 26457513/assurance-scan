#!/usr/bin/env python3
"""Run or resume the checksum-bound GitHub identity cutover."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.atomic.operations.identity_migration_cutover import (  # noqa: E402
    IdentityCutoverError,
    run_identity_cutover,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--expected-preflight-checksum", required=True)
    parser.add_argument("--cutover-at", required=True, help="Fixed ISO-8601 timestamp")
    parser.add_argument(
        "--confirm-switch",
        action="store_true",
        help="Record the logical schema switch after every validation passes",
    )
    args = parser.parse_args()
    try:
        cutover_at = dt.datetime.fromisoformat(args.cutover_at.replace("Z", "+00:00"))
        result = run_identity_cutover(
            args.database,
            expected_preflight_checksum=args.expected_preflight_checksum,
            cutover_at=cutover_at,
            confirm_switch=args.confirm_switch,
        )
    except (IdentityCutoverError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result.to_document(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
