"""Query agent - answers from frozen snapshots, never recomputes."""
from ..base import SubAgentBase
from .tools_query import TOOLS_QUERY


class QueryAgent(SubAgentBase):
    name = "查询"
    prompt_file = "query.md"
    tools = TOOLS_QUERY
