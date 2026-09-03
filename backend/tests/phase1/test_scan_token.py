"""Focused tests for the framework-free scan-token capability."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.atomic.access.scan_token import (
    CreateScanTokenCommand,
    ScanTokenActiveLimitError,
    ScanTokenAuthenticationRecord,
    ScanTokenCreateStorageDecision,
    ScanTokenCreationRateLimitError,
    ScanTokenDecision,
    ScanTokenLabelConflictError,
    ScanTokenRecord,
    ScanTokenSelectorCollisionError,
    ScanTokenValidationError,
    authenticate_scan_token,
    create_scan_token,
    digest_token_secret,
    normalize_expiry_days,
    normalize_scan_token_label,
    parse_scan_token,
)
from app.modules.atomic.access.scan_token import service as token_service
from app.modules.shared.contracts.local_scan import (
    TOKEN_ACTIVE_LIMIT,
    TOKEN_CREATION_HOURLY_LIMIT,
    TOKEN_ALLOWED_EXPIRY_DAYS,
    TOKEN_DEFAULT_EXPIRY_DAYS,
    TOKEN_MAX_EXPIRY_DAYS,
    TOKEN_PREFIX,
    TOKEN_SCOPE,
)


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class DeterministicRandom:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def random_bytes(self, size: int) -> bytes:
        self.calls.append(size)
        return bytes([len(self.calls)]) * size


class FakeRepository:
    def __init__(
        self,
        outcomes: list[ScanTokenCreateStorageDecision] | None = None,
    ) -> None:
        self.outcomes = outcomes or [ScanTokenCreateStorageDecision.CREATED]
        self.created: list[ScanTokenRecord] = []
        self.authentication_records: dict[str, ScanTokenAuthenticationRecord] = {}
        self.create_arguments: list[tuple[datetime, int, int]] = []

    async def create_token(
        self,
        record: ScanTokenRecord,
        *,
        now: datetime,
        active_limit: int,
        creation_hourly_limit: int,
    ) -> ScanTokenCreateStorageDecision:
        self.created.append(record)
        self.create_arguments.append((now, active_limit, creation_hourly_limit))
        outcome = self.outcomes.pop(0)
        if outcome is ScanTokenCreateStorageDecision.CREATED:
            self.authentication_records[record.selector] = ScanTokenAuthenticationRecord(
                token=record,
                account_name="user@example.test",
            )
        return outcome

    async def find_for_authentication(
        self,
        selector: str,
    ) -> ScanTokenAuthenticationRecord | None:
        return self.authentication_records.get(selector)


async def _issued_token() -> tuple[str, FakeRepository, ScanTokenRecord]:
    repository = FakeRepository()
    issued = await create_scan_token(
        CreateScanTokenCommand(user_id=7, label="Laptop"),
        repository=repository,
        clock=FixedClock(),
        random=DeterministicRandom(),
    )
    return issued.plaintext_token, repository, issued.record


async def test_issue_token_uses_canonical_format_digest_and_safe_repr() -> None:
    repository = FakeRepository()
    issued = await create_scan_token(
        CreateScanTokenCommand(user_id=7, label="  Ｌａｐｔｏｐ  "),
        repository=repository,
        clock=FixedClock(),
        random=DeterministicRandom(),
    )

    parsed = parse_scan_token(issued.plaintext_token)
    assert issued.plaintext_token.startswith(TOKEN_PREFIX)
    assert len(parsed.selector) == 16
    assert len(parsed.secret) == 32
    assert issued.record.secret_digest == digest_token_secret(parsed.secret)
    assert issued.record.label == "Laptop"
    assert issued.record.label_key == "laptop"
    assert issued.record.created_at == NOW
    assert issued.record.expires_at == NOW + timedelta(days=TOKEN_DEFAULT_EXPIRY_DAYS)
    assert issued.record.scope == TOKEN_SCOPE
    assert issued.record.token_version == 1
    assert repository.create_arguments == [(NOW, TOKEN_ACTIVE_LIMIT, TOKEN_CREATION_HOURLY_LIMIT)]
    assert issued.plaintext_token not in repr(issued)
    assert parsed.secret.hex() not in repr(parsed)


@pytest.mark.parametrize("days", [*TOKEN_ALLOWED_EXPIRY_DAYS, TOKEN_MAX_EXPIRY_DAYS])
async def test_issue_token_accepts_ui_expiry_choices_and_hard_max(days: int) -> None:
    issued = await create_scan_token(
        CreateScanTokenCommand(user_id=7, label="Laptop", expiry_days=days),
        repository=FakeRepository(),
        clock=FixedClock(),
        random=DeterministicRandom(),
    )
    assert issued.record.expires_at == NOW + timedelta(days=days)


@pytest.mark.parametrize("days", [0, TOKEN_MAX_EXPIRY_DAYS + 1, True, 2.5])
def test_expiry_rejects_invalid_values(days: object) -> None:
    with pytest.raises(ScanTokenValidationError):
        normalize_expiry_days(days)  # type: ignore[arg-type]


def test_label_is_nfkc_normalized_casefolded_and_control_free() -> None:
    assert normalize_scan_token_label("  ＷｏｒｋＳＴＡＴＩＯＮ  ") == (
        "WorkSTATION",
        "workstation",
    )
    for invalid in ("", "   ", "a" * 65, "lap\ntop", "lap\u200dtop"):
        with pytest.raises(ScanTokenValidationError):
            normalize_scan_token_label(invalid)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "asu_legacy_abc.def",
        f"{TOKEN_PREFIX}short.secret",
        f"{TOKEN_PREFIX}{'a' * 16}.{'b' * 42}=",
        f"{TOKEN_PREFIX}{'!' * 16}.{'b' * 43}",
    ],
)
def test_parse_rejects_malformed_or_noncanonical_tokens(token: str) -> None:
    with pytest.raises(ScanTokenValidationError):
        parse_scan_token(token)


@pytest.mark.parametrize(
    ("storage_decision", "error"),
    [
        (
            ScanTokenCreateStorageDecision.ACTIVE_LIMIT_REACHED,
            ScanTokenActiveLimitError,
        ),
        (
            ScanTokenCreateStorageDecision.LABEL_CONFLICT,
            ScanTokenLabelConflictError,
        ),
        (
            ScanTokenCreateStorageDecision.CREATION_RATE_LIMITED,
            ScanTokenCreationRateLimitError,
        ),
    ],
)
async def test_issue_maps_transactional_storage_decisions_to_domain_errors(
    storage_decision: ScanTokenCreateStorageDecision,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await create_scan_token(
            CreateScanTokenCommand(user_id=7, label="Laptop"),
            repository=FakeRepository([storage_decision]),
            clock=FixedClock(),
            random=DeterministicRandom(),
        )


async def test_issue_retries_selector_collisions_with_fresh_random_material() -> None:
    random = DeterministicRandom()
    repository = FakeRepository(
        [
            ScanTokenCreateStorageDecision.SELECTOR_COLLISION,
            ScanTokenCreateStorageDecision.CREATED,
        ]
    )
    issued = await create_scan_token(
        CreateScanTokenCommand(user_id=7, label="Laptop"),
        repository=repository,
        clock=FixedClock(),
        random=random,
    )
    assert issued.record == repository.created[-1]
    assert len(repository.created) == 2
    assert repository.created[0].selector != repository.created[1].selector
    assert random.calls == [12, 32, 16, 12, 32, 16]


async def test_issue_stops_after_bounded_selector_collisions() -> None:
    repository = FakeRepository([ScanTokenCreateStorageDecision.SELECTOR_COLLISION] * 4)
    with pytest.raises(ScanTokenSelectorCollisionError):
        await create_scan_token(
            CreateScanTokenCommand(user_id=7, label="Laptop"),
            repository=repository,
            clock=FixedClock(),
            random=DeterministicRandom(),
        )
    assert len(repository.created) == 4


async def test_valid_token_returns_principal_contract() -> None:
    plaintext, repository, record = await _issued_token()
    result = await authenticate_scan_token(
        plaintext,
        repository=repository,
        clock=FixedClock(),
    )
    assert result.authenticated is True
    assert result.decision is ScanTokenDecision.AUTHENTICATED
    assert result.principal is not None
    assert result.principal.token_id == record.token_id
    assert result.principal.user_id == 7
    assert result.principal.account_name == "user@example.test"
    assert result.principal.token_label == "Laptop"
    assert result.principal.scope == TOKEN_SCOPE


@pytest.mark.parametrize(
    ("record_change", "decision"),
    [
        ({"user_disabled_at": NOW}, ScanTokenDecision.USER_DISABLED),
        ({"revoked_at": NOW}, ScanTokenDecision.REVOKED),
        ({"expires_at": NOW}, ScanTokenDecision.EXPIRED),
        ({"scope": "other:scope"}, ScanTokenDecision.INSUFFICIENT_SCOPE),
    ],
)
async def test_authenticated_secret_still_applies_account_token_and_scope_decisions(
    record_change: dict[str, object],
    decision: ScanTokenDecision,
) -> None:
    plaintext, repository, record = await _issued_token()
    token_changes = dict(record_change)
    user_disabled_at = token_changes.pop("user_disabled_at", None)
    changed = replace(record, **token_changes)
    repository.authentication_records[record.selector] = ScanTokenAuthenticationRecord(
        token=changed,
        account_name="user@example.test",
        user_disabled_at=user_disabled_at if isinstance(user_disabled_at, datetime) else None,
    )

    result = await authenticate_scan_token(
        plaintext,
        repository=repository,
        clock=FixedClock(),
    )
    assert result.decision is decision
    assert result.principal is None


async def test_wrong_secret_is_invalid_before_token_state_is_considered() -> None:
    plaintext, repository, record = await _issued_token()
    repository.authentication_records[record.selector] = ScanTokenAuthenticationRecord(
        token=replace(record, revoked_at=NOW),
        account_name="user@example.test",
    )
    prefix, _secret = plaintext.rsplit(".", 1)
    wrong = f"{prefix}.{'A' * 43}"

    result = await authenticate_scan_token(
        wrong,
        repository=repository,
        clock=FixedClock(),
    )
    assert result.decision is ScanTokenDecision.INVALID


@pytest.mark.parametrize("plaintext", ["malformed", None])
async def test_malformed_credentials_still_execute_dummy_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
    plaintext: object,
) -> None:
    comparisons: list[tuple[object, object]] = []
    original = token_service.hmac.compare_digest

    def recording_compare(left: object, right: object) -> bool:
        comparisons.append((left, right))
        return original(left, right)  # type: ignore[arg-type]

    monkeypatch.setattr(token_service.hmac, "compare_digest", recording_compare)
    result = await authenticate_scan_token(
        plaintext,  # type: ignore[arg-type]
        repository=FakeRepository(),
        clock=FixedClock(),
    )
    assert result.decision is ScanTokenDecision.INVALID
    assert len(comparisons) == 1
    assert all(isinstance(value, bytes) and len(value) == 32 for value in comparisons[0])


async def test_unknown_selector_executes_dummy_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plaintext, _repository, _record = await _issued_token()
    comparisons: list[tuple[object, object]] = []
    original = token_service.hmac.compare_digest

    def recording_compare(left: object, right: object) -> bool:
        comparisons.append((left, right))
        return original(left, right)  # type: ignore[arg-type]

    monkeypatch.setattr(token_service.hmac, "compare_digest", recording_compare)
    result = await authenticate_scan_token(
        plaintext,
        repository=FakeRepository(),
        clock=FixedClock(),
    )
    assert result.decision is ScanTokenDecision.INVALID
    assert len(comparisons) == 1
    assert all(isinstance(value, bytes) and len(value) == 32 for value in comparisons[0])


def test_naive_clock_is_rejected_at_the_atomic_boundary() -> None:
    with pytest.raises(RuntimeError, match="timezone-aware"):
        token_service._aware_time(datetime(2026, 8, 28, 12, 0))
