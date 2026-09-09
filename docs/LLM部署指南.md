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
| `core/*` 十个算法 | ❌ 全是 `# STUB` | 工具调用直接报错 |
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
  │       → {instant: 15:30, ts_from: 15:00, ts_to: 16:00, mode: "hour"}
  │     调 query_tasks_running(instant) → 15:30 那一刻哪些任务在跑（秒级精确）
  │     调 query_load_profile / query_idle_rate(ts_from, ts_to)
  │       → 各机型本小时的能耗、空置率
  │
  ├─► SubAgent 2（绿电与低碳）
  │     调 query_grid_mix → 那一小时本地电网的风光占比（因子最细到小时）
  │     调 match_cfe_hourly → 这段用电有多少被绿电真实覆盖
  │
  └─► SubAgent 3（因子与核算）
        调 align_factors → 用哪一版排放因子，跨库差异多少
        调 token_footprint → 每百万 Token 碳足迹
        调 build_report → 结构化核算报告
  │
  ▼
② 每个工具返回前：drop_absent（闸一）→ filter_outbound（闸二）
     若本小时有 3 台机器没采到数，出网文本末尾自动附上：
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

## 三、时间分辨率定多少

**结论：报告默认按小时，但采集必须保持分钟级。这两件事要分开定。**

<span style="color:#888">（因为采集分辨率丢了就再也回不来，报告分辨率随时可以改。）</span>

### 3.0 为什么是这个结论

**第一笔账：存储。**按园区 200 台服务器、每条记录约 80 字节估算：

| 采样周期 | 点/台/天 | 年记录数 | 年存储 |
|---|---:|---:|---:|
| 1 秒 | 86,400 | 63.1 亿 | 470 GB |
| 5 秒 | 17,280 | 12.6 亿 | 94 GB |
| **1 分钟** | **1,440** | **1.05 亿** | **7.8 GB** |
| 5 分钟 | 288 | 2,102 万 | 1.6 GB |
| 15 分钟 | 96 | 701 万 | 535 MB |
| 1 小时 | 24 | 175 万 | 134 MB |

<span style="color:#888">（1 分钟采集一年 7.8 GB——对一块普通硬盘不构成压力。所以「分钟级采集太贵」这个顾虑，在这个规模下不成立。真正贵的是秒级。）</span>

**第二笔账：小时聚合会丢掉什么。**造一天分钟级功率（基线 2 kW，15:25–15:35 有一次 8 kW 的十分钟尖峰），再聚合：

| 分辨率 | 当日峰值 | 峰值/基线 | 全天电量 |
|---|---:|---:|---:|
| 1 分钟 | 8.00 kW | 4.00× | 49.0 kWh |
| 5 分钟 | 8.00 kW | 4.00× | 49.0 kWh |
| 15 分钟 | 4.00 kW | 2.00× | 49.0 kWh |
| 1 小时 | 3.00 kW | 1.50× | 49.0 kWh |

**关键发现：聚合保住能量，丢掉峰值。** 全天电量四种分辨率完全一致（49.0 kWh），但真实的 8 kW 峰值在小时均值里只显示为 3.00 kW，**低估 2.7 倍**。

这直接决定了分工：

| 你要算的东西 | 性质 | 小时够不够 |
|---|---|---|
| 能耗、碳排、碳足迹 | 能量（可加） | ✅ 完全够 |
| 绿电匹配、CFE 得分 | 能量 | ✅ 够，且小时是国际通行粒度 |
| **负荷突增、不稳定性** | **峰值/形状（不可加）** | ❌ **不够** |

**尖峰要多大多久才能在小时均值里露头？**（抬升不足 20% 视为淹没）

| 尖峰倍数 | 2 分钟 | 5 分钟 | 10 分钟 | 30 分钟 |
|---|---:|---:|---:|---:|
| 1.3× | 1% ✕ | 2% ✕ | 5% ✕ | 15% ✕ |
| 2× | 3% ✕ | 8% ✕ | 17% ✕ | 50% ✓ |
| 4× | 10% ✕ | 25% ✓ | 50% ✓ | 150% ✓ |

<span style="color:#888">（读法：一次持续 10 分钟、幅度 2 倍的负荷突增，在小时均值里只抬升 17%，基本淹没在正常波动里。而你的核心问题之一正是「哪些时段负荷突然增高」——这类问题小时分辨率答不了。）</span>

### 3.1 于是：三层分辨率

```
采集   1 分钟   ← 存下来，7.8 GB/年，丢了回不来
  │
  ├─► 报告   1 小时   ← 默认。能耗、碳排、绿电匹配都在这一层
  │
  └─► 下钻   1 分钟   ← 只在查不稳定性、定位负荷突增时才用
```

**为什么报告默认小时，三条理由：**

1. **电网排放因子本来就是小时级的。** 报告按小时，因子粒度和数据粒度严丝合缝，不必解释错配。按分钟则是伪精度——分钟级能耗乘一个小时级因子，得到的碳排并不比小时级更准。
2. **24/7 CFE 逐小时匹配是国际通行方法**（Google CFE Score、EnergyTag 都按小时）。按小时算，你的结果才和已发表工作可比——这对论文重要。
3. **一天 24 个点，人看得过来。** 1440 个点只能画图，没法逐条核对。

### 3.2 那「3:30 那一刻在跑什么任务」还答得了吗？

**答得了，而且是精确的。** 因为这里有个容易混淆的地方：

| | 数据形态 | 时间精度来源 | 受计量分辨率影响吗 |
|---|---|---|---|
| 任务清单 | **事件流**（有起止时间戳） | 日志本身，秒级 | ❌ 不受影响 |
| 能耗曲线 | **时间序列**（等间隔采样） | 采样周期 | ✅ 直接决定 |

任务记录是一条条带 `ts_start` / `ts_end` 的事件，它的时间精度来自推理服务的日志，**跟你多久采一次电表毫无关系**。所以：

- 「15:30:00 那一刻哪些任务在跑」→ **精确可答**，区间重叠查询，秒级精度
- 「那一分钟消耗了多少电」→ **取决于采集**，1 分钟采集才答得了
- 「那一分钟排放了多少碳」→ **答不了**（因子是小时级），只能给所在小时

<span style="color:#888">（所以你原来那句问话，拆开之后三个子问题的可答粒度是不一样的。报告必须分别标明，不能笼统写成「15:30 的碳足迹」。）</span>

### 3.3 时间窗口工具

```python
"""agent/subagents/tools_time.py"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from anthropic import beta_tool

TZ = timezone(timedelta(hours=8))          # park local time
SPANS = {"minute": timedelta(minutes=1),
         "bucket": timedelta(minutes=15),
         "hour": timedelta(hours=1)}


@beta_tool
def resolve_time_window(instant: str, mode: str = "hour") -> str:
    """Resolve an instant into a half-open window for energy and carbon.

    The returned `instant` keeps full precision for task-overlap queries,
    which do not depend on metering resolution.

    Args:
        instant: ISO8601 instant, e.g. 2026-08-30T15:30:00.
        mode: "hour" (default, matches grid emission factor granularity),
            "bucket" for 15 minutes, or "minute" for drill-down.
    """
    if mode not in SPANS:
        raise ValueError(f"unknown mode: {mode}")

    t = datetime.fromisoformat(instant)
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)

    floored = t.replace(second=0, microsecond=0)
    if mode == "hour":
        start = floored.replace(minute=0)
    elif mode == "bucket":
        start = floored.replace(minute=floored.minute // 15 * 15)
    else:
        start = floored

    return json.dumps({"instant": t.isoformat(),
                       "ts_from": start.isoformat(),
                       "ts_to": (start + SPANS[mode]).isoformat(),
                       "mode": mode}, ensure_ascii=False)
```

<span style="color:#888">（已实测：`15:30:47` 在 `hour` 模式下得 `15:00–16:00`，在 `minute` 模式下得 `15:30–15:31`，而 `instant` 字段始终保留 `15:30:47` 的完整精度供任务查询使用；未知 mode 抛异常而非默默取默认值。）</span>

### 3.4 「哪些任务在跑」是区间重叠，不是时刻相等

15:30 在跑的任务，绝大多数不是 15:30 开始的——它可能 15:22 就启动了，15:47 才结束。判据是**半开区间重叠**：

```sql
SELECT * FROM task_run
WHERE ts_start <  :instant_or_window_to
  AND (ts_end IS NULL OR ts_end > :instant_or_window_from)
```

<span style="color:#888">（已按此判据实测六种情形：跨越整分钟的任务命中；15:30 整开始的命中；15:31 整结束的命中；15:30 整结束的**不**命中（半开区间右端不含）；15:31 整开始的**不**命中；`ts_end IS NULL` 命中。）</span>

**`ts_end IS NULL` 要当心。** 对一次历史查询来说，它意味着这条记录没有结束时间——可能任务真的还在跑（对 10 天前的数据而言不正常），也可能是日志丢了结束事件。**这种记录的能耗应标 `imputed` 或 `absent`，不能当成正常记录参与求和。**

### 3.5 同一台服务器上跑着多个任务时，能耗必须分摊

一小时里，一台 8 卡机上可能跑过十几个任务。**整机能耗是一个数，要分到各任务头上。** ISO 的分配层级：

```
① 能细分就细分     分卡计量  ← 现实中不够可靠，见下
        ↓ 做不到
② 按物理量分配     GPU 时间份额 / 显存占用份额 / Token 份额  ← 现实中的主力
        ↓ 做不到
③ 按经济价值分配   计费额度                                 ← 最后手段
```

**空载能耗不分摊给任何任务。** 没有任务在跑的卡，功耗是无主的，单列成「空载能耗」——摊给任务会让任务碳足迹凭空变大，还掩盖了真正该改进的问题（空置率）。

<span style="color:#888">（关于分卡计量：早前我在审计文档里写过「技术上可行，应作首选」，后来查证发现 A100/H100 上 `nvidia-smi` 只采样约 25% 的运行时间，MIG 也缺乏硬件级功率归属——那个说法我已撤回。分卡数据可以用，但不能当作精确实测。分配方法必须写进 `caliber`：不同方法算出的单任务碳足迹可以差几倍，不标口径的数字没有可比性。）</span>

### 3.6 报告骨架

<span style="color:#888">（尖括号是待填的真实数值——此处不放示例数字，避免被误读成真实结果。）</span>

```
## 数据与校验缺口（先看这里）
- 功率采样覆盖率 <x>/60，缺口 <ts 范围>
- <n> 条任务记录 ts_end 为空，其能耗标为 absent，未参与求和

## 口径
查询时刻   2026-08-30 15:30:00 (+08:00)
能耗窗口   15:00:00 ~ 16:00:00，1 小时
碳排窗口   15:00:00 ~ 16:00:00，受电网因子粒度约束，无法更细
任务清单   按 15:30:00 这一时刻的区间重叠判定，秒级精确

## 15:30:00 那一刻在跑的任务
| 任务 | 模型 | 服务器 | 起止 | 本小时内运行时长 | GPU 时间份额 |
| job-<hash> | model-<hash> | sku-<hash> | 15:22–15:47 | <x> min | <x>% |

## 本小时能耗
| 服务器 | 整机能耗 | 任务分摊 | 空载（无主） | 采样覆盖率 |

## 本小时碳排放
| 项 | 数值 | 因子 | 因子粒度 |
| 运营碳排 | <x> gCO₂e | <省级电网小时因子 v2026.3> | 小时 |

## 口径声明
分配方法 / 因子版本 / 空载是否计入 / 采样推导方式
```

**报告里必须写明用了哪个口径。** 这就是 `ToolEnvelope.caliber` 字段的用途——口径不明的数字会被当成可比数字，那是碳核算里最常见的错误。

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

### 第 3 步：实现 `core/` 十个函数

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
