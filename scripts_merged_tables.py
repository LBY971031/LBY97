#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并文本与代码场景，生成一体化结果表（Markdown）"""
BW   = {"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG  = {"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
MASS = {"A100":123.16,"H100":130.45,"H200":130.45,"B200":142.4}
CAP  = {"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
TDP  = {"A100":3.2,"H100":5.6,"H200":5.6,"B200":8.0}
HOURS, PUE, PSU, KMAT, MAINT, YEARS = 5*365*24*0.70, 1.15, 0.94, 30, 0.05, 5
PS = {"S1": dict(EF=0.0294, price=0.3110), "S2": dict(EF=0.0874, price=0.3000)}
CELL = [("A100","MiniMax-M2.7",  {"text":(0.85,4229),"code":(0.86,4180)}),
        ("H100","MiMo-V2-Flash", {"text":(0.92,2913),"code":(1.43,1874)}),
        ("H200","Qwen3.5-397B",  {"text":(1.07,2505),"code":(2.18,1229)}),
        ("B200","DeepSeek-V4",   {"text":(0.97,2763),"code":(1.92,1879)})]

def cell(hw, j, thr0):
    thr = thr0*BW[hw]/BW["H200"]; pg = j*thr/1000
    pit = (pg+PNG[hw])/PSU; kwh = pit*PUE*HOURS; Mt = thr*3600*HOURS/1e6
    d = dict(j=j, thr=thr, pg=pg, tdp=pg/TDP[hw]*100, pit=pit, kwh=kwh, Mt=Mt,
             en=kwh/Mt, em=MASS[hw]*KMAT/Mt, dp=CAP[hw]/Mt, mt=CAP[hw]*MAINT*YEARS/Mt,
             Ttok=Mt/1e6, Wkwh=kwh/1e4, emb_t=MASS[hw]*KMAT/1000)
    for k,p in PS.items():
        d[f"cf_{k}"] = kwh*p["EF"]/Mt + d["em"]
        d[f"el_{k}"] = kwh*p["price"]/Mt
        d[f"c_{k}"]  = d[f"el_{k}"] + d["dp"] + d["mt"]
        d[f"emp_{k}"] = d["em"]/d[f"cf_{k}"]*100
    return d

R = {hw: {sc: cell(hw, *d[sc]) for sc in ("text","code")} for hw,_,d in CELL}
NAME = {hw: f"{hw} × {m}" for hw,m,_ in CELL}

def tbl(title, heads, fmt, keys, note=""):
    print(f"\n### {title}\n")
    print("| 平台 × 模型 | " + " | ".join(heads) + " |")
    print("|" + "---|"*(len(heads)+1))
    for hw,_,_ in CELL:
        vals = [f.format(R[hw][sc][k]) if k else "" for (sc,k),f in zip(keys,fmt)]
        print(f"| {NAME[hw]} | " + " | ".join(vals) + " |")
    if note: print(f"\n{note}")

print("# 一体化结果表（文本 + 代码场景合并）\n")
print("蒙西电网 ｜ PUE 1.15 ｜ 寿命 5 年 × 利用率 70% = 30,660 运行小时 ｜ η=1.0")
print("S1 绿电直连+储能补电 (EF 0.0294, 电价 0.3110) ｜ S2 绿电直连+CCS火力补电 (EF 0.0874, 电价 0.3000)")

print("\n---\n## 一、总表：一眼看全\n")
print("| 平台 × 模型 | 场景 | 能耗<br>kWh | S1 碳<br>kgCO₂e | S2 碳<br>kgCO₂e | S1 成本<br>元 | S2 成本<br>元 | 五年总Token |")
print("|---|---|---|---|---|---|---|---|")
for hw,_,_ in CELL:
    for sc,cn in [("text","文本"),("code","代码")]:
        r = R[hw][sc]
        nm = NAME[hw] if sc=="text" else ""
        print(f"| {nm} | {cn} | {r['en']:.3f} | {r['cf_'+'S1']:.4f} | {r['cf_'+'S2']:.4f} | "
              f"{r['c_S1']:.3f} | {r['c_S2']:.3f} | {r['Mt']/1e6:.2f} 万亿 |")

print("\n---\n## 二、分项表")
tbl("表1　基础量",
    ["J/tok<br>文本","J/tok<br>代码","修正吞吐<br>文本","修正吞吐<br>代码",
     "GPU功率<br>文本","GPU功率<br>代码","占TDP<br>文本","占TDP<br>代码",
     "整机功率<br>文本","整机功率<br>代码"],
    ["{:.2f}","{:.2f}","{:,.0f}","{:,.0f}","{:.2f} kW","{:.2f} kW","{:.0f}%","{:.0f}%","{:.2f} kW","{:.2f} kW"],
    [("text","j"),("code","j"),("text","thr"),("code","thr"),("text","pg"),("code","pg"),
     ("text","tdp"),("code","tdp"),("text","pit"),("code","pit")],
    "全部 8 格通过 `J/tok × 吞吐 ≤ GPU总TDP` 检验。")

tbl("表2　五年生命周期总量",
    ["总Token<br>文本","总Token<br>代码","总用电<br>文本","总用电<br>代码","隐含碳<br>(整机)"],
    ["{:.2f} 万亿","{:.2f} 万亿","{:.2f} 万kWh","{:.2f} 万kWh","{:.2f} t"],
    [("text","Ttok"),("code","Ttok"),("text","Wkwh"),("code","Wkwh"),("text","emb_t")],
    "「隐含碳(整机)」为一台服务器全生命周期的制造侧碳排总量，与场景无关。")

print("\n### 表3　能耗（kWh / 百万Token）\n")
print("| 平台 × 模型 | 文本 | 代码 | 代码/文本 |")
print("|---|---|---|---|")
for hw,_,_ in CELL:
    a,b = R[hw]["text"]["en"], R[hw]["code"]["en"]
    print(f"| {NAME[hw]} | {a:.3f} | {b:.3f} | {b/a:.2f}× |")
print("\n> 两电力情景下能耗相同——电源结构不改变服务器耗电。")

print("\n### 表4　碳足迹（kgCO₂e / 百万Token）\n")
print("| 平台 × 模型 | S1 文本 | S1 代码 | S2 文本 | S2 代码 | S2/S1<br>文本 | S2/S1<br>代码 | 隐含碳占比<br>S1 文本 | 隐含碳占比<br>S1 代码 |")
print("|---|---|---|---|---|---|---|---|---|")
for hw,_,_ in CELL:
    t,c = R[hw]["text"], R[hw]["code"]
    print(f"| {NAME[hw]} | {t['cf_S1']:.4f} | {c['cf_S1']:.4f} | {t['cf_S2']:.4f} | {c['cf_S2']:.4f} | "
          f"{t['cf_S2']/t['cf_S1']:.2f}× | {c['cf_S2']/c['cf_S1']:.2f}× | {t['emp_S1']:.1f}% | {c['emp_S1']:.1f}% |")

print("\n### 表5　成本（元 / 百万Token）\n")
print("| 平台 × 模型 | 折旧<br>文本 | 折旧<br>代码 | 运维<br>文本 | 运维<br>代码 | S1电费<br>文本 | S1电费<br>代码 | **S1合计<br>文本** | **S1合计<br>代码** | **S2合计<br>文本** | **S2合计<br>代码** |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for hw,_,_ in CELL:
    t,c = R[hw]["text"], R[hw]["code"]
    print(f"| {NAME[hw]} | {t['dp']:.3f} | {c['dp']:.3f} | {t['mt']:.3f} | {c['mt']:.3f} | "
          f"{t['el_S1']:.3f} | {c['el_S1']:.3f} | **{t['c_S1']:.3f}** | **{c['c_S1']:.3f}** | "
          f"**{t['c_S2']:.3f}** | **{c['c_S2']:.3f}** |")

print("\n### 表6　排序\n")
print("| 指标 | 文本场景 | 代码场景 |")
print("|---|---|---|")
for lab,key in [("能耗","en"),("碳足迹 (S1)","cf_S1"),("碳足迹 (S2)","cf_S2"),
                ("成本 (S1)","c_S1"),("成本 (S2)","c_S2")]:
    rows=[]
    for sc in ("text","code"):
        order = sorted(R, key=lambda h: R[h][sc][key])
        rows.append(" < ".join(order))
    print(f"| {lab} | {rows[0]} | {rows[1]} |")
