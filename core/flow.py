"""Energy flow: grid -> servers -> tasks -> tokens, with losses named.

The point of a flow view is that every kWh is accounted for. Idle energy is
shown as its own branch rather than folded into task figures, because it is
ownerless: nobody asked for it, and hiding it inside per-task numbers both
inflates them and conceals the idle problem.
"""
from __future__ import annotations

from . import factor as core_factor
from . import hour as core_hour


def energy_flow(hour_start: str, *, region: str = "CN-SC") -> dict:
    """Per-hour energy and carbon flow down to gCO2e per million tokens."""
    tasks = {t["task_id"]: t for t in core_hour.tasks_in_hour(hour_start)["points"]}
    energy = core_hour.energy_by_server(hour_start)
    grid = core_hour.grid_hour(hour_start)
    fmatch = core_factor.match(region, hour_start)

    ef = fmatch.get("selected_ef_gco2e_per_kwh")
    mix = grid["points"][0]["mix_pct"] if grid["points"] else None

    measured = [s for s in energy["servers"] if s["energy_kwh"] is not None]
    absent = [s for s in energy["servers"] if s["energy_kwh"] is None]
    site_kwh = round(sum(s["energy_kwh"] for s in measured), 4)
    idle_kwh = round(sum(s["idle_energy_kwh"] for s in measured), 4)
    task_kwh = round(site_kwh - idle_kwh, 4)

    by_model: dict[str, dict] = {}
    for tid, kwh in energy["task_allocation_kwh"].items():
        t = tasks[tid]
        row = by_model.setdefault(t["model_id"], {
            "model_id": t["model_id"], "kwh": 0.0, "tokens": 0, "n_tasks": 0})
        row["kwh"] += kwh
        row["tokens"] += t["prefill_tokens"] + t["decode_tokens"]
        row["n_tasks"] += 1

    per_model = []
    for row in by_model.values():
        mtok = row["tokens"] / 1e6
        per_model.append({
            "model_id": row["model_id"], "n_tasks": row["n_tasks"],
            "energy_kwh": round(row["kwh"], 4),
            "tokens": row["tokens"],
            "kwh_per_mtok": round(row["kwh"] / mtok, 4) if mtok else None,
            "gco2e_per_mtok": round(row["kwh"] * ef / mtok, 1)
                              if (mtok and ef) else None,
            "share_of_task_energy_pct": round(row["kwh"] / task_kwh * 100, 1)
                                        if task_kwh else None,
            "value_status": "derived",
        })
    per_model.sort(key=lambda r: -(r["gco2e_per_mtok"] or 0))

    total_tokens = sum(r["tokens"] for r in per_model)
    return {
        "stages": [
            {"stage": "1_grid", "kwh": site_kwh, "mix_pct": mix,
             "note": "仅统计有采样数据的服务器"},
            {"stage": "2_servers", "kwh": site_kwh,
             "measured_servers": len(measured), "absent_servers": len(absent)},
            {"stage": "3_split", "task_kwh": task_kwh, "idle_kwh": idle_kwh,
             "idle_share_pct": round(idle_kwh / site_kwh * 100, 1)
                               if site_kwh else None,
             "note": "空载为无主能耗，不分摊给任何任务"},
            {"stage": "4_tokens", "total_tokens": total_tokens,
             "kwh_per_mtok_overall": round(task_kwh / (total_tokens / 1e6), 4)
                                     if total_tokens else None},
        ],
        "per_model": per_model,
        "carbon": {
            "site_gco2e": round(site_kwh * ef, 1) if ef else None,
            "task_gco2e": round(task_kwh * ef, 1) if ef else None,
            "idle_gco2e": round(idle_kwh * ef, 1) if ef else None,
        },
        "factor": {
            "factor_id": fmatch.get("selected_factor_id"),
            "ef_gco2e_per_kwh": ef,
            "spread_pct_across_candidates": fmatch.get("spread_pct_of_selected"),
            "all_placeholder": fmatch.get("all_placeholder"),
        },
        "absent_servers": [{"scope": {"device_id": s["device_id"]},
                            "absent_reason": s.get("absent_reason", "no data"),
                            "ts_start": s.get("ts_start"),
                            "ts_end": s.get("ts_end"),
                            "value_status": "absent"} for s in absent],
        "site_energy_is_partial": bool(absent),
        "expected": len(energy["servers"]), "grade": "B",
        "caliber": {"allocation_method": energy["allocation_method"],
                    "idle_excluded_from_tasks": True,
                    "boundary": "operational only, no embodied carbon"},
    }
