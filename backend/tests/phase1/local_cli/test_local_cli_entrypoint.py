"""User-facing command tests for the thin public container entrypoint."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from types import ModuleType

from app.modules.atomic.local_cli.config_store import load_config
from app.modules.atomic.local_cli.enrollment_client import TokenIdentity
from app.modules.workflows.local_scan_execution import (
    LocalScanExecutionOutcome,
    LocalScanExecutionResult,
)


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "local-cli.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("assurance_scan_local_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auth_login_uses_hidden_token_and_owner_only_atomic_config(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cli = _module()
    config_root = tmp_path / "config"
    config_root.mkdir(mode=0o700)
    config_path = config_root / "config.json"
    token = "asu_v1_hidden-token-value"
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: token)
    monkeypatch.setattr(
        cli,
        "validate_token_identity",
        lambda _config: TokenIdentity(
            "alice@example.test",
            "laptop",
            ("scans:upload",),
            "2027-01-01T00:00:00Z",
        ),
    )

    assert cli.main(["auth", "login", "--url", "https://scan.example.test"]) == 0

    output = capsys.readouterr()
    assert "alice@example.test (laptop)" in output.out
    assert token not in output.out + output.err
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    config = load_config(config_path)
    assert config.token == token
    assert config.token_label == "laptop"


def test_scan_command_passes_branch_and_project_override_to_workflow(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cli = _module()
    commands = []
    monkeypatch.setenv("ASSURANCE_SCAN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ASSURANCE_SCAN_HOST_UID", str(os.getuid()))
    monkeypatch.setenv("ASSURANCE_SCAN_HOST_GID", str(os.getgid()))
    monkeypatch.setattr(
        cli,
        "build_local_scan_dependencies",
        lambda **_kwargs: (object(), object()),
    )

    def execute(command, _dependencies):
        commands.append(command)
        return LocalScanExecutionResult(
            LocalScanExecutionOutcome.UPLOADED,
            "018f47a2-4c72-4c9e-9f60-780cb70b8fe4",
            run_id="local-1",
            run_url="https://scan.example.test/scans/local-1",
        )

    monkeypatch.setattr(cli, "execute_local_scan", execute)

    assert cli.main([
        "scan",
        "--branch",
        "feature/local",
        "--project",
        "26457513/assurance-scan",
    ]) == 0

    assert commands[0].branch_override == "feature/local"
    assert commands[0].project_override == "26457513/assurance-scan"
    assert "https://scan.example.test/scans/local-1" in capsys.readouterr().out
