"""LangChain / LangGraph variant of SubAgentBase.

Same three gates as agent/base.py. The gates are preserved because this
class reuses the *same* tool functions: unwrapping an @beta_tool object and
rewrapping it for LangChain keeps _emit() -> filter_outbound() +
assert_no_leak() on every call path. Gate three is re-applied here after the
agent answers.

Swappable with agent/base.py: same constructor shape, same run() return
dict, so agent/orchestrator.py works with either.
"""
from __future__ import annotations

import os
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from .env import require_api_key
from .verifier import verify_numbers

# 换模型只改这一个字符串。init_chat_model 会按前缀推断 provider：
#   "claude-*" -> anthropic，"gpt-*" -> openai，也可写成 "anthropic:claude-opus-5"
# 或用环境变量 LC_MODEL 覆盖，代码一行不动。
MODEL = os.environ.get("LC_MODEL", "claude-opus-5")
PROMPT_DIR = Path(__file__).parent / "prompts"


def to_langchain_tool(bt) -> StructuredTool:
    """Rewrap an @beta_tool object as a LangChain tool, reusing its function.

    Reusing bt.func rather than reimplementing is what keeps the data
    boundary intact: the rewrapped tool still returns through _emit().
    """
    return StructuredTool.from_function(
        func=bt.func,
        name=bt.name,
        description=bt.description,
        parse_docstring=True,
    )


def _text_of(message) -> str:
    """Pull plain text out of a message whose content may be block list."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


class LangChainSubAgent:
    """Drop-in alternative to SubAgentBase, driven by LangGraph."""

    name = "sub-agent"
    prompt_file = ""
    tools: list = []

    def __init__(self, model: str = MODEL, max_tokens: int = 16000):
        require_api_key()
        llm = init_chat_model(
            model,
            max_tokens=max_tokens,
            **({"thinking": {"type": "adaptive"}}
               if model.startswith(("claude", "anthropic:")) else {}),
        )
        self.graph = create_react_agent(
            llm,
            [to_langchain_tool(t) for t in self.tools],
            prompt=self.system_prompt(),
        )

    def system_prompt(self) -> str:
        """Shared rules first, then this agent's own instructions."""
        shared = (PROMPT_DIR / "_shared.md").read_text(encoding="utf-8")
        own = (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")
        return f"{shared}\n\n---\n\n{own}"

    def run(self, user_input: str) -> dict:
        result = self.graph.invoke({"messages": [HumanMessage(user_input)]})
        messages = result["messages"]

        payloads = [str(m.content) for m in messages
                    if isinstance(m, ToolMessage)]
        finals = [m for m in messages if isinstance(m, AIMessage)]
        text = _text_of(finals[-1]) if finals else ""

        verdict = verify_numbers(text, payloads)
        return {"agent": self.name, "text": text,
                "verified": verdict.passed, "note": verdict.message()}


def as_langchain(cls) -> type[LangChainSubAgent]:
    """Build the LangChain twin of an existing SubAgent class.

    Avoids duplicating the three subclasses: name, prompt_file and tools are
    taken from the SDK version, so the two implementations can never drift.
    """
    return type(f"{cls.__name__}LC", (LangChainSubAgent,),
                {"name": cls.name, "prompt_file": cls.prompt_file,
                 "tools": cls.tools})
