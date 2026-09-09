from __future__ import annotations

import hashlib
import json
import re

from .contract import ToolEnvelope

FORBIDDEN = {
    "device_serial", "serial_no", "ip", "ip_addr", "hostname",
    "rack_location", "room_address", "contract_no", "raw_file_path",
    "token_log_detail",
}
PSEUDONYM = {"job_name": "job", "device_id": "node"}

GAP_MARK = "\n\n[DATA GAPS]"
_GAP_NOTICE = GAP_MARK + (
    " The following ranges have no data. Do not infer their values, do not "
    "substitute neighbouring periods or similar hardware, and do not treat "
    "them as zero in any aggregation:\n{gaps}"
)


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in FORBIDDEN:
                continue
            if k in PSEUDONYM and isinstance(v, str):
                h = hashlib.sha256(v.encode()).hexdigest()[:6]
                out[k] = f"{PSEUDONYM[k]}-{h}"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj


def _gap_line(a: dict) -> str:
    scope = a.get("scope") or {}
    label = "[" + ", ".join(f"{k}={v}" for k, v in scope.items()) + "] " if scope else ""
    span = (f"{a['ts_from']} ~ {a['ts_to']}" if a.get("ts_from")
            else "(all periods)")
    return f"  - {label}{span}: {a['reason']}"


def filter_outbound(env: ToolEnvelope) -> str:
    payload = _scrub(env.to_dict())
    text = json.dumps(payload, ensure_ascii=False, default=str)
    gaps = payload.get("absent_ranges") or []
    if gaps:
        text += _GAP_NOTICE.format(gaps="\n".join(_gap_line(a) for a in gaps))
    return text


def assert_no_leak(text: str) -> None:
    if re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        raise ValueError("boundary: outbound text may contain an IP")
    for m in re.finditer(r"\b[0-9a-fA-F]{16,}\b", text):
        if any(c in "abcdefABCDEF" for c in m.group(0)):
            raise ValueError("boundary: outbound text may contain a serial number")
