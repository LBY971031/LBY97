"""SubAgent 3 - emission factors and carbon accounting."""
from ..base import SubAgentBase
from .tools_hour import TOOLS_SUB3


class Sub3Factor(SubAgentBase):
    name = "因子与核算"
    prompt_file = "sub3_factor.md"
    tools = TOOLS_SUB3
