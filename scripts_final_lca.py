#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""百万Token能耗/碳足迹/成本 —— 完整核算
主结果：锚定行（四模型同台，PPT实测J/token）
副结果：对角线参数化预测（代际增益 g 为待测量）
"""
import json, os, itertools
B = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
M = json.load(open(f"{B}/data/ppt_measurements.json", encoding="utf-8"))
J = M["j_per_token_best"]
DC, EC, EMB, OV = S["datacenter"], S["economics"], S["embodied"], S["system_overhead"]
SEC_Y = 31_536_000

ANCHOR = "DGX-H200"                       # PPT平台推断值
P_NG   = OV["P_nonGPU_kW"][ANCHOR]
PSU    = OV["PSU_efficiency"]
MASS   = EMB["mass_override_kg"].get(ANCHOR, 130.45)
CAPEX  = EC["capex_CNY"][ANCHOR]
EMB_T  = MASS * EMB["k_mat_kgCO2e_per_kg"]

# 锚定行：模型 → {场景: (J/tok, 吞吐, 吞吐来源, 吞吐低, 吞吐高)}
ROW = {
 "MiniMax-M2.7": {
   "text": (0.85, 4229, "自身代码场景锚定", 4229, 4229),
   "code": (0.86, 4180, "PPT实测 TP=8 bs=256", 4180, 4180)},
 "MiMo-V2-Flash": {
   "text": (0.92, 2913, "功率区间反推", 1627, 3921),
   "code": (1.43, 1874, "功率区间反推", 1047, 2523)},
 "Qwen3.5-397B": {
   "text": (1.07, 2505, "功率区间反推", 1399, 3372),
   "code": (2.18, 1229, "功率区间反推",  687, 1655)},
 "DeepSeek-V4": {
   "text": (0.97, 2763, "PPT实测 SGLang bs=128", 2763, 2763),
   "code": (1.92, 1879, "PPT实测 SGLang bs=128", 1879, 1879)},
 "DeepSeek-V4(vLLM)": {
   "text": (4.43,  487, "PPT实测 vLLM bs=128",  487,  487),
   "code": (2.83,  764, "PPT实测 vLLM bs=128",  764,  764)},
}
PAIR = {"MiniMax-M2.7":"A100","MiMo-V2-Flash":"H100",
        "Qwen3.5-397B":"H200","DeepSeek-V4":"B200","DeepSeek-V4(vLLM)":"B200"}


def calc(j, thr, pue=None, ef=None, price=None,
         p_ng=P_NG, mass=MASS, capex=CAPEX):
    pue   = DC["PUE_baseline"] if pue   is None else pue
    ef    = DC["grid_EF_kgCO2e_per_kWh"] if ef is None else ef
    price = EC["electricity_price_CNY_per_kWh"] if price is None else price

    E_gpu = j / 3.6                                  # kWh/1M tok, GPU-only
    t_h   = (1e6 / thr) / 3600                       # 产出1M tok 的机时 (h)
    E_it  = (E_gpu + p_ng * t_h) / PSU               # 整机 IT
    E_st  = E_it * pue                               # 全站

    cf_op = E_st * ef
    Mlife = thr * SEC_Y * EC["lifetime_years"] * EC["utilization"] / 1e6
    cf_em = (mass * EMB["k_mat_kgCO2e_per_kg"]) / Mlife

    c_el  = E_st * price
    c_dp  = capex / Mlife
    c_mt  = capex * EC["maintenance_rate_per_year"] * EC["lifetime_years"] / Mlife
    return dict(E_gpu=E_gpu, t_h=t_h, E_it=E_it, E_st=E_st, ovh=E_it/E_gpu,
                cf_op=cf_op, cf_em=cf_em, cf=cf_op+cf_em,
                emb_pct=cf_em/(cf_op+cf_em)*100,
                c_el=c_el, c_dp=c_dp, c_mt=c_mt, c=c_el+c_dp+c_mt,
                el_pct=c_el/(c_el+c_dp+c_mt)*100, Mlife=Mlife)

def bar(t): print("\n" + "═"*104 + f"\n{t}\n" + "═"*104)

SC = [("text","文本"), ("code","代码")]
bar(f"主结果｜锚定行：四模型同台对比（平台推断为 {ANCHOR}）")
print(f"基准情景  PUE={DC['PUE_baseline']}  电网因子={DC['grid_EF_kgCO2e_per_kWh']} kgCO2e/kWh  "
      f"电价={EC['electricity_price_CNY_per_kWh']} 元/kWh  寿命={EC['lifetime_years']}年  "
      f"利用率={EC['utilization']:.0%}  η=1.0（即“每百万输出Token”）")

for sc, cn in SC:
    print(f"\n【表A-{cn}】能耗  (kWh / 百万Token)")
    print(f"{'模型':<20}{'J/tok':>7}{'吞吐':>7}{'GPU侧':>9}{'整机':>9}{'放大':>7}{'全站':>9}  {'吞吐来源'}")
    for m, d in ROW.items():
        j, thr, src, _, _ = d[sc]; r = calc(j, thr)
        print(f"{m:<20}{j:>7.2f}{thr:>7,}{r['E_gpu']:>9.3f}{r['E_it']:>9.3f}"
              f"{r['ovh']:>7.2f}{r['E_st']:>9.3f}  {src}")

for sc, cn in SC:
    print(f"\n【表B-{cn}】碳足迹  (kgCO2e / 百万Token)")
    print(f"{'模型':<20}{'运行碳':>10}{'隐含碳':>10}{'合计':>10}{'隐含占比':>10}{'≈驾车公里*':>12}")
    for m, d in ROW.items():
        j, thr, *_ = d[sc]; r = calc(j, thr)
        print(f"{m:<20}{r['cf_op']:>10.4f}{r['cf_em']:>10.4f}{r['cf']:>10.4f}"
              f"{r['emb_pct']:>9.1f}%{r['cf']/0.17:>12.2f}")
    print("  * 按燃油小客车 0.17 kgCO2e/km 折算，仅供直观参照")

for sc, cn in SC:
    print(f"\n【表C-{cn}】成本  (元 / 百万Token)")
    print(f"{'模型':<20}{'电费':>9}{'折旧':>9}{'运维':>9}{'合计':>10}{'电费占比':>10}{'寿命内百万Token':>16}")
    for m, d in ROW.items():
        j, thr, *_ = d[sc]; r = calc(j, thr)
        print(f"{m:<20}{r['c_el']:>9.3f}{r['c_dp']:>9.3f}{r['c_mt']:>9.3f}{r['c']:>10.3f}"
              f"{r['el_pct']:>9.1f}%{r['Mlife']:>16,.0f}")

# ── 不确定度传播 ────────────────────────────────────────────
bar("不确定度传播：吞吐反推区间如何传导到三项结果")
print(f"{'模型/场景':<22}{'吞吐区间':>18}{'全站能耗kWh':>18}{'碳kgCO2e':>18}{'成本元':>18}")
for m in ["MiMo-V2-Flash", "Qwen3.5-397B"]:
    for sc, cn in SC:
        j, thr, src, lo, hi = ROW[m][sc]
        a, b = calc(j, hi), calc(j, lo)          # 高吞吐=好，低吞吐=差
        print(f"{m+'/'+cn:<22}{f'{lo:,}–{hi:,}':>18}"
              f"{f'{a[chr(69)+chr(95)+chr(115)+chr(116)]:.3f}–{b[chr(69)+chr(95)+chr(115)+chr(116)]:.3f}':>18}"
              f"{f'{a[chr(99)+chr(102)]:.3f}–{b[chr(99)+chr(102)]:.3f}':>18}"
              f"{f'{a[chr(99)]:.1f}–{b[chr(99)]:.1f}':>18}")
print("\n  → 这两个模型的结果不确定度约 2.4 倍，全部来自吞吐反推。实测后即可收敛。")
print("  → MiniMax 与 DeepSeek 的吞吐为 PPT 实测，结果无此项不确定度。")

# ── 情景敏感性 ──────────────────────────────────────────────
bar("情景敏感性：碳足迹 (kgCO2e/百万Token)，文本场景")
ms = [m for m in ROW if m != "DeepSeek-V4(vLLM)"]
print(f"{'PUE × 电网因子':<26}" + "".join(f"{m:>16}" for m in ms))
for (pn, pv), (en, ev) in itertools.product(DC["PUE_scenarios"].items(),
                                            DC["grid_EF_scenarios"].items()):
    vals = [calc(ROW[m]["text"][0], ROW[m]["text"][1], pue=pv, ef=ev)["cf"] for m in ms]
    print(f"{f'{pn}({pv}) × {en}':<26}" + "".join(f"{v:>16.4f}" for v in vals))

bar("情景敏感性：成本 (元/百万Token)，文本场景 —— 年利用率的影响")
print(f"{'年利用率':<26}" + "".join(f"{m:>16}" for m in ms))
base_u = EC["utilization"]
for u in [0.10, 0.30, 0.50, 0.70, 0.90]:
    EC["utilization"] = u
    vals = [calc(ROW[m]["text"][0], ROW[m]["text"][1])["c"] for m in ms]
    print(f"{f'{u:.0%}' + (' ← 基准' if u == base_u else ''):<26}" + "".join(f"{v:>16.3f}" for v in vals))
EC["utilization"] = base_u

# ── 对角线参数化 ────────────────────────────────────────────
bar("副结果｜对角线：四台各跑一个模型（g = 相对PPT平台的代际能效增益，待测）")
BW = {"A100": 2039, "H100": 3350, "H200": 4800, "B200": 8000}
PL = {"A100": "DGX-A100", "H100": "DGX-H100", "H200": "DGX-H200", "B200": "DGX-B200"}
print("公式：E_GPU(目标) = E_GPU(PPT) ÷ g ；吞吐(目标) = 吞吐(PPT) × 带宽比")
print(f"\n{'平台×模型':<26}{'带宽比':>8}" + "".join(f"{'g='+str(g):>13}" for g in [1.0, 1.5, 2.0, 3.0]))
print(f"{'':<26}{'':>8}" + "".join(f"{'全站kWh':>13}" for _ in range(4)))
for hw, m in [("A100","MiniMax-M2.7"), ("H100","MiMo-V2-Flash"),
              ("H200","Qwen3.5-397B"), ("B200","DeepSeek-V4")]:
    r = BW[hw] / BW["H200"]
    j, thr, *_ = ROW[m]["text"]
    pid = PL[hw]
    row = f"{hw+' × '+m:<26}{r:>8.2f}"
    for g in [1.0, 1.5, 2.0, 3.0]:
        v = calc(j/g, thr*r, p_ng=OV["P_nonGPU_kW"][pid],
                 mass=EMB["mass_override_kg"].get(pid) or
                      {"DGX-A100":123.16,"DGX-H100":130.45,"DGX-B200":142.4}.get(pid,130.45),
                 capex=EC["capex_CNY"][pid])["E_st"]
        row += f"{v:>13.3f}"
    print(row)
print("\n  ⚠️ g 正是本研究要测的量，不能预先假定。上表用途是：实测 E_st 后反解 g，")
print("     即 g = E_GPU(PPT) ÷ E_GPU(实测)，这才是“硬件代际能效增益”的定义式。")
