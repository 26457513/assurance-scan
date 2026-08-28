"""Deterministic scan-token failure limiter tests."""

from app.modules.atomic.access.auth_failure_limiter import AuthenticationFailureLimiter


async def test_failure_limiter_enforces_selector_and_expires_window() -> None:
    now = [100.0]
    limiter = AuthenticationFailureLimiter(
        origin_limit=20,
        selector_limit=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    assert (await limiter.record_failure(origin="one", selector="selector")).allowed
    assert (await limiter.record_failure(origin="two", selector="selector")).allowed
    limited = await limiter.record_failure(origin="three", selector="selector")
    assert not limited.allowed
    assert limited.retry_after_seconds == 10

    now[0] = 111.0
    assert (await limiter.record_failure(origin="three", selector="selector")).allowed


async def test_failure_limiter_enforces_origin_across_selectors() -> None:
    limiter = AuthenticationFailureLimiter(origin_limit=1, selector_limit=10)

    assert (await limiter.record_failure(origin="one", selector="a")).allowed
    assert not (await limiter.record_failure(origin="one", selector="b")).allowed
