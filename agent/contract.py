from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ValueStatus(str, Enum):
    MEASURED = "measured"
    DERIVED = "derived"
    IMPUTED = "imputed"
    ABSENT = "absent"


class ToolStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    NO_DATA = "no_data"


@dataclass
class AbsentRange:
    reason: str
    ts_from: str | None = None
    ts_to: str | None = None
    scope: dict[str, str] | None = None


@dataclass
class ToolEnvelope:
    status: ToolStatus
    data: Any
    expected_points: int
    actual_points: int
    absent_ranges: list[AbsentRange] = field(default_factory=list)
    quality_grade: str = "B"
    caliber: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["coverage_pct"] = (
            round(self.actual_points / self.expected_points * 100, 1)
            if self.expected_points else 0.0
        )
        return d


def drop_absent(points: list[dict]) -> tuple[list[dict], list[AbsentRange]]:
    kept, gaps = [], []
    for p in points:
        if p.get("value_status") == ValueStatus.ABSENT.value:
            gaps.append(AbsentRange(
                reason=p.get("absent_reason", "unknown"),
                ts_from=p.get("ts_start"), ts_to=p.get("ts_end"),
                scope=p.get("scope"),
            ))
        else:
            kept.append(p)
    return kept, gaps


def safe_sum(points: list[dict], key: str) -> float | None:
    total = 0.0
    for p in points:
        if p.get("value_status") == ValueStatus.ABSENT.value:
            return None
        if p.get(key) is None:
            return None
        total += float(p[key])
    return total
