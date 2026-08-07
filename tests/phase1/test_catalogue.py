"""Catalogue loader and v1→v2 migration tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.catalogue import load_catalogue, load_mapping_pack
from server.catalogue.migrate_v1 import migrate_v1_to_v2


def test_migrate_v1_collapses_tbt_into_parent(sample_v1_catalogue_with_tbts: dict) -> None:
    report = migrate_v1_to_v2(sample_v1_catalogue_with_tbts)

    assert report.collapsed_count == 1
    assert report.promoted_orphans == 0
    v2 = report.migrated_doc

    # TBT-001 should be gone, its required_evidence folded into FR-001.
    fr_ids = [fr["id"] for fr in v2["frs"]]
    assert fr_ids == ["FR-001"]
    assert "TBT-001" not in fr_ids

    fr_001 = v2["frs"][0]
    assert fr_001["required_evidence"]["all_of"][0]["name_pattern"] == "tests/test_session.py::test_timeout"
    # Satisfies lists merged.
    assert "ASVS:v5.0.0-5.1.1" in fr_001["satisfies"]
    assert "ASVS:v5.0.0-5.1.2" in fr_001["satisfies"]
    # Migration provenance appended to description.
    assert "Migrated from TBT-001" in fr_001["description"]


def test_migrate_v1_promotes_orphan_tbt() -> None:
    v1 = {
        "schema_version": 1,
        "project": "p",
        "frs": [],
        "tbts": [
            {
                "id": "TBT-ORPHAN-1",
                "title": "Lonely",
                "description": "No parent.",
                "required_evidence": {},
            }
        ],
    }
    report = migrate_v1_to_v2(v1)
    assert report.promoted_orphans == 1
    assert report.collapsed_count == 0
    assert report.migrated_doc["frs"][0]["id"] == "TBT-ORPHAN-1"


def test_migrate_v1_flags_any_of_divergence() -> None:
    v1 = {
        "schema_version": 1,
        "project": "p",
        "frs": [
            {
                "id": "FR-X",
                "title": "X",
                "description": "d",
                "required_evidence": {"any_of": [{"type": "scanner-result", "source_kind": "semgrep", "rule_id": "A"}]},
            }
        ],
        "tbts": [
            {
                "id": "TBT-X",
                "title": "Y",
                "description": "d",
                "parent": "FR-X",
                "required_evidence": {"any_of": [{"type": "scanner-result", "source_kind": "semgrep", "rule_id": "B"}]},
            }
        ],
    }
    report = migrate_v1_to_v2(v1)
    assert len(report.any_of_divergence) == 1
    assert report.any_of_divergence[0]["fr_id"] == "FR-X"
    assert report.any_of_divergence[0]["tbt_id"] == "TBT-X"


def test_load_catalogue_v2_validates(tmp_path: Path, sample_v2_catalogue: dict) -> None:
    catalogue_path = tmp_path / "fr-catalog.json"
    catalogue_path.write_text(json.dumps(sample_v2_catalogue))

    loaded = load_catalogue(catalogue_path, project_path=str(tmp_path))
    assert loaded.doc["project"] == "test-project"
    assert loaded.doc["schema_version"] == 2
    assert loaded.content_hash.startswith("sha256:")


def test_load_catalogue_rejects_invalid_v2(tmp_path: Path) -> None:
    import jsonschema

    bad = {"schema_version": 2, "project": "p", "frs": [{"id": "FR-1"}]}  # missing title/desc
    catalogue_path = tmp_path / "fr-catalog.json"
    catalogue_path.write_text(json.dumps(bad))

    with pytest.raises(jsonschema.ValidationError):
        load_catalogue(catalogue_path, project_path=str(tmp_path))


def test_load_catalogue_auto_migrates_v1(
    tmp_path: Path,
    sample_v1_catalogue_with_tbts: dict,
) -> None:
    catalogue_path = tmp_path / "fr-catalog.json"
    catalogue_path.write_text(json.dumps(sample_v1_catalogue_with_tbts))

    loaded = load_catalogue(catalogue_path, project_path=str(tmp_path))
    # Migration should have run.
    assert loaded.doc["schema_version"] == 2
    fr_ids = [fr["id"] for fr in loaded.doc["frs"]]
    assert "FR-001" in fr_ids
    assert "TBT-001" not in fr_ids

    # v2 file written next to v1.
    v2_path = catalogue_path.with_suffix(".v2.json")
    assert v2_path.exists()


def test_load_mapping_pack_returns_empty_when_no_path() -> None:
    pack = load_mapping_pack(None)
    assert pack.mappings == []
    assert pack.path is None
