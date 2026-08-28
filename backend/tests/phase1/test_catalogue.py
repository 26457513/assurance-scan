"""v3 catalogue loader tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import jsonschema

from app.catalogue import load_catalogue


def test_load_v3_catalogue_validates(tmp_path: Path) -> None:
    catalogue = {
        "schema_version": 3,
        "project": "test",
        "frs": [
            {
                "id": "FR-X",
                "title": "T",
                "description": "D",
                "tests": [
                    {"id": "t1", "type": "scanner-clean", "scanner": "semgrep"}
                ],
            }
        ],
    }
    path = tmp_path / "fr-catalog.json"
    path.write_text(json.dumps(catalogue))

    loaded = load_catalogue(path, project_path=str(tmp_path))
    assert loaded.doc["project"] == "test"
    assert loaded.doc["schema_version"] == 3
    assert loaded.content_hash.startswith("sha256:")


def test_v3_rejects_v2_catalogue(tmp_path: Path) -> None:
    v2 = {
        "schema_version": 2,
        "project": "p",
        "frs": [{"id": "FR-X", "title": "T", "description": "D"}],
    }
    path = tmp_path / "fr-catalog.json"
    path.write_text(json.dumps(v2))

    with pytest.raises(ValueError, match="schema_version=2"):
        load_catalogue(path, project_path=str(tmp_path))


def test_v3_rejects_missing_tests_field(tmp_path: Path) -> None:
    bad = {
        "schema_version": 3,
        "project": "p",
        "frs": [{"id": "FR-X", "title": "T", "description": "D"}],  # no tests
    }
    path = tmp_path / "fr-catalog.json"
    path.write_text(json.dumps(bad))

    with pytest.raises(jsonschema.ValidationError):
        load_catalogue(path, project_path=str(tmp_path))


def test_v3_accepts_empty_tests_array(tmp_path: Path) -> None:
    catalogue = {
        "schema_version": 3,
        "project": "p",
        "frs": [
            {"id": "FR-X", "title": "T", "description": "D", "tests": []}
        ],
    }
    path = tmp_path / "fr-catalog.json"
    path.write_text(json.dumps(catalogue))

    loaded = load_catalogue(path, project_path=str(tmp_path))
    assert loaded.doc["frs"][0]["tests"] == []


def test_v3_supports_depends_on(tmp_path: Path) -> None:
    catalogue = {
        "schema_version": 3,
        "project": "p",
        "frs": [
            {
                "id": "FR-A",
                "title": "A",
                "description": "D",
                "tests": [{"id": "t", "type": "scanner-clean", "scanner": "x"}],
            },
            {
                "id": "FR-B",
                "title": "B",
                "description": "D",
                "tests": [],
                "depends_on": ["FR-A"],
            },
        ],
    }
    path = tmp_path / "fr-catalog.json"
    path.write_text(json.dumps(catalogue))

    loaded = load_catalogue(path, project_path=str(tmp_path))
    assert loaded.doc["frs"][1]["depends_on"] == ["FR-A"]
