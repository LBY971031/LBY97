# 三个 SubAgent 的代码实现

<span style="color:#888">（代码规格，非可运行文件。落地时按目录树拆成独立 `.py`。代码内一律英文；中文说明放在代码块外的灰字里。GitHub 会剥掉行内 `style`，灰色只在本地渲染器生效。）</span>

---

## 一、目录树

```
core/                       算力园区的确定性算法（本文范围之外）
                            ↑ 只被调用，绝不反向依赖 agent/
agent/
├── contract.py       §三   四态数据 + 工具返回信封
├── boundary.py       §四   出网过滤
├── verifier.py       §五   结论回检
├── base.py           §六   SubAgent 基类
├── subagents/        §七   三套工具 + 三个 Agent 类
├── orchestrator.py   §八   主 Agent
└── prompts/                提示词五个文件（不在本文范围）
```

### 1.1 每个文件干什么

| 文件 | 职责 | 被谁调用 | 拿掉它会怎样 |
|---|---|---|---|
| `contract.py` | 定义「一个数据点长什么样」和「一个工具能返回什么」 | 所有工具、`boundary` | 每个工具各自定义返回格式，模型面对九种形状，缺失表达迟早退化成 `null` |
| `boundary.py` | 出网前的唯一出口：剔除禁发字段、脱敏、追加缺口禁令 | 所有工具的 `_emit()` | 明细数据（IP、序列号、原始路径）随分析请求上传 |
| `verifier.py` | Agent 说完话之后，回头核对它说的每个数字 | `base.run()` | 编造的数字直接进报告，没人发现 |
| `base.py` | 三个 SubAgent 的公共骨架：拼提示词、跑 `tool_runner`、收工具返回、触发回检 | 三个 Agent 子类 | 三份重复的循环代码，三种不一致的回检时机 |
| `subagents/` | 十一个工具（`@beta_tool`）+ 三个四行的 Agent 子类 | `orchestrator` | —— 这是实际干活的地方 |
| `orchestrator.py` | 主 Agent：分派任务给三个 SubAgent、失败隔离、汇总 | 平台的调用入口 | 一个 SubAgent 报错就炸掉整次分析 |
| `prompts/` | 五个提示词文件：`_shared.md` + 四个各自的 | `base.system_prompt()` | 三道闸的自然语言版本无处安放 |

### 1.2 依赖方向（单向，不许回头）

```
        orchestrator.py          汇总、隔离失败
              │
              ▼
        subagents/               十一个工具 + 三个 Agent 子类
         │        │
         │        ▼
         │     base.py           跑 tool_runner、收工具返回
         │        │
         │        ▼
         │   verifier.py         回检数字
         │        │
         ▼        ▼
    core/     boundary.py        算数        /  过滤、脱敏、缺口禁令
                   │
                   ▼
              contract.py        地基：四态数据 + 信封
```

<span style="color:#888">（箭头是「谁 import 谁」，全图无环。`verifier` 依赖 `boundary` 只为取一个常量 `GAP_MARK`——它要把缺口告知那段切掉，免得禁令文本里的时间戳被当成数字来源。）</span>

<span style="color:#888">（三条规矩：① `core/` 不许 `import agent`——`core` 是纯算法，一旦反向依赖，「数字由代码算」这条就守不住了，§九最后一个测试专门守这个；② 工具不许自己拼返回串，必须走 `_emit()`，否则边界就有了第二个出口；③ `contract.py` 不 import 任何本项目模块，它是地基，被所有人依赖而不依赖任何人。）</span>

<span style="color:#888">（为什么 `prompts/` 分五个文件而不是一个：提示词是运行时读取的，改一个 Agent 的话术不该动到另外两个；`_shared.md` 单独一份，保证三道闸的措辞三个 Agent 完全一致。详见[工作流搭建方案](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)。）</span>

---

## 二、三道闸

<span style="color:#888">（「有就是有，没有就是没有，不能交给 LLM」这句话，如果只写进提示词，模型有相当概率照做、也有相当概率不照做。三道闸是把它翻译成代码——不是叮嘱模型，是让它做不到。）</span>

### 2.1 三道闸各自拦什么

| | 闸 | 位置 | 时机 | 拦住的事故 |
|---|---|---|---|---|
| 一 | 数据成形 | `contract.drop_absent` / `safe_sum` | 工具装信封时 | 模型看见 `null` 占位，顺手填一个「合理」的值；或缺失被当 0 求和，凭空多出节能量 |
| 二 | 出网过滤 | `boundary.filter_outbound` | 内容离开本机前 | 设备 IP、序列号、原始文件路径随请求上传；缺口存在但模型不知道 |
| 三 | 结论回检 | `verifier.verify_numbers` | Agent 说完话之后 | 数字看着像模像样，但工具从没算出过这个值 |

### 2.2 为什么必须是三道，不能合成一道

前两道都在**输入侧**——它们管的是「模型能看到什么」。但模型即使拿到一份干净、诚实、标好缺口的数据，**仍然可能在输出侧写出一个没人算过的数字**：把两个数相加、把百分比换算成绝对值、或者单纯记错。输入侧的闸拦不住输出侧的错。

闸三就是为此存在的：它不信任模型的自觉，只做一件事——**把 Agent 说出口的每个数字，拿回工具返回值里对一遍**。对不上就标红，不进报告。

<span style="color:#888">（这也是「数字由代码算，话由 Agent 说」的反向验证：既然数字全部由代码算出，那 Agent 嘴里的数字就必须能在代码的输出里找到。找不到，只有一种解释。）</span>

### 2.3 一次调用里三道闸的触发顺序

```
用户提问
   ↓
主 Agent 分派 ──► SubAgent 决定调哪个工具
                       ↓
                  工具调 core.* 拿到原始点位
                       ↓
              【闸一】drop_absent()  缺失点被剔出数据、单列成缺口声明
                       ↓            safe_sum() 遇 absent 直接返回 None
                  装进 ToolEnvelope
                       ↓
              【闸二】filter_outbound()  剔禁发字段 → 脱敏 → 追加缺口禁令
                       assert_no_leak()  兜底自检，可疑即抛异常
                       ↓
                  ── 出网，模型看到的就是这一份 ──
                       ↓
                  Agent 阅读、推理、写结论
                       ↓
              【闸三】verify_numbers()  逐个数字回工具返回里找来源
                       ↓
                  汇总（缺口写在开头，不写脚注）
```

### 2.4 闸响了怎么办

| 闸 | 触发时的表现 | 处理 |
|---|---|---|
| 一 | `safe_sum` 返回 `None` | **不是 bug。**说明这段时间的数据确实不全，报告里如实写「无法计算」，不要改成 0 |
| 二 | `assert_no_leak` 抛 `ValueError` | **中断本次调用。**先查是哪个字段漏进了 `data`，把它加进 `FORBIDDEN` 或 `PSEUDONYM`，不要放宽正则 |
| 三 | `verified: False` | 该 SubAgent 的结论**不进正文**，其未核实数字列在摘要开头。多半是提示词纵容了模型自行换算，去 `_shared.md` 里收紧 |

<span style="color:#888">（三道闸都不负责「让结果更好看」，只负责「让错的东西过不去」。闸经常响不代表代码有问题，往往说明数据采集侧有缺口——那是真实情况，不该被代码抹平。）</span>

### 2.5 第四条约束：Agent 没有计算权

| 约束 | 落点 |
|---|---|
| 数字由代码算，话由 Agent 说 | 工具只返回 `ToolEnvelope`，Agent 拿不到任何计算工具 |

<span style="color:#888">（这条没有对应的检查函数，它靠工具集的设计来保证：十一个工具全部是「查询/测算/定口径」，没有一个接受表达式或让模型自定义算法。模型能做的只有挑工具、传参数、读结果、写话。闸三是它的事后验证。）</span>

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

<span style="color:#888">（十个数据工具形状完全一致，只有 `core.*` 不同，故只给一个范例；`resolve_time_window` 是例外——纯日期计算，不读数据、不走 `core`。每个都套同一模板：取 core 结果 → `drop_absent` → 装进 `ToolEnvelope` → `_emit`。任何工具都不得自己拼返回串，否则边界就有了第二个出口。测算类工具的 `caliber` 必填，否则口径不明的数字会被当成可比数字。）</span>

| Agent | 工具 | core 函数 | 回答 |
|---|---|---|---|
| 共用 | `resolve_time_window` | 无（纯日期计算） | 把「下午 3:30」定成确切窗口 |
| 1 | `query_tasks_running` | `core.task.running_in` | 窗口内哪些任务在跑、各在哪台机器 |
| 1 | `query_idle_rate` | `core.idle.idle_rate` | 空置率、空载能耗 |
| 1 | `query_load_profile` | `core.load.profile` | 哪些时段负荷突增 |
| 1 | `forecast_energy` | `core.forecast.energy` | 下一周期能耗预测 |
| 2 | `query_grid_mix` | `core.grid.hourly_mix` | 逐小时风光占比 |
| 2 | `match_cfe_hourly` | `core.cfe.hourly_match` | 24/7 CFE 匹配得分 |
| 2 | `storage_net_effect` | `core.storage.net_carbon` | 储能真减碳还是负贡献 |
| 3 | `align_factors` | `core.factor.align` | 跨库因子对齐与差异 |
| 3 | `token_footprint` | `core.token.footprint` | 每百万 Token 碳足迹 |
| 3 | `build_report` | `core.report.render` | 核算报告 |

<span style="color:#888">（`resolve_time_window` 与 `query_tasks_running` 是为「某时刻在跑什么」这类问句加的，见 [LLM 部署指南 §三](./LLM部署指南.md)。）</span>

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
| `core/*` 十个算法 | 未实现，工具里以 `# STUB` 标出 |
| `prompts/` 五个文件 | 未写 |
| `audit.py` | 未写。每次调用追加一行 JSON：`agent_name / tool_name / 收发摘要 / token 数` |

<span style="color:#888">（`core.*` 的返回结构是按工具需要拟定的。实现 `core/` 时若不符，改工具层的取值，不要改 `ToolEnvelope` 的形状。相关文档：[提示词为什么分五个文件](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)）</span>
