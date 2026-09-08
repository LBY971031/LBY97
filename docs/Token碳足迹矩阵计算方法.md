# 「机型 × 模型」Token 碳足迹矩阵的完整计算方法

> 编制日期：2026-09-08（v2，全面版）
> 目标产出：`服务器机型 m × AI模型 k` 矩阵，每格 **gCO₂e/MTok**，作为 SubAgent 输入
> 计算位置：**全部在 `core/`**，LLM 只读结果

---

## 目录

- [一、推理能耗的内部结构（最容易被忽略的一层）](#一推理能耗的内部结构最容易被忽略的一层)
- [二、影响单 Token 能耗的完整变量清单](#二影响单-token-能耗的完整变量清单)
- [三、Token 口径的三种选择](#三token-口径的三种选择)
- [四、两个前提](#四两个前提)
- [五、字段映射表](#五字段映射表公式变量--数据表字段)
- [六、完整计算流程（伪代码级）](#六完整计算流程伪代码级)
- [七、带数字的完整算例](#七带数字的完整算例)
- [八、训练侧的计算](#八训练侧的计算)
- [九、验证与交叉校验](#九验证与交叉校验)
- [十、矩阵稀疏性与呈现](#十矩阵稀疏性与呈现)
- [十一、给 LLM 的输入格式](#十一给-llm-的输入格式)
- [十二、六个最容易犯的错](#十二六个最容易犯的错)
- [十三、诚实声明](#十三诚实声明)

---

## 一、推理能耗的内部结构（最容易被忽略的一层）

**把"推理"当成一个整体是错的。** 推理至少分两个功耗特征截然不同的阶段：

| | **Prefill（预填充）** | **Decode（解码）** |
|---|---|---|
| 干什么 | **并行**处理全部输入 token，生成 KV cache | **自回归**逐个生成输出 token |
| 瓶颈性质 | **计算密集**（compute-bound） | **访存密集**（memory-bound） |
| GPU 利用率 | **90–95%** | **20–40%** |
| 算术强度 | 200–400 ops/byte | 降到 60–80 ops/byte |
| 每操作能效 | **比 decode 好 3–4 倍** | 差 |
| **总能耗占比** | 小 | **大——是 prefill 的 16–26 倍** |

> 📎 依据来自检索摘要（arXiv 2501.08219 等）。**均为预印本，需自行核实。**

### 这对你的指标意味着什么

**输入 Token 与输出 Token 的单位能耗根本不等价：**

```
输入 token 走 prefill：并行处理，摊薄后单位能耗低
输出 token 走 decode：每生成 1 个 token 都要重读全部权重和 KV cache，单位能耗高得多
```

所以 `tokens_in + tokens_out` 简单相加作为分母，**在能耗归因上是失真的**——
它把两种成本差异巨大的产出当成同一种东西。

> ⭐ **这是你的方法论可以做出真正贡献的地方**：现有工作多用简单相加口径，
> 引入**按阶段加权的 Token 口径**是一个有依据、可验证的精化。见[第三节](#三token-口径的三种选择)。

---

## 二、影响单 Token 能耗的完整变量清单

上一版只写了"机型 m × 模型 k"，太粗。实际影响单 Token 能耗的变量分四类：

### 2.1 模型侧

| 变量 | 影响 | 数据来源 |
|---|---|---|
| 参数量 | 权重读取量 → decode 阶段能耗主因 | 模型台账 |
| **量化精度** | FP16/BF16 相比 FP32 **降低约 30% 能耗** | 服务配置 |
| 注意力架构 | MHA / GQA / MQA 影响 KV cache 大小 | 模型台账 |
| KV cache 大小 | 随上下文线性增长，直接推高 decode 能耗 | 可由上下文长度推算 |

### 2.2 运行时侧 ⭐（最容易被忽略，但影响最大）

| 变量 | 影响 | 量级 |
|---|---|---|
| **Batch size** | 增大 batch **降低**单 token 能耗（固定开销摊薄） | **32→256 区间下降最陡**（GPU 利用率从 <50% 升至接近满）；超过 256 趋平，但最大 batch 仍可达 **2–3 倍**效率提升 |
| **上下文长度** | **持续推高**单 token 能耗 | 有报告称 Llama3 70B 在上下文 2K→10K 时单 token 能耗**增加约 3 倍** |
| **推理引擎** | vLLM / TensorRT-LLM / DeepSpeed 等 | 相比 vanilla Transformers 能效好 **25–55%**（高 batch 时尤显著） |
| 并行策略 | TP / PP 切分方式影响通信开销 | 需实测 |
| 输入输出长度比 | 决定 prefill / decode 的能耗配比 | 由日志统计 |

> 🔴 **这一类变量的存在意味着：同一个「机型 × 模型」格子，在不同运行配置下能耗可以差数倍。**
> 若不记录这些配置，矩阵里的数字就失去了可比性——**你比的可能不是机型差异，而是 batch 配置差异。**
>
> **因此矩阵必须附带运行配置快照**，见[第十节](#十矩阵稀疏性与呈现)。

### 2.3 硬件侧

| 变量 | 影响 |
|---|---|
| 加速卡型号 | 算力与显存带宽 → decode 阶段是带宽敏感的 |
| 显存带宽 | **decode 阶段的直接瓶颈** |
| 卡间互联（NVLink vs PCIe） | 多卡并行时的通信能耗 |
| 单卡额定/待机功率 | 空载能耗计算的输入 |

### 2.4 环境侧

| 变量 | 影响 |
|---|---|
| PUE（分时） | 制冷开销，随温度变 |
| 分时碳强度 | 直接决定同样能耗排多少碳 |
| 分时电价 | 成本侧 |

---

## 三、Token 口径的三种选择

| 口径 | 定义 | 优点 | 缺点 | 用途 |
|---|---|---|---|---|
| **A · 简单相加** | `tokens_in + tokens_out` | 行业最常用，可对标 | **失真**——两类 token 成本不等价 | **对外报告**（因为别人也这么算） |
| **B · 仅输出** | `tokens_out` | 突出 decode 主导 | 忽略了输入的 prefill 成本 | 少数场景 |
| **C · 阶段加权** ⭐ | `tokens_in × w_in + tokens_out × w_out` | **最贴近真实能耗结构** | 需实测标定权重，无行业标准 | **内部优化决策、机型对比** |

### 加权系数怎么定

```
w_in  = 1（归一化基准）
w_out = ( E_decode ÷ tokens_out ) ÷ ( E_prefill ÷ tokens_in )
        ↑ 由实测标定，不是常数，随模型和运行配置变化
```

**标定方法**：用固定 prompt 长度、固定输出长度的基准请求，
分别测 prefill 段和 decode 段的能耗（需要 phase-aligned 的功耗采集）。

> ⚠️ 若拿不到分阶段功耗，**不要凭经验设权重**——退回口径 A 并标注，
> 这符合[数据存在性契约](../能碳.md#1610-数据存在性契约硬性-v51-新增)。

> 💡 **建议做法**：矩阵**同时出 A 口径和 C 口径两版**。
> A 版对外交代、可对标；C 版内部用于机型和配置优化。[第七节](#七带数字的完整算例)会看到两者能差近 3 倍。

---

## 四、两个前提

### 前提一：最小计算单元是 (m, k, t)，不是 (m, k)

```
Σ_t ( E_t × EF_t )  ≠  ( Σ_t E_t ) × EF_平均
```

碳强度随时段变，**先把整月能耗汇总再乘月均因子的结果是错的**。
只有碳强度恒定、或负荷与碳强度完全不相关时两者才相等——算力园区**两个条件都不成立**
（负荷有日周期，碳强度也有日周期，高度相关）。

**时段粒度建议**：与碳强度数据的发布粒度对齐，通常是**小时**。
更细（15 分钟）需要碳强度也是该粒度，否则没有意义。

### 前提二：分子分母必须同粒度对齐

某 (m,k,t) 单元若有能耗无 Token（或反之），**整个单元排除并计入覆盖率**，
**不许一边实测一边估计**。

---

## 五、字段映射表（公式变量 → 数据表字段）

实现时最需要这张表。

| 公式变量 | 来源表 | 字段 | 缺失后果 |
|---|---|---|---|
| `E_整机实测(m,t)` | `energy_records` | `energy_kwh`（`segment=IT`，按 `server_model` 过滤） | 整格 absent |
| `装机卡数(m)` | `park_structure` | `installed_cards` | 空置率算不出 |
| `被占用卡数(m,t)` | `job_records` | `cards_used`（按 `server_model` 和时段聚合） | 分摊做不了 |
| `单卡待机功率(m)` | `server_specs` | `idle_power_w_per_card` | 空载扣不掉，降级路径 C |
| `卡时(m,k,t)` | `job_records` | `gpu_hours`（关联 `model_id`） | 分摊做不了 |
| `PUE(room,t)` | `park_structure` | `pue` | 只能出 `it_only` 版 |
| `EF_grid(t)` | `emission_factors` | `factor_value`（按 `source_db` 和时段） | 碳排算不出 |
| `E_园区绿电消纳(t)` | `renewable_records` | `consumed_kwh`（`scope_level=park`） | 市场法算不出 |
| `tokens_in / tokens_out` | `token_records` | `tokens_in` / `tokens_out` | 整格 absent |
| `隐含碳(d)` | `server_specs` | `embodied_kgco2e` | 出 `include_embodied=否` 版 |
| `设计寿命(d)` | `server_specs` | `lifetime_years` | 同上 |
| `累计等效运行小时(d)` | `device_lifecycle` | `cumulative_equiv_hours` | 退回日历摊销并标注 |
| `训练总碳(k)` | `carbon_records` | 按 `job_type=训练` 且 `model_id=k` 聚合 | 只能出 Boundary B |
| `预期总服务Token(k)` | 模型台账（**需新增**） | `expected_service_tokens` | 只能出 Boundary B |
| `是否本园区训练(k)` | 模型台账（**需新增**） | `trained_internally` | **无法防重复计算** |
| **运行配置**（batch/量化/引擎/上下文） | **需新增表** `serving_config` | — | **矩阵失去可比性** |

> ⭐ 表格末三行是本版新增的必要字段，[第十四节](#十四要改到-能碳md-的内容)列出了改动清单。

---

## 六、完整计算流程（伪代码级）

```
输入：统计周期 [T0, T1]，时段粒度 Δt（默认 1 小时）
输出：矩阵 M[m][k]，每格含指标 + 口径 + 状态

═══ 阶段 0：口径与配置固化 ═══
  caliber = 读取口径配置快照(token_scope, method, boundary_level,
                            allocation_method_preference, factor_version)
  若 caliber 未固化 → 中止，提示"须先完成工作流第①步定边界与口径"

═══ 阶段 1：逐 (m, k, t) 计算 ═══
FOR t IN 时段序列(T0, T1, Δt):
  FOR m IN 机型列表:

    ── 1.1 空载能耗（先算，因为后面要扣） ──
    IF 装机卡数(m) 存在 AND 被占用卡数(m,t) 存在:
        空置卡数 = 装机卡数(m) − 被占用卡数(m,t)
        IF 单卡待机功率(m) 存在:
            空载能耗(m,t) = 空置卡数 × 单卡待机功率(m) × Δt
        ELSE:
            空载能耗(m,t) = ABSENT      # 不估，标记
    ELSE:
        空载能耗(m,t) = ABSENT

    ── 1.2 选择能耗归集路径 ──
    IF 逐卡功率(m,t) 可用 AND 卡→模型映射完整:
        path = "A"
    ELIF 整机功耗(m,t) 可用 AND 卡时(m,·,t) 可用 AND 空载能耗 ≠ ABSENT:
        path = "B"
    ELIF 卡时(m,·,t) 可用 AND 功率基线(m,·) 可用:
        path = "C"
    ELSE:
        标记该 (m, ·, t) 全部 ABSENT；CONTINUE

    ── 1.3 逐模型归集 IT 能耗 ──
    FOR k IN 模型列表:
        SWITCH path:
          CASE "A":
            E_IT = Σ_{卡c ∈ m 且 t 时段被 k 占用} ∫P_c dt
          CASE "B":
            E_可分摊 = 整机功耗(m,t) − 空载能耗(m,t)          # ⭐ 必须先扣
            份额 = 卡时(m,k,t) ÷ Σ_k' 卡时(m,k',t)
            E_IT = E_可分摊 × 份额
          CASE "C":
            E_IT = 卡时(m,k,t) × 功率基线中位数(m,k)          # 标注为估算

        ── 1.4 回加约束 ──
        （FOR 循环结束后统一校验）

    residual = 整机功耗(m,t) − [ Σ_k E_IT(m,k,t) + 空载能耗(m,t) ]
    residual_pct = |residual| ÷ 整机功耗(m,t) × 100
    按各 k 的 E_IT 相对比例回摊 residual
    IF residual_pct > 5: 标记 quality_flag = "分摊不可靠"

    ── 1.5 加 PUE ──
    FOR k:
        E_total(m,k,t) = E_IT(m,k,t) × PUE(room(m), t)

    ── 1.6 运营碳排（分时段算，不可延后汇总） ──
    FOR k:
        C_op_loc(m,k,t) = E_total(m,k,t) × EF_grid(t)
        E_green分摊 = 园区绿电消纳(t) × [E_total(m,k,t) ÷ 园区总用电(t)]
        C_op_mkt(m,k,t) = (E_total(m,k,t) − E_green分摊) × EF_grid(t)

    ── 1.7 硬件隐含碳 ──
    FOR k:
        FOR d IN 属于机型m 且 t 时段被 k 占用的设备:
            k_load = 负载率分档系数(负载率(d,t))       # <30%:0.6 30~70%:1.0 >70%:1.3
            等效运行小时 = Δt × k_load
            C_emb(m,k,t) += 隐含碳(d)_kg × 1000 × (等效运行小时 ÷ 设计寿命等效小时(d))
                                          ↑ ⭐ kg→g 换算，不做会差 1000 倍

    ── 1.8 Token 归集 ──
    FOR k:
        tok_in(m,k,t), tok_out(m,k,t) ← token_records
        tok_A(m,k,t) = tok_in + tok_out
        IF 权重 w_out 已标定:
            tok_C(m,k,t) = tok_in × 1 + tok_out × w_out(m,k)
        ELSE:
            tok_C = ABSENT

═══ 阶段 2：汇总到 (m, k) ═══
FOR m, k:
    # ⭐ 先分时段算碳，此处才求和
    C_op(m,k)  = Σ_t C_op(m,k,t)
    C_emb(m,k) = Σ_t C_emb(m,k,t)
    E_IT(m,k)  = Σ_t E_IT(m,k,t)
    E_total(m,k) = Σ_t E_total(m,k,t)
    tok_A(m,k) = Σ_t tok_A(m,k,t)
    tok_C(m,k) = Σ_t tok_C(m,k,t)

═══ 阶段 3：训练碳（Boundary C 时） ═══
FOR k:
    IF boundary_level == "C":
        IF trained_internally(k):
            C_train_per_token(k) = 跨期分摊(训练总碳(k), 预期总服务Token(k))
            # ⭐ 跨期分摊：从训练期挪到服务期，总量不变，不新增
        ELSE:
            C_train_per_token(k) = 训练总碳(k) ÷ 预期总服务Token(k)   # 上游，新增
    ELSE:
        C_train_per_token(k) = 0

═══ 阶段 4：最终指标 ═══
FOR m, k:
    C_total_B(m,k) = C_op(m,k) + C_emb(m,k)
    C_total_C(m,k) = C_total_B(m,k) + C_train_per_token(k) × tok_A(m,k)

    M[m][k] = {
      "gco2e_per_mtok_A_B": C_total_B ÷ (tok_A ÷ 1e6),   # A口径 Boundary B
      "gco2e_per_mtok_A_C": C_total_C ÷ (tok_A ÷ 1e6),   # A口径 Boundary C
      "gco2e_per_mtok_C_B": C_total_B ÷ (tok_C ÷ 1e6),   # 加权口径 Boundary B
      "kwh_per_mtok":       E_total ÷ (tok_A ÷ 1e6),
      "tokens_per_kwh":     tok_A ÷ E_IT,                # ⭐ 用 IT 电耗，不含 PUE
      "residual_pct": ..., "allocation_path": path,
      "value_status": "derived" | "absent", ...
    }

═══ 阶段 5：交叉校验 ═══
  见第九节
```

---

## 七、带数字的完整算例

> 🔴 **以下全部为假设的示例数值，仅用于演示计算流程，不是真实数据、不可引用。**

### 输入

| 项 | 值 | 来源 |
|---|---|---|
| 时段 | 2026-07-03 14:00–15:00（Δt = 1 h） | — |
| 机型 | 机型A = 8×A100 服务器 × 16 台 = 128 卡 | `park_structure` |
| 整机 IT 实测能耗 | **42.0 kWh** | `energy_records` |
| 该时段被占用卡数 | 92 卡（模型甲 40 卡，模型乙 52 卡） | `job_records` |
| 单卡待机功率 | 55 W | `server_specs` |
| PUE | 1.32 | `park_structure` |
| 电网碳强度 | 612 gCO₂e/kWh | `emission_factors` |
| 单台服务器隐含碳 | 3000 kgCO₂e，寿命 5 年 | `server_specs` |
| 模型甲 Token | `tokens_in` = 8,400,000；`tokens_out` = 2,100,000 | `token_records` |
| 负载率 | 75%（→ 分档系数 k = 1.3） | 由功率推算 |

### 逐步计算

**① 空载能耗**
```
空置卡数 = 128 − 92 = 36 卡
空载能耗 = 36 × 55 W × 1 h = 1,980 Wh = 1.98 kWh
```

**② 可分摊能耗（先扣空载）**
```
E_可分摊 = 42.0 − 1.98 = 40.02 kWh
```

**③ 模型甲的 IT 能耗（路径 B）**
```
份额 = 40 卡时 ÷ 92 卡时 = 0.4348
E_IT(A, 甲) = 40.02 × 0.4348 = 17.40 kWh
```

**④ 加 PUE**
```
E_total(A, 甲) = 17.40 × 1.32 = 22.97 kWh
```

**⑤ 运营碳排（地域法）**
```
C_op = 22.97 kWh × 612 gCO₂e/kWh = 14,056 gCO₂e
```

**⑥ 硬件隐含碳**
```
模型甲占 40 卡 ÷ 8 卡/台 = 5 台等效
等效运行小时 = 1 h × 1.3 = 1.3 h
设计寿命等效小时 = 5 年 × 8760 = 43,800 h
C_emb = 5 台 × 3,000 kg × 1000 g/kg × (1.3 ÷ 43,800)
      = 5 × 3,000,000 × 2.968e-5
      = 445 gCO₂e
```

**⑦ Boundary B 总碳**
```
C_total_B = 14,056 + 445 = 14,502 gCO₂e
```

**⑧ 口径 A（简单相加）**
```
tok_A = 8,400,000 + 2,100,000 = 10,500,000 = 10.5 MTok
gCO₂e/MTok (A口径, Boundary B) = 14,502 ÷ 10.5 = 1,381 gCO₂e/MTok
```

**⑨ 口径 C（阶段加权）**
```
假设实测标定 w_out = 10（输出 token 单位能耗是输入的 10 倍）
tok_C = 8,400,000 × 1 + 2,100,000 × 10 = 8.4 + 21.0 = 29.4 M加权Tok
gCO₂e/M加权Tok = 14,502 ÷ 29.4 = 493 gCO₂e/M加权Tok
```

### ⭐ 两个口径差 2.8 倍

| 口径 | 结果 | 说明 |
|---|---|---|
| A · 简单相加 | **1,381** gCO₂e/MTok | 对外交代用，可与他人对标 |
| C · 阶段加权 | **493** gCO₂e/M加权Tok | 内部优化用，更贴近真实能耗结构 |

> 🔴 **两者不是同一个单位，不能直接比大小。**
> 但这个对比说明一件事：**口径不标注，数字毫无意义。**
> 同一批原始数据，换个口径数值差近 3 倍。

### 配套指标

```
每百万Token电耗 = 22.97 kWh ÷ 10.5 = 2.19 kWh/MTok
能效 = 10,500,000 ÷ 17.40 kWh = 603,448 Tokens/kWh   （用 IT 电耗）
空载浪费 = 1.98 kWh（本时段该机型，不摊给任何模型）
```

### 完整标注

```
1,381 gCO₂e/MTok
（地域法｜输入+输出｜含PUE｜含隐含碳按等效运行小时｜路径B卡时分摊｜Boundary B
 ｜因子v1.2｜2026-07-03 14:00-15:00｜残差 —— ｜batch/量化/引擎配置见附表）
```

---

## 八、训练侧的计算

上一版完全没展开，这里补齐。

### 8.1 训练能耗归集

```
E_train_IT(k) = Σ_{训练任务 j ∈ 模型k} Σ_t E_IT(j, t)
E_train_total(k) = Σ_t [ E_train_IT(k,t) × PUE(t) ]
C_train_op(k) = Σ_t [ E_train_total(k,t) × EF_grid(t) ]     # 仍须分时段算
```

### 8.2 三个训练特有的问题

| 问题 | 说明 | 建议处理 |
|---|---|---|
| **失败重跑** | 训练中断重启、发散重来，这部分能耗算不算？ | **算**——它是真实发生的排放。但应**单列**，作为"无效训练碳"指标 |
| **超参搜索 / 消融实验** | 为得到最终模型跑的大量试验 | **应计入**，否则严重低估。同样建议单列 |
| **检查点存储** | 存储能耗 | 通常并入共享设施分摊 |

> ⭐ **"无效训练碳占比"是一个有价值的独立指标**：
> `(失败重跑 + 超参搜索) ÷ 训练总碳`。它衡量训练过程本身的效率，
> 且很少有人报告——**可以作为你论文的一个观察点**。

### 8.3 摊销到推理

```
每Token训练碳(k) = C_train_total(k) ÷ 预期总服务Token量(k)
```

**两种情形必须分开**（否则重复计算）：

| 情形 | 处理 |
|---|---|
| `trained_internally = true` | 训练能耗**已在运营碳里**。做**跨期分摊**：从训练期挪到服务期，**总量不变** |
| `trained_internally = false` | 上游排放，Boundary C 下**新增** |

### 8.4 敏感性分析（必做）

`预期总服务Token量` 是估计值，必须给区间：

```
取 0.5× / 1× / 2× 三档，看最终指标变化幅度
服务量小的新模型 → 训练碳占比大，敏感性高
服务量大的成熟模型 → 训练碳被摊薄，敏感性低
```

---

## 九、验证与交叉校验

算完之后怎么知道对不对？**四道校验，全部应写成自动化测试。**

### 校验一：能耗回加

```
Σ_{m,k} E_IT(m,k,t) + Σ_m 空载能耗(m,t)  ≟  Σ_m 整机实测(m,t)
容差：|差额| ÷ 总量 < 1%
```

### 校验二：碳排回加

```
Σ_{m,k} C_op(m,k,t) + 空载碳排(t)  ≟  园区总用电(t) × EF_grid(t) × [IT占比]
```

### 校验三：口径一致性

```
同一格的 A口径 与 C口径 结果，其比值应等于 tok_C ÷ tok_A
若不等 → 说明分子用了不同的碳排数，是 bug
```

### 校验四：量纲抽查

```
gCO₂e/MTok 应落在合理区间（建议先用自己的数据建立经验区间）
偏离 10 倍以上 → 大概率是单位错误（kg/g 或 kWh/Wh）
```

> 💡 **校验一和校验四能抓住绝大多数实现 bug。** 建议在 `test_carbon.py` 里做成强制用例。

---

## 十、矩阵稀疏性与呈现

### 稀疏性是常态

不是每个 (m,k) 组合都有数据——模型甲可能从没在机型C 上跑过。

**呈现规则**：

| 情形 | 显示 | 禁止 |
|---|---|---|
| 有完整数据 | 数值 + 标注 | — |
| 该组合从未运行 | **空白 + "无此组合"** | ❌ 显示 0 |
| 运行过但数据缺失 | **"数据缺失" + 缺什么** | ❌ 显示 0 或插值 |
| 样本量不足 | 数值 + **"样本不足"警示** | ❌ 不加警示直接给 |

### 必须附带运行配置快照 ⭐

因为 batch size、量化、引擎、上下文长度对能耗影响可达数倍，
**矩阵每格必须能追溯到当时的运行配置**，否则你比的可能不是机型差异而是配置差异：

```
配置快照（每 m×k 格）：
  batch_size 分布（P50 / P95）
  量化精度（FP16 / INT8 / …）
  推理引擎与版本
  平均输入长度 / 平均输出长度
  并行策略（TP/PP 度数）
```

> **若配置在统计周期内发生过变更，应分段统计而非混算。**

---

## 十一、给 LLM 的输入格式

```json
{
  "status": "partial",
  "caliber": {
    "token_scope": "in+out", "method": "location", "include_embodied": true,
    "embodied_method": "equiv_hours", "energy_boundary": "with_pue",
    "allocation_method": "B", "boundary_level": "B",
    "factor_version": "v1.2", "period": "2026-07"
  },
  "matrix": [
    {
      "server_model": "机型A", "model_id": "模型甲",
      "gco2e_per_mtok_A": 1381.0, "gco2e_per_mtok_weighted": 493.0,
      "kwh_per_mtok": 2.19, "tokens_per_kwh": 603448,
      "tokens_in": 8400000, "tokens_out": 2100000,
      "residual_pct": 2.1, "allocation_path": "B",
      "serving_config": {"batch_p50": 64, "quant": "FP16",
                         "engine": "vLLM", "ctx_avg": 3200},
      "value_status": "derived"
    },
    {
      "server_model": "机型C", "model_id": "模型甲",
      "value_status": "absent",
      "absent_reason": "该机型未接入 Token 计量"
    },
    {
      "server_model": "机型B", "model_id": "模型丙",
      "value_status": "absent",
      "absent_reason": "该组合从未运行"
    }
  ],
  "idle_energy": [{"server_model": "机型A", "kwh": 1.98,
                   "note": "无主浪费，未摊给任何模型"}],
  "coverage": {"expected_cells": 12, "computed_cells": 8, "pct": 66.7},
  "absent_ranges": [...],
  "cross_check": {"energy_balance_pct": 0.4, "passed": true},
  "quality_grade": "B"
}
```

**注意两处**：
1. `idle_energy` **单独列出**，明确"未摊给任何模型"——避免 Agent 误以为漏算了
2. `absent_reason` **区分"从未运行"和"数据缺失"**——两者含义完全不同

---

## 十二、六个最容易犯的错

| # | 错误 | 后果 | 怎么防 |
|---|---|---|---|
| 1 | 先汇总能耗再乘平均碳强度 | 系统性偏差，**看不出来** | 强制 (m,k,t) 粒度算碳后再汇总；测试用例构造"负荷与碳强度正相关"数据验证两法不等 |
| 2 | **把空载能耗摊给模型** | 空置多的机型上模型碳足迹虚高 | 路径 B 第一步先扣空载；`idle_energy` 单独列出 |
| 3 | **自训模型训练碳算两遍** | 碳足迹虚高 | `trained_internally` 标记 + 跨期分摊 |
| 4 | 隐含碳 kg / g 未换算 | 差 1000 倍 | 校验四量纲抽查 |
| 5 | **输入输出 Token 简单相加** | 低估输出密集型服务的碳强度 | 同时出加权口径；标注所用口径 |
| 6 | **忽略运行配置差异** | 比的是配置差异不是机型差异 | 矩阵附配置快照；配置变更时分段统计 |

---

## 十三、诚实声明

| 内容 | 依据 |
|---|---|
| 分时段算碳不可先汇总 | ✅ 数学事实 |
| prefill 计算密集 / decode 访存密集、利用率 90-95% vs 20-40% | ⚠️ 检索摘要，**arXiv 预印本，需核实** |
| decode 能耗为 prefill 的 16–26 倍、每操作能效差 3–4 倍 | ⚠️ 同上，**具体倍数强依赖模型与配置** |
| batch 32→256 下降最陡、最大 batch 2–3 倍提升 | ⚠️ 检索摘要（TokenPowerBench 相关），**需核实** |
| 上下文 2K→10K 单 token 能耗增约 3 倍 | ⚠️ 单一模型的报告值，**不可泛化** |
| 推理引擎能效差 25–55%、混合精度降约 30% | ⚠️ 检索摘要，**需核实** |
| **阶段加权 Token 口径** | ⚠️ **我的设计**，无行业标准，需自行标定权重 |
| 空载不摊给模型、训练碳与机型无关、自训重复计算陷阱 | ⚠️ **我的推演** |
| **无效训练碳占比指标** | ⚠️ **我的建议**，未见文献 |
| 算例中的全部数值 | 🔴 **假设值，纯演示，不可引用** |

---

## 十四、要改到 `能碳.md` 的内容

| # | 改哪里 | 改什么 |
|---|---|---|
| 1 | §5.6 口径标注 | 增加口径 C（阶段加权）与运行配置快照要求 |
| 2 | §10 数据模型 | 新增 `serving_config` 表；模型台账增 `trained_internally`、`expected_service_tokens` |
| 3 | §10 表 2 `token_records` | 增加 `phase`（prefill/decode）字段，若采集器支持 |
| 4 | §5 模块三 | 增加训练侧计算（含无效训练碳） |
| 5 | §16.8 测试 | 增加四道交叉校验为强制用例 |
| 6 | §14 已知限制 | 增加"运行配置未记录则矩阵不可比"一条 |

