"""Authorized generated-artifact inventory, downloads and SBOM projection."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.api.deps_project_access import ProjectAccessDep
from app.api.schemas.artifact import (
    ArtifactListResponse,
    ArtifactSummary,
    SbomPackage,
    SbomPackageListResponse,
)
from app.infrastructure.db.models import ScannerArtifact
from app.infrastructure.db.repositories.scanner_artifacts import ScannerArtifactRepository
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.infrastructure.project_access import require_run
from app.modules.atomic.scanning.sbom_inventory import (
    SbomInventoryError,
    apply_security_status,
    extract_packages,
    supports_package_identity,
)
from app.modules.shared.contracts.local_scan import RETENTION_DAYS


router = APIRouter(prefix="/scans/{run_id}/artifacts", tags=["artifacts"])

_ARTIFACTS = {
    "findings": ("assurance-scan/findings", "findings.json", "Normalized findings bundle", "application/json"),
    "sarif": ("assurance-scan/sarif", "results.sarif", "Unified SARIF report", "application/sarif+json"),
    "sbom": (
        "assurance-scan/sbom",
        "sbom.cyclonedx.json",
        "CycloneDX software inventory",
        "application/vnd.cyclonedx+json",
    ),
}
_BY_SCANNER = {details[0]: (name, *details[1:]) for name, details in _ARTIFACTS.items()}


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts(
    run_id: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> ArtifactListResponse:
    if await require_run(session, principal, run_id) is None:
        raise HTTPException(status_code=404, detail=f"scan {run_id} not found")
    rows = await ScannerArtifactRepository(session).list_published_for_run(run_id)
    artifacts: list[ArtifactSummary] = []
    for scanner_run, artifact in rows:
        definition = _BY_SCANNER.get(scanner_run.scanner_kind)
        if definition is None:
            continue
        name, filename, description, media_type = definition
        artifacts.append(_summary(run_id, name, filename, description, media_type, scanner_run.status, artifact))
    return ArtifactListResponse(
        run_id=run_id,
        retention_days=RETENTION_DAYS.raw_artifacts,
        artifacts=artifacts,
    )


@router.get("/sbom/packages", response_model=SbomPackageListResponse)
async def list_sbom_packages(
    run_id: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> SbomPackageListResponse:
    artifact = await _artifact_for_name(run_id, "sbom", principal, session)
    try:
        packages = extract_packages(ScannerArtifactRepository.decompress(artifact))
    except SbomInventoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finding_rows = await FindingRepository(session).list_for_run(run_id, limit=20_000)
    scanner_rows = await ScannerRunRepository(session).list_for_run(run_id)
    package_identity_supported = False
    try:
        findings_artifact = await _artifact_for_name(
            run_id, "findings", principal, session
        )
    except HTTPException as exc:
        if exc.status_code not in {404, 410}:
            raise
    else:
        package_identity_supported = supports_package_identity(
            ScannerArtifactRepository.decompress(findings_artifact)
        )
    packages = apply_security_status(
        packages,
        [
            {
                "severity": finding.severity,
                "package_name": finding.package_name,
                "package_version": finding.package_version,
                "package_ecosystem": finding.package_ecosystem,
                "package_purl": finding.package_purl,
            }
            for finding in finding_rows
            if finding.package_name or finding.package_purl
        ],
        {scanner.scanner_kind: scanner.status for scanner in scanner_rows},
        package_identity_supported=package_identity_supported,
    )
    return SbomPackageListResponse(
        run_id=run_id,
        total=len(packages),
        packages=[SbomPackage.model_validate(package) for package in packages],
    )


@router.get("/{name}")
async def download_artifact(
    run_id: str,
    name: str,
    principal: ProjectAccessDep,
    session: AsyncSession = SessionDep,
) -> Response:
    definition = _ARTIFACTS.get(name)
    if definition is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    artifact = await _artifact_for_name(run_id, name, principal, session)
    _, filename, _, media_type = definition
    return Response(
        content=ScannerArtifactRepository.decompress(artifact),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _artifact_for_name(
    run_id: str,
    name: str,
    principal: ProjectAccessDep,
    session: AsyncSession,
) -> ScannerArtifact:
    definition = _ARTIFACTS.get(name)
    if definition is None or await require_run(session, principal, run_id) is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    scanner_kind = definition[0]
    rows = await ScannerArtifactRepository(session).list_published_for_run(run_id)
    for scanner_run, artifact in rows:
        if scanner_run.scanner_kind == scanner_kind:
            if artifact is None:
                raise HTTPException(status_code=410, detail="artifact retention period has ended")
            return artifact
    raise HTTPException(status_code=404, detail="artifact not found")


def _summary(
    run_id: str,
    name: str,
    filename: str,
    description: str,
    media_type: str,
    status: str,
    artifact: ScannerArtifact | None,
) -> ArtifactSummary:
    available = artifact is not None
    created_at = artifact.created_at if artifact else None
    expires_at = (
        created_at + dt.timedelta(days=RETENTION_DAYS.raw_artifacts)
        if created_at is not None
        else None
    )
    return ArtifactSummary(
        name=name,
        filename=filename,
        description=description,
        media_type=media_type,
        status=status,
        available=available,
        size_bytes=artifact.size_bytes if artifact else None,
        content_hash=artifact.content_hash if artifact else None,
        created_at=created_at,
        expires_at=expires_at,
        download_url=f"/api/scans/{run_id}/artifacts/{name}" if available else None,
    )
