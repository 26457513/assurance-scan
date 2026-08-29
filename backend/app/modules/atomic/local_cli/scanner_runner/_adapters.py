"""Concrete bounded Docker adapter used only by the local CLI composition."""

from __future__ import annotations

import json
import hashlib
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from app.modules.atomic.ingestion.data_redactor import redact_json
from app.modules.atomic.scanning.finding_parser import ParsedFinding, parser_for
from app.modules.atomic.scanning.result_builder import build_sarif
from app.modules.atomic.scanning.scanner_catalog import SCANNER_RELEASE_SET, ci_scanner_set

from .models import LocalScannerRun, ScannerRuntimeError, ScannerRuntimeLimits
from .service import build_local_scanner_argv, findings_document, scanner_container_name


class DockerLocalScannerRunner:
    """Pull and execute the reviewed scanner set against one immutable snapshot."""

    def __init__(
        self,
        *,
        reviewed_policy_path: Path,
        limits: ScannerRuntimeLimits = ScannerRuntimeLimits(),
    ) -> None:
        self.reviewed_policy_path = reviewed_policy_path
        self.limits = limits

    def scan(self, snapshot_root: Path, request_id: str) -> LocalScannerRun:
        """Return redacted upload artifacts without retaining scanner raw output."""
        self._docker_preflight()
        scanners = ci_scanner_set()
        for image in dict.fromkeys(scanner.image for scanner in scanners):
            self._ensure_image(image)

        policy_payload = self.reviewed_policy_path.read_bytes()
        if hashlib.sha256(policy_payload).hexdigest() != SCANNER_RELEASE_SET.semgrep_policy_sha256:
            raise ScannerRuntimeError("reviewed scanner policy does not match its release digest")
        run_root = snapshot_root.parent
        results_root = run_root / "results"
        results_root.mkdir(mode=0o700, exist_ok=False)

        findings: list[ParsedFinding] = []
        scanner_results: list[dict[str, Any]] = []
        sbom_path: Path | None = None
        completed = 0
        successful = False
        try:
            for scanner in scanners:
                started = time.monotonic()
                stdout_path = results_root / f"{scanner.kind}.stdout"
                stderr_path = results_root / f"{scanner.kind}.stderr"
                name = scanner_container_name(request_id, scanner.kind)
                argv = build_local_scanner_argv(
                    str(snapshot_root), scanner, request_id
                )
                status = "failed"
                error_code: str | None = None
                try:
                    returncode = _capture_bounded(
                        argv,
                        stdout_path,
                        stderr_path,
                        timeout_seconds=scanner.timeout_seconds,
                        stdout_limit=self.limits.stdout_bytes,
                        stderr_limit=self.limits.stderr_bytes,
                        stdin_payload=policy_payload if scanner.requires_stdin else None,
                    )
                    if returncode not in scanner.success_exit_codes:
                        error_code = "scanner_exit_nonzero"
                    else:
                        raw = stdout_path.read_bytes()
                        if scanner.output_kind == "cyclonedx-json":
                            sbom_path = results_root / "sbom.cyclonedx.json"
                            _write_bounded(sbom_path, raw, self.limits.artifact_bytes)
                        findings.extend(parser_for(scanner).parse(raw))
                        completed += 1
                        status = "completed"
                except subprocess.TimeoutExpired:
                    error_code = "scanner_timeout"
                except Exception:
                    error_code = "scanner_output_invalid"
                finally:
                    self._remove_exact(name)
                    stdout_path.unlink(missing_ok=True)
                    stderr_path.unlink(missing_ok=True)
                scanner_results.append({
                    "kind": scanner.kind,
                    "status": status,
                    "duration_ms": min(86_400_000, round((time.monotonic() - started) * 1000)),
                    "image": scanner.image,
                    "tool_version": scanner.tool_version,
                    "database_version": None,
                    "error_code": error_code,
                })
            if completed == 0:
                raise ScannerRuntimeError("no scanner produced a valid result")

            document = findings_document(findings, scanner_results)
            redacted = redact_json(cast(Any, document), repository_root=str(snapshot_root)).value
            if not isinstance(redacted, dict):
                raise ScannerRuntimeError("normalized scanner result is invalid")
            findings_path = results_root / "findings.json"
            _write_json_bounded(findings_path, redacted, self.limits.findings_bytes)
            sarif_path = results_root / "results.sarif"
            redacted_sarif = redact_json(
                cast(Any, build_sarif(cast(Any, findings))),
                repository_root=str(snapshot_root),
            ).value
            _write_json_bounded(sarif_path, redacted_sarif, self.limits.artifact_bytes)
            result = LocalScannerRun(
                findings_document=redacted,
                findings_path=findings_path,
                scanner_manifest_version=SCANNER_RELEASE_SET.schema_version,
                scanner_manifest_digest=SCANNER_RELEASE_SET.sha256,
                scanner_image_digests={scanner.kind: scanner.image for scanner in scanners},
                sarif_path=sarif_path,
                sbom_path=sbom_path,
            )
            successful = True
            return result
        finally:
            if not successful:
                shutil.rmtree(results_root, ignore_errors=True)

    @staticmethod
    def _docker_preflight() -> None:
        try:
            result = subprocess.run(
                ("docker", "info", "--format", "{{.ServerVersion}}"),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScannerRuntimeError("Docker is unavailable; start the local Docker engine") from exc
        if result.returncode != 0 or not result.stdout.strip():
            raise ScannerRuntimeError("Docker is unavailable; start the local Docker engine")

    @staticmethod
    def _ensure_image(image: str) -> None:
        try:
            inspect = subprocess.run(
                ("docker", "image", "inspect", image),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScannerRuntimeError("a pinned scanner image could not be inspected") from exc
        if inspect.returncode == 0:
            return
        try:
            pulled = subprocess.run(
                ("docker", "pull", image),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=900,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScannerRuntimeError("a pinned scanner image could not be pulled") from exc
        if pulled.returncode != 0:
            raise ScannerRuntimeError("a pinned scanner image could not be pulled")

    @staticmethod
    def _remove_exact(name: str) -> None:
        try:
            subprocess.run(
                ("docker", "rm", "--force", name),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return


def _capture_bounded(
    argv: list[str],
    stdout_path: Path,
    stderr_path: Path,
    *,
    timeout_seconds: int,
    stdout_limit: int,
    stderr_limit: int,
    stdin_payload: bytes | None = None,
) -> int:
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin_payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise ScannerRuntimeError("scanner output pipes are unavailable")
    if stdin_payload is not None:
        if process.stdin is None:
            process.kill()
            raise ScannerRuntimeError("scanner policy input is unavailable")
        process.stdin.write(stdin_payload)
        process.stdin.close()
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, (stdout_path, stdout_limit))
    selector.register(process.stderr, selectors.EVENT_READ, (stderr_path, stderr_limit))
    counts = {stdout_path: 0, stderr_path: 0}
    streams = {
        stdout_path: stdout_path.open("xb"),
        stderr_path: stderr_path.open("xb"),
    }
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            for key, _ in selector.select(min(1.0, remaining)):
                output_path, limit = key.data
                descriptor = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                counts[output_path] += len(chunk)
                if counts[output_path] > limit:
                    process.kill()
                    process.wait()
                    raise ScannerRuntimeError("scanner output exceeded its local limit")
                streams[output_path].write(chunk)
        return process.wait(timeout=max(1.0, deadline - time.monotonic()))
    finally:
        selector.close()
        for stream in streams.values():
            stream.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def _write_json_bounded(path: Path, value: object, limit: int) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    _write_bounded(path, payload, limit)


def _write_bounded(path: Path, payload: bytes, limit: int) -> None:
    if len(payload) > limit:
        raise ScannerRuntimeError("normalized scanner result exceeded its local limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["DockerLocalScannerRunner"]
