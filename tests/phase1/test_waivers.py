"""FR-WAIVERS-MANAGE tests.

Verifies the waiver repository: standing waivers can be created, listed per
project and per FR, filtered by expiry, and revoked. Expiry filtering is
the security-relevant piece — an expired waiver must NOT suppress an FR.
"""
from __future__ import annotations

import datetime as dt

from server.db.repositories.waivers import WaiverRepository


async def test_create_then_list_for_project(session) -> None:
    """Created waivers come back via list_for_project, newest first."""
    repo = WaiverRepository(session)
    await repo.create(
        project_path="/proj",
        fr_id="FR-A",
        reason="architectural",
        waived_by="agent:claude",
    )
    await repo.create(
        project_path="/proj",
        fr_id="FR-B",
        reason="temporary",
        waived_by="user:jd",
    )

    rows = await repo.list_for_project("/proj")
    assert len(rows) == 2
    # Newest first (waived_at desc).
    assert rows[0].fr_id == "FR-B"
    assert rows[1].fr_id == "FR-A"


async def test_list_isolates_by_project(session) -> None:
    """Waivers are project-scoped — no cross-project leakage."""
    repo = WaiverRepository(session)
    await repo.create("/proj-A", "FR-A", "r", "u")
    await repo.create("/proj-B", "FR-B", "r", "u")
    a = await repo.list_for_project("/proj-A")
    b = await repo.list_for_project("/proj-B")
    assert len(a) == 1 and a[0].fr_id == "FR-A"
    assert len(b) == 1 and b[0].fr_id == "FR-B"


async def test_list_for_fr_filters_by_fr(session) -> None:
    """list_for_fr narrows within a project to a single FR."""
    repo = WaiverRepository(session)
    await repo.create("/p", "FR-A", "r", "u")
    await repo.create("/p", "FR-A", "another", "u")
    await repo.create("/p", "FR-B", "r", "u")

    a = await repo.list_for_fr("/p", "FR-A")
    b = await repo.list_for_fr("/p", "FR-B")
    assert len(a) == 2
    assert len(b) == 1


async def test_expired_waiver_filtered_by_default(session) -> None:
    """An expired waiver must NOT appear in the default listing — it can no
    longer suppress the FR's state.
    """
    repo = WaiverRepository(session)
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    await repo.create("/p", "FR-EXPIRED", "old", "u", expires_at=past)
    await repo.create("/p", "FR-STANDING", "ongoing", "u")  # no expiry

    default = await repo.list_for_project("/p")
    assert {w.fr_id for w in default} == {"FR-STANDING"}

    include_expired = await repo.list_for_project("/p", include_expired=True)
    assert {w.fr_id for w in include_expired} == {"FR-EXPIRED", "FR-STANDING"}


async def test_future_expiration_included_by_default(session) -> None:
    """A waiver with a future expiry is still active and appears by default."""
    repo = WaiverRepository(session)
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
    await repo.create("/p", "FR-TIMEBOXED", "review in 7d", "u", expires_at=future)
    rows = await repo.list_for_project("/p")
    assert len(rows) == 1
    assert rows[0].fr_id == "FR-TIMEBOXED"


async def test_delete_removes_waiver(session) -> None:
    """Revoking a waiver deletes it; subsequent listings don't include it."""
    repo = WaiverRepository(session)
    waiver = await repo.create("/p", "FR-A", "r", "u")
    assert await repo.delete(waiver.id) is True
    assert await repo.list_for_project("/p") == []
    # Deleting a non-existent waiver returns False (idempotent).
    assert await repo.delete(9999) is False
