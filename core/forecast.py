"""Energy intensity baseline and forecast.

A forecast here is not a model fit; it is an observed intensity applied to a
stated plan. The number of observations it rests on travels with the result,
so a one-hour baseline cannot be mistaken for a trained predictor.
"""
from __future__ import annotations

from . import hour as core_hour

MIN_OBSERVATIONS = 3        # 少于这个数，强度只作参考，不足以外推


def intensity_baseline(hour_start: str) -> dict:
    """Observed kWh per million tokens, per model, from one hour."""
    tasks = {t["task_id"]: t for t in core_hour.tasks_in_hour(hour_start)["points"]}
    alloc = core_hour.energy_by_server(hour_start)["task_allocation_kwh"]

    agg: dict[str, dict] = {}
    for tid, kwh in alloc.items():
        t = tasks[tid]
        row = agg.setdefault(t["model_id"], {
            "model_id": t["model_id"], "kwh": 0.0, "tokens": 0,
            "n_tasks": 0, "devices": set()})
        row["kwh"] += kwh
        row["tokens"] += t["prefill_tokens"] + t["decode_tokens"]
        row["n_tasks"] += 1
        row["devices"].add(t["device_id"])

    # 每个模型有多少任务因所在服务器缺数据而被排除
    excluded: dict[str, int] = {}
    for tid, t in tasks.items():
        if tid not in alloc:
            excluded[t["model_id"]] = excluded.get(t["model_id"], 0) + 1

    points = []
    for row in agg.values():
        mtok = row["tokens"] / 1e6
        points.append({
            "model_id": row["model_id"],
            "kwh": round(row["kwh"], 4),
            "tokens": row["tokens"],
            "n_tasks": row["n_tasks"],
            "n_devices": len(row["devices"]),
            "kwh_per_mtok": round(row["kwh"] / mtok, 4) if mtok else None,
            "tasks_excluded_no_energy": excluded.get(row["model_id"], 0),
            "partial_coverage": excluded.get(row["model_id"], 0) > 0,
            "sufficient_observations": row["n_tasks"] >= MIN_OBSERVATIONS,
            "value_status": "derived",
        })

    # 完全没有任何能耗数据的模型（不是部分缺）
    missing = sorted({m for m in excluded
                      if m not in {p["model_id"] for p in points}})
    # 闸一：被排除的任务必须显式列出，只把 status 标成 partial 等于没说
    gaps = [{"model_id": t["model_id"], "value_status": "absent",
             "absent_reason": "task ran on a server with no power samples",
             "scope": {"model_id": t["model_id"], "task_id": tid}}
            for tid, t in tasks.items() if tid not in alloc]

    points.sort(key=lambda p: -(p["kwh_per_mtok"] or 0))
    return {
        "points": points + gaps,
        "models_without_any_energy": missing,
        "tasks_excluded_total": sum(excluded.values()),
        "expected": len({t["model_id"] for t in tasks.values()}),
        "grade": "C",
        "method": "observed allocated energy / observed tokens, single hour",
        "min_observations_for_extrapolation": MIN_OBSERVATIONS,
    }


def forecast_energy(hour_start: str, planned_mtokens: dict[str, float]) -> dict:
    """Apply the observed intensity to a planned token volume per model.

    planned_mtokens: {model_id: millions of tokens}. A model with no observed
    intensity yields an absent row, never a guessed one.
    """
    base = {p["model_id"]: p for p in intensity_baseline(hour_start)["points"]
            if p.get("kwh_per_mtok") is not None}

    rows = []
    for model, mtok in planned_mtokens.items():
        b = base.get(model)
        if b is None or b.get("kwh_per_mtok") is None:
            rows.append({"model_id": model, "planned_mtokens": mtok,
                         "forecast_kwh": None, "value_status": "absent",
                         "absent_reason": "no observed intensity for this model",
                         "scope": {"model_id": model}})
            continue
        rows.append({
            "model_id": model, "planned_mtokens": mtok,
            "kwh_per_mtok": b["kwh_per_mtok"],
            "forecast_kwh": round(b["kwh_per_mtok"] * mtok, 4),
            "based_on_n_tasks": b["n_tasks"],
            "sufficient_observations": b["sufficient_observations"],
            "value_status": "derived",
        })

    return {"points": rows, "expected": len(planned_mtokens), "grade": "D",
            "method": f"intensity from {hour_start} x planned volume",
            "caveat": "single-hour baseline; not a fitted model"}
