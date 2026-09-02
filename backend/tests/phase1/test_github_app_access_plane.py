"""GitHub App webhook boundary and durable delivery-claim tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from app.infrastructure.db.models import GithubWebhookDelivery
from app.infrastructure.db.repositories.github_webhooks import (
    SqlAlchemyGithubWebhookDeliveryRepository,
)
from app.modules.atomic.access.github_webhook import (
    GithubWebhookError,
    GithubWebhookErrorCode,
    GithubWebhookSecrets,
    WebhookClaimDecision,
    claim_github_webhook,
    complete_github_webhook_work,
    lease_github_webhook_work,
    retry_github_webhook_work,
    verify_github_webhook,
)
from app.modules.shared.contracts.ingest_v2 import WEBHOOK_POLICY_V2


FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "fixtures" / "ingest-v2" / "webhooks"
NOW = dt.datetime(2026, 9, 2, 16, 0, tzinfo=dt.timezone.utc)
DELIVERY_ID = "f87d8b0c-29f8-4c11-8cc0-3eb13482b386"
CURRENT = b"assurance-scan-current-test-secret"
PREVIOUS = b"assurance-scan-previous-test-secret"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _signature(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def _verify(
    body: bytes,
    *,
    signature: str | None = None,
    event: str = "installation",
    secrets: GithubWebhookSecrets | None = None,
):
    return verify_github_webhook(
        body,
        content_type="application/json; charset=utf-8",
        delivery_id=DELIVERY_ID,
        event=event,
        signature=signature or _signature(CURRENT, body),
        secrets=secrets or GithubWebhookSecrets(current=CURRENT),
        now=NOW,
    )


def test_exact_raw_body_signature_and_allowlisted_action_are_accepted() -> None:
    body = _fixture("installation-created.json")

    verified = _verify(body)

    assert verified.body_hash == hashlib.sha256(body).hexdigest()
    assert verified.action == "created"
    assert verified.github_installation_id == 9001
    assert verified.mutation_allowed is True
    assert verified.used_previous_secret is False


def test_previous_secret_only_works_inside_bounded_rotation_overlap() -> None:
    body = _fixture("installation-created.json")
    signature = _signature(PREVIOUS, body)
    active = GithubWebhookSecrets(
        current=CURRENT,
        previous=PREVIOUS,
        previous_valid_until=NOW + dt.timedelta(minutes=30),
    )
    expired = replace(active, previous_valid_until=NOW - dt.timedelta(microseconds=1))
    excessive = replace(active, previous_valid_until=NOW + dt.timedelta(hours=1, seconds=1))

    assert _verify(body, signature=signature, secrets=active).used_previous_secret is True
    with pytest.raises(GithubWebhookError) as rejected:
        _verify(body, signature=signature, secrets=expired)
    assert rejected.value.code is GithubWebhookErrorCode.INVALID_SIGNATURE
    with pytest.raises(GithubWebhookError) as excessive_rejection:
        _verify(body, signature=signature, secrets=excessive)
    assert excessive_rejection.value.code is GithubWebhookErrorCode.INVALID_SIGNATURE


def test_authenticated_unsupported_event_is_acknowledged_without_mutation() -> None:
    body = _fixture("installation-created.json")

    verified = _verify(body, event="issues")

    assert verified.action == "created"
    assert verified.mutation_allowed is False


@pytest.mark.parametrize(
    ("overrides", "code"),
    (
        ({"content_type": "text/plain"}, GithubWebhookErrorCode.INVALID_CONTENT_TYPE),
        ({"delivery_id": "not-a-guid"}, GithubWebhookErrorCode.INVALID_DELIVERY_ID),
        ({"signature": "sha1=deadbeef"}, GithubWebhookErrorCode.INVALID_SIGNATURE),
    ),
)
def test_malformed_headers_fail_with_classified_errors(overrides, code) -> None:
    body = _fixture("installation-created.json")
    arguments = {
        "content_type": "application/json",
        "delivery_id": DELIVERY_ID,
        "event": "installation",
        "signature": _signature(CURRENT, body),
        "secrets": GithubWebhookSecrets(current=CURRENT),
        "now": NOW,
        **overrides,
    }

    with pytest.raises(GithubWebhookError) as rejected:
        verify_github_webhook(body, **arguments)

    assert rejected.value.code is code


def test_json_is_parsed_only_after_signature_and_duplicate_keys_fail_closed() -> None:
    body = b'{"action":"created","action":"deleted"}'
    with pytest.raises(GithubWebhookError) as invalid_signature:
        _verify(body, signature="sha256=" + "0" * 64)
    assert invalid_signature.value.code is GithubWebhookErrorCode.INVALID_SIGNATURE

    with pytest.raises(GithubWebhookError) as invalid_json:
        _verify(body)
    assert invalid_json.value.code is GithubWebhookErrorCode.INVALID_JSON


def test_oversized_body_is_rejected_before_other_header_or_signature_work() -> None:
    body = b"x" * (WEBHOOK_POLICY_V2.maximum_body_bytes + 1)

    with pytest.raises(GithubWebhookError) as rejected:
        verify_github_webhook(
            body,
            content_type="text/plain",
            delivery_id="invalid",
            event="invalid",
            signature="invalid",
            secrets=GithubWebhookSecrets(current=b""),
            now=NOW,
        )

    assert rejected.value.code is GithubWebhookErrorCode.BODY_TOO_LARGE


@pytest.mark.asyncio
async def test_delivery_claim_is_atomic_replay_or_security_conflict(session) -> None:
    body = _fixture("installation-created.json")
    verified = _verify(body)
    repository = SqlAlchemyGithubWebhookDeliveryRepository(session)

    first = await claim_github_webhook(verified, repository=repository, now=NOW)
    replay = await claim_github_webhook(verified, repository=repository, now=NOW)
    conflict = await claim_github_webhook(replace(verified, body_hash="f" * 64), repository=repository, now=NOW)

    assert first is WebhookClaimDecision.ACQUIRED
    assert replay is WebhookClaimDecision.REPLAY
    assert conflict is WebhookClaimDecision.CONFLICT
    row = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
    assert row.status == "received"
    assert row.expires_at == (NOW + dt.timedelta(days=30)).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_unsupported_delivery_is_durably_acknowledged(session) -> None:
    body = json.dumps({"action": "opened"}, separators=(",", ":")).encode()
    verified = _verify(body, event="issues")

    decision = await claim_github_webhook(
        verified,
        repository=SqlAlchemyGithubWebhookDeliveryRepository(session),
        now=NOW,
    )

    assert decision is WebhookClaimDecision.ACQUIRED
    row = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
    assert row.status == "acknowledged"
    assert row.processed_at == NOW.replace(tzinfo=None)


def test_allowlisted_mutation_requires_a_positive_installation_id() -> None:
    body = b'{"action":"created","installation":{"id":false}}'

    with pytest.raises(GithubWebhookError) as rejected:
        _verify(body)

    assert rejected.value.code is GithubWebhookErrorCode.INVALID_JSON


@pytest.mark.asyncio
async def test_mutation_work_uses_exclusive_lease_retry_and_stale_completion_protection(session) -> None:
    verified = _verify(_fixture("installation-created.json"))
    repository = SqlAlchemyGithubWebhookDeliveryRepository(session)
    await claim_github_webhook(verified, repository=repository, now=NOW)

    first = await lease_github_webhook_work(
        repository=repository,
        now=NOW,
        lease_token="d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    unavailable = await lease_github_webhook_work(
        repository=repository,
        now=NOW,
        lease_token="81385ad2-b885-48e1-b9f0-75a53f8844db",
    )

    assert first is not None
    assert first.github_installation_id == 9001
    assert first.attempt_count == 1
    assert unavailable is None
    assert await retry_github_webhook_work(
        first,
        repository=repository,
        now=NOW,
        error_code="github_unavailable",
    )
    assert (
        await lease_github_webhook_work(
            repository=repository,
            now=NOW + dt.timedelta(seconds=29),
            lease_token="be320fd7-9bcd-4fb8-826e-ce3c256e7ac7",
        )
        is None
    )
    second = await lease_github_webhook_work(
        repository=repository,
        now=NOW + dt.timedelta(seconds=30),
        lease_token="be320fd7-9bcd-4fb8-826e-ce3c256e7ac7",
    )
    assert second is not None
    assert second.attempt_count == 2
    assert not await complete_github_webhook_work(
        first,
        repository=repository,
        now=NOW + dt.timedelta(seconds=31),
    )
    assert await complete_github_webhook_work(
        second,
        repository=repository,
        now=NOW + dt.timedelta(seconds=31),
    )
    row = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
    assert row.status == "processed"
    assert row.attempt_count == 2
    assert row.lease_token is None


@pytest.mark.asyncio
async def test_eighth_mutation_attempt_fails_terminally(session) -> None:
    verified = _verify(_fixture("installation-created.json"))
    repository = SqlAlchemyGithubWebhookDeliveryRepository(session)
    await claim_github_webhook(verified, repository=repository, now=NOW)
    leased = await lease_github_webhook_work(
        repository=repository,
        now=NOW,
        lease_token="d8cf87fd-0489-4a4f-8d55-8bf7f5ff9244",
    )
    assert leased is not None

    assert await retry_github_webhook_work(
        replace(leased, attempt_count=8),
        repository=repository,
        now=NOW,
        error_code="github_unavailable",
    )
    row = (await session.execute(select(GithubWebhookDelivery))).scalar_one()
    assert row.status == "failed"
    assert row.processed_at == NOW.replace(tzinfo=None)
    assert row.last_error_code == "github_unavailable"
