from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "resources" / "assets"
DASHBOARD_ASSET_ROOT = ASSET_ROOT / "dashboard"


def load_asset(name: str) -> str:
    path = ASSET_ROOT / name
    return path.read_text() if path.exists() else ""


def load_dashboard_asset(name: str) -> str:
    path = DASHBOARD_ASSET_ROOT / name
    if not path.exists():
        raise FileNotFoundError(f"Required dashboard runtime asset is missing: {path}")
    text = path.read_text()
    if not text.strip():
        raise ValueError(f"Required dashboard runtime asset is empty: {path}")
    return text
