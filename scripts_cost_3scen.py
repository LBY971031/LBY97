#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三种电力接入情景下的成本三阶段拆解（等权，代码50%）"""
BW={"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG={"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
CAP={"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
HOURS,PUE,PSU,MAINT,YEARS=5*365*24*0.70,1.15,0.94,0.05,5
RESIDUAL,DISPOSAL=0.10,0.02
PS={"S0":dict(price=0.3500,EF=0.7000,nm="蒙西常规电网（现状）"),
    "S1":dict(price=0.3110,EF=0.0294,nm="绿电直连+储能补电"),
    "S2":dict(price=0.3000,EF=0.0874,nm="绿电直连+CCS火力补电")}
SK=["S0","S1","S2"]
CELL=[("A100","MiniMax-M2.7",{"text":(0.85,4229),"code":(0.86,4180)}),
      ("H100","MiMo-V2-Flash",{"text":(0.92,2913),"code":(1.43,1874)}),
      ("H200","Qwen3.5-397B",{"text":(1.07,2505),"code":(2.18,1229)}),
      ("B200","DeepSeek-V4",{"text":(0.97,2763),"code":(1.92,1879)})]
W=0.50

def base(hw,d):
    j=(1-W)*d["text"][0]+W*d["code"][0]
    thr=1/((1-W)/(d["text"][1]*BW[hw]/BW["H200"])+W/(d["code"][1]*BW[hw]/BW["H200"]))
    pit=(j*thr/1000+PNG[hw])/PSU
    return dict(j=j,thr=thr,pit=pit,psite=pit*PUE,kwh=pit*PUE*HOURS,Mt=thr*3600*HOURS/1e6)
R={hw:base(hw,d) for hw,_,d in CELL}
NM={hw:f"{hw} × {m}" for hw,m,_ in CELL}
HW=[h for h,_,_ in CELL]

def st(hw,k):
    r=R[hw];cap=CAP[hw];M=r["Mt"]
    pre=cap/M; el=r["kwh"]*PS[k]["price"]/M; om=cap*MAINT*YEARS/M
    ds=cap*DISPOSAL/M; rv=-cap*RESIDUAL/M
    return dict(pre=pre,el=el,om=om,mid=el+om,ds=ds,rv=rv,post=ds+rv,tot=pre+el+om+ds+rv)

def md(t,h,rows,note=""):
    print(f"\n### {t}\n");print("| "+" | ".join(h)+" |");print("|"+"---|"*len(h))
    for r in rows: print("| "+" | ".join(r)+" |")
    if note: print(f"\n{note}")

print("# 三种电力接入情景下的成本（等权：文本50% : 代码50%）\n")
print("蒙西电网区域 ｜ PUE 1.15 ｜ 寿命 5 年 × 年利用率 70% = 30,660 运行小时\n")

md("电力接入情景",
   ["情景","构成","综合到户电价<br>元/kWh","相对现状"],
   [["**S0 现状**<br>蒙西常规电网","全部电量取自公共电网","**0.3500**","—"],
    ["**S1**<br>绿电直连+储能补电","绿电直供 68% + 储能补电 32%","**0.3110**","−11.1%"],
    ["**S2**<br>绿电直连+CCS火力补电","绿电直供 68% + CCS火电 32%","**0.3000**","−14.3%"]],
   "> **S0 电价构成（蒙西大工业，110kV/35kV 接入）**：市场化电能量电价约 0.20~0.28（坑口煤火电成本低）\n"
   "> ＋ 输配电价约 0.08~0.12 ＋ 政府性基金及附加约 0.02~0.03，综合到户取 **0.35 元/kWh**。\n"
   "> 该值为**综合到户电价**，已含基本电费（按变压器容量或最大需量计收）与各项附加，故不再单列。\n"
   ">\n"
   "> **S1/S2 低于 S0 的原因**：绿电直连为专线物理直供，可规避或大幅减免公共电网的输配电价；\n"
   "> 且蒙西风电年利用小时 2800~3200h（全国约2200h），绿电 LCOE 本身就低于当地火电上网电价。")

md("阶段划分与参数",
   ["阶段","含义","科目","关键参数"],
   [["**前期**<br>投运前一次性","设备资本开支","服务器购置","购置价 140~360 万元/台"],
    ["**中期**<br>五年运营期","随运行持续发生","电费 + 运维","电价见上表<br>年运维率 5% 购置价"],
    ["**后期**<br>退役处置","停机后净支出（可为负）","报废处置<br>残值回收","处置费率 2%（估）<br>五年残值率 10%（估）"]])

for k in SK:
    md(f"情景{k[-1]}　{PS[k]['nm']}（元 / 百万Token）",
       ["平台 × 模型","**前期**<br>服务器购置","**中期**<br>电费+运维","后期<br>处置","后期<br>残值","**后期小计**","**总计**"],
       [[NM[h],f"**{s['pre']:.3f}**",f"**{s['mid']:.3f}**",f"{s['ds']:.3f}",f"{s['rv']:.3f}",
         f"**{s['post']:.3f}**",f"**{s['tot']:.3f}**"] for h in HW for s in [st(h,k)]])

md("三情景总成本对照（元 / 百万Token）",
   ["平台 × 模型","**S0 现状**","**S1 绿电+储能**","**S2 绿电+CCS**","S1 vs S0","S2 vs S0","S1 vs S2"],
   [[NM[h],f"**{a['tot']:.3f}**",f"**{b['tot']:.3f}**",f"**{c['tot']:.3f}**",
     f"{(b['tot']/a['tot']-1)*100:+.2f}%",f"{(c['tot']/a['tot']-1)*100:+.2f}%",
     f"{(b['tot']/c['tot']-1)*100:+.2f}%"]
    for h in HW for a,b,c in [(st(h,"S0"),st(h,"S1"),st(h,"S2"))]])

md("三情景的电费与占比",
   ["平台 × 模型","S0 电费","S1 电费","S2 电费","S0 电费占比","S1 电费占比","S2 电费占比"],
   [[NM[h]]+[f"{st(h,k)['el']:.3f}" for k in SK]+[f"{st(h,k)['el']/st(h,k)['tot']*100:.2f}%" for k in SK]
    for h in HW])

md("三阶段占比（以 S0 现状为例）",
   ["平台 × 模型","前期占比","中期占比","后期占比","非电费部分合计"],
   [[NM[h],f"**{s['pre']/s['tot']*100:.1f}%**",f"{s['mid']/s['tot']*100:.1f}%",
     f"{s['post']/s['tot']*100:+.1f}%",f"{(1-s['el']/s['tot'])*100:.1f}%"]
    for h in HW for s in [st(h,"S0")]])

md("五年生命周期绝对值（万元 / 台）",
   ["平台 × 模型","前期<br>购置","五年运维","S0 电费","S1 电费","S2 电费","后期<br>处置","后期<br>残值",
    "**S0 总计**","**S1 总计**","**S2 总计**"],
   [[NM[h],f"{CAP[h]/1e4:.0f}",f"{CAP[h]*MAINT*YEARS/1e4:.0f}"]+
    [f"{R[h]['kwh']*PS[k]['price']/1e4:.1f}" for k in SK]+
    [f"{CAP[h]*DISPOSAL/1e4:.1f}",f"−{CAP[h]*RESIDUAL/1e4:.0f}"]+
    [f"**{(CAP[h]*(1+MAINT*YEARS+DISPOSAL-RESIDUAL)+R[h]['kwh']*PS[k]['price'])/1e4:.1f}**" for k in SK]
    for h in HW])
