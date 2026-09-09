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
├── snapshot.py       §七   小时快照的存取（追加式版本）
├── subagents/        §八   工具集 + 三个分析 Agent
│                     §十   查询 Agent（提问时走这条）
├── orchestrator.py   §九   主 Agent：每小时跑一次，写快照
└── prompts/                提示词六个文件（不在本文范围）
```

### 1.1 每个文件干什么

| 文件 | 职责 | 被谁调用 | 拿掉它会怎样 |
|---|---|---|---|
| `contract.py` | 定义「一个数据点长什么样」和「一个工具能返回什么」 | 所有工具、`boundary` | 每个工具各自定义返回格式，模型面对九种形状，缺失表达迟早退化成 `null` |
| `boundary.py` | 出网前的唯一出口：剔除禁发字段、脱敏、追加缺口禁令 | 所有工具的 `_emit()` | 明细数据（IP、序列号、原始路径）随分析请求上传 |
| `verifier.py` | Agent 说完话之后，回头核对它说的每个数字 | `base.run()` | 编造的数字直接进报告，没人发现 |
| `base.py` | 三个 SubAgent 的公共骨架：拼提示词、跑 `tool_runner`、收工具返回、触发回检 | 三个 Agent 子类 | 三份重复的循环代码，三种不一致的回检时机 |
| `snapshot.py` | 小时快照的存取：追加式写入，旧版本永不覆盖 | `orchestrator`、查询 Agent | 报告只能现算现用，无法复现、无法审计 |
| `subagents/` | 十四个工具 + 三个分析 Agent + 一个查询 Agent | `orchestrator`、入口程序 | —— 这是实际干活的地方 |
| `orchestrator.py` | **每小时跑一次**：分派三个 SubAgent、失败隔离、把结果写成快照 | 定时任务 | 一个 SubAgent 报错就炸掉整个小时的分析 |
| `prompts/` | 六个提示词文件：`_shared.md` + 五个各自的 | `base.system_prompt()` | 三道闸的自然语言版本无处安放 |

### 1.2 依赖方向（单向，不许回头）

```
        orchestrator.py          每小时跑一次，写快照
         │            │
         │            ▼
         │       snapshot.py     快照存取（只依赖 sqlite3）
         ▼
        subagents/               十四个工具 + 四个 Agent 子类
         │        │        │
         │        │        ▼
         │        │     base.py           跑 tool_runner、收工具返回
         │        │        │
         │        │        ▼
         │        │   verifier.py         回检数字
         │        │        │
         ▼        ▼        ▼
    core/     snapshot.py   boundary.py
     算数        读快照        过滤、脱敏、缺口禁令
                                  │
                                  ▼
                             contract.py  地基：四态数据 + 信封
```

<span style="color:#888">（箭头是「谁 import 谁」，全图无环。`verifier` 依赖 `boundary` 只为取一个常量 `GAP_MARK`——它要把缺口告知那段切掉，免得禁令文本里的时间戳被当成数字来源。）</span>

<span style="color:#888">（三条规矩：① `core/` 不许 `import agent`——`core` 是纯算法，一旦反向依赖，「数字由代码算」这条就守不住了，§十一最后一个测试专门守这个；② 工具不许自己拼返回串，必须走 `_emit()`，否则边界就有了第二个出口；③ `contract.py` 不 import 任何本项目模块，它是地基，被所有人依赖而不依赖任何人。）</span>

<span style="color:#888">（为什么 `prompts/` 分六个文件而不是一个：提示词是运行时读取的，改一个 Agent 的话术不该动到其余几个；`_shared.md` 单独一份，保证三道闸的措辞所有 Agent 完全一致。详见[工作流搭建方案](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)。）</span>

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

<span style="color:#888">（这条没有对应的检查函数，它靠工具集的设计来保证：十四个工具全部是「查询/测算/定口径」，没有一个接受表达式或让模型自定义算法。模型能做的只有挑工具、传参数、读结果、写话。闸三是它的事后验证。）</span>

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
PSEUDONYM = {"job_name": "job", "device_id": "node"}

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


def _gap_line(a: dict) -> str:
    scope = a.get("scope") or {}
    label = "[" + ", ".join(f"{k}={v}" for k, v in scope.items()) + "] " if scope else ""
    span = (f"{a['ts_from']} ~ {a['ts_to']}" if a.get("ts_from")
            else "(all periods)")
    return f"  - {label}{span}: {a['reason']}"


def filter_outbound(env: ToolEnvelope) -> str:
    payload = _scrub(env.to_dict())
    text = json.dumps(payload, ensure_ascii=False, default=str)
    gaps = payload.get("absent_ranges") or []
    if gaps:
        text += _GAP_NOTICE.format(gaps="\n".join(_gap_line(a) for a in gaps))
    return text


def assert_no_leak(text: str) -> None:
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        raise ValueError("boundary: outbound text may contain an IP")
    for m in re.finditer(r"\b[0-9a-fA-F]{16,}\b", text):
        if any(c in "abcdefABCDEF" for c in m.group(0)):
            raise ValueError("boundary: outbound text may contain a serial number")
```

<span style="color:#888">（全部 SubAgent 共用这一个出口，任何 Agent 不得自带过滤逻辑——多套规则必然出现漏洞。禁发字段直接剔除、不留占位；标识类字段做稳定脱敏，同一台机器每次得到同一代号，便于跨轮次对照。**脱敏名单只放身份类字段。** `model_id`（Qwen2.5-72B 之类）和 `server_model`（8xH100）曾在名单里，实跑后移出——它们是公开的型号名而非身份，脱敏之后「哪个模型能耗最高」这个问题就没法用人话回答了，报告随之失去意义。有缺口就把禁令写进出网文本，而不是指望提示词记得住。`assert_no_leak` 是兜底：宁可中断，不可泄露。）</span>

<span style="color:#888">（序列号那条要求命中串里**至少有一个字母** a–f。实跑时它曾被 `0.39999999999999997` 这样的浮点噪声触发——数字也是合法的十六进制字符，17 位小数尾巴就满足了 16 位阈值，正常报告因此被拦下。代价是纯数字的序列号会漏过，所以真正的防线始终是 `FORBIDDEN` 名单，这条只是兜底。）</span>

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

## 七、`agent/snapshot.py` —— 小时快照

<span style="color:#888">（整套流程分两段：**每小时跑一次**分析，把结果冻成快照；**用户提问时**只读快照，不重算。这一节是两段之间的那块存储。）</span>

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly_report (
    hour_start   TEXT    NOT NULL,
    version      INTEGER NOT NULL,
    generated_at TEXT    NOT NULL,
    superseded   INTEGER NOT NULL DEFAULT 0,
    payload      TEXT    NOT NULL,
    PRIMARY KEY (hour_start, version)
);
CREATE INDEX IF NOT EXISTS idx_hour ON hourly_report(hour_start, superseded);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save(conn: sqlite3.Connection, payload: dict) -> int:
    """Append a new version of one hour's report. Never overwrites."""
    hour = payload["hour_start"]
    prev = conn.execute(
        "SELECT MAX(version) FROM hourly_report WHERE hour_start = ?", (hour,)
    ).fetchone()[0]
    version = (prev or 0) + 1
    payload = dict(payload, version=version)
    conn.execute(
        "UPDATE hourly_report SET superseded = 1 WHERE hour_start = ?", (hour,))
    conn.execute(
        "INSERT INTO hourly_report (hour_start, version, generated_at, payload)"
        " VALUES (?, ?, ?, ?)",
        (hour, version, payload["generated_at"],
         json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    return version


def load(conn, hour_start: str, version: int | None = None) -> dict | None:
    if version is None:
        sql = ("SELECT payload FROM hourly_report"
               " WHERE hour_start = ? AND superseded = 0")
        args = (hour_start,)
    else:
        sql = "SELECT payload FROM hourly_report WHERE hour_start = ? AND version = ?"
        args = (hour_start, version)
    row = conn.execute(sql, args).fetchone()
    return json.loads(row[0]) if row else None


def load_range(conn, ts_from: str, ts_to: str) -> list[dict]:
    rows = conn.execute(
        "SELECT payload FROM hourly_report"
        " WHERE hour_start >= ? AND hour_start < ? AND superseded = 0"
        " ORDER BY hour_start", (ts_from, ts_to)).fetchall()
    return [json.loads(r[0]) for r in rows]
```

<span style="color:#888">（已实测：同一小时第二次写入产生 v2 并把 v1 标记 `superseded`，但 v1 仍可按版本号取回；`load_range` 只返回各小时的当前版本；查询没有快照的小时返回 `None` 而不是空报告。）</span>

### 7.1 为什么必须追加、不许覆盖

数据补采到了、因子库更新了、分配方法改了——都会让同一小时的报告需要重算。**重算必须产生新版本，而不是原地改掉旧的。**

| 场景 | 覆盖式写入 | 追加式写入 |
|---|---|---|
| 上周的报告发给了甲方，本周因子更新 | 甲方拿到的那份已经不存在了 | 旧版本仍在，可对照说明差异 |
| 有人问「这个数当时是怎么算出来的」 | 答不了 | 取 v1 的 `caliber` 即可 |
| 补采了缺失数据 | 覆盖率静悄悄从 72% 变成 100% | 两个版本并存，能看出补了什么 |

<span style="color:#888">（碳核算报告是要对外的。一份不能复现的报告，在审计面前没有价值——这是追加式写入唯一的理由，也是足够的理由。）</span>

### 7.2 快照里存什么

```
hour_start     这份快照覆盖哪个小时
generated_at   什么时候算出来的
version        第几版
tasks          该小时运行过的任务（含起止、所在服务器、GPU 时间份额）
energy         逐服务器能耗、任务分摊、空载能耗
carbon         运营碳排、每百万 Token 碳足迹
grid           该小时电网结构、CFE 匹配得分
caliber        🔴 冻结的口径：因子版本、分配方法、采样推导方式、空载是否计入
coverage_pct   采样覆盖率
absent_ranges  缺口清单
verified       闸三是否通过
```

<span style="color:#888">（`caliber` 是快照里最重要的字段。因子库以后会更新，但这份快照用的是哪一版，必须当时就写死在里面——否则一年后没人说得清这个数是怎么来的。）</span>

<span style="color:#888">（时间字符串统一用同一个时区偏移写入（如 `+08:00`），否则 `load_range` 的字符串比较会出错——`2026-08-30T15:00:00+08:00` 和 `2026-08-30T07:00:00Z` 是同一时刻，但字符串排序不同。）</span>

---

## 八、工具层与四个 Agent

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

<span style="color:#888">（十个数据工具形状完全一致，只有 `core.*` 不同，故只给一个范例；`resolve_time_window` 与三个查询工具是例外——前者纯日期计算，后者读快照，都不走 `core`。每个都套同一模板：取 core 结果 → `drop_absent` → 装进 `ToolEnvelope` → `_emit`。任何工具都不得自己拼返回串，否则边界就有了第二个出口。测算类工具的 `caliber` 必填，否则口径不明的数字会被当成可比数字。）</span>

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
| 查询 | `get_hour_report` | 无（读快照） | 某小时的完整报告 |
| 查询 | `list_hour_reports` | 无（读快照） | 一段时间的逐小时序列 |
| 查询 | `get_report_version` | 无（读快照） | 某小时的某个历史版本 |

<span style="color:#888">（前十一个工具供**每小时的分析**使用，读原始数据；后三个供**用户提问**使用，只读快照。两组工具互不重叠——查询 Agent 拿不到任何能读原始表的工具，所以它想重算也没有手段。）</span>

<span style="color:#888">（四个 Agent 类各自只是 `SubAgentBase` 的四行子类：设定 `name`、`prompt_file`、`tools`，无需额外逻辑。）</span>

---

## 九、`agent/orchestrator.py` —— 每小时跑一次

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import snapshot
from .subagents.sub1_tasks import Sub1Tasks
from .subagents.sub2_lowcarbon import Sub2LowCarbon
from .subagents.sub3_factor import Sub3Factor

TZ = timezone(timedelta(hours=8))


class Orchestrator:
    """Runs once per hour and freezes the result into a snapshot."""

    def __init__(self, conn=None):
        self.subs = [Sub1Tasks(), Sub2LowCarbon(), Sub3Factor()]
        self.conn = conn or snapshot.connect()

    def _safe_run(self, sub, task: str) -> dict:
        try:
            return sub.run(task)
        except Exception as exc:
            return {"agent": sub.name, "text": "",
                    "verified": False, "note": f"failed: {exc}"}

    def run_hour(self, hour_start: str) -> int:
        """Analyse one clock hour and store it. Returns the new version."""
        hour_end = (datetime.fromisoformat(hour_start)
                    + timedelta(hours=1)).isoformat()
        brief = (f"Analyse the window {hour_start} to {hour_end}. "
                 f"Use only the tools; report coverage and gaps first.")

        results = [self._safe_run(s, brief) for s in self.subs]
        payload = {
            "hour_start": hour_start,
            "generated_at": datetime.now(TZ).isoformat(),
            "sections": {r["agent"]: r["text"] for r in results},
            "verified": all(r["verified"] for r in results),
            "notes": [r["note"] for r in results if not r["verified"]],
        }
        return snapshot.save(self.conn, payload)

    def backfill(self, ts_from: str, ts_to: str) -> list[str]:
        """Run every hour in a range that has no snapshot yet."""
        t = datetime.fromisoformat(ts_from)
        end = datetime.fromisoformat(ts_to)
        done = []
        while t < end:
            key = t.isoformat()
            if snapshot.load(self.conn, key) is None:
                self.run_hour(key)
                done.append(key)
            t += timedelta(hours=1)
        return done
```

<span style="color:#888">（`_safe_run` 保证一个 SubAgent 失败不拖垮其余两个——失败的那节写进 `notes`，快照照常落库，而不是整个小时丢掉。`backfill` 用于补跑：定时任务挂了几小时、或首次上线要回溯历史，只补没有快照的小时，已有的不动。）</span>

### 9.1 怎么定时触发

```bash
# crontab -e   每小时第 5 分钟，跑上一个整点
5 * * * * cd /path/to/项目 && .venv/bin/python -m agent.hourly_job >> logs/hourly.log 2>&1
```

<span style="color:#888">（推迟到第 5 分钟，是给采集留出写完最后一批数据的时间。整点就跑，很可能把还没落库的几分钟当成缺口。）</span>

<span style="color:#888">（「实时」在这套设计里的确切含义：**滞后 0–65 分钟**。15:30 发生的事，最早 16:05 出现在快照里。如果业务要求秒级实时告警，那是另一套流式架构，不是本设计的目标。）</span>

---

## 十、查询层 —— 用户提问时走这里

```python
"""agent/subagents/query_agent.py"""
from __future__ import annotations

from ..base import SubAgentBase
from .tools_query import TOOLS_QUERY


class QueryAgent(SubAgentBase):
    """Answers questions by reading frozen snapshots. Never recomputes."""

    name = "查询"
    prompt_file = "query.md"
    tools = TOOLS_QUERY
```

```python
"""agent/subagents/tools_query.py"""
from __future__ import annotations

from anthropic import beta_tool

from .. import snapshot
from ..boundary import assert_no_leak, filter_outbound
from ..contract import ToolEnvelope, ToolStatus

_CONN = snapshot.connect()


def _emit(env: ToolEnvelope) -> str:
    text = filter_outbound(env)
    assert_no_leak(text)
    return text


@beta_tool
def get_hour_report(hour_start: str) -> str:
    """Read the stored report for one clock hour.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    rep = snapshot.load(_CONN, hour_start)
    if rep is None:
        return _emit(ToolEnvelope(
            status=ToolStatus.NO_DATA, data=None,
            expected_points=1, actual_points=0,
            absent_ranges=[{"reason": "no snapshot for this hour",
                            "ts_from": hour_start}],
        ))
    return _emit(ToolEnvelope(
        status=ToolStatus.OK, data=rep,
        expected_points=1, actual_points=1,
        caliber=rep.get("caliber"),
    ))
```

<span style="color:#888">（查询层只有三个工具：`get_hour_report`（取某小时）、`list_hour_reports`（取一段时间的序列，做时序和不稳定性分析）、`get_report_version`（取某个历史版本，用于对照）。三个形状一致，此处只给第一个。）</span>

### 10.1 查询层为什么不碰原始数据

| | 每次现算 | 读快照 |
|---|---|---|
| 同一问题问两次 | 可能得到两个答案 | 必然一致 |
| 响应时间 | 三个 Agent 跑一轮 | 一次 LLM 调用 |
| 成本 | 每次都付全价 | 每小时付一次，查询近乎免费 |
| 口径 | 每次重新决定 | 快照里冻着 |
| 数据缺口 | 每次重新判断 | 如实转述当时的判断 |

<span style="color:#888">（这条边界要守住：查询 Agent 的工具集里**没有**任何能读原始表的工具。它想重算也没有手段——和「Agent 没有计算权」是同一个思路，靠工具集的设计来保证，而不是靠提示词叮嘱。）</span>

### 10.2 「某个节点的情况」怎么问

「节点」有两种意思，两种都支持：

| 问法 | 落到哪个工具 | 得到什么 |
|---|---|---|
| **时间节点**：「8 月 30 号下午 3 点半的情况」 | `get_hour_report("...T15:00:00+08:00")` | 那一小时的完整快照 |
| **算力节点**：「node-4f8086 那天怎么样」 | `list_hour_reports` 取当天 24 份，按节点筛 | 该节点全天的逐小时序列 |
| **两者叠加**：「那台机器 3 点半在跑什么」 | 先取该小时快照，再从 `tasks` 里筛该节点 | 精确到任务级 |

<span style="color:#888">（时刻落到小时是代码做的，不由模型猜：`resolve_time_window` 把 15:30 归到 15:00–16:00，这样同一句话问一百次都命中同一份快照。）</span>

---

## 十一、`tests/test_gates.py`

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

## 十二、状态

| 项 | 状态 |
|---|---|
| 三道闸 | 已实测通过（含容差、平凡数字、脱敏、缺口禁令等边界用例） |
| 快照的追加式版本 | 已实测通过（v2 覆盖 v1 的当前标记、v1 仍可按版本取回、缺失小时返回 `None`） |
| `tool_runner` 参数表 | 已用 anthropic 1.4.0 的 `inspect.signature` 实读确认 |
| `core/*` 十个算法 | 未实现，工具里以 `# STUB` 标出 |
| `prompts/` 六个文件 | 未写 |
| 三个查询工具 | 只给了 `get_hour_report`，另两个同构未展开 |
| `hourly_job.py` 定时入口 | 未写（`crontab` 那行调用的就是它，内容只是算出上一个整点再调 `run_hour`） |
| `audit.py` | 未写。每次调用追加一行 JSON：`agent_name / tool_name / 收发摘要 / token 数` |

<span style="color:#888">（`core.*` 的返回结构是按工具需要拟定的。实现 `core/` 时若不符，改工具层的取值，不要改 `ToolEnvelope` 的形状。相关文档：[提示词为什么分文件](./工作流搭建方案.md#三-bis三个-subagent-的提示词该放一个文件还是三个)、[LLM 部署指南](./LLM部署指南.md)）</span>
