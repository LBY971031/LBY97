"""Tools for the query agent. These read stored snapshots and nothing else.

There is deliberately no tool here that can reach the raw tables. The query
agent cannot recompute even if it wanted to - the same idea as "the agent has
no calculator", enforced by the tool set rather than by the prompt.
"""
from __future__ import annotations

from anthropic import beta_tool

from .. import snapshot
from ..boundary import assert_no_leak, filter_outbound
from ..contract import AbsentRange, ToolEnvelope, ToolStatus

_CONN = None


def _conn():
    global _CONN
    if _CONN is None:
        _CONN = snapshot.connect()
    return _CONN


def _emit(env: ToolEnvelope) -> str:
    text = filter_outbound(env)
    assert_no_leak(text)
    return text


def _missing(hour_start: str, note: str) -> str:
    return _emit(ToolEnvelope(
        status=ToolStatus.NO_DATA, data=None,
        expected_points=1, actual_points=0,
        absent_ranges=[AbsentRange(reason=note, ts_from=hour_start,
                                   scope={"hour_start": hour_start})],
    ))


@beta_tool
def get_hour_report(hour_start: str) -> str:
    """Read the stored report for one clock hour.

    Args:
        hour_start: ISO8601 start of the hour, e.g. 2026-08-30T15:00:00+08:00.
    """
    rep = snapshot.load(_conn(), hour_start)
    if rep is None:
        return _missing(hour_start, "no snapshot stored for this hour")
    return _emit(ToolEnvelope(
        status=ToolStatus.OK, data=rep,
        expected_points=1, actual_points=1,
        caliber=rep.get("caliber"),
    ))


@beta_tool
def list_hour_reports(ts_from: str, ts_to: str) -> str:
    """List stored reports across a period, oldest first.

    Args:
        ts_from: ISO8601 start of the period, inclusive.
        ts_to: ISO8601 end of the period, exclusive.
    """
    reps = snapshot.load_range(_conn(), ts_from, ts_to)
    hours = int((_hours(ts_to) - _hours(ts_from)))
    return _emit(ToolEnvelope(
        status=ToolStatus.OK if len(reps) == hours else ToolStatus.PARTIAL,
        data={"reports": reps, "found": len(reps), "hours_in_period": hours},
        expected_points=max(hours, 1), actual_points=len(reps),
        absent_ranges=([] if len(reps) == hours else
                       [AbsentRange(
                           reason=f"{hours - len(reps)} hour(s) have no snapshot",
                           ts_from=ts_from, ts_to=ts_to)]),
    ))


@beta_tool
def get_report_version(hour_start: str, version: int) -> str:
    """Read one historical version of an hour's report.

    Args:
        hour_start: ISO8601 start of the hour.
        version: Version number, 1 being the first ever stored.
    """
    rep = snapshot.load(_conn(), hour_start, version=version)
    if rep is None:
        return _missing(hour_start, f"version {version} does not exist")
    return _emit(ToolEnvelope(
        status=ToolStatus.OK, data=rep,
        expected_points=1, actual_points=1,
        caliber=rep.get("caliber"),
    ))


def _hours(ts: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(ts).timestamp() / 3600


TOOLS_QUERY = [get_hour_report, list_hour_reports, get_report_version]
