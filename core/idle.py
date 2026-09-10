"""Idle rate per server and per SKU.

Idle energy is ownerless: no task asked for it. Folding it into per-task
figures both inflates them and hides the idle problem, so it is reported on
its own axis here.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import hour as core_hour


def idle_rate(hour_start: str) -> dict:
    """Share of the hour each server spent with no task on it."""
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = core_hour._load()
    spans = [(datetime.fromisoformat(t["ts_start"]),
              datetime.fromisoformat(t["ts_end"]), t) for t in d["tasks"]]

    rows, gaps = [], []
    for dev, meta in d["servers"].items():
        pts = [p for p in d["power_samples"]
               if p["device_id"] == dev
               and w_from <= datetime.fromisoformat(p["ts_start"]) < w_to]
        missing = [p for p in pts if p["value_status"] == "absent"]
        if missing:
            gaps.append({"device_id": dev, "value_status": "absent",
                         "absent_reason": missing[0]["absent_reason"],
                         "ts_start": min(p["ts_start"] for p in missing),
                         "ts_end": max(p["ts_end"] for p in missing),
                         "scope": {"device_id": dev}})
            continue

        idle_min = busy_gpu_min = idle_kwh = 0.0
        for p in pts:
            ts = datetime.fromisoformat(p["ts_start"])
            busy = sum(t["gpus"] for s, e, t in spans
                       if t["device_id"] == dev and s <= ts < e)
            busy_gpu_min += busy
            if busy == 0:
                idle_min += 1
                idle_kwh += p["power_kw"] / 60.0

        n = len(pts)
        capacity = n * meta["gpu_count"]
        rows.append({
            "device_id": dev, "server_model": meta["server_model"],
            "gpu_count": meta["gpu_count"],
            "idle_minutes": round(idle_min, 1),
            "idle_rate_pct": round(idle_min / n * 100, 1) if n else None,
            "gpu_utilisation_pct": round(busy_gpu_min / capacity * 100, 1)
                                   if capacity else None,
            "idle_energy_kwh": round(idle_kwh, 4),
            "value_status": "measured",
        })

    by_sku: dict[str, dict] = {}
    for r in rows:
        s = by_sku.setdefault(r["server_model"], {
            "server_model": r["server_model"], "servers": 0,
            "idle_minutes": 0.0, "idle_energy_kwh": 0.0, "gpu_minutes": 0.0,
            "capacity_gpu_minutes": 0.0})
        s["servers"] += 1
        s["idle_minutes"] += r["idle_minutes"]
        s["idle_energy_kwh"] += r["idle_energy_kwh"]
    for s in by_sku.values():
        s["idle_energy_kwh"] = round(s["idle_energy_kwh"], 4)
        s.pop("gpu_minutes"), s.pop("capacity_gpu_minutes")

    return {"points": rows + gaps, "by_sku": list(by_sku.values()),
            "expected": len(d["servers"]), "grade": "A",
            "caliber": {"idle_definition": "no task occupying any GPU",
                        "idle_energy_is_ownerless": True,
                        "sampling_interval_s": d["sampling_interval_s"]}}
