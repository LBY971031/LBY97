# 三个 SubAgent 的代码实现

> 编制日期：2026-09-09
> 定位：**代码规格与参考实现**。本文把代码集中在一个 md 里便于通读与审阅；
> 落地时应按[目录树](#一目录树)拆成独立 `.py` 文件。
>
> ⚠️ **提示词（prompt）仍建议分三个文件**——那是运行时加载的，与本文的代码组织是两件事。
> 见[工作流方案 三-bis](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)。

---

## 零、本实现遵守的硬约束

代码里每一条都有对应的强制点，不是靠注释提醒：

| # | 约束 | 代码里怎么保证 |
|---|---|---|
| 1 | **数字由代码算，话由 Agent 说** | 工具只从 `core/` 取已算好的结果，Agent 侧无任何算术 |
| 2 | **四态数据，`absent` ≠ `0`** | `ValueStatus` 枚举 + `ToolEnvelope.absent_ranges` |
| 3 | **闸一：不给 null** | `envelope.data` 中缺失点**直接剔除**，不留 `None` 占位 |
| 4 | **闸二：自动附加禁令** | `boundary.filter_outbound()` 检测到缺失自动追加禁令文本 |
| 5 | **闸三：结论回检** | `verifier.verify_numbers()` 逐个数字回查 |
| 6 | **工具按 Agent 分开挂载** | 三个 `TOOLS_SUB*` 常量，各 Agent 只传自己那组 |
| 7 | **`core/` 不 import `agent/`** | 依赖单向，见[依赖检查测试](#八测试骨架) |
| 8 | **审计记录发起方** | `audit.log_call(agent_name=...)` 必填参数 |

---

## 一、目录树

```
agent/
├── __init__.py
├── contract.py         # 四态数据、工具返回信封     ← §二
├── boundary.py         # 数据边界过滤 + 脱敏 + 禁令  ← §三
├── audit.py            # 调用审计                   ← §三
├── verifier.py         # 结论回检                   ← §四
├── base.py             # SubAgent 基类              ← §五
├── subagents/
│   ├── __init__.py
│   ├── tools_sub1.py   # SubAgent 1 工具集          ← §六
│   ├── tools_sub2.py   # SubAgent 2 工具集
│   ├── tools_sub3.py   # SubAgent 3 工具集
│   ├── sub1_forecast.py
│   ├── sub2_lowcarbon.py
│   └── sub3_factor.py
├── orchestrator.py     # 主 Agent                   ← §七
└── prompts/            # 提示词（分五个文件，见工作流方案）
    ├── _shared.md
    ├── orchestrator.md
    ├── sub1_forecast.md
    ├── sub2_lowcarbon.md
    └── sub3_factor.md
```

> 🔴 **`core/` 的确定性算法不在本文范围内。** 本文的工具函数调用 `core.*`，
> 那些函数的签名以 `# STUB` 标出，需另行实现。

---

## 二、`agent/contract.py` — 四态数据与工具返回信封

```python
"""数据存在性契约：四态数据 + 工具返回信封。

这是整个 Agent 层的地基。核心命题：
    「没测到」和「测得是 0」是两回事，必须在类型层面分开。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ValueStatus(str, Enum):
    """数据点的来源状态。四态，不是「有值/null」二态。"""

    MEASURED = "measured"   # 实测值
    DERIVED = "derived"     # 由实测值确定性推导
    IMPUTED = "imputed"     # 补全值，必须带 method
    ABSENT = "absent"       # 没有。不是 0，不是 None


class ToolStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    NO_DATA = "no_data"


@dataclass
class AbsentRange:
    """一段明确的缺失。显式列出，不让模型自己去发现。"""

    reason: str
    ts_from: str | None = None
    ts_to: str | None = None
    scope: str | None = None       # 如 "server_model=H100-8卡"


@dataclass
class ImputedField:
    field_name: str
    method: str                    # 补全方法，必填
    count: int


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
    """所有工具的统一返回结构。禁止返回裸数据。"""

    status: ToolStatus
    data: Any
    coverage: Coverage
    absent_ranges: list[AbsentRange] = field(default_factory=list)
    imputed_fields: list[ImputedField] = field(default_factory=list)
    quality_grade: str = "B"       # A/B/C/D
    caliber: dict[str, Any] | None = None   # 口径标注，测算类工具必填

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["coverage"]["pct"] = self.coverage.pct
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def drop_absent(points: list[dict[str, Any]]) -> tuple[list[dict], list[AbsentRange]]:
    """闸一：把 absent 的点**从 data 里剔除**，而不是留 None 占位。

    模型看不到空位，就没有空位可填。
    """
    kept: list[dict] = []
    absent: list[AbsentRange] = []
    for p in points:
        if p.get("value_status") == ValueStatus.ABSENT.value:
            absent.append(
                AbsentRange(
                    reason=p.get("absent_reason", "未知原因"),
                    ts_from=p.get("ts_start"),
                    ts_to=p.get("ts_end"),
                    scope=p.get("scope"),
                )
            )
        else:
            kept.append(p)
    return kept, absent


def safe_sum(points: list[dict], key: str) -> float | None:
    """对可能含 absent 的序列求和。

    🔴 只要有一个 absent，返回 None 而不是把它当 0 加进去。
       这是「absent 不当 0」在代码层的兑现。
    """
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

## 三、`agent/boundary.py` 与 `agent/audit.py`

```python
"""agent/boundary.py — 数据边界过滤、脱敏、自动禁令。

⚠️ 全部 Agent 共用这一个出口。任何 SubAgent 不得自带过滤逻辑——
   多套规则必然出现漏洞。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .contract import ToolEnvelope

# 禁止出网的字段名（精确匹配）
FORBIDDEN_KEYS = {
    "device_serial", "serial_no", "ip", "ip_addr", "hostname",
    "rack_location", "room_address", "contract_no", "raw_file_path",
    "token_log_detail",
}

# 需要脱敏的字段名 → 代号前缀
PSEUDONYM_KEYS = {
    "job_name": "job",
    "model_id": "模型",
    "server_model": "机型",
    "device_id": "node",
}

_ABSENT_NOTICE = (
    "\n\n【数据缺失告知】以下范围无数据。"
    "不得推断其数值，不得用相邻时段或相似机型的值替代，"
    "不得将其视为 0 参与任何求和：\n{ranges}"
)


def _pseudonymize(value: str, prefix: str) -> str:
    """稳定脱敏：同一原值每次得到同一代号，便于跨轮次对照。"""
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]
    return f"{prefix}-{h}"


def _scrub(obj: Any, enable_pseudonym: bool = True) -> Any:
    """递归剔除禁发字段、脱敏标识类字段。"""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                continue                      # 直接剔除，不留占位
            if enable_pseudonym and k in PSEUDONYM_KEYS and isinstance(v, str):
                out[k] = _pseudonymize(v, PSEUDONYM_KEYS[k])
            else:
                out[k] = _scrub(v, enable_pseudonym)
        return out
    if isinstance(obj, list):
        return [_scrub(x, enable_pseudonym) for x in obj]
    return obj


def filter_outbound(env: ToolEnvelope, *, enable_pseudonym: bool = True) -> str:
    """闸二：出网前的唯一出口。

    1. 剔除禁发字段、脱敏标识
    2. 检测到 absent_ranges 非空 → 自动追加禁令文本
    """
    payload = _scrub(env.to_dict(), enable_pseudonym)
    text = __import__("json").dumps(payload, ensure_ascii=False, default=str)

    if env.absent_ranges:
        lines = []
        for a in env.absent_ranges:
            scope = f"[{a.scope}] " if a.scope else ""
            span = f"{a.ts_from} ~ {a.ts_to}" if a.ts_from else "（全时段）"
            lines.append(f"  - {scope}{span}：{a.reason}")
        text += _ABSENT_NOTICE.format(ranges="\n".join(lines))

    return text


def assert_no_leak(text: str) -> None:
    """兜底自检：出网文本里不应出现 IP 形态或长十六进制串。

    发现即抛异常——宁可中断，不可泄露。
    """
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        raise ValueError("边界告警：出网内容疑似包含 IP 地址")
    if re.search(r"\b[0-9a-fA-F]{16,}\b", text):
        raise ValueError("边界告警：出网内容疑似包含设备序列号")
```

```python
"""agent/audit.py — 调用审计。每条必须记录发起方是哪个 Agent。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_PATH = Path("data/agent_audit.log")


def log_call(
    *,
    agent_name: str,          # 必填：主 Agent 还是哪个 SubAgent
    tool_name: str,
    sent_summary: str,
    returned_summary: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent_name,
        "tool": tool_name,
        "sent": sent_summary[:500],
        "returned": returned_summary[:500],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

---

## 四、`agent/verifier.py` — 闸三：结论回检

```python
"""闸三：Agent 说出的每个数字，都必须能在工具返回中找到。

这是「数字由代码算，话由 Agent 说」的反向验证：
既然数字由代码算，那 Agent 说的数字就应该在代码算出的结果里。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

# 匹配文本里的数字（含千分位与小数）
_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")

# 这些数字不视为「事实数字」，跳过校验
_WHITELIST = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
              "100", "24", "2026", "2025"}


@dataclass
class VerifyResult:
    passed: bool
    unverified: list[str]

    def message(self) -> str:
        if self.passed:
            return "结论回检通过"
        return (
            "结论回检未通过。以下数字未能在工具返回中找到，"
            f"疑似编造：{', '.join(self.unverified)}"
        )


def _collect_numbers(obj) -> set[str]:
    """从工具返回的结构里收集所有数值，归一化为字符串集合。"""
    found: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)):
            found.add(_norm(o))
        elif isinstance(o, str):
            for m in _NUM_RE.finditer(o):
                found.add(_norm(m.group(0)))

    walk(obj)
    return found


def _norm(v) -> str:
    """归一化：去千分位、去尾随 0，便于比对。"""
    s = str(v).replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    if f == int(f):
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def verify_numbers(agent_text: str, tool_payloads: list[str],
                   *, tolerance_ratio: float = 0.01) -> VerifyResult:
    """逐个校验 Agent 输出里的数字是否有据可依。

    tolerance_ratio: 允许的相对误差（Agent 可能做了合理的四舍五入）。
    """
    allowed: set[str] = set()
    numeric_pool: list[float] = []
    for p in tool_payloads:
        try:
            obj = json.loads(p.split("\n\n【数据缺失告知】")[0])
        except json.JSONDecodeError:
            continue
        nums = _collect_numbers(obj)
        allowed |= nums
        for n in nums:
            try:
                numeric_pool.append(float(n))
            except ValueError:
                pass

    unverified: list[str] = []
    for m in _NUM_RE.finditer(agent_text):
        raw = m.group(0)
        n = _norm(raw)
        if n in _WHITELIST or n in allowed:
            continue
        # 容差匹配：允许 Agent 做四舍五入
        try:
            val = float(n)
        except ValueError:
            continue
        if any(
            abs(val - c) <= abs(c) * tolerance_ratio
            for c in numeric_pool
            if c != 0
        ):
            continue
        unverified.append(raw)

    return VerifyResult(passed=not unverified, unverified=unverified)
```

---

## 五、`agent/base.py` — SubAgent 基类

```python
"""SubAgent 基类。三个子 Agent 共用同一套会话骨架，只是工具集与提示词不同。

⚠️ SDK 用法核验提示：
   bundled 文档展示的 tool_runner 示例未包含 system / thinking 参数。
   tool_runner 被定位为 messages.create 的薄封装，故此处按同名参数传入。
   **首次运行前请对照你安装的 anthropic 版本核验**；若该版本不接受，
   改用手写循环（见 §九 备选方案）。
"""
from __future__ import annotations

from pathlib import Path

import anthropic
from anthropic import (
    APIConnectionError,
    APIStatusError,
    NotFoundError,
    RateLimitError,
)

from . import audit
from .verifier import verify_numbers, VerifyResult

MODEL = "claude-opus-5"
PROMPT_DIR = Path(__file__).parent / "prompts"


class AgentUnavailable(RuntimeError):
    """Agent 不可用（无密钥/网络故障）。调用方应降级而非崩溃。"""


class SubAgentBase:
    name: str = "base"
    prompt_file: str = ""
    tools: list = []

    def __init__(self, client: anthropic.Anthropic | None = None):
        try:
            # 零参构造：SDK 自行从环境变量解析凭据，不硬编码 key
            self.client = client or anthropic.Anthropic()
        except Exception as e:                       # 无凭据等
            raise AgentUnavailable(
                "未配置 ANTHROPIC_API_KEY，Agent 不可用；其余功能正常"
            ) from e

    # ---------- 提示词 ----------
    def system_prompt(self) -> str:
        """共用层 + 本 Agent 专属层，拼接加载。"""
        shared = (PROMPT_DIR / "_shared.md").read_text(encoding="utf-8")
        own = (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")
        return f"{shared}\n\n---\n\n{own}"

    # ---------- 主流程 ----------
    def run(self, user_input: str, *, max_tokens: int = 16000) -> dict:
        """跑一轮。返回 {text, verified, tool_payloads}。"""
        collected: list[str] = []

        try:
            runner = self.client.beta.messages.tool_runner(
                model=MODEL,
                max_tokens=max_tokens,
                system=self.system_prompt(),
                thinking={"type": "adaptive"},       # 不用 budget_tokens，Opus 5 会 400
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                tools=self.tools,
                messages=[{"role": "user", "content": user_input}],
            )

            final = None
            for message in runner:
                final = message
                # 收集本轮所有工具返回，供闸三回检
                resp = runner.generate_tool_call_response()
                if resp is not None:
                    for block in resp.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            collected.append(str(block.get("content", "")))

        except NotFoundError as e:
            raise AgentUnavailable(f"模型或资源不存在：{e}") from e
        except RateLimitError as e:
            raise AgentUnavailable(f"触发限流，请稍后重试：{e}") from e
        except APIStatusError as e:
            raise AgentUnavailable(f"API 返回错误 {e.status_code}：{e}") from e
        except APIConnectionError as e:
            raise AgentUnavailable(f"网络不可达：{e}") from e

        # 拒绝回退：先看 stop_reason，再读 content
        if final is not None and final.stop_reason == "refusal":
            detail = getattr(final, "stop_details", None)
            return {
                "text": f"[模型拒绝作答] {detail}",
                "verified": VerifyResult(passed=True, unverified=[]),
                "tool_payloads": collected,
                "refused": True,
            }

        text = _extract_text(final)

        # ── 闸三：结论回检 ──
        vr = verify_numbers(text, collected)

        audit.log_call(
            agent_name=self.name,
            tool_name="(session)",
            sent_summary=user_input,
            returned_summary=text,
            input_tokens=getattr(getattr(final, "usage", None), "input_tokens", None),
            output_tokens=getattr(getattr(final, "usage", None), "output_tokens", None),
        )

        return {"text": text, "verified": vr,
                "tool_payloads": collected, "refused": False}


def _extract_text(message) -> str:
    if message is None:
        return ""
    parts = []
    for b in getattr(message, "content", []):
        if getattr(b, "type", None) == "text":
            parts.append(b.text)
    return "\n".join(parts)
```

---

## 六、工具层

### 6.1 `agent/subagents/tools_sub1.py` — 能碳预测

```python
"""SubAgent 1 的工具集。

规则：
  · 只从 core/ 取已算好的结果，本文件不做任何算术
  · 一律返回 boundary.filter_outbound() 处理过的字符串
"""
from __future__ import annotations

from anthropic import beta_tool

from core import analysis, energy, forecast, idle          # STUB：确定性算法层
from .. import boundary
from ..contract import ToolEnvelope


def _emit(env: ToolEnvelope) -> str:
    """信封 → 边界过滤 → 字符串。所有工具的统一出口。"""
    text = boundary.filter_outbound(env)
    boundary.assert_no_leak(text)
    return text


@beta_tool
def query_energy_summary(park_id: str, ts_start: str, ts_end: str) -> str:
    """查询指定园区与时段的能耗汇总。

    Args:
        park_id: 园区标识，如 naxi-01。
        ts_start: 起始时间，ISO 格式，如 2026-07-01T00:00。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = energy.summarize(park_id, ts_start, ts_end)   # STUB
    return _emit(env)


@beta_tool
def query_idle_rate(park_id: str, ts_start: str, ts_end: str) -> str:
    """按服务器机型分别查询空置率与空载能耗。

    返回逐机型的：装机卡数、被占用卡数、逻辑空置率、空载能耗、
    空载电费、空载碳排。缺单卡待机功率时空载能耗标记为 absent。

    Args:
        park_id: 园区标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = idle.by_server_model(park_id, ts_start, ts_end)  # STUB
    return _emit(env)


@beta_tool
def analyze_variability(park_id: str, ts_start: str, ts_end: str) -> str:
    """差异性分析：模型 × 机型的能效矩阵、变异系数、离群组合。

    能效使用 IT 电耗计算，不含 PUE——PUE 是机房属性，
    摊进机型对比会污染结论。

    Args:
        park_id: 园区标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = analysis.variability(park_id, ts_start, ts_end)  # STUB
    return _emit(env)


@beta_tool
def forecast_task_energy(park_id: str, horizon_hours: int) -> str:
    """预测待执行任务的能耗与碳排。

    返回点估计与 P25–P75 区间，并附基线所用的历史样本数。
    样本数低于门槛时标注为不可靠。

    Args:
        park_id: 园区标识。
        horizon_hours: 预测时长，单位小时。
    """
    env: ToolEnvelope = forecast.task_energy(park_id, horizon_hours)   # STUB
    return _emit(env)


TOOLS_SUB1 = [
    query_energy_summary,
    query_idle_rate,
    analyze_variability,
    forecast_task_energy,
]
```

### 6.2 `agent/subagents/tools_sub2.py` — 低碳识别

```python
"""SubAgent 2 的工具集。"""
from __future__ import annotations

from anthropic import beta_tool

from core import cfe, grid, storage, temporality              # STUB
from .. import boundary
from ..contract import ToolEnvelope


def _emit(env: ToolEnvelope) -> str:
    text = boundary.filter_outbound(env)
    boundary.assert_no_leak(text)
    return text


@beta_tool
def query_grid_renewable(region: str, ts_start: str, ts_end: str) -> str:
    """查询当地电网级风光出力与占比趋势。

    注意这是电网级数据（scope_level=grid），决定你买的电有多绿；
    与园区自建风光（scope_level=park）作用机制不同，不可混算。

    Args:
        region: 电网区域标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = grid.renewable_profile(region, ts_start, ts_end)  # STUB
    return _emit(env)


@beta_tool
def match_lowcarbon_window(park_id: str, ts_start: str, ts_end: str) -> str:
    """识别低碳窗口与高碳窗口，并给出任务迁移的理论可迁移量。

    仅给建议，不下发任何调度指令。

    Args:
        park_id: 园区标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = cfe.match_windows(park_id, ts_start, ts_end)   # STUB
    return _emit(env)


@beta_tool
def analyze_storage(park_id: str, ts_start: str, ts_end: str) -> str:
    """储能有效性：充放电时段碳强度对比、往返效率、净减碳量。

    净减碳量可能为负——那说明储能在增碳。为负时结果中会带 warning 标记。
    缺 charge_source 字段时该测算标记为 absent。

    Args:
        park_id: 园区标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = storage.net_reduction(park_id, ts_start, ts_end)  # STUB
    return _emit(env)


@beta_tool
def analyze_temporality(park_id: str, ts_start: str, ts_end: str) -> str:
    """时序性分析：周期分解、自相关、各曲线对的相位差与错配矩阵。

    相位差是描述性统计，不构成因果结论。

    Args:
        park_id: 园区标识。
        ts_start: 起始时间，ISO 格式。
        ts_end: 结束时间，ISO 格式。
    """
    env: ToolEnvelope = temporality.analyze(park_id, ts_start, ts_end)  # STUB
    return _emit(env)


TOOLS_SUB2 = [
    query_grid_renewable,
    match_lowcarbon_window,
    analyze_storage,
    analyze_temporality,
]
```

### 6.3 `agent/subagents/tools_sub3.py` — 因子对齐与核算

```python
"""SubAgent 3 的工具集。"""
from __future__ import annotations

from anthropic import beta_tool

from core import carbon, factors, lifecycle, report           # STUB
from .. import boundary
from ..contract import ToolEnvelope


def _emit(env: ToolEnvelope) -> str:
    text = boundary.filter_outbound(env)
    boundary.assert_no_leak(text)
    return text


@beta_tool
def align_emission_factors(activity: str, region: str, year: str) -> str:
    """在多个排放因子库间检索、对齐并呈现分歧。

    返回各库取值、系统边界、地域适用性、数据年份，以及分歧幅度
    （最大值除以最小值）与匹配可靠性分级。

    本工具不替使用者选定因子——分歧必须呈现，由人拍板。

    Args:
        activity: 活动描述，如 外购电力。
        region: 地域范围，如 华东。
        year: 数据年份，如 2026。
    """
    env: ToolEnvelope = factors.align(activity, region, year)      # STUB
    return _emit(env)


@beta_tool
def factor_sensitivity(activity: str, region: str, year: str) -> str:
    """换库敏感性分析：改用不同因子库时最终结果的变化幅度。

    Args:
        activity: 活动描述。
        region: 地域范围。
        year: 数据年份。
    """
    env: ToolEnvelope = factors.sensitivity(activity, region, year)  # STUB
    return _emit(env)


@beta_tool
def calc_token_footprint(park_id: str, period: str, boundary_level: str) -> str:
    """查询机型 × 模型的每百万 Token 碳足迹矩阵。

    矩阵已在 core 层算完，本工具只做读取。结果附完整口径标注，
    并区分从未运行与数据缺失两种空格子。

    Args:
        park_id: 园区标识。
        period: 统计周期，如 2026-07。
        boundary_level: 边界层级，B 或 C。B 用于机型对比，C 用于对外交代。
    """
    env: ToolEnvelope = carbon.token_matrix(park_id, period, boundary_level)  # STUB
    return _emit(env)


@beta_tool
def analyze_lifecycle(park_id: str, period: str) -> str:
    """设备生命周期：使用强度、等效寿命消耗率、隐含碳摊销速率、
    生命周期成本、残值与可再利用潜力。

    寿命折损为工程简化模型，不用于预测设备失效时间。

    Args:
        park_id: 园区标识。
        period: 统计周期。
    """
    env: ToolEnvelope = lifecycle.summary(park_id, period)          # STUB
    return _emit(env)


@beta_tool
def generate_carbon_report(park_id: str, period: str) -> str:
    """生成碳核算报告所需的结构化素材。

    返回结果、边界与假设、活动数据来源与质量、因子溯源、
    不确定性、局限声明七项素材。报告文字由 Agent 组织。

    Args:
        park_id: 园区标识。
        period: 统计周期。
    """
    env: ToolEnvelope = report.assemble(park_id, period)            # STUB
    return _emit(env)


TOOLS_SUB3 = [
    align_emission_factors,
    factor_sensitivity,
    calc_token_footprint,
    analyze_lifecycle,
    generate_carbon_report,
]
```

---

## 七、三个 SubAgent 与主 Agent

```python
"""agent/subagents/sub1_forecast.py"""
from ..base import SubAgentBase
from .tools_sub1 import TOOLS_SUB1


class ForecastAgent(SubAgentBase):
    """SubAgent 1 · 任务需求与能碳预测。时态：面向未来。"""

    name = "sub1_forecast"
    prompt_file = "sub1_forecast.md"
    tools = TOOLS_SUB1
```

```python
"""agent/subagents/sub2_lowcarbon.py"""
from ..base import SubAgentBase
from .tools_sub2 import TOOLS_SUB2


class LowCarbonAgent(SubAgentBase):
    """SubAgent 2 · 风光趋势匹配与低碳识别。时态：面向未来 × 时段。"""

    name = "sub2_lowcarbon"
    prompt_file = "sub2_lowcarbon.md"
    tools = TOOLS_SUB2
```

```python
"""agent/subagents/sub3_factor.py"""
from ..base import SubAgentBase
from .tools_sub3 import TOOLS_SUB3


class FactorAgent(SubAgentBase):
    """SubAgent 3 · 因子对齐与碳核算报告。时态：面向过去。"""

    name = "sub3_factor"
    prompt_file = "sub3_factor.md"
    tools = TOOLS_SUB3
```

```python
"""agent/orchestrator.py — 主 Agent。

职责：分解 · 调度 · 汇总 · 冲突仲裁。
不直接算数、不直接读库、不改数据——只能通过 SubAgent。
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import AgentUnavailable
from .subagents.sub1_forecast import ForecastAgent
from .subagents.sub2_lowcarbon import LowCarbonAgent
from .subagents.sub3_factor import FactorAgent


@dataclass
class SubResult:
    name: str
    ok: bool
    text: str
    verified_ok: bool
    note: str = ""


class Orchestrator:
    """按依赖关系调度三个 SubAgent，并汇总。

    依赖：SubAgent 2 依赖 SubAgent 1 的预测；SubAgent 3 独立。
    """

    def __init__(self):
        self.sub1 = ForecastAgent()
        self.sub2 = LowCarbonAgent()
        self.sub3 = FactorAgent()

    def run(self, question: str, *, need_forecast: bool = True) -> dict:
        results: list[SubResult] = []

        # SubAgent 3 独立，先跑
        results.append(self._safe_run(self.sub3, question))

        if need_forecast:
            r1 = self._safe_run(self.sub1, question)
            results.append(r1)
            if r1.ok:
                # 把 SubAgent 1 的结论作为上下文传给 2（仍是聚合值）
                results.append(
                    self._safe_run(
                        self.sub2,
                        f"{question}\n\n【上游预测结果】\n{r1.text}",
                    )
                )
            else:
                results.append(
                    SubResult(
                        name=self.sub2.name, ok=False, text="",
                        verified_ok=False,
                        note="上游 SubAgent 1 失败，低碳窗口识别不可用",
                    )
                )

        return {"results": results, "summary": self._summarize(results)}

    @staticmethod
    def _safe_run(agent, prompt: str) -> SubResult:
        """单个 SubAgent 失败不拖垮整体。"""
        try:
            out = agent.run(prompt)
        except AgentUnavailable as e:
            return SubResult(agent.name, False, "", False, note=str(e))

        vr = out["verified"]
        return SubResult(
            name=agent.name,
            ok=not out["refused"],
            text=out["text"],
            verified_ok=vr.passed,
            note="" if vr.passed else vr.message(),
        )

    @staticmethod
    def _summarize(results: list[SubResult]) -> str:
        """汇总。缺失与回检失败必须放在开头，不许塞末尾小字。"""
        problems = [r for r in results if not r.ok or not r.verified_ok]
        head = ""
        if problems:
            lines = [f"  - {r.name}：{r.note or '结论回检未通过'}" for r in problems]
            head = "【本次结论存在缺口，请先看这里】\n" + "\n".join(lines) + "\n\n"

        body = "\n\n".join(
            f"## {r.name}\n{r.text}" for r in results if r.ok and r.text
        )
        return head + body
```

---

## 八、测试骨架

```python
"""tests/test_data_contract.py — absent 绝不能被当成 0。"""
import pytest

from agent.contract import ValueStatus, safe_sum, drop_absent


def test_absent_never_summed_as_zero():
    points = [
        {"energy_kwh": 10.0, "value_status": ValueStatus.MEASURED.value},
        {"energy_kwh": None, "value_status": ValueStatus.ABSENT.value,
         "absent_reason": "采集器离线"},
        {"energy_kwh": 20.0, "value_status": ValueStatus.MEASURED.value},
    ]
    # 若被当成 0，结果会是 30.0；正确行为是返回 None
    assert safe_sum(points, "energy_kwh") is None


def test_real_zero_is_kept():
    points = [{"energy_kwh": 0.0, "value_status": ValueStatus.MEASURED.value}]
    assert safe_sum(points, "energy_kwh") == 0.0


def test_absent_dropped_not_nulled():
    points = [
        {"energy_kwh": 10.0, "value_status": ValueStatus.MEASURED.value},
        {"energy_kwh": None, "value_status": ValueStatus.ABSENT.value,
         "absent_reason": "采集器离线"},
    ]
    kept, absent = drop_absent(points)
    assert len(kept) == 1                    # 缺失点被剔除
    assert all(p.get("energy_kwh") is not None for p in kept)   # 无 None 占位
    assert len(absent) == 1 and absent[0].reason == "采集器离线"
```

```python
"""tests/test_boundary.py — 边界过滤与自动禁令。"""
from agent.boundary import filter_outbound, assert_no_leak, FORBIDDEN_KEYS
from agent.contract import ToolEnvelope, ToolStatus, Coverage, AbsentRange
import pytest


def _env(data, absent=None):
    return ToolEnvelope(
        status=ToolStatus.PARTIAL if absent else ToolStatus.OK,
        data=data,
        coverage=Coverage(expected_points=10, actual_points=8),
        absent_ranges=absent or [],
    )


def test_forbidden_keys_removed():
    out = filter_outbound(_env({"ip": "10.0.0.5", "energy_kwh": 42.0}))
    assert "10.0.0.5" not in out
    assert "42" in out


def test_absent_triggers_notice():
    out = filter_outbound(_env(
        {"x": 1},
        [AbsentRange(reason="采集器离线", ts_from="2026-07-03T14:00",
                     ts_to="2026-07-03T18:00")],
    ))
    assert "不得推断" in out and "不得将其视为 0" in out


def test_leak_guard_raises_on_ip():
    with pytest.raises(ValueError):
        assert_no_leak("节点地址 192.168.1.7 能耗偏高")
```

```python
"""tests/test_verifier.py — 编造的数字必须被拦住。"""
from agent.verifier import verify_numbers


def test_fabricated_number_flagged():
    payload = '{"gco2e_per_mtok": 1381.0, "tokens": 10500000}'
    text = "该组合碳足迹为 1381 gCO₂e/MTok，另一机型为 9999 gCO₂e/MTok。"
    r = verify_numbers(text, [payload])
    assert not r.passed and "9999" in r.unverified


def test_grounded_numbers_pass():
    payload = '{"gco2e_per_mtok": 1381.0}'
    r = verify_numbers("碳足迹 1381 gCO₂e/MTok。", [payload])
    assert r.passed
```

```python
"""tests/test_layering.py — core 不得依赖 agent。"""
import ast
import pathlib


def test_core_does_not_import_agent():
    """测算层必须能在 Agent 全关时独立工作。"""
    offenders = []
    for py in pathlib.Path("core").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n.split(".")[0] == "agent" for n in names):
                offenders.append(str(py))
    assert not offenders, f"core 不得 import agent：{offenders}"
```

---

## 九、最小可运行示例与备选方案

```python
"""examples/run_orchestrator.py"""
from agent.orchestrator import Orchestrator

if __name__ == "__main__":
    orch = Orchestrator()
    out = orch.run(
        "纳溪服务区 2026 年 7 月，哪些机型和模型的组合碳足迹最高？"
        "空置情况如何？有没有可以错峰到低碳时段的任务？"
    )
    print(out["summary"])
    for r in out["results"]:
        print(f"[{r.name}] ok={r.ok} verified={r.verified_ok} {r.note}")
```

### 备选：若 `tool_runner` 不接受 `system` / `thinking`

改用手写循环（同样能满足全部硬约束，只是要自己维护消息历史）：

```python
messages = [{"role": "user", "content": user_input}]
tool_map = {t.__name__: t for t in self.tools}

while True:
    resp = self.client.messages.create(
        model=MODEL, max_tokens=16000,
        system=self.system_prompt(),
        thinking={"type": "adaptive"},
        tools=[t.to_dict() for t in self.tools],   # 按 SDK 实际方法名调整
        messages=messages,
    )
    messages.append({"role": "assistant", "content": resp.content})
    if resp.stop_reason != "tool_use":
        break
    results = []
    for block in resp.content:
        if block.type == "tool_use":
            out = tool_map[block.name](**block.input)   # 工具内部已做边界过滤
            collected.append(out)
            results.append({"type": "tool_result",
                            "tool_use_id": block.id, "content": out})
    messages.append({"role": "user", "content": results})   # 全部结果放一条消息
```

> ⚠️ 并行工具调用时，**所有 `tool_result` 必须放在同一条 user 消息里**，
> 拆成多条会让模型逐渐不再并行调用。

---

## 十、未实现与待办

| 项 | 状态 |
|---|---|
| `core/` 的确定性算法（标 `# STUB` 处） | ❌ 未实现，是主要工作量 |
| 五个提示词文件 `agent/prompts/*.md` | ❌ 未写，见[工作流方案 三-bis](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个) |
| 发送前的人工预览确认 UI | ❌ 未实现（Streamlit 侧） |
| 纯本地模式开关 | ❌ 未实现 |
| Agent eval 评测集 | ❌ 未实现 |

### 诚实声明

| 内容 | 状态 |
|---|---|
| `@beta_tool` / `tool_runner` / `generate_tool_call_response` 的用法 | ✅ 来自 SDK 参考文档 |
| **`tool_runner` 与 `system` / `thinking` / `betas` 同用** | ⚠️ **文档未展示该组合**，按薄封装定位推断，**首次运行须核验** |
| `runner.generate_tool_call_response()` 返回结构中 `tool_result` 的取法 | ⚠️ **按常见结构推断**，须核验 |
| 模型 ID、adaptive thinking、fallbacks、错误类型链 | ✅ 来自 SDK 参考文档 |
| 契约层、边界层、回检层的设计 | ⚠️ **我的实现**，无外部依据 |
| **全部代码均未运行过** | 🔴 **静态编写，需你在真实环境跑通并调整** |

