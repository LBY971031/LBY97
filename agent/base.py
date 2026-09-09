"""Shared skeleton for the three analysis SubAgents."""
from __future__ import annotations

from pathlib import Path

import anthropic

from .env import require_api_key
from .verifier import verify_numbers

MODEL = "claude-opus-5"
PROMPT_DIR = Path(__file__).parent / "prompts"


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
        final = None
        for message in runner:
            final = message
            resp = runner.generate_tool_call_response()
            if resp is not None:
                payloads += [str(b.get("content", "")) for b in resp["content"]]

        if final is not None and final.stop_reason == "refusal":
            return {"agent": self.name, "text": "", "verified": False,
                    "note": "model refused the request"}

        text = "".join(b.text for b in (final.content if final else [])
                       if getattr(b, "type", "") == "text")
        result = verify_numbers(text, payloads)
        return {"agent": self.name, "text": text,
                "verified": result.passed, "note": result.message()}
