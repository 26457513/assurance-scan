"""Generated artifact API and CycloneDX inventory contracts."""

from __future__ import annotations

import json

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.atomic.scanning.sbom_inventory import (
    SbomInventoryError,
    apply_security_status,
    extract_packages,
    supports_package_identity,
)


@pytest_asyncio.fixture
async def client():
    from app.infrastructure.db.connection import get_engine, get_sessionmaker
    from app.infrastructure.db.models import Base, Project, Run, ScannerRun
    from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
    from app.infrastructure.db.repositories.findings import FindingRepository

    app = create_app()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as session:
        project = Project(tag="artifacts", local_path="/projects/artifacts")
        session.add(project)
        await session.flush()
        session.add(Run(run_id="run-artifacts", project_id=project.id, origin="server", status="completed"))
        await session.flush()
        for scanner_kind, kind, content in (
            (
                "assurance-scan/findings",
                "json",
                b'{"capabilities":["package-identity-v1"],"findings":[]}',
            ),
            ("assurance-scan/sarif", "sarif", b'{"version":"2.1.0","runs":[]}'),
            (
                "assurance-scan/sbom",
                "cyclonedx-json",
                json.dumps(_sbom()).encode(),
            ),
        ):
            scanner_run = ScannerRun(run_id="run-artifacts", scanner_kind=scanner_kind, status="completed")
            session.add(scanner_run)
            await session.flush()
            await ScannerArtifactRepository(session).store(scanner_run.id, kind, content)
        session.add(ScannerRun(run_id="run-artifacts", scanner_kind="grype", status="completed"))
        await FindingRepository(session).bulk_insert([{
            "run_id": "run-artifacts",
            "scanner_kind": "grype",
            "rule_id": "CVE-1",
            "severity": "HIGH",
            "message": "svelte 5.0.0 vulnerable to CVE-1",
            "theme": "dependency",
            "compliance_tags": [],
            "package_name": "svelte",
            "package_version": "5.0.0",
            "package_ecosystem": "npm",
            "package_purl": "pkg:npm/svelte@5.0.0",
        }])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client

    from app.infrastructure.db import connection

    await engine.dispose()
    connection._engine = None
    connection._sessionmaker = None


def _sbom() -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {
                "bom-ref": "pkg:npm/svelte@5.0.0",
                "type": "library",
                "name": "svelte",
                "version": "5.0.0",
                "purl": "pkg:npm/svelte@5.0.0",
                "licenses": [{"license": {"id": "MIT"}}],
            }
        ],
        "vulnerabilities": [{"id": "CVE-1", "affects": [{"ref": "pkg:npm/svelte@5.0.0"}]}],
    }


def test_extract_packages_normalizes_cyclonedx() -> None:
    packages = extract_packages(json.dumps(_sbom()).encode())
    assert packages == [{
        "bom_ref": "pkg:npm/svelte@5.0.0",
        "name": "svelte",
        "version": "5.0.0",
        "ecosystem": "npm",
        "component_type": "library",
        "purl": "pkg:npm/svelte@5.0.0",
        "licenses": ["MIT"],
        "security_status": "not_assessed",
        "highest_severity": None,
        "finding_count": 0,
    }]


def test_extract_packages_rejects_non_cyclonedx() -> None:
    try:
        extract_packages(b'{"bomFormat":"SPDX","components":[]}')
    except SbomInventoryError as exc:
        assert str(exc) == "SBOM is not a CycloneDX document"
    else:
        raise AssertionError("non-CycloneDX document was accepted")


def test_security_status_is_conservative_and_uses_structured_identity() -> None:
    packages = extract_packages(json.dumps(_sbom()).encode())
    finding = {
        "package_name": "svelte",
        "package_version": "5.0.0",
        "package_ecosystem": "npm",
        "package_purl": "pkg:npm/svelte@5.0.0",
        "severity": "MEDIUM",
    }
    assert apply_security_status(
        packages,
        [finding],
        {"grype": "completed"},
        package_identity_supported=True,
    )[0] == {
        **packages[0],
        "security_status": "finding",
        "highest_severity": "MEDIUM",
        "finding_count": 1,
    }
    assert apply_security_status(
        packages,
        [],
        {"grype": "completed"},
        package_identity_supported=True,
    )[0]["security_status"] == "clear"
    assert apply_security_status(
        packages,
        [],
        {"grype": "completed"},
        package_identity_supported=False,
    )[0]["security_status"] == "not_assessed"
    assert apply_security_status(
        packages,
        [],
        {"grype": "failed"},
        package_identity_supported=True,
    )[0]["security_status"] == "not_assessed"


def test_package_identity_capability_is_explicit_and_fails_closed() -> None:
    assert supports_package_identity(
        b'{"capabilities":["package-identity-v1"]}'
    )
    assert not supports_package_identity(b'{"findings":[]}')
    assert not supports_package_identity(b"not-json")


async def test_artifact_inventory_and_download(client) -> None:
    response = await client.get("/api/scans/run-artifacts/artifacts")
    assert response.status_code == 200
    body = response.json()
    assert body["retention_days"] == 30
    assert [item["name"] for item in body["artifacts"]] == ["findings", "sarif", "sbom"]
    assert all(item["available"] for item in body["artifacts"])

    download = await client.get("/api/scans/run-artifacts/artifacts/sarif")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == 'attachment; filename="results.sarif"'
    assert download.headers["cache-control"] == "private, no-store"
    assert download.json()["version"] == "2.1.0"


async def test_sbom_package_projection(client) -> None:
    response = await client.get("/api/scans/run-artifacts/artifacts/sbom/packages")
    assert response.status_code == 200
    assert response.json()["packages"][0]["name"] == "svelte"
    assert response.json()["packages"][0]["security_status"] == "failing"
    assert response.json()["packages"][0]["highest_severity"] == "HIGH"
    assert response.json()["packages"][0]["finding_count"] == 1


async def test_unknown_artifact_does_not_expose_storage(client) -> None:
    response = await client.get("/api/scans/run-artifacts/artifacts/../../config")
    assert response.status_code == 404
