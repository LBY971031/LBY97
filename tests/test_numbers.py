"""Numeric correctness: conservation, and agreement across code paths."""
from __future__ import annotations

from core import factor, flow, forecast, hour

HOUR = "2026-08-30T15:00:00+08:00"
TOL = 1e-6


def test_energy_conservation_per_server():
    """整机能耗 = 空载 + 各任务分摊。"""
    e = hour.energy_by_server(HOUR)
    tasks = {t["task_id"]: t["device_id"]
             for t in hour.tasks_in_hour(HOUR)["points"]}
    by_dev: dict[str, float] = {}
    for tid, kwh in e["task_allocation_kwh"].items():
        by_dev[tasks[tid]] = by_dev.get(tasks[tid], 0.0) + kwh
    for s in e["servers"]:
        if s["energy_kwh"] is None:
            continue
        expected = s["idle_energy_kwh"] + by_dev.get(s["device_id"], 0.0)
        assert abs(s["energy_kwh"] - expected) < TOL, s["device_id"]


def test_energy_agrees_between_hour_and_flow():
    e = hour.energy_by_server(HOUR)
    site = sum(s["energy_kwh"] for s in e["servers"]
               if s["energy_kwh"] is not None)
    assert abs(site - flow.energy_flow(HOUR)["stages"][0]["kwh"]) < TOL


def test_carbon_agrees_between_hour_and_flow():
    c = sum(r["carbon_gco2e"] for r in hour.carbon_hour(HOUR)["points"]
            if r["carbon_gco2e"] is not None)
    assert abs(c - flow.energy_flow(HOUR)["carbon"]["site_gco2e"]) < 0.2


def test_intensity_agrees_between_forecast_and_flow():
    a = {p["model_id"]: p["kwh_per_mtok"]
         for p in forecast.intensity_baseline(HOUR)["points"]
         if p.get("kwh_per_mtok") is not None}
    b = {p["model_id"]: p["kwh_per_mtok"] for p in flow.energy_flow(HOUR)["per_model"]}
    assert a == b


def test_flow_stages_add_up():
    stages = {s["stage"]: s for s in flow.energy_flow(HOUR)["stages"]}
    split = stages["3_split"]
    assert abs(stages["1_grid"]["kwh"]
               - (split["task_kwh"] + split["idle_kwh"])) < TOL


def test_task_overlap_is_half_open():
    """15:30 整结束的任务不算在 15:30 起的窗口内；15:31 结束的算。"""
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    w_from = datetime(2026, 8, 30, 15, 30, tzinfo=tz)
    w_to = w_from + timedelta(minutes=1)
    mk = lambda a, b: {"ts_start": f"2026-08-30T{a}:00+08:00",
                       "ts_end": f"2026-08-30T{b}:00+08:00" if b else None}
    assert hour._overlaps(mk("15:22", "15:47"), w_from, w_to)
    assert hour._overlaps(mk("15:30", "15:35"), w_from, w_to)
    assert hour._overlaps(mk("15:28", "15:31"), w_from, w_to)
    assert hour._overlaps(mk("15:29", None), w_from, w_to)
    assert not hour._overlaps(mk("15:20", "15:30"), w_from, w_to)
    assert not hour._overlaps(mk("15:31", "15:40"), w_from, w_to)


def test_factor_prefers_local_hourly_and_reports_the_spread():
    r = factor.match("CN-SC", HOUR)
    assert r["selected_factor_id"] == "CN-SC-HOURLY-2026"
    assert r["spread_pct_of_selected"] > 50, "候选差距必须被量化出来"
    assert r["all_placeholder"] is True


def test_forecast_returns_null_for_unknown_model():
    r = forecast.forecast_energy(HOUR, {"Qwen2.5-72B": 5.0, "从未见过": 3.0})
    unknown = [p for p in r["points"] if p["model_id"] == "从未见过"][0]
    assert unknown["forecast_kwh"] is None
    assert unknown["value_status"] == "absent"
