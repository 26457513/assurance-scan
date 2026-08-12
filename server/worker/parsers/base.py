"""Parser interface shared by all scanner-specific parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedFinding:
    """One finding, normalized across all scanner types."""

    scanner_kind: str
    rule_id: str | None
    severity: str               # CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN
    file_path: str | None
    line_start: int | None
    line_end: int | None
    message: str
    theme: str | None = None
    fix_strategy: str | None = None
    compliance_tags: tuple[str, ...] = ()


class FindingParser(ABC):
    """Convert raw scanner output into normalized findings."""

    @abstractmethod
    def parse(self, raw: bytes) -> list[ParsedFinding]:
        """Parse scanner stdout. Raises ParserError on malformed input."""
        raise NotImplementedError
