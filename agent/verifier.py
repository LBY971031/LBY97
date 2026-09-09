from __future__ import annotations

import re
from dataclasses import dataclass

from .boundary import GAP_MARK

_NUM = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
_TRIVIAL = {float(n) for n in range(11)} | {100.0, 24.0, 2025.0, 2026.0}


@dataclass
class VerifyResult:
    passed: bool
    unverified: list[str]

    def message(self) -> str:
        return ("verification passed" if self.passed else
                "unverified numbers: " + ", ".join(self.unverified))


def _numbers(text: str) -> list[float]:
    return [float(m.group(0).replace(",", "")) for m in _NUM.finditer(text)]


def verify_numbers(agent_text: str, tool_payloads: list[str],
                   *, tolerance: float = 0.01) -> VerifyResult:
    pool = [n for p in tool_payloads for n in _numbers(p.split(GAP_MARK)[0])]
    bad = [
        m.group(0) for m in _NUM.finditer(agent_text)
        if (v := float(m.group(0).replace(",", ""))) not in _TRIVIAL
        and not any(abs(v - n) <= tolerance * max(abs(n), 1e-9) for n in pool)
    ]
    return VerifyResult(passed=not bad, unverified=bad)
