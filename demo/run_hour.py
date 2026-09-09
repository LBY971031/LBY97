"""End-to-end run over the synthetic hour.

Stage 1 (always runs, no API key needed): call the tools, pass the three
gates, and print exactly what would leave this machine.
Stage 2 (needs ANTHROPIC_API_KEY): hand that payload to Claude and let it
write the prose, then verify every number it used.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.subagents.tools_hour import (query_energy, query_grid_mix,
                                        query_tasks_running)
from agent.verifier import verify_numbers

HOUR = "2026-08-30T15:00:00+08:00"
MODEL = "claude-opus-5"

SYSTEM = """You analyse one hour of compute-park energy and carbon data.

Hard rules:
- Use only numbers present in the tool results. Never compute new ones.
- Never infer, interpolate, or substitute values for absent ranges.
- Never treat absent data as zero in any total.
- Open with data coverage and gaps, then the analysis.
- State the caliber (allocation method, factor granularity) for every figure.
- Carbon can be no finer than the emission factor's granularity.

Write in Chinese."""

QUESTION = ("请给出 2026 年 8 月 30 日 15:00-16:00 这一小时的"
            "算力任务情况、实时能耗分析和碳足迹报告。")


def collect() -> list[str]:
    return [query_tasks_running(HOUR), query_energy(HOUR), query_grid_mix(HOUR)]


def main() -> int:
    payloads = collect()
    print("=" * 72)
    print("将要出网的内容（已过三道闸）")
    print("=" * 72)
    for name, p in zip(("tasks", "energy", "grid"), payloads):
        print(f"\n--- {name}  ({len(p)} chars) ---\n{p}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n" + "=" * 72)
        print("ANTHROPIC_API_KEY 未设置，到此为止。")
        print("上面的数字全部由代码算出，不需要模型；")
        print("设置密钥后重跑，模型只负责把它们写成一段话。")
        return 0

    import anthropic

    client = anthropic.Anthropic()
    msg = client.beta.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user",
                   "content": QUESTION + "\n\n工具返回：\n" + "\n\n".join(payloads)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")

    print("\n" + "=" * 72)
    print("Claude 写出的报告")
    print("=" * 72)
    print(text)

    result = verify_numbers(text, payloads)
    print("\n" + "=" * 72)
    print(f"闸三回检：{result.message()}")
    print(f"用量：输入 {msg.usage.input_tokens}，输出 {msg.usage.output_tokens}")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
