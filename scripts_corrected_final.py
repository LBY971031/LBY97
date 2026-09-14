#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修正版最终结果：物理自洽的对角线 × 蒙西参数 × 两电力情景"""
BW   = {"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG  = {"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
MASS = {"A100":123.16,"H100":130.45,"H200":130.45,"B200":142.4}
CAP  = {"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
TDP  = {"A100":3.2,"H100":5.6,"H200":5.6,"B200":8.0}
HOURS, PUE, PSU, KMAT, MAINT, YEARS = 5*365*24*0.70, 1.15, 0.94, 30, 0.05, 5
PS = {"S1": dict(name="绿电直连+储能补电",    EF=0.0294, price=0.3110),
      "S2": dict(name="绿电直连+CCS火力补电", EF=0.0874, price=0.3000)}
CELL = [("A100","MiniMax-M2.7",  {"text":(0.85,4229),"code":(0.86,4180)}),
        ("H100","MiMo-V2-Flash", {"text":(0.92,2913),"code":(1.43,1874)}),
        ("H200","Qwen3.5-397B",  {"text":(1.07,2505),"code":(2.18,1229)}),
        ("B200","DeepSeek-V4",   {"text":(0.97,2763),"code":(1.92,1879)})]

def cell(hw, j, thr0):
    thr = thr0 * BW[hw]/BW["H200"]                 # 带宽比修正
    pg  = j*thr/1000
    pit = (pg + PNG[hw])/PSU
    kwh = pit*PUE*HOURS
    Mt  = thr*3600*HOURS/1e6
    return dict(thr=thr, pg=pg, tdp_pct=pg/TDP[hw]*100, kwh=kwh, Mt=Mt,
                en=kwh/Mt, cf_em=MASS[hw]*KMAT/Mt,
                capex=CAP[hw], opex=CAP[hw]*MAINT*YEARS)

def bar(t): print("\n"+"═"*104+f"\n{t}\n"+"═"*104)

bar("修正版基础量（带宽比修正，全部通过 TDP 检验）")
for sc,cn in [("text","文本"),("code","代码")]:
    print(f"\n【{cn}场景】")
    print(f"{'平台×模型':<24}{'J/tok':>7}{'修正吞吐':>9}{'GPU功率':>9}{'占TDP':>7}{'整机':>8}"
          f"{'五年总Token':>13}{'五年总用电':>12}")
    for hw,m,d in CELL:
        j,t0 = d[sc]; r = cell(hw,j,t0)
        ok = "✅" if r["tdp_pct"]<100 else "❌"
        print(f"{hw+' × '+m:<24}{j:>7.2f}{r['thr']:>9,.0f}{r['pg']:>8.2f}kW{r['tdp_pct']:>6.0f}%{ok}"
              f"{(r['pg']+PNG[hw])/PSU:>6.2f}kW{r['Mt']/1e6:>11.2f}万亿{r['kwh']/1e4:>10.2f}万kWh")

bar("修正版最终结果：每百万Token（蒙西参数：PUE 1.15）")
for sc,cn in [("text","文本"),("code","代码")]:
    print(f"\n╔═ 【{cn}场景】")
    print(f"{'平台×模型':<24}{'能耗':>8}│{'S1运行碳':>10}{'隐含碳':>9}{'S1碳合计':>10}│"
          f"{'S2运行碳':>10}{'隐含碳':>9}{'S2碳合计':>10}")
    print(f"{'':<24}{'kWh':>8}│{'kgCO₂e':>10}{'kgCO₂e':>9}{'kgCO₂e':>10}│{'kgCO₂e':>10}{'kgCO₂e':>9}{'kgCO₂e':>10}")
    for hw,m,d in CELL:
        j,t0 = d[sc]; r = cell(hw,j,t0)
        o1,o2 = r["kwh"]*PS["S1"]["EF"]/r["Mt"], r["kwh"]*PS["S2"]["EF"]/r["Mt"]
        print(f"{hw+' × '+m:<24}{r['en']:>8.3f}│{o1:>10.4f}{r['cf_em']:>9.4f}{o1+r['cf_em']:>10.4f}│"
              f"{o2:>10.4f}{r['cf_em']:>9.4f}{o2+r['cf_em']:>10.4f}")

    print(f"\n{'平台×模型':<24}{'折旧':>9}{'运维':>8}│{'S1电费':>9}{'S1成本合计':>12}{'电费占比':>9}│"
          f"{'S2电费':>9}{'S2成本合计':>12}{'电费占比':>9}")
    for hw,m,d in CELL:
        j,t0 = d[sc]; r = cell(hw,j,t0)
        dp, mt = r["capex"]/r["Mt"], r["opex"]/r["Mt"]
        e1, e2 = r["kwh"]*PS["S1"]["price"]/r["Mt"], r["kwh"]*PS["S2"]["price"]/r["Mt"]
        c1, c2 = e1+dp+mt, e2+dp+mt
        print(f"{hw+' × '+m:<24}{dp:>9.3f}{mt:>8.3f}│{e1:>9.3f}{c1:>12.3f}{e1/c1*100:>8.1f}%│"
              f"{e2:>9.3f}{c2:>12.3f}{e2/c2*100:>8.1f}%")

bar("S1 与 S2 的差异")
for sc,cn in [("text","文本"),("code","代码")]:
    print(f"\n【{cn}场景】")
    print(f"{'平台×模型':<24}{'S1碳':>9}{'S2碳':>9}{'S2/S1':>8}│{'S1成本':>9}{'S2成本':>9}{'差额':>9}{'差异率':>9}")
    for hw,m,d in CELL:
        j,t0 = d[sc]; r = cell(hw,j,t0)
        f1 = r["kwh"]*PS["S1"]["EF"]/r["Mt"]+r["cf_em"]; f2 = r["kwh"]*PS["S2"]["EF"]/r["Mt"]+r["cf_em"]
        base = (r["capex"]+r["opex"])/r["Mt"]
        c1 = r["kwh"]*PS["S1"]["price"]/r["Mt"]+base; c2 = r["kwh"]*PS["S2"]["price"]/r["Mt"]+base
        print(f"{hw+' × '+m:<24}{f1:>9.4f}{f2:>9.4f}{f2/f1:>7.2f}×│{c1:>9.3f}{c2:>9.3f}"
              f"{c1-c2:>+9.4f}{(c1/c2-1)*100:>+8.2f}%")

bar("排序")
for sc,cn in [("text","文本"),("code","代码")]:
    for k in ["S1","S2"]:
        rk = {}
        for hw,m,d in CELL:
            j,t0 = d[sc]; r = cell(hw,j,t0)
            rk[hw] = (r["en"],
                      r["kwh"]*PS[k]["EF"]/r["Mt"]+r["cf_em"],
                      r["kwh"]*PS[k]["price"]/r["Mt"]+(r["capex"]+r["opex"])/r["Mt"])
        for i,lab in enumerate(["能耗","碳足迹","成本"]):
            print(f"  {cn}/{k} {lab:<4}: " + "  <  ".join(sorted(rk, key=lambda x: rk[x][i])))
    print()
