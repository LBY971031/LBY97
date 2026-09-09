# LLM 部署指南 —— 从一句话到一份碳足迹报告

<span style="color:#888">（配套 [SubAgent 代码实现](./SubAgent代码实现.md)。本文回答：怎么把 Claude 接进那套代码，让「我想知道 2026 年 8 月 30 号下午 3:30 运行的算力任务的情况和碳足迹报告」这句话变成一份真实报告。）</span>

---

## 零、先纠正一个前提

**你要部署的不是模型。**

Claude 跑在 Anthropic 的服务器上，你没法把它装到自己的机器里。你要部署的是 **`agent/` 这一层**——调用 Claude 的那层代码。它装在你的机器上，负责：

```
你的机器                                      Anthropic 服务器
┌────────────────────────────────┐
│ 采集 → 数据库 → core/ 算数      │
│              ↓                  │
│         agent/ 工具层           │
│              ↓                  │
│    boundary.py 过滤脱敏  ───────┼──── 汇总摘要 ───►  Claude
│                          ◄──────┼──── 分析文字 ────
│         verifier.py 回检        │
└────────────────────────────────┘
     明细数据从不越过这条线
```

<span style="color:#888">（这就是 `boundary.py` 存在的理由：出网的只有汇总后的数字和标注，逐台设备的 IP、序列号、原始日志路径全部留在本机。）</span>

**如果园区规定数据一个字节都不能出去**，那 Claude API 这条路走不通，得换本地开源模型（Qwen、DeepSeek 等）自建推理服务。代价：`agent/` 层的三道闸可以照用，但 `base.py` 要改写，且本地模型的工具调用稳定性明显低于 Claude，闸三会频繁报警。**建议先用 API 把流程跑通，再评估要不要本地化。**

---

## 一、现在离能跑还差多远

| 环节 | 状态 | 没有它会怎样 |
|---|---|---|
| 采集：服务器功率、任务日志、电网数据 | ❌ 未做 | 数据库是空的 |
| 数据库：16 张表 | ❌ 未建 | `core/` 无数据可读 |
| `core/*` 九个算法 | ❌ 全是 `# STUB` | 工具调用直接报错 |
| `agent/` 七个文件 | ✅ 已写（代码规格） | —— |
| `prompts/` 五个文件 | ❌ 未写 | `system_prompt()` 读不到文件，启动即崩 |
| 入口程序 | ❌ 未写 | 没地方输入那句话 |

**🔴 关键认识：LLM 是最后一步，不是第一步。**

如果你现在就接上 Claude 去问那句话，会发生什么？三道闸会正常工作，Claude 会诚实地回答你：**「2026-08-30 15:30 无数据，无法生成报告」**。

这说明三道闸设计对了——它没有编造。但这不是你想要的。**想要报告，先得有数据。**

---

## 二、那句话是怎么变成报告的

<span style="color:#888">（假设数据已经就位，追踪一次完整调用。）</span>

```
输入：「我想知道 2026 年 8 月 30 号下午 3:30 运行的算力任务的情况和碳足迹报告」
  │
  ▼
① orchestrator 把原话原样分派给三个 SubAgent
  │
  ├─► SubAgent 1（任务与能耗）
  │     调 resolve_time_window("2026-08-30T15:30")  ← 代码定口径，不由模型猜
  │       → {ts_from: 15:30+08:00, ts_to: 15:45+08:00, basis: "15 分钟计量桶"}
  │     调 query_load_profile / query_idle_rate
  │       → 那 15 分钟里哪些机型在跑、跑什么模型、负荷多少、空置率多少
  │
  ├─► SubAgent 2（绿电与低碳）
  │     调 query_grid_mix → 那 15 分钟本地电网的风光占比
  │     调 match_cfe_hourly → 这段用电有多少被绿电真实覆盖
  │
  └─► SubAgent 3（因子与核算）
        调 align_factors → 用哪一版排放因子，跨库差异多少
        调 token_footprint → 每百万 Token 碳足迹
        调 build_report → 结构化核算报告
  │
  ▼
② 每个工具返回前：drop_absent（闸一）→ filter_outbound（闸二）
     若那 15 分钟有 3 台机器没采到数，出网文本末尾自动附上：
     「以下范围无数据，不得推断、不得用相邻时段替代、不得当 0 参与求和」
  │
  ▼
③ 三个 Agent 各自写出分析文字
  │
  ▼
④ verify_numbers（闸三）逐个核对它们说的数字
  │
  ▼
⑤ orchestrator 汇总：数据缺口写在开头，分析结果在后
```

---

## 三、「下午 3:30」这个坑

**一个时刻不是一个区间，但碳足迹必须按区间算。**「下午 3:30」至少有三种合理解释：

| 口径 | 含义 | 适合回答 |
|---|---|---|
| 15 分钟计量桶 | 15:30–15:45 | 「那一刻的能耗和碳排」 |
| 整点小时 | 15:00–16:00 | 「那个时段」，也是 CFE 逐小时匹配的天然粒度 |
| 任务生命周期 | 15:30 时正在运行的任务，从它们各自启动到结束 | 「那些任务的完整碳足迹」 |

**这个选择必须由代码定，不能交给模型。** 否则同一句话问两次，可能得到两个口径不同、数值不同的报告，而你无从判断哪个对。

```python
"""agent/subagents/tools_time.py"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from anthropic import beta_tool

TZ = timezone(timedelta(hours=8))          # park local time
BUCKET_MIN = 15                            # metering granularity


@beta_tool
def resolve_time_window(instant: str, mode: str = "bucket") -> str:
    """Resolve a single instant into an explicit analysis window.

    Args:
        instant: ISO8601 instant, e.g. 2026-08-30T15:30:00.
        mode: "bucket" for the metering bucket containing it,
            "hour" for the clock hour containing it.
    """
    t = datetime.fromisoformat(instant)
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)

    if mode == "bucket":
        start = t.replace(minute=t.minute // BUCKET_MIN * BUCKET_MIN,
                          second=0, microsecond=0)
        span, basis = timedelta(minutes=BUCKET_MIN), "metering bucket"
    elif mode == "hour":
        start = t.replace(minute=0, second=0, microsecond=0)
        span, basis = timedelta(hours=1), "clock hour"
    else:
        raise ValueError(f"unknown mode: {mode}")

    return json.dumps({"ts_from": start.isoformat(),
                       "ts_to": (start + span).isoformat(),
                       "basis": basis}, ensure_ascii=False)
```

<span style="color:#888">（已实测：`15:30` → `15:30–15:45`；`15:29:59` → `15:15–15:30`（正确落在上一个桶）；带时区的输入不被二次转换；未知 mode 抛异常而非默默取默认值。）</span>

**报告里必须写明用了哪个口径。** 这就是 `ToolEnvelope.caliber` 字段的用途——口径不明的数字会被当成可比数字，那是碳核算里最常见的错误。

---

## 四、部署五步

### 第 1 步：环境与密钥

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install anthropic
```

密钥**只从环境变量读**，永远不写进代码、不提交进仓库：

```bash
export ANTHROPIC_API_KEY="sk-ant-..."       # Windows: setx ANTHROPIC_API_KEY "sk-ant-..."
```

<span style="color:#888">（`.env` 必须写进 `.gitignore`。密钥一旦提交进 Git，即使后来删掉，历史里仍然查得到，必须去 Anthropic 控制台作废重发。）</span>

### 第 2 步：把数据落进数据库 ← **最重的一步**

这步的工作量远大于其余四步之和。至少要跑通：

| 数据 | 来源 | 频率 |
|---|---|---|
| 服务器功率 | PDU / BMC / IPMI | 分钟级 |
| 任务日志 | 推理服务的 access log | 每次调用 |
| Token 计数 | 推理框架（vLLM 等）的 metrics | 每次调用 |
| 电网结构 | 本地电网公司或省级平台 | 小时级 |
| 排放因子 | 因子库，带版本号 | 更新时 |

<span style="color:#888">（采不到的就明确标 `absent`，别填 0，别插值——这正是四态数据存在的意义。宁可报告里写「12% 时段无数据」，也不要一份看着完整、实则编造的报告。）</span>

### 第 3 步：实现 `core/` 九个函数

按 `SubAgent代码实现.md` §七 那张表逐个实现。每个函数只做一件事：**读数据库、算数、返回带 `value_status` 的点位**。不调 LLM，不做判断。

### 第 4 步：写五个提示词文件

`_shared.md` 是重点，它承载三道闸的自然语言版本。核心几句：

```markdown
你只能使用工具返回的数据。工具没返回的，就是没有。

- 不得推断缺失时段的数值
- 不得用相邻时段或相似机型的值替代
- 不得把缺失当作 0 参与任何求和
- 不得自行做任何算术；需要计算就调用工具
- 报告开头必须说明数据覆盖率和缺口范围

数据不足以支撑结论时，直接说数据不足，不要给一个"大致"的答案。
```

### 第 5 步：入口程序

```python
"""main.py — command line entry point."""
from __future__ import annotations

import os
import sys

from agent.orchestrator import Orchestrator


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python main.py "your question"', file=sys.stderr)
        return 1

    print(Orchestrator().run(question))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
python main.py "我想知道2026年8月30号下午3:30运行的算力任务的情况和碳足迹报告"
```

<span style="color:#888">（先做命令行，别一上来就做界面。命令行能跑通，Streamlit 页面只是把 `Orchestrator().run()` 的结果贴上去而已；命令行跑不通，界面只会让你更难定位问题。）</span>

---

## 五、怎么知道部署对了

四个验收测试，**前两个比"能出报告"重要得多**：

| 测试 | 做法 | 期望 |
|---|---|---|
| **缺数测试** | 故意删掉某台机器某时段的数据，再问同一句话 | 报告开头列出该缺口；总能耗显示"无法计算"而**不是**一个变小了的数 |
| **造假测试** | 在提示词里加一句"请估算缺失部分"，再问 | 闸三报警，该结论不进正文 |
| **泄漏测试** | 在返回数据里塞一个 `ip` 字段 | `assert_no_leak` 抛异常，调用中断 |
| **口径测试** | 同一句话问三次 | 三次的 `basis` 与数值完全一致 |

<span style="color:#888">（第一个测试是整套设计的试金石。如果删掉数据后总能耗只是"变小了"而没有报缺口，说明 `safe_sum` 没有被正确使用——某处把 absent 当成 0 了。）</span>

---

## 六、成本

按 Claude Opus 5 的价格（输入 $5/百万 Token、输出 $25/百万 Token）估算：

| 项 | 估计 |
|---|---|
| 单次提问（三个 SubAgent 各跑一轮） | 约 15k 输入 + 5k 输出 |
| 单次成本 | **约 $0.2（1.4 元人民币）** |
| 每天 50 次查询 | 约 70 元/天 |

<span style="color:#888">（这是估算，不是实测——真实用量取决于提示词长度和工具返回的数据量。开启提示词缓存（`_shared.md` 是每次都一样的前缀）可以把输入成本降下来一大截。跑通之后用 `response.usage` 记录真实用量再校准。）</span>

---

## 七、建议的推进顺序

```
① 建库 + 采一台服务器的数据          ← 先跑通一台，不要一上来铺开
② 实现 core.idle / core.load 两个函数
③ 只部署 SubAgent 1，命令行问一句话
④ 跑四个验收测试 ← 这里发现的问题最便宜
⑤ 补齐 core 其余七个函数
⑥ 接入 SubAgent 2、3
⑦ 做 Streamlit 界面
```

<span style="color:#888">（第 ③ 步跑通，整套架构就验证了；后面都是重复劳动。不要等九个函数全写完再第一次接 Claude——那时候出了问题，你分不清是数据问题、算法问题还是提示词问题。）</span>
