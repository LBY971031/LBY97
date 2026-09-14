#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成本按前期/中期/后期分阶段核算（等权情景，代码50%）"""
BW={"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG={"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
CAP={"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
HOURS,PUE,PSU,MAINT,YEARS=5*365*24*0.70,1.15,0.94,0.05,5
PS={"S1":dict(price=0.3110,nm="绿电直连+储能补电"),"S2":dict(price=0.3000,nm="绿电直连+CCS火力补电")}
CELL=[("A100","MiniMax-M2.7",{"text":(0.85,4229),"code":(0.86,4180)}),
      ("H100","MiMo-V2-Flash",{"text":(0.92,2913),"code":(1.43,1874)}),
      ("H200","Qwen3.5-397B",{"text":(1.07,2505),"code":(2.18,1229)}),
      ("B200","DeepSeek-V4",{"text":(0.97,2763),"code":(1.92,1879)})]
W=0.50
# 新增的分阶段参数
DC_BUILD = 8000     # 元/kW IT — 机房基础设施(土建+暖通+配电+UPS)单位造价，蒙西风冷+自然冷却
RESIDUAL = 0.10     # 五年后残值率(占购置价)
DISPOSAL = 0.02     # 报废处置费率(拆解+数据销毁+环保处理)

def base(hw,d):
    j=(1-W)*d["text"][0]+W*d["code"][0]
    thr=1/((1-W)/(d["text"][1]*BW[hw]/BW["H200"])+W/(d["code"][1]*BW[hw]/BW["H200"]))
    pg=j*thr/1000; pit=(pg+PNG[hw])/PSU
    return dict(j=j,thr=thr,pit=pit,psite=pit*PUE,
                kwh=pit*PUE*HOURS, Mt=thr*3600*HOURS/1e6)
R={hw:base(hw,d) for hw,_,d in CELL}
NM={hw:f"{hw} × {m}" for hw,m,_ in CELL}
HW=[h for h,_,_ in CELL]

def stages(hw,k):
    r=R[hw]; cap=CAP[hw]; M=r["Mt"]
    pre_srv = cap/M                                  # 前期-服务器购置
    pre_dc  = DC_BUILD*r["pit"]/M                    # 前期-机房基础设施
    mid_el  = r["kwh"]*PS[k]["price"]/M              # 中期-电费
    mid_om  = cap*MAINT*YEARS/M                      # 中期-运维
    post_ds = cap*DISPOSAL/M                         # 后期-报废处置
    post_rv = -cap*RESIDUAL/M                        # 后期-残值回收(负=收益)
    return dict(pre_srv=pre_srv,pre_dc=pre_dc,pre=pre_srv+pre_dc,
                mid_el=mid_el,mid_om=mid_om,mid=mid_el+mid_om,
                post_ds=post_ds,post_rv=post_rv,post=post_ds+post_rv,
                tot=pre_srv+pre_dc+mid_el+mid_om+post_ds+post_rv)

def md(t,h,rows,note=""):
    print(f"\n### {t}\n"); print("| "+" | ".join(h)+" |"); print("|"+"---|"*len(h))
    for r in rows: print("| "+" | ".join(r)+" |")
    if note: print(f"\n{note}")

print("# 成本的三阶段拆解（等权情景：文本50% : 代码50%）\n")
print("蒙西电网 ｜ PUE 1.15 ｜ 寿命 5 年 × 年利用率 70% = 30,660 运行小时\n")
md("阶段划分与参数",
   ["阶段","含义","本核算包含的科目","关键参数"],
   [["**前期**<br>投运前一次性","设备与基础设施的资本开支","服务器购置<br>机房基础设施分摊",
     f"购置价 140~360 万元/台<br>机房造价 {DC_BUILD:,} 元/kW IT（估）"],
    ["**中期**<br>五年运营期","随运行持续发生的支出","电费<br>运维（备件·人工·保修）",
     f"电价 S1 {PS['S1']['price']}／S2 {PS['S2']['price']} 元/kWh<br>年运维率 {MAINT:.0%} 购置价"],
    ["**后期**<br>退役处置","停机后的净支出（可为负）","报废处置<br>残值回收",
     f"处置费率 {DISPOSAL:.0%}（估）<br>五年残值率 {RESIDUAL:.0%}（估）"]],
   "> 电力接入配套（储能系统、CCS 机组）的投资在本模型中**通过购电价传导**，计入中期电费，\n"
   "> 而非数据中心的前期资本开支——对应「向电网/售电方购电」的商业模式。自建情形见文末讨论。")

for k in ["S1","S2"]:
    md(f"情景{k[-1]}　{PS[k]['nm']}　三阶段成本（元 / 百万Token）",
       ["平台 × 模型","前期<br>服务器购置","前期<br>机房设施","**前期小计**",
        "中期<br>电费","中期<br>运维","**中期小计**","后期<br>处置","后期<br>残值","**后期小计**","**总计**"],
       [[NM[h]]+[f"{s[x]:.3f}" if not x.startswith("p") or x in("pre_srv","pre_dc","post_ds","post_rv")
                 else f"**{s[x]:.3f}**" for x in
                 ["pre_srv","pre_dc","pre","mid_el","mid_om","mid","post_ds","post_rv","post","tot"]]
        for h in HW for s in [stages(h,k)]])

for k in ["S1","S2"]:
    md(f"情景{k[-1]}　三阶段占比",
       ["平台 × 模型","前期占比","中期占比","后期占比","其中电费占比"],
       [[NM[h],f"**{s['pre']/s['tot']*100:.1f}%**",f"{s['mid']/s['tot']*100:.1f}%",
         f"{s['post']/s['tot']*100:+.1f}%",f"{s['mid_el']/s['tot']*100:.2f}%"]
        for h in HW for s in [stages(h,k)]])

md("五年生命周期绝对值（万元 / 台）",
   ["平台 × 模型","前期<br>购置","前期<br>机房","中期<br>S1电费","中期<br>S2电费","中期<br>运维",
    "后期<br>处置","后期<br>残值","**S1总计**","**S2总计**"],
   [[NM[h],f"{CAP[h]/1e4:.0f}",f"{DC_BUILD*R[h]['pit']/1e4:.1f}",
     f"{R[h]['kwh']*PS['S1']['price']/1e4:.1f}",f"{R[h]['kwh']*PS['S2']['price']/1e4:.1f}",
     f"{CAP[h]*MAINT*YEARS/1e4:.0f}",f"{CAP[h]*DISPOSAL/1e4:.1f}",f"−{CAP[h]*RESIDUAL/1e4:.0f}",
     f"**{(CAP[h]*(1+MAINT*YEARS+DISPOSAL-RESIDUAL)+DC_BUILD*R[h]['pit']+R[h]['kwh']*PS['S1']['price'])/1e4:.1f}**",
     f"**{(CAP[h]*(1+MAINT*YEARS+DISPOSAL-RESIDUAL)+DC_BUILD*R[h]['pit']+R[h]['kwh']*PS['S2']['price'])/1e4:.1f}**"]
    for h in HW])

# 自建储能的敏感度
print("\n### 若数据中心自建储能（前期自持而非购电传导）\n")
print("| 平台 × 模型 | 全站功率 | 日补电量 | 所需储能容量 | 储能投资<br>@1000元/kWh | 占前期比重 |")
print("|---|---|---|---|---|---|")
for h in HW:
    ps=R[h]["psite"]; daily=ps*24*0.32; cap_kwh=daily; inv=cap_kwh*1000
    pre_abs=CAP[h]+DC_BUILD*R[h]["pit"]
    print(f"| {NM[h]} | {ps:.2f} kW | {daily:.1f} kWh | {cap_kwh:.0f} kWh | {inv/1e4:.2f} 万元 | {inv/pre_abs*100:.2f}% |")
