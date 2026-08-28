"""Data types returned by the shared redaction capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class RedactionResult:
    """A detached redacted value and the number of replacements made."""

    value: JSONValue
    replacements: int


__all__ = ["JSONValue", "RedactionResult"]
