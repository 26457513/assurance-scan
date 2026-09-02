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
