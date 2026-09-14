#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绿色Token生命周期核算引擎
功能单位: 1,000,000 有效Token (1M effective tokens)
边界: 运行侧(推理用电 × PUE) + 隐含侧(制造/运输/废弃, 质量法分摊)
"""
import json, os, itertools

BASE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(BASE, "data/platforms.json"), encoding="utf-8"))
S = json.load(open(os.path.join(BASE, "data/scenario.json"), encoding="utf-8"))

SEC_PER_YEAR = 3600 * 24 * 365


def compute(pid, pue=None, ef=None):
    """返回单台整机、单位百万有效Token的能耗/碳/成本明细"""
    plat = next(x for x in P["platforms"] if x["id"] == pid)
    wl = S["workload"][pid]
    eta = S["quality"][pid]
    dc, ec, emb = S["datacenter"], S["economics"], S["embodied"]

    pue = pue if pue is not None else dc["PUE_baseline"]
    ef = ef if ef is not None else dc["grid_EF_kgCO2e_per_kWh"]

    # --- 有效吞吐 ---
    thr_raw = wl["throughput_tok_s"]              # 原始输出Token/s
    thr_eff = thr_raw * eta                       # 有效Token/s

    # --- 能耗 ---
    p_it = plat["max_input_power_kW"] * wl["load_factor"]   # IT侧实际功率 kW
    t_1M = 1e6 / thr_eff                                     # 产出1M有效Token耗时 s
    E_it = p_it * t_1M / 3600                                # IT能耗 kWh/1M tok
    E_site = E_it * pue                                      # 全站能耗 kWh/1M tok

    # --- 运行碳 ---
    CF_op = E_site * ef                                      # kgCO2e/1M tok

    # --- 隐含碳 ---
    mass = emb["mass_override_kg"].get(pid) or plat["chassis_mass_kg"]
    CF_total_emb = mass * emb["k_mat_kgCO2e_per_kg"]         # kgCO2e/台(全生命周期制造侧)
    Mtok_life = thr_eff * SEC_PER_YEAR * ec["lifetime_years"] * ec["utilization"] / 1e6
    CF_emb = CF_total_emb / Mtok_life                        # kgCO2e/1M tok

    # --- 成本 ---
    capex = ec["capex_CNY"][pid]
    C_elec = E_site * ec["electricity_price_CNY_per_kWh"]
    C_dep = capex / Mtok_life
    C_maint = capex * ec["maintenance_rate_per_year"] * ec["lifetime_years"] / Mtok_life

    return {
        "id": pid, "model": plat["model_under_test"], "mass_kg": mass,
        "thr_raw": thr_raw, "eta": eta, "thr_eff": thr_eff,
        "p_it_kW": p_it, "t_1M_s": t_1M,
        "E_it": E_it, "E_site": E_site,
        "CF_op": CF_op, "CF_emb": CF_emb, "CF_tot": CF_op + CF_emb,
        "emb_share": (CF_op + CF_emb) and CF_emb / (CF_op + CF_emb) * 100,
        "Mtok_life": Mtok_life,
        "C_elec": C_elec, "C_dep": C_dep, "C_maint": C_maint,
        "C_tot": C_elec + C_dep + C_maint,
    }


def md_table(rows, cols, headers, fmts):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(f.format(r[c]) for c, f in zip(cols, fmts)) + " |")
    return "\n".join(out)


def main():
    ids = [p["id"] for p in P["platforms"]]
    rows = [compute(i) for i in ids]
    L = []
    A = L.append

    A("# 绿色Token生命周期核算结果（基准情景）\n")
    A(f"功能单位：**1,000,000 有效Token** ｜ PUE={S['datacenter']['PUE_baseline']} ｜ "
      f"电网因子={S['datacenter']['grid_EF_kgCO2e_per_kWh']} kgCO2e/kWh ｜ "
      f"电价={S['economics']['electricity_price_CNY_per_kWh']} 元/kWh ｜ "
      f"寿命={S['economics']['lifetime_years']}年 ｜ 利用率={S['economics']['utilization']:.0%}\n")
    A("> ⚠️ 吞吐、实测功率系数、购置价、材料碳强度当前为占位值，结论为**方法学演示**，"
      "须用实测数据替换后方可引用。\n")

    A("\n## 表1 能耗\n")
    A(md_table(rows, ["id", "model", "thr_eff", "p_it_kW", "t_1M_s", "E_it", "E_site"],
               ["平台", "模型", "有效吞吐 tok/s", "IT功率 kW", "产出1M tok耗时 s",
                "IT能耗 kWh/1M tok", "全站能耗 kWh/1M tok"],
               ["{}", "{}", "{:,.0f}", "{:.2f}", "{:,.0f}", "{:.3f}", "{:.3f}"]))

    A("\n## 表2 碳足迹\n")
    A(md_table(rows, ["id", "CF_op", "CF_emb", "CF_tot", "emb_share"],
               ["平台", "运行碳 kgCO2e/1M tok", "隐含碳 kgCO2e/1M tok",
                "合计 kgCO2e/1M tok", "隐含碳占比 %"],
               ["{}", "{:.4f}", "{:.4f}", "{:.4f}", "{:.1f}"]))

    A("\n## 表3 成本（元/百万有效Token）\n")
    A(md_table(rows, ["id", "C_elec", "C_dep", "C_maint", "C_tot", "Mtok_life"],
               ["平台", "电费", "设备折旧", "运维", "合计", "寿命内产出 百万Token"],
               ["{}", "{:.3f}", "{:.3f}", "{:.3f}", "{:.3f}", "{:,.0f}"]))

    # 相对基准
    base = rows[0]
    A("\n## 表4 相对基准平台(DGX A100 = 100)\n")
    rel = [{"id": r["id"],
            "e": r["E_site"] / base["E_site"] * 100,
            "c": r["CF_tot"] / base["CF_tot"] * 100,
            "m": r["C_tot"] / base["C_tot"] * 100} for r in rows]
    A(md_table(rel, ["id", "e", "c", "m"], ["平台", "能耗指数", "碳指数", "成本指数"],
               ["{}", "{:.1f}", "{:.1f}", "{:.1f}"]))

    # 情景矩阵
    A("\n## 表5 情景敏感性：碳足迹 kgCO2e/1M tok\n")
    pues = S["datacenter"]["PUE_scenarios"]
    efs = S["datacenter"]["grid_EF_scenarios"]
    hdr = ["情景 (PUE × 电网)"] + ids
    lines = ["| " + " | ".join(hdr) + " |", "|" + "|".join(["---"] * len(hdr)) + "|"]
    for (pn, pv), (en, ev) in itertools.product(pues.items(), efs.items()):
        vals = [compute(i, pue=pv, ef=ev) for i in ids]
        lines.append("| " + " | ".join([f"{pn}({pv}) × {en}"] +
                     [f"{v['CF_tot']:.4f}" for v in vals]) + " |")
    A("\n".join(lines))

    txt = "\n".join(L) + "\n"
    open(os.path.join(BASE, "docs/02-核算结果.md"), "w", encoding="utf-8").write(txt)

    # CSV
    cols = ["id", "model", "thr_eff", "p_it_kW", "E_it", "E_site",
            "CF_op", "CF_emb", "CF_tot", "C_elec", "C_dep", "C_maint", "C_tot", "Mtok_life"]
    with open(os.path.join(BASE, "data/results.csv"), "w", encoding="utf-8-sig") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(str(round(r[c], 6) if isinstance(r[c], float) else r[c])
                             for c in cols) + "\n")
    print(txt)


if __name__ == "__main__":
    main()
