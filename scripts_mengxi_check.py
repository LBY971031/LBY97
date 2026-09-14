#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""蒙西电网参数下的复核重算"""
import json, os
B = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
EC, EMB, OV = S["economics"], S["embodied"], S["system_overhead"]
YEARS, UTIL, PSU = EC["lifetime_years"], EC["utilization"], OV["PSU_efficiency"]
HOURS = YEARS*365*24*UTIL

CASE = {                       # PUE, 电网EF, 电网电价, 绿电LCOE, α, 储能成本, CCS电价
 "原假设(全国)": dict(pue=1.30, gEF=0.5703, gP=0.60, Lg=0.28, a=0.60, Cs=0.30, Pc=0.55),
 "蒙西实际":     dict(pue=1.15, gEF=0.70,   gP=0.35, Lg=0.22, a=0.68, Cs=0.26, Pc=0.47),
}
EFg, e, EFs, EFc = 0.025, 0.90, 0.011, 0.22

def elec(c):
    S1 = dict(EF=c["a"]*EFg+(1-c["a"])*(EFg/e+EFs), price=c["a"]*c["Lg"]+(1-c["a"])*(c["Lg"]/e+c["Cs"]))
    S2 = dict(EF=c["a"]*EFg+(1-c["a"])*EFc,        price=c["a"]*c["Lg"]+(1-c["a"])*c["Pc"])
    G  = dict(EF=c["gEF"], price=c["gP"])
    return {"电网":G, "S1":S1, "S2":S2}

CELL = [("DGX-A100","MiniMax-M2.7",123.16,0.85,4229),
        ("DGX-H100","MiMo-V2-Flash",130.45,0.92,2913),
        ("DGX-H200","Qwen3.5-397B",130.45,1.07,2505),
        ("DGX-B200","DeepSeek-V4",142.4,0.97,2763)]

def per_M(pid, mass, j, thr, pue, ps):
    p_it = (j*thr/1000 + OV["P_nonGPU_kW"][pid])/PSU
    kwh  = p_it*pue*HOURS
    M    = thr*3600*HOURS/1e6
    cap  = EC["capex_CNY"][pid]
    return dict(en=kwh/M,
                cf=(kwh*ps["EF"] + mass*EMB["k_mat_kgCO2e_per_kg"])/M,
                cf_em=mass*EMB["k_mat_kgCO2e_per_kg"]/M,
                c=(kwh*ps["price"] + cap + cap*EC["maintenance_rate_per_year"]*YEARS)/M)

def bar(t): print("\n"+"═"*112+f"\n{t}\n"+"═"*112)

bar("电力侧等效系数：原假设 vs 蒙西")
print(f"{'':<14}" + "".join(f"{k:>34}" for k in CASE))
print(f"{'':<14}" + "".join(f"{'EF':>11}{'电价':>11}{'':>12}" for _ in CASE))
for s in ["电网","S1","S2"]:
    row=f"{s:<14}"
    for k,c in CASE.items():
        p=elec(c)[s]; row += f"{p['EF']:>11.4f}{p['price']:>11.4f}{'':>12}"
    print(row)

bar("百万Token 三项结果：原假设 vs 蒙西（文本场景）")
for s in ["S1","S2"]:
    print(f"\n▼ 情景{s[-1]}  {'绿电直连+储能补电' if s=='S1' else '绿电直连+CCS火力补电'}")
    print(f"{'平台×模型':<24}│{'能耗 kWh':>20}│{'碳 kgCO2e':>24}│{'成本 元':>22}")
    print(f"{'':<24}│{'原假设':>9}{'蒙西':>7}{'Δ':>4}│{'原假设':>10}{'蒙西':>8}{'Δ':>6}│{'原假设':>9}{'蒙西':>7}{'Δ':>6}")
    for pid,m,mass,j,thr in CELL:
        r=[per_M(pid,mass,j,thr,c["pue"],elec(c)[s]) for c in CASE.values()]
        print(f"{pid[4:]+' × '+m:<24}│{r[0]['en']:>9.3f}{r[1]['en']:>7.3f}{(r[1]['en']/r[0]['en']-1)*100:>+4.0f}%"
              f"│{r[0]['cf']:>10.4f}{r[1]['cf']:>8.4f}{(r[1]['cf']/r[0]['cf']-1)*100:>+5.0f}%"
              f"│{r[0]['c']:>9.3f}{r[1]['c']:>7.3f}{(r[1]['c']/r[0]['c']-1)*100:>+5.0f}%")

bar("结论稳健性复核")
c0,c1 = CASE["原假设(全国)"], CASE["蒙西实际"]
for nm,c in [("原假设",c0),("蒙西",c1)]:
    p=elec(c); pid,m,mass,j,thr = CELL[0]
    r={k:per_M(pid,mass,j,thr,c["pue"],p[k]) for k in p}
    mac = ((c["Lg"]/e + c["Cs"]) - c["Pc"]) / (EFc - (EFg/e + EFs))
    print(f"\n【{nm}】")
    print(f"  ① S2/S1 碳比值            : {r['S2']['cf']/r['S1']['cf']:.2f}×")
    print(f"  ② S1与S2成本差            : {abs(r['S1']['c']-r['S2']['c'])/r['S1']['c']*100:.2f}%")
    print(f"  ③ 边际减碳成本            : {mac*1000:.0f} 元/吨CO2")
    print(f"  ④ 隐含碳占比 (S1 / S2)    : {r['S1']['cf_em']/r['S1']['cf']*100:.1f}% / {r['S2']['cf_em']/r['S2']['cf']*100:.1f}%")
    print(f"  ⑤ 电费占成本 (S1)         : {(r['S1']['c']-r['S1']['c']+ (per_M(pid,mass,j,thr,c['pue'],p['S1'])['en']*p['S1']['price']))/r['S1']['c']*100:.1f}%")
    print(f"  ⑥ S1相对电网碳降幅        : {(1-r['S1']['cf']/r['电网']['cf'])*100:.1f}%")
    print(f"  ⑦ S2相对电网碳降幅        : {(1-r['S2']['cf']/r['电网']['cf'])*100:.1f}%")
