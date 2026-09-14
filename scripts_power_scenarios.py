#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两种电力接入情景下的百万Token能耗/碳足迹/成本核算
S1 绿电直连 + 储能补电    S2 绿电直连 + CCS火力补电
"""
import json, os
B = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
DC, EC, EMB, OV, PW = S["datacenter"], S["economics"], S["embodied"], S["system_overhead"], S["power_supply"]
C, S1, S2 = PW["common"], PW["S1_储能补电"], PW["S2_CCS火电补电"]
SEC_Y, ANCHOR = 31_536_000, "DGX-H200"
P_NG, PSU = OV["P_nonGPU_kW"][ANCHOR], OV["PSU_efficiency"]
MASS, CAPEX = 130.45, EC["capex_CNY"][ANCHOR]

ROW = {  # 模型 -> 场景 -> (J/tok, 吞吐, 来源)
 "MiniMax-M2.7":  {"text": (0.85, 4229, "推"), "code": (0.86, 4180, "测")},
 "MiMo-V2-Flash": {"text": (0.92, 2913, "推"), "code": (1.43, 1874, "推")},
 "Qwen3.5-397B":  {"text": (1.07, 2505, "推"), "code": (2.18, 1229, "推")},
 "DeepSeek-V4":   {"text": (0.97, 2763, "测"), "code": (1.92, 1879, "测")},
}
PLAT = {"MiniMax-M2.7":"A100","MiMo-V2-Flash":"H100","Qwen3.5-397B":"H200","DeepSeek-V4":"B200"}


def power(alpha=None):
    """返回两情景的 (等效EF, 等效电价, 绿电需求系数, 补电电量系数)"""
    a = C["alpha_green_direct"] if alpha is None else alpha
    g, L = C["EF_green_lifecycle"], C["LCOE_green"]
    e, fs, cs = S1["eta_roundtrip"], S1["EF_storage_facility"], S1["cost_storage_facility"]
    return {
      "S1": dict(EF=a*g + (1-a)*(g/e + fs), price=a*L + (1-a)*(L/e + cs),
                 green=a + (1-a)/e, backup=1-a, name="绿电直连+储能补电"),
      "S2": dict(EF=a*g + (1-a)*S2["EF_ccs_thermal"], price=a*L + (1-a)*S2["price_ccs_thermal"],
                 green=a, backup=1-a, name="绿电直连+CCS火力补电"),
      "BASE": dict(EF=DC["grid_EF_kgCO2e_per_kWh"], price=EC["electricity_price_CNY_per_kWh"],
                   green=0.0, backup=1.0, name="全国电网均值(对照)"),
    }


def calc(j, thr, ps, pue=None):
    pue = DC["PUE_baseline"] if pue is None else pue
    E_gpu = j / 3.6
    t_h   = (1e6 / thr) / 3600
    E_it  = (E_gpu + P_NG * t_h) / PSU
    E_st  = E_it * pue                                  # 全站用电
    Mlife = thr * SEC_Y * EC["lifetime_years"] * EC["utilization"] / 1e6
    return dict(
      E_st=E_st, E_green=E_st*ps["green"], E_backup=E_st*ps["backup"],
      cf_op=E_st*ps["EF"], cf_em=(MASS*EMB["k_mat_kgCO2e_per_kg"])/Mlife,
      c_el=E_st*ps["price"], c_dp=CAPEX/Mlife,
      c_mt=CAPEX*EC["maintenance_rate_per_year"]*EC["lifetime_years"]/Mlife, Mlife=Mlife)


def bar(t): print("\n" + "═"*100 + f"\n{t}\n" + "═"*100)

PS = power()
bar("电力侧等效系数（绿电直供比例 α=60%）")
print(f"{'情景':<26}{'等效EF':>12}{'等效电价':>11}{'绿电需求':>11}{'补电电量':>11}")
for k in ["BASE","S1","S2"]:
    p = PS[k]
    print(f"{p['name']:<26}{p['EF']:>12.4f}{p['price']:>11.4f}{p['green']:>11.4f}{p['backup']:>11.2f}")
print("  单位：kgCO2e/kWh ｜ 元/kWh ｜ kWh每kWh负荷 ｜ kWh每kWh负荷")

for sc, cn in [("text","文本"), ("code","代码")]:
    bar(f"【{cn}场景】百万Token 三项结果 — 两种电力接入情景")
    print(f"{'模型':<16}{'平台':<7}{'全站用电':>9}{'绿电需求':>9}{'补电':>7}│"
          f"{'S1碳':>8}{'S2碳':>8}{'S1成本':>9}{'S2成本':>9}│{'S1 vs 电网':>11}{'S2 vs 电网':>11}")
    print(f"{'':<16}{'':<7}{'kWh':>9}{'kWh':>9}{'kWh':>7}│{'kgCO2e':>8}{'kgCO2e':>8}{'元':>9}{'元':>9}│{'碳降幅':>11}{'碳降幅':>11}")
    for m, d in ROW.items():
        j, thr, src = d[sc]
        r1, r2, rb = (calc(j, thr, PS[k]) for k in ["S1","S2","BASE"])
        cf1, cf2, cfb = (r["cf_op"]+r["cf_em"] for r in (r1, r2, rb))
        c1, c2 = (r["c_el"]+r["c_dp"]+r["c_mt"] for r in (r1, r2))
        print(f"{m:<16}{PLAT[m]:<7}{r1['E_st']:>9.3f}{r1['E_green']:>9.3f}{r1['E_backup']:>7.3f}│"
              f"{cf1:>8.4f}{cf2:>8.4f}{c1:>9.3f}{c2:>9.3f}│"
              f"{(1-cf1/cfb)*100:>10.1f}%{(1-cf2/cfb)*100:>10.1f}%")

    print(f"\n  碳足迹结构拆解（{cn}场景）")
    print(f"{'模型':<16}│{'S1: 运行碳':>11}{'隐含碳':>9}{'合计':>9}{'隐含占比':>9}│"
          f"{'S2: 运行碳':>11}{'隐含碳':>9}{'合计':>9}{'隐含占比':>9}")
    for m, d in ROW.items():
        j, thr, _ = d[sc]
        r1, r2 = calc(j, thr, PS["S1"]), calc(j, thr, PS["S2"])
        t1, t2 = r1["cf_op"]+r1["cf_em"], r2["cf_op"]+r2["cf_em"]
        print(f"{m:<16}│{r1['cf_op']:>11.4f}{r1['cf_em']:>9.4f}{t1:>9.4f}{r1['cf_em']/t1*100:>8.1f}%│"
              f"{r2['cf_op']:>11.4f}{r2['cf_em']:>9.4f}{t2:>9.4f}{r2['cf_em']/t2*100:>8.1f}%")

# ── α 敏感性 ────────────────────────────────────────────────
bar("绿电直供比例 α 的敏感性（文本场景，MiniMax-M2.7 / A100）")
j, thr, _ = ROW["MiniMax-M2.7"]["text"]
print(f"{'α':<8}{'EF₁':>9}{'EF₂':>9}{'P₁':>9}{'P₂':>9}│{'S1碳':>9}{'S2碳':>9}{'碳差倍数':>10}│{'S1成本':>9}{'S2成本':>9}{'成本差':>9}")
for a in [0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
    p = power(a)
    r1, r2 = calc(j, thr, p["S1"]), calc(j, thr, p["S2"])
    cf1, cf2 = r1["cf_op"]+r1["cf_em"], r2["cf_op"]+r2["cf_em"]
    c1, c2 = r1["c_el"]+r1["c_dp"]+r1["c_mt"], r2["c_el"]+r2["c_dp"]+r2["c_mt"]
    star = " ←基准" if abs(a-0.6) < 1e-9 else ""
    print(f"{f'{a:.0%}'+star:<8}{p['S1']['EF']:>9.4f}{p['S2']['EF']:>9.4f}"
          f"{p['S1']['price']:>9.4f}{p['S2']['price']:>9.4f}│"
          f"{cf1:>9.4f}{cf2:>9.4f}{cf2/cf1:>10.2f}×│{c1:>9.3f}{c2:>9.3f}{c1-c2:>9.4f}")

# ── 边际减碳成本 ────────────────────────────────────────────
bar("S1 相对 S2 的边际减碳成本（决定两方案的经济优劣）")
print("推导：Δ电价 = (1-α)·[(LCOE_绿/η + 储能成本) − CCS电价]")
print("      ΔEF   = (1-α)·[EF_CCS − (EF_绿/η + EF_储能)]")
print("      → 比值中的 (1-α) 相消，边际减碳成本与 α 无关\n")
dp = (C["LCOE_green"]/S1["eta_roundtrip"] + S1["cost_storage_facility"]) - S2["price_ccs_thermal"]
de = S2["EF_ccs_thermal"] - (C["EF_green_lifecycle"]/S1["eta_roundtrip"] + S1["EF_storage_facility"])
mac = dp/de
print(f"  Δ电价 = ({C['LCOE_green']}/{S1['eta_roundtrip']} + {S1['cost_storage_facility']}) − {S2['price_ccs_thermal']} = {dp:+.4f} 元/kWh")
print(f"  ΔEF   = {S2['EF_ccs_thermal']} − ({C['EF_green_lifecycle']}/{S1['eta_roundtrip']} + {S1['EF_storage_facility']}) = {de:+.4f} kgCO2e/kWh")
print(f"\n  ★ 边际减碳成本 = {mac:.4f} 元/kgCO2e = 【{mac*1000:.0f} 元/吨CO₂】（与 α、与模型均无关）\n")
print(f"{'碳价情景':<34}{'碳价(元/吨)':>12}{'经济最优方案':>16}")
for nm, cp in [("全国碳市场 CEA 当前区间下沿", 60), ("全国碳市场 CEA 当前区间上沿", 100),
               ("★ 本方案打平点", round(mac*1000)), ("欧盟 ETS 典型水平", 550)]:
    win = "S1 储能" if cp > mac*1000 else ("打平" if cp == round(mac*1000) else "S2 CCS火电")
    print(f"{nm:<34}{cp:>12}{win:>16}")

# ── 成本结构 ────────────────────────────────────────────────
bar("成本结构：为什么换电源几乎不改变成本（文本场景）")
print(f"{'模型':<16}{'情景':<10}{'电费':>9}{'折旧':>10}{'运维':>9}{'合计':>10}{'电费占比':>10}")
for m in ROW:
    j, thr, _ = ROW[m]["text"]
    for k in ["BASE","S1","S2"]:
        r = calc(j, thr, PS[k]); t = r["c_el"]+r["c_dp"]+r["c_mt"]
        print(f"{m if k=='BASE' else '':<16}{PS[k]['name'][:8]:<10}{r['c_el']:>9.3f}"
              f"{r['c_dp']:>10.3f}{r['c_mt']:>9.3f}{t:>10.3f}{r['c_el']/t*100:>9.1f}%")
    print()
