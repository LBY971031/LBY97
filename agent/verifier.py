from __future__ import annotations

import re
from dataclasses import dataclass

from .boundary import GAP_MARK

_NUM = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w])")
# 已知盲区，这是一个自觉的取舍。
# 0-59 全部视为平凡数字，因为报告里的时刻（15:00、45 分钟、30 日）无法与
# 同量级的编造数字区分。放过它们，是为了不让每一份写了日期时刻的正常报告
# 都被标记未通过——那样闸三会被用的人直接关掉，反而一点用没有。
# 代价：小于 60 的编造整数可能蒙混过关（例如凭空的「同比下降 15%」）。
# 这个代价可接受，因为本项目真正要守的是能耗与碳排数值，它们几乎总是带
# 小数、且远大于 60；小整数极少承载实质结论。
_TRIVIAL = {float(n) for n in range(60)} | {100.0, 2025.0, 2026.0}


@dataclass
class VerifyResult:
    passed: bool
    unverified: list[str]

    def message(self) -> str:
        return ("verification passed" if self.passed else
                "unverified numbers: " + ", ".join(self.unverified))


_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _numbers(text: str) -> list[float]:
    """Every number a tool payload vouches for.

    Dates are split into year/month/day as well: an agent writing "8 月 30 日"
    is quoting the data, not inventing a number, but the plain scan never sees
    that 30 because "30T15" reads as one word to the regex. Clock parts are
    handled by _TRIVIAL instead - see the note there.
    """
    out = [float(m.group(0).replace(",", "")) for m in _NUM.finditer(text)]
    for m in _ISO_DATE.finditer(text):
        out += [float(g) for g in m.groups()]
    return out


def verify_numbers(agent_text: str, tool_payloads: list[str],
                   *, tolerance: float = 0.01) -> VerifyResult:
    pool = [n for p in tool_payloads for n in _numbers(p.split(GAP_MARK)[0])]
    bad = [
        m.group(0) for m in _NUM.finditer(agent_text)
        if (v := float(m.group(0).replace(",", ""))) not in _TRIVIAL
        and not any(abs(v - n) <= tolerance * max(abs(n), 1e-9) for n in pool)
    ]
    return VerifyResult(passed=not bad, unverified=bad)
