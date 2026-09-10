"""Minute-level load profile and surge detection.

Hourly averages hide surges: a ten-minute spike to four times baseline shows
up as a 50% lift in the hour and can be mistaken for normal variation. This
module works on the raw minute samples so the shape survives.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import hour as core_hour

SURGE_RATIO = 1.5      # 相对基线的抬升倍数
SURGE_MIN_MINUTES = 3  # 至少持续这么久才算突增，避免把单点抖动当事件


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def load_profile(hour_start: str, *, surge_ratio: float = SURGE_RATIO,
                 min_minutes: int = SURGE_MIN_MINUTES) -> dict:
    """Per-server minute series, baseline, peak and surge windows."""
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = core_hour._load()

    rows, gaps, surges = [], [], []
    for dev, meta in d["servers"].items():
        pts = sorted((p for p in d["power_samples"]
                      if p["device_id"] == dev
                      and w_from <= datetime.fromisoformat(p["ts_start"]) < w_to),
                     key=lambda p: p["ts_start"])
        missing = [p for p in pts if p["value_status"] == "absent"]
        if missing:
            gaps.append({"device_id": dev, "value_status": "absent",
                         "absent_reason": missing[0]["absent_reason"],
                         "ts_start": min(p["ts_start"] for p in missing),
                         "ts_end": max(p["ts_end"] for p in missing),
                         "scope": {"device_id": dev}})
            continue

        kw = [p["power_kw"] for p in pts]
        # 基线取本小时功率的中位数，即这台机器当前的「常态」。
        # 不能用空载功率——正常干活时功率本来就远高于空载，那样几乎
        # 每一分钟都会被标成突增，等于没检测。
        baseline = max(_median(kw), meta["idle_kw"])
        peak = max(kw)
        rows.append({
            "device_id": dev, "server_model": meta["server_model"],
            "baseline_kw": round(baseline, 4),
            "idle_kw": meta["idle_kw"],
            "peak_kw": round(peak, 4),
            "mean_kw": round(sum(kw) / len(kw), 4),
            "peak_over_baseline": round(peak / baseline, 2) if baseline else None,
            "n_samples": len(pts), "value_status": "measured",
        })

        # 连续超过阈值的区段
        run_start = None
        for i, p in enumerate(pts):
            hot = p["power_kw"] >= baseline * surge_ratio
            if hot and run_start is None:
                run_start = i
            elif not hot and run_start is not None:
                _close(surges, pts, run_start, i, dev, baseline, min_minutes)
                run_start = None
        if run_start is not None:
            _close(surges, pts, run_start, len(pts), dev, baseline, min_minutes)

    return {"points": rows + gaps, "surges": surges,
            "expected": len(d["servers"]), "grade": "A",
            "caliber": {"baseline": "median power of the window",
                        "surge_ratio": surge_ratio,
                        "surge_min_minutes": min_minutes,
                        "sampling_interval_s": d["sampling_interval_s"]}}


def _close(surges, pts, i, j, dev, baseline, min_minutes) -> None:
    if j - i < min_minutes:
        return
    seg = pts[i:j]
    peak = max(p["power_kw"] for p in seg)
    surges.append({
        "device_id": dev,
        "ts_start": seg[0]["ts_start"], "ts_end": seg[-1]["ts_end"],
        "minutes": j - i,
        "peak_kw": round(peak, 4),
        "peak_over_baseline": round(peak / baseline, 2) if baseline else None,
        "value_status": "derived",
    })
