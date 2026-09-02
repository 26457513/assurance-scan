"""Framework- and persistence-neutral GitHub webhook contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class GithubWebhookErrorCode(StrEnum):
    BODY_TOO_LARGE = "body_too_large"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    INVALID_DELIVERY_ID = "invalid_delivery_id"
    INVALID_EVENT = "invalid_event"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_JSON = "invalid_json"


class WebhookClaimDecision(StrEnum):
    ACQUIRED = "acquired"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class GithubWebhookSecrets:
    current: bytes = field(repr=False)
    previous: bytes | None = field(default=None, repr=False)
    previous_valid_until: datetime | None = None


@dataclass(frozen=True)
class VerifiedGithubWebhook:
    delivery_id: str
    body_hash: str
    event: str
    action: str
    payload: dict[str, Any]
    mutation_allowed: bool
    used_previous_secret: bool


class GithubWebhookError(ValueError):
    """A safe, classified webhook boundary rejection."""

    def __init__(self, code: GithubWebhookErrorCode) -> None:
        super().__init__(code.value)
        self.code = code
