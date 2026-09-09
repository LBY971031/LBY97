"""Call ONE SubAgent on one hour of data.

    python demo/run_one_agent.py 1
    python demo/run_one_agent.py 2 2026-08-30T15:00:00+08:00

Needs ANTHROPIC_API_KEY (in .env or the shell). The three SubAgents are
independent: calling one does not require the other two.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic

from agent.subagents.sub1_tasks import Sub1Tasks
from agent.subagents.sub2_lowcarbon import Sub2LowCarbon
from agent.subagents.sub3_factor import Sub3Factor

AGENTS = {"1": Sub1Tasks, "2": Sub2LowCarbon, "3": Sub3Factor}
DEFAULT_HOUR = "2026-08-30T15:00:00+08:00"


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which not in AGENTS:
        print("用法: python demo/run_one_agent.py <1|2|3> [hour_start]\n",
              file=sys.stderr)
        for k, cls in AGENTS.items():
            print(f"  {k} = {cls.__name__:<14} {cls.name:<10} "
                  f"工具: {[t.name for t in cls.tools]}", file=sys.stderr)
        return 1

    hour = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_HOUR
    cls = AGENTS[which]
    print(f"SubAgent {which} · {cls.name}   窗口 {hour}\n" + "=" * 68)

    agent = cls()                       # 缺 key 会在这里给出设置指引并退出
    try:
        result = agent.run(f"请分析 {hour} 这一小时。只使用工具返回的数据，"
                           f"开头先写覆盖率与缺口。")
    except anthropic.AuthenticationError:
        print("密钥无效，请检查 .env 里的 ANTHROPIC_API_KEY。", file=sys.stderr)
        return 1
    except anthropic.RateLimitError:
        print("触发速率限制，稍等片刻重试。", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as exc:
        print(f"API 返回 {exc.status_code}：{exc.message}", file=sys.stderr)
        return 1
    except anthropic.APIConnectionError:
        print("连不上 Anthropic，检查网络或代理。", file=sys.stderr)
        return 1

    print(result["text"])
    print("=" * 68)
    print(f"闸三回检：{result['note']}")
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
