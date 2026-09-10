"""Structure: the three SubAgents, their tools, and the LangChain twin."""
from __future__ import annotations

import pathlib

import pytest

from agent.subagents.sub1_tasks import Sub1Tasks
from agent.subagents.sub2_lowcarbon import Sub2LowCarbon
from agent.subagents.sub3_factor import Sub3Factor

HOUR = "2026-08-30T15:00:00+08:00"
AGENTS = [Sub1Tasks, Sub2LowCarbon, Sub3Factor]


@pytest.mark.parametrize("cls", AGENTS)
def test_agent_has_prompt_and_tools(cls):
    assert cls.tools, f"{cls.__name__} 没有工具"
    assert (pathlib.Path("agent/prompts") / cls.prompt_file).exists()


@pytest.mark.parametrize("cls", AGENTS)
def test_system_prompt_carries_the_shared_rules(cls):
    prompt = cls.__new__(cls).system_prompt()
    assert "数字由代码算" in prompt
    assert "不得把缺失当作 0" in prompt


def test_tools_are_not_shared_between_agents():
    names = [t.name for cls in AGENTS for t in cls.tools]
    assert len(names) == len(set(names)), "同一个工具挂在多个 Agent 上"


SAMPLE_ARGS = {
    "hour_start": HOUR,
    "instant": "2026-08-30T15:30:00+08:00",
    "region": "CN-SC",
    "mode": "hour",
    "planned_mtokens_json": '{"Qwen2.5-72B": 1.0}',
    "ts_from": "2026-08-30T00:00:00+08:00",
    "ts_to": "2026-08-31T00:00:00+08:00",
    "version": 1,
}


def _call(tool):
    """Build arguments from the tool's own schema rather than guessing."""
    props = tool.input_schema.get("properties", {})
    unknown = set(props) - set(SAMPLE_ARGS)
    assert not unknown, f"{tool.name} 有测试未覆盖的参数: {unknown}"
    return tool(**{k: SAMPLE_ARGS[k] for k in props})


@pytest.mark.parametrize("cls", AGENTS)
def test_every_tool_passes_the_boundary(cls):
    """任何工具的返回都必须已脱敏——即绕不过 _emit()。"""
    for tool in cls.tools:
        assert "srv-0" not in _call(tool), f"{tool.name} 泄漏了原始设备 ID"


def test_langchain_twin_tracks_the_sdk_version(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from agent.base_langchain import as_langchain
    for cls in AGENTS:
        twin = as_langchain(cls)
        assert twin.name == cls.name
        assert [t.name for t in twin.tools] == [t.name for t in cls.tools]


def test_langchain_tool_wrapper_keeps_the_boundary(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from agent.base_langchain import to_langchain_tool
    lc = to_langchain_tool(Sub3Factor.tools[1])
    out = lc.invoke({"hour_start": HOUR, "region": "CN-SC"})
    assert "srv-0" not in out and "node-" in out
    assert "[DATA GAPS]" in out


def test_orchestrator_isolates_a_failing_subagent():
    from agent import snapshot
    from agent.orchestrator import Orchestrator

    class Fake:
        def __init__(self, name, boom=False):
            self.name, self.boom = name, boom
        def run(self, task):
            if self.boom:
                raise RuntimeError("core unavailable")
            return {"agent": self.name, "text": "ok", "verified": True,
                    "note": "ok"}

    import tempfile
    conn = snapshot.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")
    orch = Orchestrator(conn=conn,
                        subs=[Fake("a"), Fake("b", boom=True), Fake("c")])
    orch.run_hour(HOUR)
    rep = snapshot.load(conn, HOUR)
    assert rep is not None, "一个 Agent 失败不应导致快照丢失"
    assert rep["verified"] is False
    assert len([t for t in rep["sections"].values() if t]) == 2


# ------------------------------------------------------- query layer
def test_query_agent_cannot_reach_raw_data():
    """查询 Agent 的工具集里不得有任何能读原始表的工具。"""
    from agent.subagents import tools_hour
    from agent.subagents.query_agent import QueryAgent

    raw_tools = {t.name for t in (tools_hour.TOOLS_SUB1 + tools_hour.TOOLS_SUB2
                                  + tools_hour.TOOLS_SUB3)}
    query_tools = {t.name for t in QueryAgent.tools}
    assert not (query_tools & raw_tools), "查询 Agent 拿到了能重算的工具"


def test_query_tools_report_a_missing_snapshot_as_missing():
    import json

    from agent.subagents.tools_query import get_hour_report
    env = json.loads(get_hour_report("1999-01-01T00:00:00+08:00")
                     .split("\n\n[DATA GAPS]")[0])
    assert env["status"] == "no_data"
    assert env["absent_ranges"], "没有快照时必须说明，而不是返回空报告"


def test_hourly_job_is_importable():
    import agent.hourly_job as job
    assert callable(job.main)


def test_audit_requires_an_agent_name():
    import inspect

    from agent.audit import log_call
    params = inspect.signature(log_call).parameters
    assert params["agent_name"].default is inspect.Parameter.empty
