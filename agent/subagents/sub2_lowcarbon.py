"""SubAgent 2 - grid mix and low-carbon matching."""
from ..base import SubAgentBase
from .tools_hour import TOOLS_SUB2


class Sub2LowCarbon(SubAgentBase):
    name = "电力结构·因子匹配"
    prompt_file = "sub2_lowcarbon.md"
    tools = TOOLS_SUB2
