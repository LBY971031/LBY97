"""24/7 carbon-free energy matching.

Annual totals let a site claim green power it never actually consumed: the
wind blew at night, the load ran at noon. Hourly matching only credits green
electricity generated in the same interval it was used, which is why the CFE
score here can be far below the naive "green share" of the same period.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import hour as core_hour


def hourly_match(hour_start: str) -> dict:
    """Match onsite green generation against actual consumption, interval by interval."""
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = core_hour._load()
    energy = core_hour.energy_by_server(hour_start)

    measured = [s for s in energy["servers"] if s["energy_kwh"] is not None]
    absent = [s for s in energy["servers"] if s["energy_kwh"] is None]
    load_kwh = round(sum(s["energy_kwh"] for s in measured), 4)

    gen = [g for g in d.get("onsite_generation", [])
           if w_from <= datetime.fromisoformat(g["ts_start"]) < w_to]
    if not gen:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": "no onsite generation data"}

    step_h = ((datetime.fromisoformat(gen[0]["ts_end"])
               - datetime.fromisoformat(gen[0]["ts_start"])).total_seconds() / 3600)
    green_kwh = round(sum((g["pv_kw"] + g["wind_kw"]) * step_h for g in gen), 4)

    # 逐区间匹配：每个区间只能用当区间发的绿电，多发的不结转。
    # 负荷必须取该区间的真实值——按小时均摊会抹掉时序错配，
    # 而时序错配正是 CFE 要揭示的东西。
    ok_devices = {s["device_id"] for s in measured}
    intervals, matched = [], 0.0
    for g in gen:
        g_from = datetime.fromisoformat(g["ts_start"])
        g_to = datetime.fromisoformat(g["ts_end"])
        l_kwh = sum(p["power_kw"] / 60.0 for p in d["power_samples"]
                    if p["device_id"] in ok_devices
                    and p["value_status"] != "absent"
                    and g_from <= datetime.fromisoformat(p["ts_start"]) < g_to)
        g_kwh = (g["pv_kw"] + g["wind_kw"]) * step_h
        m = min(g_kwh, l_kwh)
        matched += m
        intervals.append({
            "ts_start": g["ts_start"], "ts_end": g["ts_end"],
            "green_kwh": round(g_kwh, 4), "load_kwh": round(l_kwh, 4),
            "matched_kwh": round(m, 4),
            "surplus_kwh": round(max(g_kwh - l_kwh, 0), 4),
            "value_status": "derived",
        })

    naive = round(green_kwh / load_kwh * 100, 1) if load_kwh else None
    cfe = round(matched / load_kwh * 100, 1) if load_kwh else None
    return {
        "points": intervals,
        "load_kwh": load_kwh, "green_generated_kwh": green_kwh,
        "green_matched_kwh": round(matched, 4),
        "cfe_score_pct": cfe,
        "naive_green_share_pct": naive,
        "overstatement_pct_points": (round(naive - cfe, 1)
                                     if None not in (naive, cfe) else None),
        "load_is_partial": bool(absent),
        "absent_servers": [{"scope": {"device_id": s["device_id"]},
                            "absent_reason": s.get("absent_reason", "no data"),
                            "value_status": "absent"} for s in absent],
        "expected": len(gen), "grade": "B",
        "caliber": {"method": "interval-by-interval, no carry-over",
                    "interval_s": int(step_h * 3600),
                    "load_allocation": "actual per-interval samples"},
    }
