#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文本与代码场景的加权归一"""
BW={"A100":2039,"H100":3350,"H200":4800,"B200":8000}
PNG={"A100":1.9,"H100":2.3,"H200":2.3,"B200":2.6}
MASS={"A100":123.16,"H100":130.45,"H200":130.45,"B200":142.4}
CAP={"A100":1.4e6,"H100":2.4e6,"H200":3.0e6,"B200":3.6e6}
HOURS,PUE,PSU,KMAT,MAINT,YEARS=5*365*24*0.70,1.15,0.94,30,0.05,5
PS={"S1":dict(EF=0.0294,price=0.3110),"S2":dict(EF=0.0874,price=0.3000)}
CELL=[("A100","MiniMax-M2.7",{"text":(0.85,4229),"code":(0.86,4180)}),
      ("H100","MiMo-V2-Flash",{"text":(0.92,2913),"code":(1.43,1874)}),
      ("H200","Qwen3.5-397B",{"text":(1.07,2505),"code":(2.18,1229)}),
      ("B200","DeepSeek-V4",{"text":(0.97,2763),"code":(1.92,1879)})]

def cell(hw,j,t0):
    thr=t0*BW[hw]/BW["H200"]; pg=j*thr/1000
    pit=(pg+PNG[hw])/PSU; psite=pit*PUE
    kwh=psite*HOURS; Mt=thr*3600*HOURS/1e6
    d=dict(thr=thr,psite=psite,en=kwh/Mt,em=MASS[hw]*KMAT/Mt,
           dp=CAP[hw]/Mt,mt=CAP[hw]*MAINT*YEARS/Mt)
    for k,p in PS.items():
        d[f"cf_{k}"]=kwh*p["EF"]/Mt+d["em"]
        d[f"c_{k}"]=kwh*p["price"]/Mt+d["dp"]+d["mt"]
    return d
R={hw:{sc:cell(hw,*d[sc]) for sc in ("text","code")} for hw,_,d in CELL}
NM={hw:f"{hw} × {m}" for hw,m,_ in CELL}

def bar(t): print("\n"+"═"*100+f"\n{t}\n"+"═"*100)

bar("一、两种加权口径的区别（这一步不能搞错）")
print("""
口径A【Token占比】 每产出100万Token中，w_code 比例是代码Token
      X_综合 = (1−w)·X_文本 + w·X_代码           ← 对单位指标直接加权平均

口径B【机时占比】 机器运行时间中，f_code 比例在跑代码任务
      X_综合 = Σ(功率ᵢ·时间ᵢ) / Σ(吞吐ᵢ·时间ᵢ)    ← 先加总量再相除

两者不等价：同样的50:50，因两场景吞吐不同，折算出的Token占比会偏向高吞吐的那一边。
""")
print(f"{'平台×模型':<24}{'机时50:50→Token占比':>22}{'能耗(口径A)':>13}{'能耗(口径B)':>13}{'差异':>8}")
for hw,_,_ in CELL:
    t,c=R[hw]["text"],R[hw]["code"]
    wc=c["thr"]/(t["thr"]+c["thr"])                        # 机时50:50 折算的代码Token占比
    A=0.5*t["en"]+0.5*c["en"]                              # 口径A用50:50 Token占比
    B=(t["psite"]*0.5+c["psite"]*0.5)/((t["thr"]*0.5+c["thr"]*0.5)*3600/1e6)  # 口径B
    print(f"{NM[hw]:<24}{f'文本{1-wc:.0%} : 代码{wc:.0%}':>22}{A:>13.3f}{B:>13.3f}{(B/A-1)*100:>+7.1f}%")
print("\n→ 本课题功能单位是「百万Token」，应采用【口径A：Token占比】。下文均用口径A。")

bar("二、四组权重情景下的综合结果")
WSET=[("PPT测试配比", 0.889, "W1文本256请求×1024 vs W3代码1024请求×2048，Token上限比1:8"),
      ("通用对话为主", 0.30, "面向C端聊天/问答服务的典型画像"),
      ("等权",         0.50, "无业务先验时的中性假设"),
      ("代码助手为主", 0.70, "面向研发场景的典型画像")]
for nm,wc,why in WSET:
    print(f"\n▼ {nm}　代码Token占比 {wc:.0%}　（{why}）")
    print(f"  {'平台×模型':<24}{'能耗kWh':>9}{'S1碳':>9}{'S2碳':>9}{'S1成本':>9}{'S2成本':>9}")
    for hw,_,_ in CELL:
        t,c=R[hw]["text"],R[hw]["code"]
        f=lambda k:(1-wc)*t[k]+wc*c[k]
        print(f"  {NM[hw]:<24}{f('en'):>9.3f}{f('cf_S1'):>9.4f}{f('cf_S2'):>9.4f}"
              f"{f('c_S1'):>9.3f}{f('c_S2'):>9.3f}")
    for lab,k in [("能耗","en"),("碳(S1)","cf_S1"),("成本(S1)","c_S1")]:
        o=sorted(R,key=lambda h:(1-wc)*R[h]["text"][k]+wc*R[h]["code"][k])
        print(f"  {lab:<8}排序: " + " < ".join(o))

bar("三、★ 排序翻转的临界权重（最关键的输出）")
print("综合指标是权重 w 的线性函数：X(w) = X_文本 + w·(X_代码 − X_文本)")
print("两格排名互换处即为临界权重 w*。\n")
import itertools
for lab,k in [("能耗","en"),("碳足迹 S1","cf_S1"),("碳足迹 S2","cf_S2"),("成本 S1","c_S1"),("成本 S2","c_S2")]:
    print(f"【{lab}】")
    found=False
    for a,b in itertools.combinations([h for h,_,_ in CELL],2):
        ta,ca=R[a]["text"][k],R[a]["code"][k]; tb,cb=R[b]["text"][k],R[b]["code"][k]
        den=(ca-ta)-(cb-tb)
        if abs(den)<1e-12: continue
        w=(tb-ta)/den
        if 0<w<1:
            lead_lo = a if ta<tb else b
            lead_hi = b if ta<tb else a
            print(f"   w* = {w:>6.1%}  代码占比低于此值时 {lead_lo} 优于 {lead_hi}，高于则反转")
            found=True
    if not found: print("   区间内无翻转，排序与权重无关")

bar("四、线性系数表：任意权重可自行代入")
print("X(w) = a + b·w      （w = 代码Token占比，0≤w≤1）\n")
for lab,k in [("能耗 kWh","en"),("碳 S1","cf_S1"),("碳 S2","cf_S2"),("成本 S1","c_S1"),("成本 S2","c_S2")]:
    print(f"【{lab}】")
    print(f"   {'平台×模型':<24}{'a (截距=文本值)':>16}{'b (斜率=代码−文本)':>19}")
    for hw,_,_ in CELL:
        a=R[hw]["text"][k]; b=R[hw]["code"][k]-a
        print(f"   {NM[hw]:<24}{a:>16.4f}{b:>+19.4f}")
    print()

bar("五、多目标冲突：同一权重下三项指标的最优解不同")
print(f"{'代码Token占比':<14}{'能耗最优':>12}{'碳(S1)最优':>13}{'成本(S1)最优':>14}{'是否一致':>10}")
for wc in [0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0]:
    best={}
    for lab,k in [("en","en"),("cf","cf_S1"),("c","c_S1")]:
        best[lab]=min(R,key=lambda h:(1-wc)*R[h]["text"][k]+wc*R[h]["code"][k])
    same = "✅" if len(set(best.values()))==1 else "❌ 冲突"
    print(f"{wc:<14.0%}{best['en']:>12}{best['cf']:>13}{best['c']:>14}{same:>10}")
