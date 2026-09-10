"""Shared skeleton for the three analysis SubAgents."""
from __future__ import annotations

from pathlib import Path

import anthropic

from .env import require_api_key
from .verifier import verify_numbers

MODEL = "claude-opus-5"
PROMPT_DIR = Path(__file__).parent / "prompts"


def collect_payloads(resp: dict | None) -> tuple[list[str], list[str]]:
    """Split a tool-call response into evidence and errors.

    The SDK runner swallows exceptions raised inside a tool and hands the
    model repr(exc) as an ordinary tool result. Two consequences we must
    handle rather than inherit:

    1. A boundary violation no longer aborts the run - the agent just reads
       an error string and carries on. So the caller has to notice.
    2. Error text must not join the evidence pool, or gate three would treat
       numbers inside an exception message as vouched-for data.
    """
    if resp is None:
        return [], []
    evidence, errors = [], []
    for block in resp.get("content", []):
        text = str(block.get("content", ""))
        (errors if block.get("is_error") else evidence).append(text)
    return evidence, errors


class SubAgentBase:
    name = "sub-agent"
    prompt_file = ""
    tools: list = []

    def __init__(self, client: anthropic.Anthropic | None = None):
        if client is None:
            require_api_key()
            client = anthropic.Anthropic()
        self.client = client

    def system_prompt(self) -> str:
        """Shared rules first, then this agent's own instructions."""
        shared = (PROMPT_DIR / "_shared.md").read_text(encoding="utf-8")
        own = (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")
        return f"{shared}\n\n---\n\n{own}"

    def run(self, user_input: str, *, max_tokens: int = 16000) -> dict:
        runner = self.client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=max_tokens,
            system=self.system_prompt(),
            thinking={"type": "adaptive"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            tools=self.tools,
            messages=[{"role": "user", "content": user_input}],
        )

        payloads: list[str] = []
        tool_errors: list[str] = []
        final = None
        for message in runner:
            final = message
            evidence, errors = collect_payloads(runner.generate_tool_call_response())
            payloads += evidence
            tool_errors += errors

        if final is not None and final.stop_reason == "refusal":
            return {"agent": self.name, "text": "", "verified": False,
                    "note": "model refused the request"}

        text = "".join(b.text for b in (final.content if final else [])
                       if getattr(b, "type", "") == "text")
        result = verify_numbers(text, payloads)

        # 工具报错不能当作没发生：闸二靠抛异常阻止泄漏，而 runner 会把异常
        # 咽掉并让模型继续往下写。这里把它显式地变成「未通过」。
        if tool_errors:
            return {"agent": self.name, "text": text, "verified": False,
                    "note": f"{len(tool_errors)} 次工具调用失败: "
                            + "; ".join(t[:120] for t in tool_errors[:3])}
        return {"agent": self.name, "text": text,
                "verified": result.passed, "note": result.message()}
