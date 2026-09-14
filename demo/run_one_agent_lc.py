"""Call ONE SubAgent through LangChain / LangGraph instead of the SDK runner.

    python demo/run_one_agent_lc.py 1
    python demo/run_one_agent_lc.py 3 2026-08-30T15:00:00+08:00

Same three gates as demo/run_one_agent.py: the tools are literally the same
functions, and verify_numbers still runs on the answer. Use this to compare
the two implementations on identical data.

Needs: pip install -r requirements-langchain.txt
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base_langchain import as_langchain
from agent.subagents.sub1_tasks import Sub1Tasks
from agent.subagents.sub2_lowcarbon import Sub2LowCarbon
from agent.subagents.sub3_factor import Sub3Factor

AGENTS = {"1": Sub1Tasks, "2": Sub2LowCarbon, "3": Sub3Factor}
DEFAULT_HOUR = "2026-08-30T15:00:00+08:00"


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which not in AGENTS:
        print("用法: python demo/run_one_agent_lc.py <1|2|3> [hour_start]\n",
              file=sys.stderr)
        for k, cls in AGENTS.items():
            print(f"  {k} = {cls.__name__:<14} {cls.name:<10} "
                  f"工具: {[t.name for t in cls.tools]}", file=sys.stderr)
        return 1

    hour = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_HOUR
    cls = AGENTS[which]
    print(f"[LangChain] SubAgent {which} · {cls.name}   窗口 {hour}\n" + "=" * 68)

    agent = as_langchain(cls)()
    try:
        result = agent.run(f"请分析 {hour} 这一小时。只使用工具返回的数据，"
                           f"开头先写覆盖率与缺口。")
    except Exception as exc:
        # 换了模型之后提示也要跟着换，否则用 DeepSeek 的人会被指去查 Anthropic 的 key
        from agent.env import provider_for
        env_name, _, _ = provider_for(os.environ.get("LC_MODEL", ""))
        vendor = "DeepSeek" if env_name == "DEEPSEEK_API_KEY" else "Anthropic"
        name = type(exc).__name__
        if "Authentication" in name:
            print(f"密钥无效，请检查 .env 里的 {env_name}。", file=sys.stderr)
        elif "RateLimit" in name:
            print("触发速率限制，稍等片刻重试。", file=sys.stderr)
        elif "Connection" in name:
            print(f"连不上 {vendor}，检查网络或代理。", file=sys.stderr)
        else:
            print(f"{name}: {exc}", file=sys.stderr)
        return 1

    print(result["text"])
    print("=" * 68)
    print(f"闸三回检：{result['note']}")
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
