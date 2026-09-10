"""Deterministic per-hour computation over the raw tables.

Numbers are computed here and only here. The agent layer never does
arithmetic; it only selects tools, reads envelopes and writes prose.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "samples" / "hour_2026-08-30T15.json"


def _load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _overlaps(task: dict, w_from: datetime, w_to: datetime) -> bool:
    """Half-open interval overlap: start < window_to AND end > window_from."""
    start = datetime.fromisoformat(task["ts_start"])
    end = task.get("ts_end")
    return start < w_to and (end is None or datetime.fromisoformat(end) > w_from)


def tasks_in_hour(hour_start: str) -> dict:
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = _load()
    out = []
    for t in d["tasks"]:
        if not _overlaps(t, w_from, w_to):
            continue
        s = max(datetime.fromisoformat(t["ts_start"]), w_from)
        e = min(datetime.fromisoformat(t["ts_end"]), w_to)
        minutes = (e - s).total_seconds() / 60
        out.append({**t,
                    "minutes_in_hour": round(minutes, 1),
                    "gpu_minutes_in_hour": round(minutes * t["gpus"], 1),
                    "crosses_boundary": (t["ts_start"] < hour_start
                                         or t["ts_end"] > w_to.isoformat()),
                    "value_status": "measured"})
    return {"points": out, "expected": len(d["tasks"]), "grade": "A"}


def energy_by_server(hour_start: str) -> dict:
    """Energy per server, plus per-task allocation and ownerless idle energy.

    Allocation runs minute by minute: a minute with no task running is idle
    (ownerless); a minute with tasks is split by GPU-share within that minute.
    """
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = _load()
    spans = {t["task_id"]: (datetime.fromisoformat(t["ts_start"]),
                            datetime.fromisoformat(t["ts_end"]), t)
             for t in d["tasks"]}

    servers: dict[str, dict] = {}
    alloc: dict[str, float] = {}
    gaps = []

    for dev, meta in d["servers"].items():
        pts = [p for p in d["power_samples"]
               if p["device_id"] == dev
               and w_from <= datetime.fromisoformat(p["ts_start"]) < w_to]
        rec = {"device_id": dev, "server_model": meta["server_model"],
               "expected_points": 60, "actual_points": 0,
               "energy_kwh": None, "idle_energy_kwh": None,
               "value_status": "measured"}

        missing = [p for p in pts if p["value_status"] == "absent"]
        if missing:
            gaps.append({"scope": {"device_id": dev},
                         "ts_start": min(p["ts_start"] for p in missing),
                         "ts_end": max(p["ts_end"] for p in missing),
                         "absent_reason": missing[0]["absent_reason"],
                         "value_status": "absent"})
            rec.update(value_status="absent",
                       absent_reason=missing[0]["absent_reason"],
                       ts_start=min(p["ts_start"] for p in missing),
                       ts_end=max(p["ts_end"] for p in missing),
                       scope={"device_id": dev},
                       actual_points=len(pts) - len(missing))
            servers[dev] = rec
            continue

        total = idle = 0.0
        for p in pts:
            kwh = p["power_kw"] / 60.0
            total += kwh
            ts = datetime.fromisoformat(p["ts_start"])
            running = [t for tid, (s, e, t) in spans.items()
                       if t["device_id"] == dev and s <= ts < e]
            if not running:
                idle += kwh
                continue
            gsum = sum(t["gpus"] for t in running)
            for t in running:
                alloc[t["task_id"]] = alloc.get(t["task_id"], 0.0) + kwh * t["gpus"] / gsum

        rec.update(actual_points=len(pts),
                   energy_kwh=round(total, 4),
                   idle_energy_kwh=round(idle, 4))
        servers[dev] = rec

    return {"servers": list(servers.values()),
            "task_allocation_kwh": {k: round(v, 4) for k, v in sorted(alloc.items())},
            "gaps": gaps,
            "allocation_method": "gpu_share_per_minute",
            "idle_excluded_from_tasks": True}


def grid_hour(hour_start: str) -> dict:
    d = _load()
    g = d["grid"]
    if g["hour_start"] != hour_start:
        return {"points": [], "expected": 1, "grade": "D"}
    return {"points": [{**g, "value_status": "measured"}],
            "expected": 1, "grade": "B"}


def carbon_hour(hour_start: str, *, region: str = "CN-SC") -> dict:
    """Operational carbon for the hour. Energy x hourly grid factor.

    Carbon inherits the factor's granularity: it can be no finer than the
    hour, however finely the energy was metered.
    """
    from . import factor as core_factor

    e = energy_by_server(hour_start)
    g = grid_hour(hour_start)
    if not g["points"]:
        return {"points": [], "expected": 1, "grade": "D"}

    # 因子只有一个入口：因子库。小时数据里的 ef_gco2e_per_kwh 仅供参考，
    # 不参与计算——否则同一小时会从两条路径算出两个碳排。
    fm = core_factor.match(region, hour_start)
    ef = fm.get("selected_ef_gco2e_per_kwh")
    if ef is None:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": "no applicable emission factor"}

    rows = []
    for s in e["servers"]:
        if s["energy_kwh"] is None:
            rows.append({**s, "carbon_gco2e": None})
            continue
        rows.append({"device_id": s["device_id"],
                     "server_model": s["server_model"],
                     "energy_kwh": s["energy_kwh"],
                     "carbon_gco2e": round(s["energy_kwh"] * ef, 1),
                     "idle_carbon_gco2e": round(s["idle_energy_kwh"] * ef, 1),
                     "value_status": "derived"})

    tasks = {t["task_id"]: t for t in tasks_in_hour(hour_start)["points"]}
    per_task = []
    for tid, kwh in e["task_allocation_kwh"].items():
        t = tasks[tid]
        mtok = (t["prefill_tokens"] + t["decode_tokens"]) / 1e6
        per_task.append({
            "task_id": tid, "model_id": t["model_id"],
            "energy_kwh": kwh,
            "carbon_gco2e": round(kwh * ef, 1),
            "tokens_total": t["prefill_tokens"] + t["decode_tokens"],
            "gco2e_per_mtok": round(kwh * ef / mtok, 1) if mtok else None,
            "value_status": "derived"})

    return {"points": rows, "per_task": per_task, "ef_gco2e_per_kwh": ef,
            "factor_id": fm.get("selected_factor_id"),
            "expected": len(e["servers"]), "grade": "B",
            "caliber": {"scope": "operational only (Boundary A)",
                        "embodied_included": False,
                        "factor_id": fm.get("selected_factor_id"),
                        "factor_all_placeholder": fm.get("all_placeholder"),
                        "ef_granularity_s": 3600}}
