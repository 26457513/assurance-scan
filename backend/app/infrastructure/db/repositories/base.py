"""Common repository base class.

Provides a typed session holder and a flush helper. Concrete repositories
inherit and add table-specific methods. Kept intentionally small — no
generic CRUD magic; each method is explicit and named for what it does.
"""
from __future__ import annotations

from typing import Generic, Type, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Base


ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Per-table repository base."""

    model: Type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _flush(self) -> None:
        """Flush pending changes without committing. Caller owns the commit."""
        await self.session.flush()
