from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_sync_module():
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "sync_authority_rulesets",
        REPO_ROOT / "scripts" / "sync-authority-rulesets.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthorityRulesetSyncTests(unittest.TestCase):
    def test_asvs_transform_uses_official_flat_export_shape(self) -> None:
        module = load_sync_module()
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "ASVS-v5.0.0.zip"
            with ZipFile(raw_path, "w") as archive:
                archive.writestr(
                    module.ASVS_FLAT_JSON,
                    json.dumps({
                        "requirements": [
                            {
                                "chapter_id": "V7",
                                "chapter_name": "Session Management",
                                "section_id": "V7.1",
                                "section_name": "Session Token Generation",
                                "req_id": "V7.1.1",
                                "req_description": "Verify expired sessions are rejected.",
                                "L": "1",
                            }
                        ]
                    }),
                )
            ruleset = module.transform_asvs({"version": "v5.0.0", "artifact": "ASVS"}, raw_path)
        self.assertEqual("ASVS", ruleset["ruleset"])
        self.assertEqual("v5.0.0", ruleset["version"])
        self.assertEqual(1, len(ruleset["rows"]))
        row = ruleset["rows"][0]
        self.assertEqual("v5.0.0-7.1.1", row["id"])
        self.assertEqual("Session Token Generation", row["title"])
        self.assertEqual("V7", row["group"])
        self.assertEqual("V7.1", row["section"])
        self.assertEqual("L1", row["level"])
        self.assertEqual("V7.1.1", row["metadata"]["authority_req_id"])
        self.assertEqual(module.ASVS_FLAT_JSON, row["metadata"]["source_export"])

    def test_nist_flatten_parts_preserves_nested_words(self) -> None:
        module = load_sync_module()
        text = module.flatten_nist_parts([
            {
                "prose": "Parent prose.",
                "parts": [
                    {"prose": "Nested prose."},
                ],
            }
        ])
        self.assertEqual("Parent prose. Nested prose.", text)
        self.assertNotIn("N e s t e d", text)


if __name__ == "__main__":
    unittest.main()
