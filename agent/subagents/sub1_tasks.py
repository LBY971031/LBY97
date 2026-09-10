"""SubAgent 1 - compute tasks and energy."""
from ..base import SubAgentBase
from .tools_hour import TOOLS_SUB1


class Sub1Tasks(SubAgentBase):
    name = "任务·服务器·能耗预测"
    prompt_file = "sub1_tasks.md"
    tools = TOOLS_SUB1
