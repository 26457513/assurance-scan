from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.modules.atomic.local_cli.config_store import (
    ConfigStoreError,
    load_config,
    login_config,
    logout_config,
    resolve_config,
    save_config,
    validate_api_url,
)


def _directory(tmp_path: Path) -> Path:
    path = tmp_path / "config"
    path.mkdir(mode=0o700)
    return path


def test_login_atomic_0600_rotation_and_logout_preserve_installation(tmp_path: Path) -> None:
    path = _directory(tmp_path) / "config.json"
    first = login_config(None, api_url="https://SCAN.example/", token="asu_v1_one", token_label="laptop")
    save_config(path, first)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_config(path) == first

    rotated = login_config(first, api_url="https://scan.example", token="asu_v1_two", token_label="laptop")
    assert rotated.installation_id == first.installation_id
    save_config(path, rotated)
    logged_out = logout_config(load_config(path))
    assert logged_out.installation_id == first.installation_id
    assert logged_out.token is None


def test_refuses_symlinks_and_group_readable_paths(tmp_path: Path) -> None:
    directory = _directory(tmp_path)
    target = directory / "target.json"
    config = login_config(None, api_url="https://scan.example", token="token", token_label="laptop")
    save_config(target, config)
    link = directory / "config.json"
    link.symlink_to(target)
    with pytest.raises(ConfigStoreError, match="symlink"):
        load_config(link)

    link.unlink()
    target.chmod(0o640)
    with pytest.raises(ConfigStoreError, match="owner-only"):
        load_config(target)

    target.chmod(0o600)
    directory.chmod(0o750)
    with pytest.raises(ConfigStoreError, match="directory"):
        save_config(target, config)


def test_https_and_explicit_loopback_development_policy() -> None:
    assert validate_api_url("https://Scan.Example/") == "https://scan.example"
    with pytest.raises(ConfigStoreError, match="HTTPS"):
        validate_api_url("http://scan.example")
    assert validate_api_url("http://127.0.0.1:8000", allow_insecure_loopback=True) == "http://127.0.0.1:8000"
    assert validate_api_url("http://[::1]:8000", allow_insecure_loopback=True) == "http://[::1]:8000"
    with pytest.raises(ConfigStoreError):
        validate_api_url("https://user:secret@scan.example")


def test_explicit_loopback_development_config_can_be_persisted(tmp_path: Path) -> None:
    path = _directory(tmp_path) / "config.json"
    config = login_config(
        None,
        api_url="http://localhost:8000",
        token="token",
        token_label="dev",
        allow_insecure_loopback=True,
    )
    save_config(path, config, allow_insecure_loopback=True)
    assert load_config(path, allow_insecure_loopback=True) == config


def test_environment_override_is_explicit_and_non_persistent(tmp_path: Path) -> None:
    path = _directory(tmp_path) / "config.json"
    stored = login_config(None, api_url="https://scan.example", token="stored", token_label="laptop")
    save_config(path, stored)
    resolved = resolve_config(
        stored,
        {"ASSURANCE_SCAN_URL": "https://other.example", "ASSURANCE_SCAN_TOKEN": "override"},
    )
    assert resolved.environment_override_used is True
    assert resolved.config.token == "override"
    assert load_config(path).token == "stored"
    assert os.stat(path).st_uid == os.getuid()
