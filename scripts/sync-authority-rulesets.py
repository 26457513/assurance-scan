#!/usr/bin/env python3
"""Synchronize ruleset snapshots from authority source definitions.

The script has two modes:

- default/offline: keep the reviewed local ruleset content, but ensure it
  carries raw-artifact and transform provenance.
- --download: fetch public authority artifacts before transforming supported
  sources such as the NIST OSCAL catalog.

Licensed/user-supplied sources are never fetched automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from zipfile import ZipFile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifact_hashing import canonical_json_sha256, file_sha256
from load_target_artifacts import TargetArtifactError, load_target_artifact


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "scripts/sync-authority-rulesets.py"
TRANSFORM_VERSION = "2"
ASVS_FLAT_JSON = "ASVS-5.0.0/5.0/docs_en/OWASP_Application_Security_Verification_Standard_5.0.0_en.flat.json"


def asvs_row_id(req_id: str, version: str) -> str:
    parts = str(req_id or "").strip().removeprefix("V").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid ASVS requirement id: {req_id!r}")
    return f"{version}-" + ".".join(parts)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(errors="replace"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url: str, path: Path) -> None:
    if not url:
        raise SystemExit(f"Cannot fetch {path}: missing url")
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "assurance-scan-authority-sync/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "application/zip"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def raw_artifact(path: Path, *, url: str = "") -> dict[str, Any]:
    if not path.exists():
        return {}
    return {
        "path": rel(path),
        "url": url,
        "sha256": file_sha256(path, prefixed=True),
        "bytes": path.stat().st_size,
        "media_type": media_type_for(path),
    }


def provenance(source: dict[str, Any], raw_path: Path, output: dict[str, Any], *, downloaded: bool) -> dict[str, Any]:
    existing = output.get("source") or {}
    raw = raw_artifact(raw_path, url=str(source.get("url") or ""))
    raw_artifacts = [raw] if raw else existing.get("raw_artifacts") or []
    provisional = json.loads(json.dumps(output))
    provisional_source = dict(existing)
    provisional_source.update({
        "authority": source.get("authority"),
        "url": source.get("url") or existing.get("url", ""),
        "version_tag": source.get("version"),
        "license": source.get("license") or existing.get("license", ""),
        "retrieved_at": existing.get("retrieved_at") or now_iso(),
        "source_file": rel(Path(source.get("output_path", ""))),
        "raw_artifacts": raw_artifacts,
    })
    provisional_source["transform"] = {
        "tool": SCRIPT_NAME,
        "version": TRANSFORM_VERSION,
        "command": "sync-authority-rulesets --download" if downloaded else "sync-authority-rulesets",
        "output_sha256": "sha256:" + "0" * 64,
    }
    provisional["source"] = provisional_source
    output_hash = canonical_json_sha256(provisional)
    provisional["source"]["transform"]["output_sha256"] = output_hash
    return provisional


def flatten_nist_parts(parts: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for part in parts or []:
        prose = str(part.get("prose") or "").strip()
        if prose:
            texts.append(prose)
        nested = flatten_nist_parts(part.get("parts") or [])
        if nested:
            texts.append(nested)
    return " ".join(texts).strip()


def transform_nist(source: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    raw = load_json(raw_path)
    catalog = raw.get("catalog") or raw
    groups = {group.get("id"): group.get("title") for group in catalog.get("groups") or [] if group.get("id")}
    controls: list[dict[str, Any]] = []

    def add_control(control: dict[str, Any], *, family: str, family_title: str, parent: str | None = None) -> None:
        control_id = str(control.get("id") or "")
        if not control_id:
            return
        controls.append({
            "id": control_id,
            "title": control.get("title") or control_id,
            "description": flatten_nist_parts(control.get("parts") or []) or control.get("title") or control_id,
            "group": family,
            "parent": parent,
            "metadata": {
                "family_title": family_title or groups.get(family, ""),
                "class": "SP800-53",
            },
        })
        for child in control.get("controls") or []:
            add_control(child, family=family, family_title=family_title, parent=control_id)

    for group in catalog.get("groups") or []:
        family = str(group.get("id") or "").upper()
        family_title = str(group.get("title") or "")
        for control in group.get("controls") or []:
            add_control(control, family=family, family_title=family_title)
    return {
        "schema_version": 1,
        "ruleset": "NIST-800-53",
        "version": str(source.get("version") or ""),
        "title": "NIST 800-53 Controls",
        "source": {},
        "rows": controls,
    }


def transform_asvs(source: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    version = str(source.get("version") or "v5.0.0")
    if not raw_path.exists():
        raise SystemExit(f"ASVS authority archive missing: {raw_path}")
    with ZipFile(raw_path) as archive:
        try:
            raw = json.loads(archive.read(ASVS_FLAT_JSON))
        except KeyError as exc:
            raise SystemExit(f"ASVS archive does not contain expected export: {ASVS_FLAT_JSON}") from exc
    rows: list[dict[str, Any]] = []
    for req in raw.get("requirements") or []:
        req_id = str(req.get("req_id") or "")
        description = str(req.get("req_description") or "").strip()
        if not req_id or not description:
            continue
        chapter_id = str(req.get("chapter_id") or "")
        section_id = str(req.get("section_id") or "")
        section_name = str(req.get("section_name") or "")
        row_id = asvs_row_id(req_id, version)
        rows.append({
            "id": row_id,
            "title": section_name or str(req.get("chapter_name") or row_id),
            "description": description,
            "group": chapter_id,
            "section": section_id,
            "level": f"L{req.get('L')}",
            "metadata": {
                "authority_req_id": req_id,
                "chapter_name": req.get("chapter_name") or "",
                "section_name": section_name,
                "source_export": ASVS_FLAT_JSON,
            },
        })
    rows.sort(key=lambda row: [int(part) for part in row["id"].split("-", 1)[1].split(".")])
    return {
        "schema_version": 1,
        "ruleset": "ASVS",
        "version": version,
        "title": "OWASP Application Security Verification Standard",
        "description": str(source.get("artifact") or "Application Security Verification Standard"),
        "source": {},
        "rows": rows,
    }


def transform_existing(source: dict[str, Any], output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        raise SystemExit(f"Existing ruleset missing for {source.get('id')}: {output_path}")
    return load_json(output_path)


def sync_source(source: dict[str, Any], *, download: bool) -> Path:
    raw_path = REPO_ROOT / str(source.get("raw_path"))
    output_path = REPO_ROOT / str(source.get("output_path"))
    access = source.get("access")
    downloaded = False
    if download and access == "public_fetch":
        fetch(str(source.get("url") or ""), raw_path)
        downloaded = True
    if access == "licensed_user_supplied" and download:
        print(f"SKIP fetch licensed source: {source.get('id')}", file=sys.stderr)

    if source.get("id") == "ruleset-asvs-v5.0.0" and raw_path.exists():
        output = transform_asvs(source, raw_path)
    elif source.get("id") == "ruleset-nist-800-53-5.2.0" and raw_path.exists():
        output = transform_nist(source, raw_path)
    else:
        output = transform_existing(source, output_path)
        if not raw_path.exists():
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(raw_path, {
                "source": source.get("id"),
                "mode": "reviewed_snapshot_reference",
                "note": "Raw authority artifact was not fetched in this run; this marker records the reviewed local snapshot as the current transform input.",
                "snapshot_sha256": file_sha256(output_path, prefixed=True) if output_path.exists() else "",
            })

    output = provenance(source, raw_path, output, downloaded=downloaded)
    write_json(output_path, output)
    try:
        load_target_artifact(output_path, "ruleset", strict=True)
    except TargetArtifactError as exc:
        raise SystemExit(exc._format()) from exc
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "data" / "authority-sources" / "rulesets.json")
    parser.add_argument("--source-id", action="append", default=[], help="Only sync this source id; may be repeated.")
    parser.add_argument("--download", action="store_true", help="Fetch public authority artifacts before transforming.")
    args = parser.parse_args()

    registry = load_target_artifact(args.registry, "authority_source_registry", strict=True).raw
    selected = set(args.source_id or [])
    synced: list[Path] = []
    for source in registry.get("sources") or []:
        if selected and source.get("id") not in selected:
            continue
        synced.append(sync_source(source, download=args.download))
    for path in synced:
        print(f"synced {rel(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
