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
  │       → {ts_from: 15:30+08:00, ts_to: 15:31+08:00, mode: "minute"}
  │     调 query_tasks_running → 这一分钟里哪些任务在跑、各在哪台机器上
  │     调 query_load_profile / query_idle_rate
  │       → 各机型这一分钟的功率、能耗、空置率
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

## 三、口径已定：那一分钟

**「下午 3:30」= 15:30:00–15:31:00 这一分钟。** 要回答的是四件事：

1. 这一分钟里有哪些算力任务在跑
2. 它们分别跑在哪些服务器上
3. 这一分钟的实时能耗
4. 这一分钟的碳排放

<span style="color:#888">（口径由代码定死，不由模型猜。同一句话问一百次，必须得到同一个窗口。）</span>

```python
"""agent/subagents/tools_time.py"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from anthropic import beta_tool

TZ = timezone(timedelta(hours=8))          # park local time
BUCKET_MIN = 15                            # PDU metering granularity


@beta_tool
def resolve_time_window(instant: str, mode: str = "minute") -> str:
    """Resolve a single instant into an explicit half-open analysis window.

    Args:
        instant: ISO8601 instant, e.g. 2026-08-30T15:30:00.
        mode: "minute" (default), "bucket" for the 15-minute metering
            bucket containing it, or "hour" for the clock hour.
    """
    t = datetime.fromisoformat(instant)
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)
    t = t.replace(second=0, microsecond=0)

    if mode == "minute":
        start, span = t, timedelta(minutes=1)
    elif mode == "bucket":
        start = t.replace(minute=t.minute // BUCKET_MIN * BUCKET_MIN)
        span = timedelta(minutes=BUCKET_MIN)
    elif mode == "hour":
        start, span = t.replace(minute=0), timedelta(hours=1)
    else:
        raise ValueError(f"unknown mode: {mode}")

    return json.dumps({"ts_from": start.isoformat(),
                       "ts_to": (start + span).isoformat(),
                       "mode": mode}, ensure_ascii=False)
```

<span style="color:#888">（已实测：`15:30:00` 与 `15:30:47` 都归到 `15:30–15:31`；`bucket` 模式得 `15:30–15:45`，`hour` 模式得 `15:00–16:00`；未知 mode 抛异常而非默默取默认值。）</span>

**但把口径定到一分钟，会带出四个后果，每一个都会影响报告的可信度。**

### 3.1 「哪些任务在跑」是区间重叠，不是时刻相等

15:30 在跑的任务，绝大多数不是 15:30 开始的——它可能 15:22 就启动了，15:47 才结束。判据是**半开区间重叠**：

```sql
SELECT * FROM task_run
WHERE ts_start <  :window_to        -- 任务在窗口结束前就已开始
  AND (ts_end IS NULL OR ts_end > :window_from)   -- 且在窗口开始后才结束
```

<span style="color:#888">（已按此判据实测六种情形：跨越整分钟的任务命中；15:30 整开始的命中；15:31 整结束的命中；15:30 整结束的**不**命中（半开区间右端不含）；15:31 整开始的**不**命中；`ts_end IS NULL` 命中。）</span>

**`ts_end IS NULL` 要当心。** 对一次历史查询来说，它意味着「这条任务记录没有结束时间」——可能是任务真的还在跑（对 10 天前的数据而言不正常），也可能是日志丢了结束事件。**这种记录的能耗应标 `imputed` 或直接 `absent`，不能当成正常记录参与求和。**

### 3.2 一分钟里可能只有一个采样点，甚至没有

这是最容易被忽略的一点：

| 采集源 | 典型采样周期 | 一分钟窗口内的点数 |
|---|---|---|
| BMC / IPMI | 1–5 秒 | 12–60 个 ✅ |
| GPU（`nvidia-smi`） | 1 秒 | 约 60 个，但实际采样覆盖率远低于此 ⚠️ |
| PDU 计费表 | **15 分钟** | **0 或 1 个** 🔴 |

**如果你的功率数据来自 PDU 计费表，你根本得不到「那一分钟」的能耗。** 你能得到的是它所在 15 分钟桶的平均功率，再乘以一分钟。这时：

- `value_status` 必须是 `derived`，不是 `measured`
- `caliber` 里必须写明 `sampling_interval_s: 900` 和推导方式
- 报告里必须说「由 15 分钟均值推导」，**不能假装有分钟级精度**

<span style="color:#888">（关于 `nvidia-smi`：早前我在审计文档里写过「分卡计量技术上可行，应作首选」，后来查证发现 A100/H100 上它只采样约 25% 的运行时间，MIG 也缺乏硬件级功率归属——那个说法我已撤回。分卡数据可以用，但不能当作精确的实测。）</span>

### 3.3 一台服务器上跑着多个任务时，能耗必须分摊

一分钟里，一台 8 卡机上可能同时跑着 3 个任务。**整机功率是一个数，要分到三个任务头上。** ISO 的分配层级是：

```
① 能细分就细分     分卡计量  ← 见上，现实中不够可靠
        ↓ 做不到
② 按物理量分配     GPU 时间份额 / 显存占用份额 / Token 份额  ← 现实中的主力
        ↓ 做不到
③ 按经济价值分配   计费额度                                 ← 最后手段
```

**空载能耗不分摊给任何任务。** 那一分钟里没有任务在跑的卡，功耗是无主的，单列成「空载能耗」——把它摊给任务，会让任务的碳足迹凭空变大，也掩盖了真正该改进的问题（空置率）。

<span style="color:#888">（分配方法必须写进 `caliber`。不同分配方法算出的单任务碳足迹可以差几倍，不标口径的数字没有可比性。）</span>

### 3.4 碳排放做不到分钟级精度

**电网排放因子最细通常只到小时。** 那一分钟的碳排 = 那一分钟的能耗 × 15:00–16:00 那个小时的因子。

所以：

| 量 | 能达到的精度 |
|---|---|
| 能耗 | 分钟级（取决于采样，见 3.2） |
| 碳排 | **小时级** —— 分钟级碳排是伪精度 |

这不是系统缺陷，是物理现实。**但如果报告不写明，读者会以为碳排也精确到分钟。** 因子粒度必须进 `caliber`：

```
caliber: {
    "window": "2026-08-30T15:30:00+08:00 ~ 15:31:00+08:00",
    "energy_basis": "BMC 1s sampling, 58/60 points",
    "allocation_method": "gpu_time_share",
    "ef_source": "省级电网小时因子 v2026.3",
    "ef_granularity_s": 3600,
    "idle_energy_excluded": true
}
```

### 3.5 那一分钟的报告长什么样

<span style="color:#888">（骨架，尖括号是待填的真实数值——此处不放示例数字，避免被误读成真实结果。）</span>

```
## 数据与校验缺口（先看这里）
- 功率采样覆盖率 <x>/60，缺口 <ts 范围>
- <n> 条任务记录 ts_end 为空，其能耗标为 absent，未参与求和

## 窗口
2026-08-30 15:30:00 ~ 15:31:00 (+08:00)，共 60 秒

## 那一分钟在跑的任务
| 任务 | 模型 | 服务器 | 起止 | 窗口内占比 | GPU 时间份额 |
| job-<hash> | model-<hash> | sku-<hash> | 15:22–15:47 | 100% | <x>% |

## 能耗
| 服务器 | 整机能耗 | 任务分摊 | 空载（无主） | 覆盖率 |

## 碳排放
| 项 | 数值 | 因子 | 因子粒度 |
| 运营碳排 | <x> gCO₂e | <省级电网小时因子> | 小时 |

## 口径声明
分配方法 / 因子版本 / 空载是否计入 / 采样推导方式
```

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
