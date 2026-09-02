#!/usr/bin/env python3
"""Compare two independent identity-cutover rehearsal reports."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.atomic.operations.identity_migration_cutover import (  # noqa: E402
    IdentityCutoverError,
    compare_rehearsal_documents,
)


def _load_report(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise IdentityCutoverError("rehearsal report must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise IdentityCutoverError("rehearsal report must be a regular file")
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityCutoverError("rehearsal report could not be read") from exc
    if not isinstance(document, dict):
        raise IdentityCutoverError("rehearsal report must contain a JSON object")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    try:
        if args.first.resolve() == args.second.resolve():
            raise IdentityCutoverError("two distinct rehearsal reports are required")
        result = compare_rehearsal_documents(_load_report(args.first), _load_report(args.second))
    except IdentityCutoverError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
