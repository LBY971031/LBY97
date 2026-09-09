"""Main agent: runs once per hour and freezes the result into a snapshot.

The three SubAgents are numbered by responsibility, NOT by execution order.
They are independent: no output of one feeds another, and _safe_run() keeps a
failure in any one of them from taking down the other two or the snapshot.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import snapshot
from .subagents.sub1_tasks import Sub1Tasks
from .subagents.sub2_lowcarbon import Sub2LowCarbon
from .subagents.sub3_factor import Sub3Factor

TZ = timezone(timedelta(hours=8))


class Orchestrator:
    def __init__(self, conn=None, subs=None):
        self.subs = subs if subs is not None else [
            Sub1Tasks(), Sub2LowCarbon(), Sub3Factor()]
        self.conn = conn or snapshot.connect()

    def _safe_run(self, sub, task: str) -> dict:
        try:
            return sub.run(task)
        except Exception as exc:
            return {"agent": sub.name, "text": "",
                    "verified": False, "note": f"failed: {exc}"}

    def run_hour(self, hour_start: str) -> int:
        """Analyse one clock hour and store it. Returns the new version."""
        hour_end = (datetime.fromisoformat(hour_start)
                    + timedelta(hours=1)).isoformat()
        brief = (f"请分析 {hour_start} 至 {hour_end} 这一小时。"
                 f"只使用工具返回的数据，开头先写覆盖率与缺口。")

        results = [self._safe_run(s, brief) for s in self.subs]
        payload = {
            "hour_start": hour_start,
            "generated_at": datetime.now(TZ).isoformat(),
            "sections": {r["agent"]: r["text"] for r in results},
            "verified": all(r["verified"] for r in results),
            "notes": [f"{r['agent']}: {r['note']}"
                      for r in results if not r["verified"]],
        }
        return snapshot.save(self.conn, payload)

    def backfill(self, ts_from: str, ts_to: str) -> list[str]:
        """Run every hour in a range that has no snapshot yet."""
        t = datetime.fromisoformat(ts_from)
        end = datetime.fromisoformat(ts_to)
        done = []
        while t < end:
            key = t.isoformat()
            if snapshot.load(self.conn, key) is None:
                self.run_hour(key)
                done.append(key)
            t += timedelta(hours=1)
        return done
