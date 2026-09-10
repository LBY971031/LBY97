"""Call audit: one JSON line per tool call, so a report can be traced back."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_PATH = Path("data/agent_audit.log")


def log_call(*, agent_name: str, tool_name: str, sent_summary: str,
             returned_summary: str, input_tokens: int | None = None,
             output_tokens: int | None = None,
             path: Path = AUDIT_PATH) -> None:
    """Record one call. agent_name is required - an unattributed line is useless."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent_name,
        "tool": tool_name,
        "sent": sent_summary[:500],
        "returned": returned_summary[:500],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
