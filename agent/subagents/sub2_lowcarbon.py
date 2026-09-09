"""SubAgent 2 - grid mix and low-carbon matching."""
from ..base import SubAgentBase
from .tools_hour import TOOLS_SUB2


class Sub2LowCarbon(SubAgentBase):
    name = "绿电与低碳"
    prompt_file = "sub2_lowcarbon.md"
    tools = TOOLS_SUB2
