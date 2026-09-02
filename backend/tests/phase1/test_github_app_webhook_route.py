"""HTTP boundary tests for feature-gated GitHub App webhooks."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import github_app_webhook
from app.infrastructure.db.connection import get_session
from app.infrastructure.db.models import Base, GithubWebhookDelivery
from app.modules.shared.contracts.ingest_v2 import WEBHOOK_POLICY_V2


FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "fixtures" / "ingest-v2" / "webhooks"
DELIVERY_ID = "f87d8b0c-29f8-4c11-8cc0-3eb13482b386"
SECRET = "assurance-scan-current-test-secret"


def _headers(body: bytes, *, event: str = "installation") -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-GitHub-Delivery": DELIVERY_ID,
        "X-GitHub-Event": event,
        "X-Hub-Signature-256": f"sha256={digest}",
    }


@pytest.mark.asyncio
async def test_valid_delivery_and_replay_are_durably_acknowledged(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'webhook.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with sessions() as database_session:
            yield database_session

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        github_webhook_enabled=True,
        github_webhook_secret=SECRET,
        github_webhook_previous_secret="",
        github_webhook_previous_valid_until="",
    )
    app.include_router(github_app_webhook.router, prefix="/api")
    app.dependency_overrides[get_session] = session_override
    body = (FIXTURES / "installation-created.json").read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        accepted = await client.post("/api/v2/github/webhook", content=body, headers=_headers(body))
        replayed = await client.post("/api/v2/github/webhook", content=body, headers=_headers(body))

    assert accepted.status_code == 202
    assert accepted.json() == {"status": "accepted"}
    assert replayed.status_code == 202
    assert replayed.json() == {"status": "replayed"}
    async with sessions() as database_session:
        delivery = (await database_session.execute(select(GithubWebhookDelivery))).scalar_one()
        assert delivery.delivery_id == DELIVERY_ID
        assert delivery.github_installation_id == 9001
        assert delivery.status == "received"
        assert delivery.available_at is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_id_reuse_with_another_signed_body_is_a_conflict(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'conflict.sqlite'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with sessions() as database_session:
            yield database_session

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        github_webhook_enabled=True,
        github_webhook_secret=SECRET,
        github_webhook_previous_secret="",
        github_webhook_previous_valid_until="",
    )
    app.include_router(github_app_webhook.router, prefix="/api")
    app.dependency_overrides[get_session] = session_override
    created = (FIXTURES / "installation-created.json").read_bytes()
    added = (FIXTURES / "repositories-added.json").read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        assert (await client.post("/api/v2/github/webhook", content=created, headers=_headers(created))).status_code == 202
        conflict = await client.post(
            "/api/v2/github/webhook",
            content=added,
            headers=_headers(added, event="installation_repositories"),
        )

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "webhook delivery conflict"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_webhook_is_invisible_when_disabled_and_rejects_oversize_before_verification() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(github_webhook_enabled=False)
    app.include_router(github_app_webhook.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        hidden = await client.post("/api/v2/github/webhook", content=b"{}")
    assert hidden.status_code == 404

    app.state.settings = SimpleNamespace(
        github_webhook_enabled=True,
        github_webhook_secret=SECRET,
        github_webhook_previous_secret="",
        github_webhook_previous_valid_until="",
    )
    oversized = b"x" * (WEBHOOK_POLICY_V2.maximum_body_bytes + 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://scan.example.test") as client:
        rejected = await client.post("/api/v2/github/webhook", content=oversized)
    assert rejected.status_code == 413
