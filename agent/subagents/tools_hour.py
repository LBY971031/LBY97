"""Tools for the hourly analysis pass. Every return goes through _emit()."""
from __future__ import annotations

from anthropic import beta_tool

from ..boundary import assert_no_leak, filter_outbound
from ..contract import ToolEnvelope, ToolStatus, drop_absent, safe_sum


def _round(v: float | None, nd: int = 4) -> float | None:
    """Keep float noise out of the payload."""
    return None if v is None else round(v, nd)


def _emit(env: ToolEnvelope) -> str:
    text = filter_outbound(env)
    assert_no_leak(text)
    return text


@beta_tool
def query_tasks_running(hour_start: str) -> str:
    """List compute tasks overlapping one clock hour.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    from core import hour as core_hour

    raw = core_hour.tasks_in_hour(hour_start)
    kept, gaps = drop_absent(raw["points"])
    return _emit(ToolEnvelope(
        status=ToolStatus.PARTIAL if gaps else ToolStatus.OK,
        data={"tasks": kept,
              "total_prefill_tokens": safe_sum(kept, "prefill_tokens"),
              "total_decode_tokens": safe_sum(kept, "decode_tokens")},
        expected_points=raw["expected"], actual_points=len(kept),
        absent_ranges=gaps, quality_grade=raw["grade"],
        caliber={"overlap_rule": "half-open: start < hour_end AND end > hour_start"},
    ))


@beta_tool
def query_energy(hour_start: str) -> str:
    """Per-server energy, per-task allocation and ownerless idle energy.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    from core import hour as core_hour

    raw = core_hour.energy_by_server(hour_start)
    kept, gaps = drop_absent(raw["servers"])
    return _emit(ToolEnvelope(
        status=ToolStatus.PARTIAL if gaps else ToolStatus.OK,
        data={"servers": kept,
              "task_allocation_kwh": raw["task_allocation_kwh"],
              "site_energy_kwh": _round(safe_sum(raw["servers"], "energy_kwh")),
              "measured_servers_energy_kwh": _round(safe_sum(kept, "energy_kwh")),
              "idle_energy_kwh": _round(safe_sum(kept, "idle_energy_kwh"))},
        expected_points=sum(s["expected_points"] for s in raw["servers"]),
        actual_points=sum(s["actual_points"] for s in raw["servers"]),
        absent_ranges=gaps, quality_grade="B",
        caliber={"allocation_method": raw["allocation_method"],
                 "idle_excluded_from_tasks": raw["idle_excluded_from_tasks"],
                 "sampling_interval_s": 60},
    ))


@beta_tool
def query_grid_mix(hour_start: str) -> str:
    """Grid generation mix and emission factor for one clock hour.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    from core import hour as core_hour

    raw = core_hour.grid_hour(hour_start)
    kept, gaps = drop_absent(raw["points"])
    return _emit(ToolEnvelope(
        status=ToolStatus.OK if kept else ToolStatus.NO_DATA,
        data={"grid": kept[0] if kept else None},
        expected_points=raw["expected"], actual_points=len(kept),
        absent_ranges=gaps, quality_grade=raw["grade"],
        caliber={"ef_granularity_s": kept[0]["ef_granularity_s"] if kept else None},
    ))


@beta_tool
def query_carbon(hour_start: str) -> str:
    """Operational carbon per server and per task, plus gCO2e per million tokens.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    from core import hour as core_hour

    raw = core_hour.carbon_hour(hour_start)
    kept, gaps = drop_absent(raw["points"])
    return _emit(ToolEnvelope(
        status=ToolStatus.PARTIAL if gaps else ToolStatus.OK,
        data={"servers": kept,
              "per_task": raw.get("per_task", []),
              "ef_gco2e_per_kwh": raw.get("ef_gco2e_per_kwh"),
              "total_carbon_gco2e": _round(safe_sum(raw["points"], "carbon_gco2e"), 1),
              "measured_carbon_gco2e": _round(safe_sum(kept, "carbon_gco2e"), 1),
              "idle_carbon_gco2e": _round(safe_sum(kept, "idle_carbon_gco2e"), 1)},
        expected_points=raw["expected"], actual_points=len(kept),
        absent_ranges=gaps, quality_grade=raw["grade"],
        caliber=raw.get("caliber"),
    ))


# 编号在这里落地：三个 SubAgent 各自能调的工具
TOOLS_SUB1 = [query_tasks_running, query_energy]
TOOLS_SUB2 = [query_grid_mix]
TOOLS_SUB3 = [query_carbon]
