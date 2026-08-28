"""Tests for the REST catalogue save endpoint (FRs page paste flow)."""
from __future__ import annotations

import json

from sqlalchemy import select as sa_select

from app.api.routes.frs import SaveCatalogueBody, save_catalogue
from app.catalogue.loader import load_catalogue_from_dict
from app.infrastructure.db.models import CatalogueSnapshot

V3_CATALOGUE = {
    "schema_version": 3,
    "project": "doc2context",
    "catalogue_version": "2026-08-18T00:00:00Z",
    "frs": [
        {
            "id": "FR-001",
            "title": "No eval",
            "description": "Source must not use eval.",
            "implemented_by": [{"kind": "glob", "ref": "backend/**/*.py"}],
            "tests": [
                {
                    "id": "T-001",
                    "type": "scanner-clean",
                    "scanner": "semgrep",
                    "rule_pattern": "python.lang.security.audit.eval*",
                }
            ],
        }
    ],
}


async def test_save_catalogue_stores_snapshot(session) -> None:
    raw = json.dumps(V3_CATALOGUE)
    res = await save_catalogue(
        project_path="github:26457513/doc2context",
        body=SaveCatalogueBody(catalogue_json=raw),
        session=session,
    )
    assert res["status"] == "saved"
    assert res["fr_count"] == 1

    snaps = (await session.execute(
        sa_select(CatalogueSnapshot).where(
            CatalogueSnapshot.project_path == "github:26457513/doc2context"
        )
    )).scalars().all()
    assert len(snaps) == 1
    stored = json.loads(snaps[0].snapshot_json)
    assert stored["frs"][0]["id"] == "FR-001"


async def test_save_catalogue_rejects_invalid_json(session) -> None:
    from fastapi import HTTPException

    try:
        await save_catalogue(
            project_path="p", body=SaveCatalogueBody(catalogue_json="{not json"), session=session
        )
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400


async def test_save_catalogue_rejects_invalid_schema(session) -> None:
    from fastapi import HTTPException

    try:
        await save_catalogue(
            project_path="p", body=SaveCatalogueBody(catalogue_json=json.dumps({"schema_version": 99})), session=session
        )
        raise AssertionError("expected 422")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_load_catalogue_from_dict_accepts_fixture() -> None:
    loaded = load_catalogue_from_dict(V3_CATALOGUE, "proj")
    assert loaded.doc["frs"][0]["id"] == "FR-001"
