#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五年生命周期总量法：先算五年总产出/总投入，再归一到百万Token"""
import json, os
B = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
DC, EC, EMB, OV, PW = S["datacenter"], S["economics"], S["embodied"], S["system_overhead"], S["power_supply"]
C, SS1, SS2 = PW["common"], PW["S1_储能补电"], PW["S2_CCS火电补电"]

YEARS, UTIL, PUE, PSU = EC["lifetime_years"], EC["utilization"], DC["PUE_baseline"], OV["PSU_efficiency"]
HOURS = YEARS * 365 * 24 * UTIL                      # 五年内实际运行小时

a, EFg, Lg = C["alpha_green_direct"], C["EF_green_lifecycle"], C["LCOE_green"]
e, EFs, Cs = SS1["eta_roundtrip"], SS1["EF_storage_facility"], SS1["cost_storage_facility"]
PS = {
 "S1": dict(name="绿电直连+储能补电",    EF=a*EFg+(1-a)*(EFg/e+EFs), price=a*Lg+(1-a)*(Lg/e+Cs), green=a+(1-a)/e),
 "S2": dict(name="绿电直连+CCS火力补电", EF=a*EFg+(1-a)*SS2["EF_ccs_thermal"], price=a*Lg+(1-a)*SS2["price_ccs_thermal"], green=a),
}

# 四个配对：平台专有参数(质量/购置价/非GPU功率) + PPT携带参数(J/tok, 吞吐)
CELL = [
 ("DGX-A100","MiniMax-M2.7",  123.16, {"text":(0.85,4229),"code":(0.86,4180)}),
 ("DGX-H100","MiMo-V2-Flash", 130.45, {"text":(0.92,2913),"code":(1.43,1874)}),
 ("DGX-H200","Qwen3.5-397B",  130.45, {"text":(1.07,2505),"code":(2.18,1229)}),
 ("DGX-B200","DeepSeek-V4",   142.4,  {"text":(0.97,2763),"code":(1.92,1879)}),
]

def life(pid, mass, j, thr):
    """五年生命周期总量"""
    p_gpu  = j * thr / 1000                                    # kW，GPU侧
    p_it   = (p_gpu + OV["P_nonGPU_kW"][pid]) / PSU            # kW，整机IT
    p_site = p_it * PUE                                        # kW，全站
    tok    = thr * 3600 * HOURS                                # 五年总Token
    kwh    = p_site * HOURS                                    # 五年总用电 kWh
    capex  = EC["capex_CNY"][pid]
    return dict(p_gpu=p_gpu, p_it=p_it, p_site=p_site, tok=tok, Mtok=tok/1e6, kwh=kwh,
                emb=mass*EMB["k_mat_kgCO2e_per_kg"], capex=capex,
                opex=capex*EC["maintenance_rate_per_year"]*YEARS)

def bar(t): print("\n"+"═"*102+f"\n{t}\n"+"═"*102)

bar(f"五年生命周期基础量（寿命 {YEARS} 年 × 年利用率 {UTIL:.0%} = 实际运行 {HOURS:,.0f} 小时）")
for sc, cn in [("text","文本"),("code","代码")]:
    print(f"\n【{cn}场景】")
    print(f"{'平台':<11}{'模型':<16}{'J/tok':>7}{'吞吐':>7}{'GPU功率':>9}{'整机功率':>9}{'全站功率':>9}"
          f"{'五年总Token':>15}{'':>3}{'(万亿)':>8}")
    for pid, m, mass, d in CELL:
        j, thr = d[sc]; r = life(pid, mass, j, thr)
        print(f"{pid:<11}{m:<16}{j:>7.2f}{thr:>7,}{r['p_gpu']:>8.2f}kW{r['p_it']:>8.2f}kW"
              f"{r['p_site']:>8.2f}kW{r['tok']:>15,.0f}{'':>3}{r['tok']/1e12:>8.2f}")

bar("五年生命周期总量：总能耗 / 总碳排 / 总成本")
for sc, cn in [("text","文本"),("code","代码")]:
    print(f"\n【{cn}场景】　总能耗与总成本（与电力情景相关的项分列）")
    print(f"{'平台×模型':<26}{'总用电':>12}{'S1绿电需求':>12}{'S2绿电需求':>12}│"
          f"{'购置':>9}{'五年运维':>9}{'S1电费':>9}{'S2电费':>9}{'S1总成本':>10}{'S2总成本':>10}")
    print(f"{'':<26}{'万kWh':>12}{'万kWh':>12}{'万kWh':>12}│"
          f"{'万元':>9}{'万元':>9}{'万元':>9}{'万元':>9}{'万元':>10}{'万元':>10}")
    for pid, m, mass, d in CELL:
        j, thr = d[sc]; r = life(pid, mass, j, thr)
        e1 = r["kwh"]*PS["S1"]["price"]/1e4; e2 = r["kwh"]*PS["S2"]["price"]/1e4
        cap, op = r["capex"]/1e4, r["opex"]/1e4
        print(f"{pid[4:]+' × '+m:<26}{r['kwh']/1e4:>12.2f}{r['kwh']*PS['S1']['green']/1e4:>12.2f}"
              f"{r['kwh']*PS['S2']['green']/1e4:>12.2f}│{cap:>9.0f}{op:>9.0f}{e1:>9.2f}{e2:>9.2f}"
              f"{cap+op+e1:>10.2f}{cap+op+e2:>10.2f}")

    print(f"\n【{cn}场景】　总碳排（tCO₂e）")
    print(f"{'平台×模型':<26}{'整机隐含碳':>12}│{'S1运行碳':>11}{'S1总碳':>10}{'隐含占比':>10}│"
          f"{'S2运行碳':>11}{'S2总碳':>10}{'隐含占比':>10}")
    for pid, m, mass, d in CELL:
        j, thr = d[sc]; r = life(pid, mass, j, thr)
        emb = r["emb"]/1000
        o1, o2 = r["kwh"]*PS["S1"]["EF"]/1000, r["kwh"]*PS["S2"]["EF"]/1000
        t1, t2 = o1+emb, o2+emb
        print(f"{pid[4:]+' × '+m:<26}{emb:>12.2f}│{o1:>11.2f}{t1:>10.2f}{emb/t1*100:>9.1f}%│"
              f"{o2:>11.2f}{t2:>10.2f}{emb/t2*100:>9.1f}%")

bar("归一化结果：每百万Token 的能耗 / 碳足迹 / 成本")
for k in ["S1","S2"]:
    p = PS[k]
    print(f"\n▼ 情景{k[-1]}　{p['name']}　(EF={p['EF']:.4f} kgCO₂e/kWh，电价={p['price']:.4f} 元/kWh)")
    for sc, cn in [("text","文本"),("code","代码")]:
        print(f"\n  【{cn}场景】")
        print(f"  {'平台×模型':<26}{'能耗':>9}│{'运行碳':>9}{'隐含碳':>9}{'碳合计':>9}│"
              f"{'电费':>8}{'折旧':>9}{'运维':>8}{'成本合计':>10}")
        print(f"  {'':<26}{'kWh':>9}│{'kgCO₂e':>9}{'kgCO₂e':>9}{'kgCO₂e':>9}│"
              f"{'元':>8}{'元':>9}{'元':>8}{'元':>10}")
        for pid, m, mass, d in CELL:
            j, thr = d[sc]; r = life(pid, mass, j, thr); M = r["Mtok"]
            en  = r["kwh"]/M
            cop = r["kwh"]*p["EF"]/M; cem = r["emb"]/M
            el  = r["kwh"]*p["price"]/M; dp = r["capex"]/M; mt = r["opex"]/M
            print(f"  {pid[4:]+' × '+m:<26}{en:>9.3f}│{cop:>9.4f}{cem:>9.4f}{cop+cem:>9.4f}│"
                  f"{el:>8.3f}{dp:>9.3f}{mt:>8.3f}{el+dp+mt:>10.3f}")
