# 三个 SubAgent 的代码实现

<span style="color:#888">（本文是代码规格，不是可直接运行的文件。落地时按第一节的目录树拆成独立 `.py`。代码一律英文；中文说明放在括号里，以注释或灰字呈现。）</span>

<span style="color:#888">（注：GitHub 会剥掉行内 `style`，灰色只在 VS Code 预览、Typora 等本地渲染器里生效；代码块内的中文注释在任何渲染器下都是灰的。）</span>

---

## 一、目录树

```
agent/
├── contract.py       ← §二   (四态数据 + 工具返回信封)
├── boundary.py       ← §三   (出网过滤，闸二)
├── verifier.py       ← §四   (结论回检，闸三)
├── base.py           ← §五   (SubAgent 基类)
├── subagents/
│   ├── tools_sub1.py ← §六   (任务监测与能碳预测)
│   ├── tools_sub2.py ← §六   (绿电匹配与低碳识别)
│   ├── tools_sub3.py ← §六   (因子对齐与核算)
│   ├── sub1_forecast.py
│   ├── sub2_lowcarbon.py
│   └── sub3_factor.py
├── orchestrator.py   ← §七   (主 Agent)
└── prompts/                  (提示词五个文件，不在本文范围)
```

<span style="color:#888">（`core/` 的确定性算法不在本文范围。工具函数调用的 `core.*` 以 `# STUB` 标出，需另行实现。）</span>

---

## 二、三道闸 —— 约束落到哪一行

| 约束 | 落点 |
|---|---|
| absent 不是 0，不是 None | `contract.py` 的 `safe_sum()` / `drop_absent()` |
| 明细数据不出本机 | `boundary.py` 的 `filter_outbound()` |
| Agent 说的数字必须有据 | `verifier.py` 的 `verify_numbers()` |
| 数字由代码算，话由 Agent 说 | 工具只返回 `ToolEnvelope`；Agent 无计算权 |

---

## 三、`agent/contract.py`

```python
"""Data existence contract: four-state values + a uniform tool envelope."""
# （地基。核心命题：「没测到」和「测得是 0」必须在类型层面分开。）
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ValueStatus(str, Enum):
    MEASURED = "measured"   # （实测）
    DERIVED = "derived"     # （由实测值确定性推导）
    IMPUTED = "imputed"     # （补全值，必须带 method）
    ABSENT = "absent"       # （没有。不是 0，不是 None）


class ToolStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    NO_DATA = "no_data"


@dataclass
class AbsentRange:
    """One explicit gap in the data."""
    # （显式列出，不让模型自己去发现。）
    reason: str
    ts_from: str | None = None
    ts_to: str | None = None
    scope: str | None = None


@dataclass
class Coverage:
    expected_points: int
    actual_points: int

    @property
    def pct(self) -> float:
        if self.expected_points == 0:
            return 0.0
        return round(self.actual_points / self.expected_points * 100, 1)


@dataclass
class ToolEnvelope:
    """The only shape a tool may return."""
    # （禁止返回裸数据：模型必须同时看到数值和它的覆盖度。）
    status: ToolStatus
    data: Any
    coverage: Coverage
    absent_ranges: list[AbsentRange] = field(default_factory=list)
    quality_grade: str = "B"                 # （A/B/C/D）
    caliber: dict[str, Any] | None = None    # （口径标注，测算类工具必填）

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["coverage"]["pct"] = self.coverage.pct
        return d


def drop_absent(points: list[dict]) -> tuple[list[dict], list[AbsentRange]]:
    """Remove absent points from data; return them as declared gaps."""
    # （闸一。模型看不到空位，就没有空位可填——留 None 占位等于邀请它猜。）
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
    """Sum a series that may contain absent points. Returns None if any is absent."""
    # （🔴 只要有一个 absent 就返回 None，绝不当 0 加进去。
    #    这是「有就是有，没有就是没有」在代码层唯一的兑现方式。）
    total = 0.0
    for p in points:
        if p.get("value_status") == ValueStatus.ABSENT.value:
            return None
        v = p.get(key)
        if v is None:
            return None
        total += float(v)
    return total
```

---

## 四、`agent/boundary.py`

```python
"""Outbound boundary: the single exit through which anything reaches the API."""
# （所有 SubAgent 共用这一个出口。任何 SubAgent 不得自带过滤逻辑——多套规则必然出现漏洞。）
from __future__ import annotations

import hashlib
import json
import re

from .contract import ToolEnvelope

FORBIDDEN_KEYS = {                      # （精确匹配即剔除）
    "device_serial", "serial_no", "ip", "ip_addr", "hostname",
    "rack_location", "room_address", "contract_no", "raw_file_path",
    "token_log_detail",
}

PSEUDONYM_KEYS = {                      # （字段名 → 代号前缀）
    "job_name": "job", "model_id": "model",
    "server_model": "sku", "device_id": "node",
}

_GAP_NOTICE = (
    "\n\n[DATA GAPS] The following ranges have no data. "
    "Do not infer their values, do not substitute neighbouring periods or "
    "similar hardware, and do not treat them as zero in any aggregation:\n{gaps}"
)


def _pseudonymize(value: str, prefix: str) -> str:
    """Stable pseudonym: same input always yields the same code."""
    # （稳定脱敏，便于跨轮次对照同一台机器。）
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:6]}"


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                continue                # （直接剔除，不留占位）
            if k in PSEUDONYM_KEYS and isinstance(v, str):
                out[k] = _pseudonymize(v, PSEUDONYM_KEYS[k])
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


def filter_outbound(env: ToolEnvelope) -> str:
    """Scrub the envelope and append an explicit prohibition when gaps exist."""
    # （闸二。有缺口就把禁令写进出网文本，而不是指望提示词记得住。）
    text = json.dumps(_scrub(env.to_dict()), ensure_ascii=False, default=str)
    if env.absent_ranges:
        lines = [
            f"  - {('[' + a.scope + '] ') if a.scope else ''}"
            f"{(a.ts_from + ' ~ ' + a.ts_to) if a.ts_from else '(all periods)'}: {a.reason}"
            for a in env.absent_ranges
        ]
        text += _GAP_NOTICE.format(gaps="\n".join(lines))
    return text


def assert_no_leak(text: str) -> None:
    """Last-resort self-check. Raises rather than leaks."""
    # （宁可中断，不可泄露。）
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        raise ValueError("boundary: outbound text looks like it contains an IP")
    if re.search(r"\b[0-9a-fA-F]{16,}\b", text):
        raise ValueError("boundary: outbound text looks like it contains a serial number")
```

<span style="color:#888">（另有 `agent/audit.py`，把每次调用的 `agent_name / tool_name / 收发摘要 / token 数` 追加成一行 JSON。结构直白，此处从略。）</span>

---

## 五、`agent/verifier.py`

```python
"""Gate three: every number the agent utters must trace back to a tool result."""
# （「数字由代码算，话由 Agent 说」的反向验证：既然数字由代码算，
#   那 Agent 说出的数字就应当能在代码算出的结果里找到。）
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
_TRIVIAL = {str(n) for n in range(11)} | {"100", "24", "2025", "2026"}
# （个位数、百分数基数、年份不视为「事实数字」，跳过校验。）


@dataclass
class VerifyResult:
    passed: bool
    unverified: list[str]

    def message(self) -> str:
        if self.passed:
            return "verification passed"
        return ("unverified numbers (possibly fabricated): "
                + ", ".join(self.unverified))


def _norm(v) -> str:
    """Normalise for comparison: strip thousands separators and trailing zeros."""
    s = str(v).replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else f"{f:.6f}".rstrip("0").rstrip(".")


def _harvest(obj, pool: set[str]) -> None:
    """Recursively collect every numeric value appearing in a tool payload."""
    if isinstance(obj, dict):
        for v in obj.values():
            _harvest(v, pool)
    elif isinstance(obj, list):
        for v in obj:
            _harvest(v, pool)
    elif isinstance(obj, (int, float)):
        pool.add(_norm(obj))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            pool.add(_norm(m.group(0)))


def verify_numbers(agent_text: str, tool_payloads: list[str],
                   *, tolerance: float = 0.01) -> VerifyResult:
    """Check each number in the agent's prose against the tool results."""
    # （tolerance 是相对误差：Agent 做合理四舍五入应当放行，凭空造数不应当。）
    pool: set[str] = set()
    for p in tool_payloads:
        try:
            _harvest(json.loads(p.split("\n\n[DATA GAPS]")[0]), pool)
        except json.JSONDecodeError:
            _harvest(p, pool)

    numeric = []
    for s in pool:
        try:
            numeric.append(float(s))
        except ValueError:
            pass

    bad = []
    for m in _NUM.finditer(agent_text):
        raw = m.group(0)
        key = _norm(raw)
        if key in _TRIVIAL or key in pool:
            continue
        try:
            val = float(key)
        except ValueError:
            continue
        if any(abs(val - n) <= tolerance * max(abs(n), 1e-9) for n in numeric):
            continue                    # （在容差内找到了来源）
        bad.append(raw)

    return VerifyResult(passed=not bad, unverified=bad)
```

---

## 六、`agent/base.py`

```python
"""Shared base for the three SubAgents."""
from __future__ import annotations

import os
from pathlib import Path

import anthropic

from .verifier import verify_numbers

MODEL = "claude-opus-5"
PROMPT_DIR = Path(__file__).parent / "prompts"


class SubAgentBase:
    name: str = "sub-agent"
    prompt_file: str = ""
    tools: list = []

    def __init__(self, client: anthropic.Anthropic | None = None):
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set; agent features are unavailable "
                    "(the rest of the platform still works)"
                )
            client = anthropic.Anthropic()
        self.client = client

    def system_prompt(self) -> str:
        """Shared rules first, then this agent's own instructions."""
        # （_shared.md 承载三道闸的自然语言版本，三个 Agent 共用一份，避免各写各的。）
        shared = (PROMPT_DIR / "_shared.md").read_text(encoding="utf-8")
        own = (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")
        return f"{shared}\n\n---\n\n{own}"

    def run(self, user_input: str, *, max_tokens: int = 16000) -> dict:
        runner = self.client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=max_tokens,
            system=self.system_prompt(),
            thinking={"type": "adaptive"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            tools=self.tools,
            messages=[{"role": "user", "content": user_input}],
        )

        payloads: list[str] = []
        final = None
        for message in runner:
            final = message
            resp = runner.generate_tool_call_response()
            if resp is not None:
                for block in resp["content"]:
                    payloads.append(str(block.get("content", "")))

        text = "".join(b.text for b in (final.content if final else [])
                       if getattr(b, "type", "") == "text")

        result = verify_numbers(text, payloads)
        return {
            "agent": self.name,
            "text": text,
            "verified": result.passed,
            "verify_message": result.message(),
        }
```

<span style="color:#888">（`tool_runner` 接受 `system` / `thinking` / `betas` / `fallbacks` —— 已在 anthropic 1.4.0 上用 `inspect.signature` 核对过完整参数表，不是推测。）</span>

---

## 七、工具层

<span style="color:#888">（九个工具形状完全一致，只有 `core.*` 不同。这里给出统一出口和一个完整范例，其余用签名表列出，不重复贴同构代码。）</span>

```python
"""agent/subagents/tools_sub1.py — task monitoring and energy/carbon forecast."""
from __future__ import annotations

from anthropic import beta_tool

from ..boundary import assert_no_leak, filter_outbound
from ..contract import Coverage, ToolEnvelope, ToolStatus, drop_absent


def _emit(env: ToolEnvelope) -> str:
    """The only way a tool returns. Filter, then self-check, then hand over."""
    # （任何工具都不得自己拼返回串——否则边界就有了第二个出口。）
    text = filter_outbound(env)
    assert_no_leak(text)
    return text


@beta_tool
def query_idle_rate(model_sku: str, ts_from: str, ts_to: str) -> str:
    """Report idle rate and idle energy for one server SKU over a period.

    Args:
        model_sku: Server SKU identifier.
        ts_from: ISO8601 start timestamp, inclusive.
        ts_to: ISO8601 end timestamp, exclusive.
    """
    from core import idle as core_idle          # STUB

    raw = core_idle.idle_rate(model_sku, ts_from, ts_to)
    kept, gaps = drop_absent(raw["points"])
    return _emit(ToolEnvelope(
        status=ToolStatus.OK if not gaps else ToolStatus.PARTIAL,
        data={"points": kept, "idle_energy_kwh": raw["idle_energy_kwh"]},
        coverage=Coverage(raw["expected"], len(kept)),
        absent_ranges=gaps,
        quality_grade=raw["grade"],
        caliber={"idle_threshold_pct": raw["threshold"]},
    ))


# （query_load_profile / forecast_energy 同构，见下表。）
TOOLS_SUB1 = [query_idle_rate, query_load_profile, forecast_energy]
```

### 九个工具

| Agent | 工具 | 调用的 core 函数 | 回答哪个问题 |
|---|---|---|---|
| 1 | `query_idle_rate` | `core.idle.idle_rate` | 空置率、空载能耗 |
| 1 | `query_load_profile` | `core.load.profile` | 哪些时段负荷突增 |
| 1 | `forecast_energy` | `core.forecast.energy` | 下一周期能耗预测 |
| 2 | `query_grid_mix` | `core.grid.hourly_mix` | 逐小时风光占比 |
| 2 | `match_cfe_hourly` | `core.cfe.hourly_match` | 24/7 CFE 匹配得分 |
| 2 | `storage_net_effect` | `core.storage.net_carbon` | 储能是真减碳还是负贡献 |
| 3 | `align_factors` | `core.factor.align` | 跨库因子对齐与差异 |
| 3 | `token_footprint` | `core.token.footprint` | 每百万 Token 碳足迹 |
| 3 | `build_report` | `core.report.render` | 核算报告 |

<span style="color:#888">（每个都套用上面的模板：取 core 结果 → `drop_absent` → 装进 `ToolEnvelope` → `_emit`。测算类工具的 `caliber` 必填，否则口径不明的数字会被当成可比数字。）</span>

---

## 八、`agent/orchestrator.py`

```python
"""Main agent: fan out to the three SubAgents, then assemble."""
from __future__ import annotations

from .subagents.sub1_forecast import Sub1Forecast
from .subagents.sub2_lowcarbon import Sub2LowCarbon
from .subagents.sub3_factor import Sub3Factor


class Orchestrator:
    def __init__(self):
        self.subs = [Sub1Forecast(), Sub2LowCarbon(), Sub3Factor()]

    def _safe_run(self, sub, task: str) -> dict:
        """One failing SubAgent must not take the other two down with it."""
        try:
            return sub.run(task)
        except Exception as exc:
            return {"agent": sub.name, "text": "", "verified": False,
                    "verify_message": f"failed: {exc}"}

    def run(self, task: str) -> str:
        results = [self._safe_run(s, task) for s in self.subs]
        return self._summarize(results)

    def _summarize(self, results: list[dict]) -> str:
        """Gaps go first, findings second."""
        # （🔴 缺口写在开头，不写成脚注。折叠进脚注的缺口，和没写没有区别。）
        gaps = [r for r in results if not r["verified"]]
        out = []
        if gaps:
            out.append("## 数据与校验缺口（先看这里）")
            out += [f"- **{r['agent']}**：{r['verify_message']}" for r in gaps]
            out.append("")
        out.append("## 分析结果")
        out += [f"### {r['agent']}\n{r['text']}" for r in results if r["text"]]
        return "\n".join(out)
```

---

## 九、测试骨架

```python
"""tests/test_gates.py — the three gates, one assertion each."""
import ast
import pathlib

import pytest

from agent.boundary import assert_no_leak, filter_outbound
from agent.contract import Coverage, ToolEnvelope, ToolStatus, safe_sum
from agent.verifier import verify_numbers


def test_absent_is_never_summed_as_zero():
    points = [{"value_status": "measured", "kwh": 10},
              {"value_status": "absent", "kwh": None}]
    assert safe_sum(points, "kwh") is None    # （不是 10）


def test_forbidden_key_never_leaves():
    env = ToolEnvelope(ToolStatus.OK, {"ip": "10.0.0.1", "kwh": 5},
                       Coverage(1, 1))
    text = filter_outbound(env)
    assert "10.0.0.1" not in text
    assert "kwh" in text


def test_leak_check_raises():
    with pytest.raises(ValueError):
        assert_no_leak('{"note": "node at 192.168.1.7"}')


def test_fabricated_number_is_caught():
    payload = '{"total_kwh": 1200}'
    assert verify_numbers("总能耗 1200 kWh", [payload]).passed
    assert not verify_numbers("总能耗 9999 kWh", [payload]).passed


def test_core_must_not_import_agent():
    """core/ is deterministic and must stay independent of the agent layer."""
    # （分层检查：core 一旦反向依赖 agent，「数字由代码算」就守不住了。）
    for path in pathlib.Path("core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod = (node.module if isinstance(node, ast.ImportFrom)
                   else getattr(node, "names", [None])[0])
            name = mod if isinstance(mod, str) else getattr(mod, "name", "")
            assert not str(name).startswith("agent"), f"{path} imports agent"
```

---

## 十、未实现

| 项 | 状态 |
|---|---|
| `core/*` 九个确定性算法 | 未实现，工具里以 `# STUB` 标出 |
| `prompts/` 五个提示词文件 | 未写 |
| `audit.py` | 结构已定，代码从略 |
| 排放因子库的版本管理 | 未设计 |

**已核实**：`tool_runner` 的参数表（含 `system` / `thinking` / `betas` / `fallbacks` / `output_config`）经 anthropic 1.4.0 的 `inspect.signature` 实际读取确认。

**未核实**：`core.*` 的返回结构是我按工具需要拟定的，`core/` 实现时若与此不符，改工具层的取值，不要改 `ToolEnvelope` 的形状。

<span style="color:#888">（相关文档：[提示词为什么分五个文件](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)）</span>
