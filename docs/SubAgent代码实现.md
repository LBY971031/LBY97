# 三个 SubAgent 的代码实现

<span style="color:#888">（代码规格，非可运行文件。落地时按目录树拆成独立 `.py`。代码内一律英文；中文说明放在代码块外的灰字里。GitHub 会剥掉行内 `style`，灰色只在本地渲染器生效。）</span>

---

## 一、目录树

```
agent/
├── contract.py       §三   四态数据 + 工具返回信封
├── boundary.py       §四   出网过滤
├── verifier.py       §五   结论回检
├── base.py           §六   SubAgent 基类
├── subagents/        §七   三套工具 + 三个 Agent 类
├── orchestrator.py   §八   主 Agent
└── prompts/                提示词五个文件（不在本文范围）
```

<span style="color:#888">（`core/` 的确定性算法不在本文范围，工具里以 `# STUB` 标出。）</span>

---

## 二、三道闸

| 约束 | 落点 |
|---|---|
| absent 不是 0，不是 None | `contract.safe_sum` / `drop_absent` |
| 明细数据不出本机 | `boundary.filter_outbound` |
| Agent 说的数字必须有据 | `verifier.verify_numbers` |
| 数字由代码算，话由 Agent 说 | 工具只返回 `ToolEnvelope`，Agent 无计算权 |

---

## 三、`agent/contract.py`

```python
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
    scope: str | None = None


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
```

<span style="color:#888">（四态而非「有值/null」二态——「没测到」和「测得是 0」必须在类型层面分开。`drop_absent` 把缺失点从数据里剔除、单列成缺口声明：模型看不到空位，就没有空位可填。`safe_sum` 只要遇到一个 absent 就返回 `None`，绝不当 0 加进去——这是「有就是有，没有就是没有」在代码层唯一的兑现方式。）</span>

---

## 四、`agent/boundary.py`

```python
from __future__ import annotations

import hashlib
import json
import re

from .contract import ToolEnvelope

FORBIDDEN = {
    "device_serial", "serial_no", "ip", "ip_addr", "hostname",
    "rack_location", "room_address", "contract_no", "raw_file_path",
    "token_log_detail",
}
PSEUDONYM = {"job_name": "job", "model_id": "model",
             "server_model": "sku", "device_id": "node"}

GAP_MARK = "\n\n[DATA GAPS]"
_GAP_NOTICE = GAP_MARK + (
    " The following ranges have no data. Do not infer their values, do not "
    "substitute neighbouring periods or similar hardware, and do not treat "
    "them as zero in any aggregation:\n{gaps}"
)


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in FORBIDDEN:
                continue
            if k in PSEUDONYM and isinstance(v, str):
                h = hashlib.sha256(v.encode()).hexdigest()[:6]
                out[k] = f"{PSEUDONYM[k]}-{h}"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


def filter_outbound(env: ToolEnvelope) -> str:
    text = json.dumps(_scrub(env.to_dict()), ensure_ascii=False, default=str)
    if env.absent_ranges:
        lines = [
            f"  - {('[' + a.scope + '] ') if a.scope else ''}"
            f"{(a.ts_from + ' ~ ' + a.ts_to) if a.ts_from else '(all periods)'}"
            f": {a.reason}"
            for a in env.absent_ranges
        ]
        text += _GAP_NOTICE.format(gaps="\n".join(lines))
    return text


def assert_no_leak(text: str) -> None:
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        raise ValueError("boundary: outbound text may contain an IP")
    if re.search(r"\b[0-9a-fA-F]{16,}\b", text):
        raise ValueError("boundary: outbound text may contain a serial number")
```

<span style="color:#888">（全部 SubAgent 共用这一个出口，任何 Agent 不得自带过滤逻辑——多套规则必然出现漏洞。禁发字段直接剔除、不留占位；标识类字段做稳定脱敏，同一台机器每次得到同一代号，便于跨轮次对照。有缺口就把禁令写进出网文本，而不是指望提示词记得住。`assert_no_leak` 是兜底：宁可中断，不可泄露。）</span>

---

## 五、`agent/verifier.py`

```python
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
```

<span style="color:#888">（「数字由代码算，话由 Agent 说」的反向验证：既然数字由代码算，Agent 说出的数字就应当能在代码算出的结果里找到。`tolerance` 放行合理四舍五入，不放行凭空造数；`_TRIVIAL` 让个位数、百分数基数、年份不参与校验，避免"共 3 台"这类表述误报。缺口告知段落被切掉，防止其中的时间戳被当成数据来源。）</span>

---

## 六、`agent/base.py`

```python
from __future__ import annotations

import os
from pathlib import Path

import anthropic

from .verifier import verify_numbers

MODEL = "claude-opus-5"
PROMPT_DIR = Path(__file__).parent / "prompts"


class SubAgentBase:
    name = "sub-agent"
    prompt_file = ""
    tools: list = []

    def __init__(self, client: anthropic.Anthropic | None = None):
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic()
        self.client = client

    def system_prompt(self) -> str:
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

        payloads, final = [], None
        for message in runner:
            final = message
            resp = runner.generate_tool_call_response()
            if resp is not None:
                payloads += [str(b.get("content", "")) for b in resp["content"]]

        text = "".join(b.text for b in (final.content if final else [])
                       if getattr(b, "type", "") == "text")
        result = verify_numbers(text, payloads)
        return {"agent": self.name, "text": text,
                "verified": result.passed, "note": result.message()}
```

<span style="color:#888">（`_shared.md` 承载三道闸的自然语言版本，三个 Agent 共用一份，避免各写各的。`tool_runner` 接受 `system` / `thinking` / `betas` / `fallbacks` —— 已在 anthropic 1.4.0 上用 `inspect.signature` 核对过完整参数表，不是推测。）</span>

---

## 七、工具层

```python
from anthropic import beta_tool

from ..boundary import assert_no_leak, filter_outbound
from ..contract import ToolEnvelope, ToolStatus, drop_absent


def _emit(env: ToolEnvelope) -> str:
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
    from core import idle as core_idle           # STUB

    raw = core_idle.idle_rate(model_sku, ts_from, ts_to)
    kept, gaps = drop_absent(raw["points"])
    return _emit(ToolEnvelope(
        status=ToolStatus.PARTIAL if gaps else ToolStatus.OK,
        data={"points": kept, "idle_energy_kwh": raw["idle_energy_kwh"]},
        expected_points=raw["expected"], actual_points=len(kept),
        absent_ranges=gaps, quality_grade=raw["grade"],
        caliber={"idle_threshold_pct": raw["threshold"]},
    ))
```

<span style="color:#888">（九个工具形状完全一致，只有 `core.*` 不同，故只给一个范例。每个都套同一模板：取 core 结果 → `drop_absent` → 装进 `ToolEnvelope` → `_emit`。任何工具都不得自己拼返回串，否则边界就有了第二个出口。测算类工具的 `caliber` 必填，否则口径不明的数字会被当成可比数字。）</span>

| Agent | 工具 | core 函数 | 回答 |
|---|---|---|---|
| 1 | `query_idle_rate` | `core.idle.idle_rate` | 空置率、空载能耗 |
| 1 | `query_load_profile` | `core.load.profile` | 哪些时段负荷突增 |
| 1 | `forecast_energy` | `core.forecast.energy` | 下一周期能耗预测 |
| 2 | `query_grid_mix` | `core.grid.hourly_mix` | 逐小时风光占比 |
| 2 | `match_cfe_hourly` | `core.cfe.hourly_match` | 24/7 CFE 匹配得分 |
| 2 | `storage_net_effect` | `core.storage.net_carbon` | 储能真减碳还是负贡献 |
| 3 | `align_factors` | `core.factor.align` | 跨库因子对齐与差异 |
| 3 | `token_footprint` | `core.token.footprint` | 每百万 Token 碳足迹 |
| 3 | `build_report` | `core.report.render` | 核算报告 |

<span style="color:#888">（三个 Agent 类各自只是 `SubAgentBase` 的四行子类：设定 `name`、`prompt_file`、`tools`，无需额外逻辑。）</span>

---

## 八、`agent/orchestrator.py`

```python
from __future__ import annotations

from .subagents.sub1_forecast import Sub1Forecast
from .subagents.sub2_lowcarbon import Sub2LowCarbon
from .subagents.sub3_factor import Sub3Factor


class Orchestrator:
    def __init__(self):
        self.subs = [Sub1Forecast(), Sub2LowCarbon(), Sub3Factor()]

    def _safe_run(self, sub, task: str) -> dict:
        try:
            return sub.run(task)
        except Exception as exc:
            return {"agent": sub.name, "text": "",
                    "verified": False, "note": f"failed: {exc}"}

    def run(self, task: str) -> str:
        results = [self._safe_run(s, task) for s in self.subs]
        gaps = [r for r in results if not r["verified"]]

        out = []
        if gaps:
            out.append("## 数据与校验缺口（先看这里）")
            out += [f"- **{r['agent']}**：{r['note']}" for r in gaps]
            out.append("")
        out.append("## 分析结果")
        out += [f"### {r['agent']}\n{r['text']}" for r in results if r["text"]]
        return "\n".join(out)
```

<span style="color:#888">（`_safe_run` 保证一个 SubAgent 失败不拖垮其余两个。缺口写在摘要开头，不写成脚注——折叠进脚注的缺口，和没写没有区别。）</span>

---

## 九、`tests/test_gates.py`

```python
import ast
import pathlib

import pytest

from agent.boundary import assert_no_leak, filter_outbound
from agent.contract import ToolEnvelope, ToolStatus, safe_sum
from agent.verifier import verify_numbers


def test_absent_is_never_summed_as_zero():
    pts = [{"value_status": "measured", "kwh": 10},
           {"value_status": "absent", "kwh": None}]
    assert safe_sum(pts, "kwh") is None


def test_forbidden_key_never_leaves():
    env = ToolEnvelope(ToolStatus.OK, {"ip": "10.0.0.1", "kwh": 5}, 1, 1)
    text = filter_outbound(env)
    assert "10.0.0.1" not in text and "kwh" in text


def test_leak_check_raises():
    with pytest.raises(ValueError):
        assert_no_leak('{"note": "node at 192.168.1.7"}')


def test_fabricated_number_is_caught():
    payload = '{"total_kwh": 1200}'
    assert verify_numbers("总能耗 1200 kWh", [payload]).passed
    assert not verify_numbers("总能耗 9999 kWh", [payload]).passed


def test_core_must_not_import_agent():
    for path in pathlib.Path("core").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agent"), path
            elif isinstance(node, ast.Import):
                for a in node.names:
                    assert not a.name.startswith("agent"), path
```

<span style="color:#888">（最后一条是分层检查：`core/` 一旦反向依赖 `agent`，「数字由代码算」就守不住了。）</span>

---

## 十、状态

| 项 | 状态 |
|---|---|
| 三道闸 | 已实测通过（含容差、平凡数字、脱敏、缺口禁令等边界用例） |
| `tool_runner` 参数表 | 已用 anthropic 1.4.0 的 `inspect.signature` 实读确认 |
| `core/*` 九个算法 | 未实现，工具里以 `# STUB` 标出 |
| `prompts/` 五个文件 | 未写 |
| `audit.py` | 未写。每次调用追加一行 JSON：`agent_name / tool_name / 收发摘要 / token 数` |

<span style="color:#888">（`core.*` 的返回结构是按工具需要拟定的。实现 `core/` 时若不符，改工具层的取值，不要改 `ToolEnvelope` 的形状。相关文档：[提示词为什么分五个文件](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)）</span>
