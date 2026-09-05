"""Parser tests for each scanner output format."""
from __future__ import annotations

import json

from app.modules.atomic.scanning.finding_parser import GitleaksJsonParser
from app.modules.atomic.scanning.finding_parser import GrypeJsonParser
from app.modules.atomic.scanning.finding_parser import OsvScannerJsonParser
from app.modules.atomic.scanning.finding_parser import SemgrepSarifParser
from app.modules.atomic.scanning.finding_parser import SyftSbomParser
from app.modules.atomic.scanning.finding_parser import TrivyJsonParser


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
                            "region": {"startLine": 10, "endLine": 12},
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
    assert f.line_end == 12


def test_gitleaks_parser_extracts_leak() -> None:
    raw = json.dumps([{
        "RuleID": "aws-access-key",
        "File": "/src/src/config.py",
        "StartLine": 5,
        "EndLine": 7,
        "Description": "AWS access key",
        "Secret": "AKIAIOSFODNN7EXAMPLE",
    }]).encode()
    findings = GitleaksJsonParser().parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "aws-access-key"
    assert f.severity == "HIGH"
    assert f.theme == "secrets"
    assert (f.line_start, f.line_end) == (5, 7)
    assert "AKIAIOSFODNN7EXAMPLE" not in f.message
    assert "AKIAIOSF" not in f.message


def test_trivy_fs_parser_extracts_vulnerabilities() -> None:
    raw = json.dumps({
        "Results": [{
            "Target": "package-lock.json",
            "Vulnerabilities": [{
                "VulnerabilityID": "CVE-2024-1",
                "PkgName": "lodash",
                "InstalledVersion": "4.17.20",
                "PkgType": "npm",
                "PkgIdentifier": {"PURL": "pkg:npm/lodash@4.17.20"},
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
    assert (f.package_name, f.package_version, f.package_ecosystem) == ("lodash", "4.17.20", "npm")
    assert f.package_purl == "pkg:npm/lodash@4.17.20"


def test_trivy_config_parser_extracts_misconfigurations() -> None:
    raw = json.dumps({
        "Results": [{
            "Target": "/src/Dockerfile",
            "Misconfigurations": [{
                "ID": "DS001",
                "Title": "Root user",
                "Description": "Container runs as root.",
                "Severity": "MEDIUM",
                "CauseMetadata": {"StartLine": 4, "EndLine": 6},
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
    assert f.file_path == "Dockerfile"
    assert (f.line_start, f.line_end) == (4, 6)


def test_scanner_ranges_are_not_invented_from_invalid_values() -> None:
    semgrep = SemgrepSarifParser().parse(json.dumps({
        "runs": [{
            "tool": {"driver": {"rules": []}},
            "results": [{
                "ruleId": "python.test",
                "level": "warning",
                "message": {"text": "unsafe call"},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": "src/app.py"},
                        "region": {"startLine": "4", "endLine": 9},
                    }
                }],
            }],
        }]
    }).encode())[0]
    gitleaks = GitleaksJsonParser().parse(json.dumps([{
        "RuleID": "generic-api-key",
        "File": "/src/app.env",
        "StartLine": True,
        "EndLine": 3,
    }]).encode())[0]

    assert (semgrep.line_start, semgrep.line_end) == (None, None)
    assert (gitleaks.line_start, gitleaks.line_end) == (None, None)


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
                "type": "npm",
                "purl": "pkg:npm/express@4.0.0",
                "locations": [{"path": "/yarn.lock"}],
            },
        }]
    }).encode()
    findings = GrypeJsonParser().parse(raw)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "CVE-2024-2"
    assert f.severity == "HIGH"
    assert f.file_path == "yarn.lock"
    assert (f.line_start, f.line_end) == (None, None)
    assert (f.package_name, f.package_version, f.package_ecosystem) == ("express", "4.0.0", "npm")
    assert f.package_purl == "pkg:npm/express@4.0.0"


def test_osv_scanner_parser_extracts_results() -> None:
    raw = json.dumps({
        "results": [{
            "source": {"path": "/src/package-lock.json"},
            "packages": [{
                "package": {
                    "name": "lodash",
                    "version": "4.17.20",
                    "ecosystem": "npm",
                    "purl": "pkg:npm/lodash@4.17.20",
                },
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
    assert f.file_path == "package-lock.json"
    assert (f.line_start, f.line_end) == (None, None)
    assert (f.package_name, f.package_version, f.package_ecosystem) == ("lodash", "4.17.20", "npm")
    assert f.package_purl == "pkg:npm/lodash@4.17.20"


def test_syft_parser_emits_no_findings() -> None:
    raw = b'{"components": []}'
    findings = SyftSbomParser().parse(raw)
    assert findings == []


def test_semgrep_parser_handles_malformed_json() -> None:
    import pytest
    from app.modules.atomic.scanning.finding_parser import SemgrepParserError as ParserError
    with pytest.raises(ParserError):
        SemgrepSarifParser().parse(b"not json")
