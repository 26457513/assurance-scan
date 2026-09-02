#!/usr/bin/env python3
"""Emit a deterministic, read-only GitHub identity migration inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.atomic.operations.identity_migration_preflight import (  # noqa: E402
    IdentityPreflightError,
    inspect_identity_migration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Existing SQLite database to inspect")
    args = parser.parse_args()
    try:
        report = inspect_identity_migration(args.database)
    except IdentityPreflightError as exc:
        parser.error(str(exc))
    print(json.dumps(report.to_document(), indent=2, sort_keys=True))
    return 2 if report.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
