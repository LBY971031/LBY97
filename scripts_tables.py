#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成三张核算输入参数表（服务器 / 模型 / 情景），并导出 CSV"""
import json, os, csv
B = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
M = json.load(open(f"{B}/data/ppt_measurements.json", encoding="utf-8"))
J = M["j_per_token_best"]
EC, EMB, OV, DC = S["economics"], S["embodied"], S["system_overhead"], S["datacenter"]

# ── 表1 服务器 ──────────────────────────────────────────────
GPU = {  # 单卡: TDP(W), 显存(GB), 带宽(GB/s), 支持精度
 "DGX-A100": ("A100 SXM", 400, 80,  2039, "BF16/FP16/TF32/INT8"),
 "DGX-H100": ("H100 SXM", 700, 80,  3350, "+FP8"),
 "DGX-H200": ("H200 SXM", 700, 141, 4800, "+FP8"),
 "DGX-B200": ("B200 SXM",1000, 180, 8000, "+FP8/FP4"),
}
ARCH = {"DGX-A100":"Ampere","DGX-H100":"Hopper","DGX-H200":"Hopper","DGX-B200":"Blackwell"}
MASS = {"DGX-A100":123.16,"DGX-H100":130.45,"DGX-H200":130.45,"DGX-B200":142.4}
MASS_NOTE={"DGX-H200":"原表“待核实”，按与H100同底座取值"}
NAME = {"DGX-A100":6.5,"DGX-H100":10.2,"DGX-H200":10.2,"DGX-B200":14.3}
POS  = {"DGX-A100":"基准平台","DGX-H100":"高性能计算","DGX-H200":"大显存推理","DGX-B200":"新一代AI计算"}
PAIR = {"DGX-A100":"MiniMax-M2.7","DGX-H100":"MiMo-V2-Flash",
        "DGX-H200":"Qwen3.5-397B","DGX-B200":"DeepSeek-V4"}

t1 = []
for pid in GPU:
    g, tdp, vram, bw, prec = GPU[pid]
    gtdp = tdp * 8 / 1000
    png  = OV["P_nonGPU_kW"][pid]
    mass = MASS[pid]
    t1.append({
      "平台": pid, "GPU架构": ARCH[pid], "GPU型号": g, "GPU数量": 8,
      "单卡显存GB": vram, "总显存GB": vram*8,
      "单卡显存带宽GB/s": bw, "整机聚合带宽TB/s": round(bw*8/1000, 1),
      "单卡TDP_W": tdp, "GPU总TDP_kW": round(gtdp,1),
      "支持精度": prec, "系统内存TB": 2,
      "铭牌最大功率kW": NAME[pid],
      "非GPU部件功率kW(估)": png, "PSU效率": OV["PSU_efficiency"],
      "实测整机功率kW": "待PDU实测",
      "整机质量kg": mass, "质量备注": MASS_NOTE.get(pid,"厂商标称"),
      "隐含碳kgCO2e(估)": round(mass*EMB["k_mat_kgCO2e_per_kg"]),
      "购置价万元(估)": round(EC["capex_CNY"][pid]/1e4),
      "平台定位": POS[pid], "配属模型": PAIR[pid],
    })

# ── 表2 模型 ────────────────────────────────────────────────
MODELS = [
 # id, 显示名, 总参B, 激活B, 架构, 专家, 精度, KV特性, 平台
 ("MiniMax-M2.7","MiniMax-M2.7 REAP",172,10,"MoE + REAP剪枝","—","BF16","标准","DGX-A100"),
 ("MiMo-V2-Flash","MiMo-V2-Flash",None,None,"MoE Hybrid SWA+GA","—","FP8 block","SWA滑窗，KV常数化","DGX-H100"),
 ("Qwen3.5-397B","Qwen 3.5-397B-A17B",397,17,"MoE","384E","FP8","标准","DGX-H200"),
 ("DeepSeek-V4","DeepSeek-V4-Flash",None,None,"MoE Hybrid CSA+HCA","—","FP4+FP8","CSA+HCA","DGX-B200"),
]
BYTES = {"BF16":2.0,"FP8":1.0,"FP8 block":1.0,"FP4+FP8":0.5}
t2 = []
for mid, disp, tot, act, arch, exp, prec, kv, plat in MODELS:
    w = round(tot*BYTES[prec]) if tot else None
    jt, jc = J[mid]["text"], J[mid]["code"]
    t2.append({
      "模型": disp, "总参数B": tot or "PPT未给出", "激活参数B": act or "PPT未给出",
      "架构": arch, "专家数": exp, "量化精度": prec,
      "权重显存GB": w or "待确认", "KV-Cache特性": kv,
      "配属平台": plat, "平台总显存GB": GPU[plat][2]*8,
      "显存占用率": f"{w/(GPU[plat][2]*8)*100:.0f}%" if w else "待确认",
      "PPT_J/tok_文本": jt, "PPT_J/tok_代码": jc,
      "跨场景放大": round(jc/jt, 2),
      "GPU侧kWh/百万tok_文本": round(jt/3.6, 3),
      "GPU侧kWh/百万tok_代码": round(jc/3.6, 3),
      "多模态支持": "否（PPT标注文·代）",
      "实测吞吐tok/s": "待实测", "实测TTFT_ms": "待实测",
      "实测TPOT_ms": "待实测", "实测GPU利用率%": "待实测",
      "有效Token率η": "待实测",
    })

# ── 表3 情景与核算参数 ──────────────────────────────────────
t3 = [
 ("能耗","PUE-先进液冷","",DC["PUE_scenarios"]["先进液冷"],"—","情景值","全站能耗 = 整机能耗 × PUE"),
 ("能耗","PUE-良好风冷(基准)","",DC["PUE_scenarios"]["良好风冷"],"—","情景值","同上"),
 ("能耗","PUE-一般机房","",DC["PUE_scenarios"]["一般机房"],"—","情景值","同上"),
 ("能耗","非GPU部件功率","kW","见表1","部件估算","⚠️待PDU实测","GPU-only→整机的修正项"),
 ("能耗","PSU效率","—",OV["PSU_efficiency"],"80Plus Titanium典型","估计值","整机功率 = (P_GPU+P_nonGPU)/η_PSU"),
 ("碳","电网因子-绿电为主","kgCO2e/kWh",DC["grid_EF_scenarios"]["绿电为主"],"—","情景值","运行碳 = 全站能耗 × EF"),
 ("碳","电网因子-全国均值(基准)","kgCO2e/kWh",DC["grid_EF_scenarios"]["全国电网均值"],DC["grid_EF_source"],"权威值","同上"),
 ("碳","电网因子-煤电密集","kgCO2e/kWh",DC["grid_EF_scenarios"]["煤电密集区"],"—","情景值","同上"),
 ("碳","材料碳强度 k_mat","kgCO2e/kg",EMB["k_mat_kgCO2e_per_kg"],f"区间{EMB['k_mat_range']}","⚠️估计值","隐含碳 = 整机质量 × k_mat"),
 ("成本","工业电价","元/kWh",EC["electricity_price_CNY_per_kWh"],"IDC综合电价","可调","电费 = 全站能耗 × 电价"),
 ("成本","设备寿命","年",EC["lifetime_years"],"行业惯例","可调","折旧分母"),
 ("成本","年利用率","—",EC["utilization"],"行业惯例","⚠️敏感参数","寿命内Token数 = 吞吐×31536000×寿命×利用率"),
 ("成本","年运维率","占购置价",EC["maintenance_rate_per_year"],"行业惯例","可调","运维 = 购置价×运维率×寿命/寿命内Token数"),
 ("负载","W1文本-请求数","",M["workloads"]["W1_text"]["requests"],"PPT幻灯片5","PPT给定","lm-arena-chat"),
 ("负载","W1文本-max_output","tok",M["workloads"]["W1_text"]["max_output"],"PPT幻灯片5","PPT给定","同上"),
 ("负载","W1文本-批大小","",256,"沿用PPT","建议值","四台一致"),
 ("负载","W3代码-请求数","",M["workloads"]["W3_code"]["requests"],"PPT幻灯片5","PPT给定","sourcegraph-fim"),
 ("负载","W3代码-max_output","tok",M["workloads"]["W3_code"]["max_output"],"PPT幻灯片5","PPT给定","同上"),
 ("负载","W3代码-批大小","",128,"显存约束","⚠️必须降至128","640GB平台跑不了bs=256"),
 ("测量栈","推理引擎","",M["measurement_stack"]["engine"],"PPT幻灯片6","必须一致","否则PPT锚定行失效"),
 ("测量栈","能耗测量库","",M["measurement_stack"]["energy_lib"],"PPT幻灯片6","必须一致","GPU-only口径"),
 ("测量栈","Benchmark框架","",M["measurement_stack"]["benchmark"],"PPT幻灯片6","必须一致","—"),
 ("测量栈","Tokenizer","",M["measurement_stack"]["tokenizer"],"PPT幻灯片6","必须一致","影响token计数"),
]

# ── 导出 CSV ────────────────────────────────────────────────
os.makedirs(f"{B}/data/tables", exist_ok=True)
for name, rows in [("表1-服务器基本参数", t1), ("表2-模型基本参数", t2)]:
    with open(f"{B}/data/tables/{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
with open(f"{B}/data/tables/表3-核算情景参数.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f); w.writerow(["用途","参数","单位","取值","来源","状态","进入的计算"]); w.writerows(t3)

for n, r in [("表1 服务器", t1), ("表2 模型", t2)]:
    print(f"{n}: {len(r)} 行 × {len(r[0])} 列")
print(f"表3 情景: {len(t3)} 行 × 7 列")
print("→ data/tables/ 下已导出三份 CSV")
