#!/usr/bin/env python3
"""Recoverable operator tooling for the local-scan SQLite cutover."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.atomic.operations.sqlite_cutover import (  # noqa: E402
    CutoverSafetyError,
    create_verified_backup,
    inspect_database,
    restore_database,
    retention_report,
    verify_backup,
)
from app.infrastructure.db.migrations.identity_preflight import (  # noqa: E402
    IdentityPreflightError,
    build_identity_plan,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="local-cutover", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="read-only database and retention report")
    preflight.add_argument("--database", required=True, type=Path)

    backup = commands.add_parser("backup", help="create and verify an online SQLite backup")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--backup", required=True, type=Path)
    backup.add_argument("--manifest", required=True, type=Path)
    backup.add_argument("--application-revision", required=True)

    verify = commands.add_parser("verify-backup", help="verify a backup against its manifest")
    verify.add_argument("--backup", required=True, type=Path)
    verify.add_argument("--manifest", required=True, type=Path)

    retention = commands.add_parser("retention-report", help="read-only retention dry run")
    retention.add_argument("--database", required=True, type=Path)

    restore = commands.add_parser("restore", help="verify or execute a guarded recoverable restore")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--manifest", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    restore.add_argument("--stopped-writer-evidence", required=True, type=Path)
    restore.add_argument("--confirm", required=True)
    restore.add_argument(
        "--execute",
        action="store_true",
        help="perform the swap; omission produces only a verified restore plan",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result: Any
        if args.command == "preflight":
            database_report = inspect_database(args.database)
            result = {
                "database": dataclasses.asdict(database_report),
                "retention_dry_run": dataclasses.asdict(retention_report(args.database)),
                "identity_cutover": _identity_preflight(
                    args.database, database_report.schema_revision
                ),
            }
        elif args.command == "backup":
            result = create_verified_backup(
                args.database,
                args.backup,
                args.manifest,
                application_revision=args.application_revision,
            )
        elif args.command == "verify-backup":
            result = verify_backup(args.backup, args.manifest)
        elif args.command == "retention-report":
            result = retention_report(args.database)
        else:
            result = restore_database(
                args.backup,
                args.manifest,
                args.target,
                args.stopped_writer_evidence,
                confirmation=args.confirm,
                execute=args.execute,
            )
        payload = dataclasses.asdict(cast(Any, result)) if dataclasses.is_dataclass(result) else result
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (CutoverSafetyError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


def _identity_preflight(database: Path, revision: str | None) -> dict[str, Any]:
    """Reuse the migration's deterministic 0021 preflight when applicable."""
    if revision != "0020_snapshot_source_branch":
        return {"status": "not-applicable", "schema_revision": revision}
    uri = (
        f"sqlite:///file:{database.expanduser().resolve()}"
        "?mode=ro&immutable=1&uri=true"
    )
    engine = sa.create_engine(uri)
    try:
        with engine.connect() as connection:
            try:
                plan = build_identity_plan(connection)
            except IdentityPreflightError as exc:
                return {"status": "blocked", "report": exc.report}
        return {"status": "ready", "report": plan.report}
    finally:
        engine.dispose()
if __name__ == "__main__":
    raise SystemExit(main())
