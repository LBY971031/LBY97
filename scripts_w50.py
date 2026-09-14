#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等权情景（代码Token占比50%）完整结果表"""
BW={"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG={"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
MASS={"A100":123.16,"H100":130.45,"H200":130.45,"B200":142.4}
CAP={"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
TDP={"A100":3.2,"H100":5.6,"H200":5.6,"B200":8.0}
HOURS,PUE,PSU,KMAT,MAINT,YEARS=5*365*24*0.70,1.15,0.94,30,0.05,5
PS={"S1":dict(EF=0.0294,price=0.3110,nm="绿电直连+储能补电"),
    "S2":dict(EF=0.0874,price=0.3000,nm="绿电直连+CCS火力补电")}
CELL=[("A100","MiniMax-M2.7",{"text":(0.85,4229),"code":(0.86,4180)}),
      ("H100","MiMo-V2-Flash",{"text":(0.92,2913),"code":(1.43,1874)}),
      ("H200","Qwen3.5-397B",{"text":(1.07,2505),"code":(2.18,1229)}),
      ("B200","DeepSeek-V4",{"text":(0.97,2763),"code":(1.92,1879)})]
W=0.50   # 代码Token占比

def cell(hw,j,t0):
    thr=t0*BW[hw]/BW["H200"]; pg=j*thr/1000
    pit=(pg+PNG[hw])/PSU; kwh=pit*PUE*HOURS; Mt=thr*3600*HOURS/1e6
    d=dict(j=j,thr=thr,pg=pg,tdp=pg/TDP[hw]*100,pit=pit,psite=pit*PUE,
           Mt=Mt,Ttok=Mt/1e6,Wkwh=kwh/1e4,en=kwh/Mt,
           em=MASS[hw]*KMAT/Mt,dp=CAP[hw]/Mt,mt=CAP[hw]*MAINT*YEARS/Mt)
    for k,p in PS.items():
        d[f"op_{k}"]=kwh*p["EF"]/Mt; d[f"cf_{k}"]=d[f"op_{k}"]+d["em"]
        d[f"el_{k}"]=kwh*p["price"]/Mt; d[f"c_{k}"]=d[f"el_{k}"]+d["dp"]+d["mt"]
    return d
RAW={hw:{sc:cell(hw,*d[sc]) for sc in ("text","code")} for hw,_,d in CELL}
# 加权（口径A：Token占比）
R={hw:{k:(1-W)*RAW[hw]["text"][k]+W*RAW[hw]["code"][k] for k in RAW[hw]["text"]} for hw,_,_ in CELL}
# 修正：吞吐须用调和平均（同样Token数下两场景耗时相加），功率与总量随之重算
for hw,_,_ in CELL:
    t,c=RAW[hw]["text"],RAW[hw]["code"]
    thr=1/((1-W)/t["thr"]+W/c["thr"])                 # 调和平均
    pg=R[hw]["j"]*thr/1000
    pit=(pg+PNG[hw])/PSU; psite=pit*PUE
    R[hw].update(thr=thr,pg=pg,tdp=pg/TDP[hw]*100,pit=pit,psite=psite,
                 Ttok=thr*3600*HOURS/1e12, Wkwh=psite*HOURS/1e4)
NM={hw:f"{hw} × {m}" for hw,m,_ in CELL}
HW=[h for h,_,_ in CELL]

def md(title,heads,rows,note=""):
    print(f"\n### {title}\n")
    print("| "+" | ".join(heads)+" |"); print("|"+"---|"*len(heads))
    for r in rows: print("| "+" | ".join(r)+" |")
    if note: print(f"\n{note}")

print("# 等权情景结果表（文本 50% : 代码 50%，按 Token 占比加权）\n")
print("**核算边界**：蒙西电网 ｜ PUE 1.15 ｜ 寿命 5 年 × 年利用率 70% = 30,660 运行小时 ｜ PSU 效率 0.94 ｜ η=1.0")
print("\n**两种电力接入情景**\n")
print("| 情景 | 构成 | 等效排放因子 kgCO₂e/kWh | 等效电价 元/kWh |")
print("|---|---|---|---|")
print("| **S1** | 绿电直连 68% + 储能补电 32% | 0.0294 | 0.3110 |")
print("| **S2** | 绿电直连 68% + CCS火力补电 32% | 0.0874 | 0.3000 |")

md("表1　加权后的运行基础量",
   ["平台 × 模型","加权 J/tok","加权吞吐<br>tok/s","GPU功率<br>kW","占TDP","整机功率<br>kW","全站功率<br>kW"],
   [[NM[h],f"{R[h]['j']:.3f}",f"{R[h]['thr']:,.0f}",f"{R[h]['pg']:.2f}",
     f"{R[h]['tdp']:.0f}%",f"{R[h]['pit']:.2f}",f"{R[h]['psite']:.2f}"] for h in HW],
   "> **加权方式**：J/tok 与各项单位指标按 Token 占比取**算术平均**；\n"
   "> 吞吐取**调和平均** `1/thr = 0.5/thr文本 + 0.5/thr代码`——因为产出同样多的 Token，两场景的耗时是相加的。\n"
   "> 功率 = 加权 J/tok × 加权吞吐，保证 `总用电 ÷ 总Token` 与表3的能耗完全一致。")

md("表2　五年生命周期总量",
   ["平台 × 模型","五年总Token","五年总用电<br>万kWh","整机隐含碳<br>tCO₂e","购置价<br>万元","五年运维<br>万元"],
   [[NM[h],f"{R[h]['Ttok']:.3f} 万亿",f"{R[h]['Wkwh']:.2f}",f"{MASS[h]*KMAT/1000:.2f}",
     f"{CAP[h]/1e4:.0f}",f"{CAP[h]*MAINT*YEARS/1e4:.0f}"] for h in HW])

md("表3　能耗（kWh / 百万Token）",
   ["平台 × 模型","全站能耗","相对最优","占比说明"],
   [[NM[h],f"**{R[h]['en']:.3f}**",f"{R[h]['en']/min(R[x]['en'] for x in HW)*100:.0f}",
     "最优" if R[h]['en']==min(R[x]['en'] for x in HW) else f"高 {R[h]['en']/min(R[x]['en'] for x in HW)*100-100:.0f}%"] for h in HW],
   "> 两种电力情景下能耗相同——电源结构不改变服务器耗电量。")

for k,p in PS.items():
    md(f"表4-{k[-1]}　碳足迹（kgCO₂e / 百万Token）— 情景{k[-1]} {p['nm']}",
       ["平台 × 模型","运行碳","隐含碳","**合计**","隐含碳占比","相对最优"],
       [[NM[h],f"{R[h]['op_'+k]:.4f}",f"{R[h]['em']:.4f}",f"**{R[h]['cf_'+k]:.4f}**",
         f"{R[h]['em']/R[h]['cf_'+k]*100:.1f}%",
         f"{R[h]['cf_'+k]/min(R[x]['cf_'+k] for x in HW)*100:.0f}"] for h in HW])

for k,p in PS.items():
    md(f"表5-{k[-1]}　成本（元 / 百万Token）— 情景{k[-1]} {p['nm']}",
       ["平台 × 模型","电费","折旧","运维","**合计**","电费占比","折旧占比","相对最优"],
       [[NM[h],f"{R[h]['el_'+k]:.3f}",f"{R[h]['dp']:.3f}",f"{R[h]['mt']:.3f}",
         f"**{R[h]['c_'+k]:.3f}**",f"{R[h]['el_'+k]/R[h]['c_'+k]*100:.1f}%",
         f"{R[h]['dp']/R[h]['c_'+k]*100:.1f}%",
         f"{R[h]['c_'+k]/min(R[x]['c_'+k] for x in HW)*100:.0f}"] for h in HW])

md("表6　S1 与 S2 对照",
   ["平台 × 模型","S1 碳","S2 碳","S2/S1","S1 成本","S2 成本","成本差","成本差异率"],
   [[NM[h],f"{R[h]['cf_S1']:.4f}",f"{R[h]['cf_S2']:.4f}",f"{R[h]['cf_S2']/R[h]['cf_S1']:.2f}×",
     f"{R[h]['c_S1']:.3f}",f"{R[h]['c_S2']:.3f}",f"+{R[h]['c_S1']-R[h]['c_S2']:.4f}",
     f"+{(R[h]['c_S1']/R[h]['c_S2']-1)*100:.2f}%"] for h in HW])

md("表7　三项指标排序",
   ["指标","第1","第2","第3","第4"],
   [[lab]+[f"{h}<br>{R[h][k]:.4f}" if "碳" in lab else f"{h}<br>{R[h][k]:.3f}"
           for h in sorted(HW,key=lambda x:R[x][k])]
    for lab,k in [("能耗","en"),("碳足迹 S1","cf_S1"),("碳足迹 S2","cf_S2"),
                  ("成本 S1","c_S1"),("成本 S2","c_S2")]])

md("表8　与两个端点场景的对照",
   ["平台 × 模型","指标","纯文本<br>(w=0)","**等权<br>(w=50%)**","纯代码<br>(w=100%)","代码/文本"],
   [x for h in HW for x in
    [[NM[h],"能耗 kWh",f"{RAW[h]['text']['en']:.3f}",f"**{R[h]['en']:.3f}**",
      f"{RAW[h]['code']['en']:.3f}",f"{RAW[h]['code']['en']/RAW[h]['text']['en']:.2f}×"],
     ["","碳 S1",f"{RAW[h]['text']['cf_S1']:.4f}",f"**{R[h]['cf_S1']:.4f}**",
      f"{RAW[h]['code']['cf_S1']:.4f}",f"{RAW[h]['code']['cf_S1']/RAW[h]['text']['cf_S1']:.2f}×"],
     ["","成本 S1",f"{RAW[h]['text']['c_S1']:.3f}",f"**{R[h]['c_S1']:.3f}**",
      f"{RAW[h]['code']['c_S1']:.3f}",f"{RAW[h]['code']['c_S1']/RAW[h]['text']['c_S1']:.2f}×"]]])
