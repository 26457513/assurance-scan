#!/usr/bin/env python3
"""Public container CLI for local Assurance Scan execution and upload."""

from __future__ import annotations

import argparse
import getpass
import os
import signal
import sys
from pathlib import Path

from app.infrastructure.local_cli import build_local_scan_dependencies
from app.modules.atomic.local_cli.config_store import (
    ConfigStoreError,
    load_config,
    login_config,
    logout_config,
    save_config,
    validate_api_url,
)
from app.modules.atomic.local_cli.enrollment_client import (
    EnrollmentConfig,
    EnrollmentError,
    validate_token_identity,
)
from app.modules.atomic.local_cli.git_metadata import GitMetadataError
from app.modules.atomic.local_cli.outbox_storage import OutboxStorageError, OutboxStore
from app.modules.atomic.local_cli.scanner_runner import ScannerRuntimeError
from app.modules.atomic.local_cli.source_snapshot import SourceSnapshotError
from app.modules.workflows.local_scan_execution import (
    LocalScanExecutionCommand,
    LocalScanExecutionOutcome,
    execute_local_scan,
)


VERSION = os.environ.get("ASSURANCE_SCAN_CLI_VERSION", "0.0.0-dev")
CONFIG_PATH = Path(os.environ.get("ASSURANCE_SCAN_CONFIG_FILE", "/config/config.json"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="assurance-scan", description=__doc__)
    root.add_argument("--version", action="version", version=f"assurance-scan {VERSION}")
    commands = root.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="manage the account-bound upload token")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_commands.add_parser("login", help="validate and securely save a copied token")
    login.add_argument("--url", required=True, help="Assurance Scan HTTPS origin")
    auth_commands.add_parser("status", help="show the enrolled account label")
    auth_commands.add_parser("logout", help="remove credentials but preserve installation identity")

    scan = commands.add_parser("scan", help="scan the repository mounted at the working directory")
    scan.add_argument("--no-upload", action="store_true", help="retain the result in the local outbox")
    scan.add_argument("--branch", help="branch name for detached HEAD scans")
    scan.add_argument("--project", help="audited owner/repo identity override")
    scan.add_argument("--url", help="override the configured server origin for this invocation")

    upload = commands.add_parser("upload", help="upload an existing immutable outbox bundle")
    upload.add_argument("--retry", required=True, metavar="REQUEST_ID")

    cache = commands.add_parser("cache", help="inspect or prune retained result bundles")
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    cache_commands.add_parser("list", help="list retained requests without displaying payloads")
    cache_commands.add_parser("prune", help="apply the seven-day and 1-GiB retention policy")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "auth":
            return _auth(args)
        if args.command == "cache":
            return _cache(args)
        return _execute(args)
    except KeyboardInterrupt:
        print("interrupted; temporary scanner containers will be cleaned on the next run", file=sys.stderr)
        return 130
    except (ConfigStoreError, EnrollmentError, OutboxStorageError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (GitMetadataError, SourceSnapshotError) as exc:
        print(f"repository preflight failed: {exc}", file=sys.stderr)
        return 3
    except ScannerRuntimeError as exc:
        print(f"scanner failed: {exc}", file=sys.stderr)
        return 4
    except (OSError, RuntimeError) as exc:
        print(f"local scan failed: {exc}", file=sys.stderr)
        return 3


def _auth(args: argparse.Namespace) -> int:
    uid, _ = _host_identity(require_environment=False)
    if args.auth_command == "login":
        allow_loopback = os.environ.get("ASSURANCE_SCAN_ALLOW_LOOPBACK_HTTP") == "1"
        api_url = validate_api_url(args.url, allow_insecure_loopback=allow_loopback)
        token = getpass.getpass("Assurance Scan token: ").strip()
        if not token:
            raise ConfigStoreError("token is required")
        identity = validate_token_identity(EnrollmentConfig(
            api_url=api_url,
            token=token,
            custom_ca_file=_custom_ca(),
            allow_loopback_http=allow_loopback,
        ))
        existing = (
            load_config(
                CONFIG_PATH,
                expected_uid=uid,
                allow_insecure_loopback=allow_loopback,
            )
            if CONFIG_PATH.exists()
            else None
        )
        config = login_config(
            existing,
            api_url=api_url,
            token=token,
            token_label=identity.token_label,
            allow_insecure_loopback=allow_loopback,
        )
        save_config(
            CONFIG_PATH,
            config,
            expected_uid=uid,
            allow_insecure_loopback=allow_loopback,
        )
        print(f"authenticated as {identity.account} ({identity.token_label})")
        return 0
    allow_loopback = os.environ.get("ASSURANCE_SCAN_ALLOW_LOOPBACK_HTTP") == "1"
    config = load_config(
        CONFIG_PATH,
        expected_uid=uid,
        allow_insecure_loopback=allow_loopback,
    )
    if args.auth_command == "logout":
        save_config(
            CONFIG_PATH,
            logout_config(config),
            expected_uid=uid,
            allow_insecure_loopback=allow_loopback,
        )
        print("credentials removed; installation identity preserved")
        return 0
    label = config.token_label or "not enrolled"
    print(f"server: {config.api_url}\ntoken: {label}\ninstallation: {config.installation_id}")
    return 0


def _execute(args: argparse.Namespace) -> int:
    uid, gid = _host_identity(require_environment=True)
    cache_root = _cache_root()
    environment = dict(os.environ)
    if getattr(args, "url", None):
        environment["ASSURANCE_SCAN_URL"] = args.url
    project_override = getattr(args, "project", None)
    dependencies, _ = build_local_scan_dependencies(
        config_path=CONFIG_PATH,
        cache_root=cache_root,
        host_uid=uid,
        host_gid=gid,
        project_override=project_override,
        environ=environment,
    )
    if args.command == "upload":
        command = LocalScanExecutionCommand(
            project_path=Path.cwd(),
            retry_request_id=args.retry,
        )
    else:
        command = LocalScanExecutionCommand(
            project_path=Path.cwd(),
            no_upload=args.no_upload,
            branch_override=args.branch,
            project_override=project_override,
            request_id=os.environ.get("ASSURANCE_SCAN_REQUEST_ID"),
        )
    result = execute_local_scan(command, dependencies)
    if result.outcome is LocalScanExecutionOutcome.UPLOADED:
        print(result.run_url or f"uploaded request {result.request_id}")
        return 0
    if result.outcome is LocalScanExecutionOutcome.SCANNED_ONLY:
        print(f"result retained: {cache_root / 'outbox' / result.request_id}")
        return 0
    if result.outcome is LocalScanExecutionOutcome.IN_PROGRESS:
        print(f"upload is still processing; retry request {result.request_id}", file=sys.stderr)
        return 6
    if result.error_code == "not_enrolled":
        print(f"result retained: {result.request_id}; run auth login before retrying", file=sys.stderr)
        return 2
    retryable = result.error_code in {
        "network_error",
        "network_retry_exhausted",
        "server_retry_exhausted",
    }
    print(f"result retained for retry: {result.request_id} ({result.error_code})", file=sys.stderr)
    return 6 if retryable else 5


def _cache(args: argparse.Namespace) -> int:
    uid, gid = _host_identity(require_environment=True)
    store = OutboxStore(
        _cache_root() / "outbox",
        expected_uid=uid,
        expected_gid=gid,
    )
    if args.cache_command == "prune":
        result = store.prune()
        print(
            f"removed={len(result.removed_request_ids)} "
            f"skipped_active={len(result.skipped_locked_request_ids)} "
            f"retained_bytes={result.retained_bytes}"
        )
        return 0
    for entry in store.list():
        print(
            f"{entry.record.request_id} {entry.record.state.value} "
            f"{entry.record.total_bytes} {entry.record.updated_at.isoformat()}"
        )
    return 0


def _host_identity(*, require_environment: bool) -> tuple[int, int]:
    uid_raw = os.environ.get("ASSURANCE_SCAN_HOST_UID")
    gid_raw = os.environ.get("ASSURANCE_SCAN_HOST_GID")
    if uid_raw is None or gid_raw is None:
        if require_environment and os.geteuid() == 0:
            raise ConfigStoreError("ASSURANCE_SCAN_HOST_UID and ASSURANCE_SCAN_HOST_GID are required")
        return os.getuid(), os.getgid()
    try:
        uid, gid = int(uid_raw), int(gid_raw)
    except ValueError as exc:
        raise ConfigStoreError("host UID/GID must be integers") from exc
    if uid < 0 or gid < 0:
        raise ConfigStoreError("host UID/GID must be non-negative")
    return uid, gid


def _cache_root() -> Path:
    value = os.environ.get("ASSURANCE_SCAN_CACHE_DIR")
    if not value:
        raise ConfigStoreError("ASSURANCE_SCAN_CACHE_DIR must name the mounted host cache")
    return Path(value)


def _custom_ca() -> Path | None:
    value = os.environ.get("ASSURANCE_SCAN_CA_FILE")
    return None if not value else Path(value)


def _terminate_as_interruption(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate_as_interruption)
    raise SystemExit(main())
