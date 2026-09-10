"""Generate one hour of SYNTHETIC compute-park data for pipeline testing.

WARNING: every number below is invented for testing. It is NOT measured data
from any real facility and must never appear in a report or a paper.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
HOUR = datetime(2026, 8, 30, 15, 0, tzinfo=TZ)
OUT = Path(__file__).parent / "hour_2026-08-30T15.json"

# sku, gpu_count, idle_kw, max_kw
SERVERS = {
    "srv-01": ("SKU-A/8xH100", 8, 1.20, 6.50),
    "srv-02": ("SKU-A/8xH100", 8, 1.20, 6.50),
    "srv-03": ("SKU-B/8xA100", 8, 1.00, 4.80),
    "srv-04": ("SKU-C/4xL40S", 4, 0.50, 1.80),
}

# id, model, server, gpus, start, end, prefill_tok, decode_tok
TASKS = [
    ("T01", "Qwen2.5-72B",  "srv-01", 4, "14:52", "15:18",  820_000,  145_000),
    ("T02", "Qwen2.5-72B",  "srv-01", 4, "15:00", "15:45", 1_240_000, 268_000),
    ("T03", "DeepSeek-V3",  "srv-01", 8, "15:47", "16:20", 2_100_000, 415_000),
    ("T04", "Llama-3.1-8B", "srv-02", 1, "15:05", "15:12",   96_000,   31_000),
    ("T05", "Llama-3.1-8B", "srv-02", 1, "15:12", "15:19",  102_000,   28_000),
    ("T06", "GLM-4-9B",     "srv-02", 2, "15:30", "15:58",  340_000,   87_000),
    ("T07", "DeepSeek-V3",  "srv-03", 8, "15:10", "15:52", 1_880_000, 392_000),
    ("T08", "bge-m3",       "srv-04", 1, "15:00", "15:30",  610_000,        0),
    ("T09", "bge-m3",       "srv-04", 1, "15:30", "16:00",  655_000,        0),
    ("T10", "Qwen2.5-7B",   "srv-04", 2, "15:40", "15:55",  188_000,   44_000),
]

# BMC on srv-03 dropped out for this stretch: no power samples at all.
GAP = ("srv-03", "15:20", "15:35", "BMC unreachable, no power samples")

# 园区自发绿电（合成）。15:00-16:00 是下午，光伏在衰减、风力小幅波动。
# 刻意让前几个区间的光伏出力超过当时的负荷：绿电发得出、用不掉，
# 富余部分在逐区间匹配下不能结转。这是 24/7 CFE 与「年度总量互抵」
# 拉开差距的地方，样本必须能触发它，否则两种算法永远同值、测不出区别。
PV_KW = [9.0, 8.4, 7.8, 7.0, 6.2, 5.4, 4.6, 3.8, 3.2, 2.7, 2.3, 2.0]  # 每 5 分钟
WIND_KW = [0.8, 0.9, 1.1, 1.4, 1.2, 0.9, 0.7, 0.6, 0.8, 1.0, 1.1, 0.9]
# 储能：正为放电（对外供电），负为充电。这一小时先充后放。
STORAGE_KW = [-1.5, -1.5, -1.2, -0.8, 0.0, 0.0, 0.5, 1.2, 1.8, 1.5, 0.8, 0.0]
STORAGE_EFFICIENCY = 0.88          # 往返效率


def _t(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    day = HOUR.day + (1 if h < 6 else 0)          # none here, kept explicit
    return datetime(2026, 8, day, h, m, tzinfo=TZ)


def build() -> dict:
    tasks = [{"task_id": i, "model_id": m, "device_id": s, "gpus": g,
              "ts_start": _t(a).isoformat(), "ts_end": _t(b).isoformat(),
              "prefill_tokens": pf, "decode_tokens": dc}
             for i, m, s, g, a, b, pf, dc in TASKS]

    gap_dev, gap_a, gap_b, gap_why = GAP
    gap_from, gap_to = _t(gap_a), _t(gap_b)

    spans = {t["task_id"]: (datetime.fromisoformat(t["ts_start"]),
                            datetime.fromisoformat(t["ts_end"]))
             for t in tasks}

    power = []
    for dev, (sku, ngpu, idle_kw, max_kw) in SERVERS.items():
        for k in range(60):
            ts = HOUR + timedelta(minutes=k)
            busy = sum(t["gpus"] for t in tasks
                       if t["device_id"] == dev
                       and spans[t["task_id"]][0] <= ts < spans[t["task_id"]][1])
            util = min(busy / ngpu, 1.0)
            rec = {"device_id": dev, "server_model": sku,
                   "ts_start": ts.isoformat(),
                   "ts_end": (ts + timedelta(minutes=1)).isoformat(),
                   "busy_gpus": busy, "gpu_count": ngpu}
            if dev == gap_dev and gap_from <= ts < gap_to:
                rec.update(power_kw=None, value_status="absent",
                           absent_reason=gap_why, scope=f"device={dev}")
            else:
                rec.update(power_kw=round(idle_kw + (max_kw - idle_kw) * util, 4),
                           value_status="measured")
            power.append(rec)

    return {
        "_warning": "SYNTHETIC TEST DATA. Not measured. Never publish as real.",
        "hour_start": HOUR.isoformat(),
        "sampling_interval_s": 60,
        "servers": {k: {"server_model": v[0], "gpu_count": v[1],
                        "idle_kw": v[2], "max_kw": v[3]}
                    for k, v in SERVERS.items()},
        "tasks": tasks,
        "power_samples": power,
        "onsite_generation": [
            {"ts_start": (HOUR + timedelta(minutes=k * 5)).isoformat(),
             "ts_end": (HOUR + timedelta(minutes=k * 5 + 5)).isoformat(),
             "pv_kw": PV_KW[k], "wind_kw": WIND_KW[k],
             "value_status": "measured"}
            for k in range(12)
        ],
        "storage": {
            "round_trip_efficiency": STORAGE_EFFICIENCY,
            "samples": [
                {"ts_start": (HOUR + timedelta(minutes=k * 5)).isoformat(),
                 "ts_end": (HOUR + timedelta(minutes=k * 5 + 5)).isoformat(),
                 "power_kw": STORAGE_KW[k],
                 "mode": ("charge" if STORAGE_KW[k] < 0
                          else "discharge" if STORAGE_KW[k] > 0 else "idle"),
                 "value_status": "measured"}
                for k in range(12)
            ],
        },
        "grid": {
            "hour_start": HOUR.isoformat(),
            "mix_pct": {"hydro": 62.0, "wind": 8.0, "solar": 11.0, "thermal": 19.0},
            "ef_gco2e_per_kwh": 280.0,
            "ef_source": "PLACEHOLDER - not a real published factor",
            "ef_granularity_s": 3600,
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {OUT}")
