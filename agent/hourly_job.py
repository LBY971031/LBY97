"""Cron entry point: analyse the hour that just ended.

    5 * * * * cd /path/to/项目 && .venv/bin/python -m agent.hourly_job

Runs at minute 5 rather than on the hour so collection has time to write its
last samples; starting on the hour tends to report the final minutes as gaps.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from .orchestrator import TZ, Orchestrator


def main() -> int:
    now = datetime.now(TZ)
    hour = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    try:
        version = Orchestrator().run_hour(hour.isoformat())
    except Exception as exc:                      # cron 里没人看着，要留痕
        print(f"{hour.isoformat()} FAILED: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    print(f"{hour.isoformat()} -> v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
