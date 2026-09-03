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


# Scanner containers see the project at this mount point; some report
# absolute container paths that must be made repo-relative.
MOUNT_PREFIX = "/src"


def strip_mount_prefix(path: str | None) -> str | None:
    """Normalize scanner container paths to repository-relative locations."""
    if not isinstance(path, str) or not path:
        return None
    if path.startswith(MOUNT_PREFIX + "/"):
        return path[len(MOUNT_PREFIX) + 1 :]
    normalized = path.lstrip("/")
    return normalized or None


def normalize_line_range(
    start: object,
    end: object = None,
) -> tuple[int | None, int | None]:
    """Keep a trustworthy positive scanner range without inventing a location."""

    line_start = _positive_line(start)
    if line_start is None:
        return None, None
    line_end = _positive_line(end)
    if line_end is None or line_end < line_start:
        line_end = line_start
    return line_start, line_end


def _positive_line(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


class FindingParser(ABC):
    """Convert raw scanner output into normalized findings."""

    @abstractmethod
    def parse(self, raw: bytes) -> list[ParsedFinding]:
        """Parse scanner stdout. Raises ParserError on malformed input."""
        raise NotImplementedError
