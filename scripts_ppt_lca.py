#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于PPT实测 J/token 的系统级百万Token能耗/碳/成本核算
关键修正：PPT的 J/token 由 Zeus 经 NVML 读取，为 GPU-only；
本脚本补上 非GPU部件 + PSU损耗 + PUE，得到真正的"系统级"与"全站"能耗。
"""
import json, os
B = os.path.dirname(os.path.abspath(__file__))
M = json.load(open(f"{B}/data/ppt_measurements.json", encoding="utf-8"))
S = json.load(open(f"{B}/data/scenario.json", encoding="utf-8"))
OV, DC, EC = S["system_overhead"], S["datacenter"], S["economics"]

PLATFORM = "DGX-H200"          # PPT平台推断值，可切换
PNG = OV["P_nonGPU_kW"][PLATFORM]
PSU = OV["PSU_efficiency"]


def per_1M(j_tok, tok_s, pue=None, ef=None, price=None):
    """返回每百万Token的能耗链路。tok_s 为 None 时只能给 GPU 侧。"""
    pue = pue if pue is not None else DC["PUE_baseline"]
    ef = ef if ef is not None else DC["grid_EF_kgCO2e_per_kWh"]
    price = price if price is not None else EC["electricity_price_CNY_per_kWh"]
    E_gpu = j_tok / 3.6                                   # kWh/1M tok, GPU-only
    r = {"E_gpu": E_gpu}
    if tok_s:
        t_h = (1e6 / tok_s) / 3600                        # 产出1M tok 的机时 h
        E_sys = (E_gpu + PNG * t_h) / PSU                 # 整机IT侧
        r.update(t_h=t_h, E_sys=E_sys, overhead=E_sys / E_gpu,
                 E_site=E_sys * pue, CF=E_sys * pue * ef, C_elec=E_sys * pue * price)
    return r


def hdr(t): print("\n" + t + "\n" + "─" * len(t) * 2)

# ── 1. 系统级修正 ────────────────────────────────────────────
hdr(f"表A 系统级修正（平台假定 {PLATFORM}，非GPU {PNG} kW，PSU {PSU:.0%}，PUE {DC['PUE_baseline']}）")
print(f"{'模型/场景':<28}{'J/tok':>7}{'tok/s':>7}{'GPU能耗':>9}{'整机能耗':>10}{'放大':>7}{'全站能耗':>10}{'碳kg':>8}{'电费元':>8}")
print(f"{'':<28}{'':>7}{'':>7}{'kWh/1Mtok':>9}{'kWh/1Mtok':>10}{'倍':>7}{'kWh/1Mtok':>10}{'/1Mtok':>8}{'/1Mtok':>8}")
rows = []
for c in M["configs_with_throughput"]:
    r = per_1M(c["j_per_tok"], c["tok_s"])
    lab = f"{c['model']}/{c['scene']}" + (f"[{c['engine']}]" if c.get("engine") else "")
    rows.append((lab, c, r))
    print(f"{lab:<28}{c['j_per_tok']:>7.2f}{c['tok_s']:>7}{r['E_gpu']:>9.3f}{r['E_sys']:>10.3f}"
          f"{r['overhead']:>7.2f}{r['E_site']:>10.3f}{r['CF']:>8.4f}{r['C_elec']:>8.3f}")

# ── 2. 只有 J/tok 的模型 ────────────────────────────────────
hdr("表B 仅有 J/token 的模型：GPU侧百万Token能耗（缺吞吐，无法做系统级修正）")
print(f"{'模型':<18}{'参数':>7}{'精度':>6}{'架构':>6}   文本    代码   多模态   (kWh/1M tok, GPU-only)")
for k, v in M["j_per_token_best"].items():
    if k.startswith("_"): continue
    f = lambda x: f"{x/3.6:>6.3f}" if x else "     —"
    print(f"{k:<18}{str(v['params'] or '—'):>7}{v['precision']:>6}{v['arch']:>6}  "
          f"{f(v['text'])} {f(v['code'])} {f(v['image'])}")

# ── 3. 引擎对比 ─────────────────────────────────────────────
hdr("表C 推理引擎更换的全口径影响（DeepSeek-V4, BS=128）")
print(f"{'场景':<6}{'引擎':<8}{'吞吐':>7}{'GPU能耗':>9}{'整机能耗':>10}{'放大倍':>8}{'碳':>9}{'电费':>8}")
for sc in ["text", "code"]:
    sub = [c for c in M["configs_with_throughput"] if c["model"] == "DeepSeek-V4" and c["scene"] == sc]
    vs = []
    for c in sub:
        r = per_1M(c["j_per_tok"], c["tok_s"]); vs.append(r)
        print(f"{sc:<6}{c['engine']:<8}{c['tok_s']:>7}{r['E_gpu']:>9.3f}{r['E_sys']:>10.3f}"
              f"{r['overhead']:>8.2f}{r['CF']:>9.4f}{r['C_elec']:>8.3f}")
    a, b = vs
    print(f"{'':6}{'降幅':<8}{'':>7}{(1-b['E_gpu']/a['E_gpu'])*100:>8.0f}%{(1-b['E_sys']/a['E_sys'])*100:>9.0f}%"
          f"{'':>8}{(1-b['CF']/a['CF'])*100:>8.0f}%{(1-b['C_elec']/a['C_elec'])*100:>7.0f}%")

# ── 4. 全生命周期（含隐含碳与折旧）───────────────────────────
hdr("表D 全生命周期：百万Token的碳与成本拆解")
P = json.load(open(f"{B}/data/platforms.json", encoding="utf-8"))
plat = next(x for x in P["platforms"] if x["id"] == PLATFORM)
mass = S["embodied"]["mass_override_kg"].get(PLATFORM) or plat["chassis_mass_kg"]
emb_total = mass * S["embodied"]["k_mat_kgCO2e_per_kg"]
capex = EC["capex_CNY"][PLATFORM]
SEC_Y = 3600 * 24 * 365
print(f"{'模型/场景':<28}{'运行碳':>8}{'隐含碳':>8}{'碳合计':>8}{'隐含%':>7}{'电费':>7}{'折旧':>8}{'运维':>7}{'成本合计':>9}")
for lab, c, r in rows:
    Mlife = c["tok_s"] * SEC_Y * EC["lifetime_years"] * EC["utilization"] / 1e6
    emb = emb_total / Mlife
    dep = capex / Mlife
    mnt = capex * EC["maintenance_rate_per_year"] * EC["lifetime_years"] / Mlife
    tot_c = r["CF"] + emb
    tot_m = r["C_elec"] + dep + mnt
    print(f"{lab:<28}{r['CF']:>8.4f}{emb:>8.4f}{tot_c:>8.4f}{emb/tot_c*100:>6.1f}%"
          f"{r['C_elec']:>7.3f}{dep:>8.3f}{mnt:>7.3f}{tot_m:>9.3f}")
print(f"\n（{PLATFORM}: 质量{mass}kg × {S['embodied']['k_mat_kgCO2e_per_kg']}kgCO2e/kg = {emb_total:.0f}kgCO2e；"
      f"购置{capex/1e4:.0f}万元；寿命{EC['lifetime_years']}年 @ 利用率{EC['utilization']:.0%}）")
