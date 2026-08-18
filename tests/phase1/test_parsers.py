"""Parser tests for each scanner output format."""
from __future__ import annotations

import json
from pathlib import Path

from server.worker.parsers.gitleaks import GitleaksJsonParser
from server.worker.parsers.grype import GrypeJsonParser
from server.worker.parsers.osv_scanner import OsvScannerJsonParser
from server.worker.parsers.semgrep import SemgrepSarifParser
from server.worker.parsers.syft import SyftSbomParser
from server.worker.parsers.trivy import TrivyJsonParser


def test_semgrep_parser_extracts_findings_from_sarif() -> None:
    sarif = {
        "runs": [{
            "tool": {"driver": {"rules": [
                {"id": "eval-detected", "properties": {"security-severity": 8.0}}
            ]}},
            "results": [
                {
                    "ruleId": "eval-detected",
                    "level": "warning",
                    "message": {"text": "Detected eval()"},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": "/src/foo.py"},
                            "region": {"startLine": 10, "endLine": 10},
                        }
                    }],
                }
            ],
        }]
    }
    raw = json.dumps(sarif).encode()
    findings = SemgrepSarifParser(project_root="/src").parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner_kind == "semgrep"
    assert f.rule_id == "eval-detected"
    assert f.severity == "HIGH"
    assert f.file_path == "foo.py"
    assert f.line_start == 10


def test_gitleaks_parser_extracts_leak() -> None:
    raw = json.dumps([{
        "RuleID": "aws-access-key",
        "File": "/src/src/config.py",
        "StartLine": 5,
        "Description": "AWS access key",
        "Secret": "AKIAIOSFODNN7EXAMPLE",
    }]).encode()
    findings = GitleaksJsonParser().parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "aws-access-key"
    assert f.severity == "HIGH"
    assert f.theme == "secrets"


def test_trivy_fs_parser_extracts_vulnerabilities() -> None:
    raw = json.dumps({
        "Results": [{
            "Target": "package-lock.json",
            "Vulnerabilities": [{
                "VulnerabilityID": "CVE-2024-1",
                "PkgName": "lodash",
                "InstalledVersion": "4.17.20",
                "FixedVersion": "4.17.21",
                "Severity": "HIGH",
                "Description": "Prototype pollution.",
            }],
        }]
    }).encode()
    findings = TrivyJsonParser(scanner_kind="trivy-fs", mode="vuln").parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner_kind == "trivy-fs"
    assert f.rule_id == "CVE-2024-1"
    assert f.severity == "HIGH"
    assert f.fix_strategy == "dependency-update"


def test_trivy_config_parser_extracts_misconfigurations() -> None:
    raw = json.dumps({
        "Results": [{
            "Target": "Dockerfile",
            "Misconfigurations": [{
                "ID": "DS001",
                "Title": "Root user",
                "Description": "Container runs as root.",
                "Severity": "MEDIUM",
                "Resolution": "Add USER directive.",
            }],
        }]
    }).encode()
    findings = TrivyJsonParser(scanner_kind="trivy-config", mode="config").parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner_kind == "trivy-config"
    assert f.rule_id == "DS001"
    assert f.fix_strategy == "config-only"


def test_grype_parser_extracts_matches() -> None:
    raw = json.dumps({
        "matches": [{
            "vulnerability": {
                "id": "CVE-2024-2",
                "severity": "High",
                "description": "RCE",
                "fix": {"versions": ["1.2.3"]},
            },
            "artifact": {
                "name": "express",
                "version": "4.0.0",
                "locations": [{"path": "package.json"}],
            },
        }]
    }).encode()
    findings = GrypeJsonParser().parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CVE-2024-2"
    assert f.severity == "HIGH"


def test_osv_scanner_parser_extracts_results() -> None:
    raw = json.dumps({
        "results": [{
            "source": {"path": "/src/package-lock.json"},
            "packages": [{
                "package": {"name": "lodash", "version": "4.17.20"},
                "vulnerabilities": [{
                    "id": "GHSA-1",
                    "summary": "Prototype pollution.",
                    "database_specific": {"severity": "HIGH"},
                    "affected": [{"ranges": [{"events": [{"fixed": "4.17.21"}]}]}],
                }],
            }],
        }]
    }).encode()
    findings = OsvScannerJsonParser().parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.scanner_kind == "osv-scanner"
    assert f.rule_id == "GHSA-1"


def test_syft_parser_emits_no_findings() -> None:
    raw = b'{"components": []}'
    findings = SyftSbomParser().parse(raw)
    assert findings == []


def test_semgrep_parser_handles_malformed_json() -> None:
    import pytest
    from server.worker.parsers.semgrep import ParserError
    with pytest.raises(ParserError):
        SemgrepSarifParser().parse(b"not json")
