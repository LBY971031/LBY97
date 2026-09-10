"""The three gates, plus regressions for every bug the audit found."""
from __future__ import annotations

import ast
import pathlib
import tempfile

import pytest

from agent.boundary import assert_no_leak, filter_outbound
from agent.contract import AbsentRange, ToolEnvelope, ToolStatus, safe_sum
from agent.verifier import verify_numbers

HOUR = "2026-08-30T15:00:00+08:00"


# ---------------------------------------------------------------- gate one
def test_absent_is_never_summed_as_zero():
    pts = [{"value_status": "measured", "kwh": 10},
           {"value_status": "absent", "kwh": None}]
    assert safe_sum(pts, "kwh") is None


def test_site_energy_is_null_when_a_server_is_missing():
    from core import hour as core_hour
    servers = core_hour.energy_by_server(HOUR)["servers"]
    assert safe_sum(servers, "energy_kwh") is None


# ---------------------------------------------------------------- gate two
def test_forbidden_key_never_leaves():
    text = filter_outbound(ToolEnvelope(
        ToolStatus.OK, {"ip": "10.0.0.1", "kwh": 5}, 1, 1))
    assert "10.0.0.1" not in text and "kwh" in text


def test_device_id_is_pseudonymised_everywhere_including_gap_notice():
    text = filter_outbound(ToolEnvelope(
        ToolStatus.PARTIAL, {"device_id": "srv-9"}, 2, 1,
        absent_ranges=[AbsentRange("BMC down", "T1", "T2",
                                   {"device_id": "srv-9"})]))
    assert "srv-9" not in text
    assert "node-" in text.split("[DATA GAPS]")[1]


@pytest.mark.parametrize("payload", [
    '{"n": "192.168.1.7"}',                       # IPv4
    '{"n": "fe80::1234:5678:9abc:def0"}',         # IPv6
    '{"s": "deadbeefcafebabe01"}',                # serial
])
def test_leak_check_fires(payload):
    with pytest.raises(ValueError):
        assert_no_leak(payload)


def test_float_noise_is_not_mistaken_for_a_serial():
    assert_no_leak('{"x": 0.39999999999999997}')


# -------------------------------------------------------------- gate three
@pytest.fixture(scope="module")
def payloads():
    from agent.subagents.tools_hour import (energy_flow_report, query_energy,
                                            query_tasks_running)
    return [query_tasks_running(HOUR), query_energy(HOUR),
            energy_flow_report(HOUR)]


@pytest.mark.parametrize("text,expected", [
    ("全站能耗 8.0912 kWh", True),
    ("整体 1.0728 kWh/百万 Token", True),
    ("2026 年 8 月 30 日 15:00 至 16:00", True),   # 日期不得误判
    ("总能耗 9999 kWh", False),
    ("碳排 3200.7 gCO2e", False),
    ("能耗 8.09e3 kWh", False),                    # 科学计数法不得漏判
])
def test_verifier(payloads, text, expected):
    assert verify_numbers(text, payloads).passed is expected


def test_verifier_blind_spot_is_deliberate(payloads):
    """小于 60 的整数按设计放行；见 verifier._TRIVIAL 的说明。"""
    assert verify_numbers("同比下降 15%", payloads).passed


# ------------------------------------------------- regressions from audit
def test_carbon_has_exactly_one_factor_source(monkeypatch):
    """P0-1: query_carbon 与 energy_flow_report 曾用两个因子源。"""
    from core import factor, flow, hour
    lib = factor._load()
    lib["factors"][0]["ef_gco2e_per_kwh"] = 999.0
    monkeypatch.setattr(factor, "_load", lambda: lib)
    assert (hour.carbon_hour(HOUR)["ef_gco2e_per_kwh"]
            == flow.energy_flow(HOUR)["factor"]["ef_gco2e_per_kwh"] == 999.0)


def test_partial_status_always_explains_what_is_missing():
    """P1-4: energy_intensity 曾说 partial 却不列缺口。"""
    import json

    from agent.subagents.tools_hour import energy_intensity
    env = json.loads(energy_intensity(HOUR).split("\n\n[DATA GAPS]")[0])
    if env["status"] == "partial":
        assert env["absent_ranges"], "partial 必须附带缺口说明"


def test_snapshot_normalises_timezone():
    """P2-7: 同一时刻的两种时区写法曾被当成两个小时。"""
    from agent import snapshot
    conn = snapshot.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")
    snapshot.save(conn, {"hour_start": HOUR, "generated_at": "T"})
    snapshot.save(conn, {"hour_start": "2026-08-30T07:00:00Z",
                         "generated_at": "T"})
    rows = snapshot.load_range(conn, "2026-08-30T00:00:00+08:00",
                               "2026-08-31T00:00:00+08:00")
    assert len(rows) == 1 and rows[0]["version"] == 2


def test_snapshot_keeps_old_versions():
    from agent import snapshot
    conn = snapshot.connect(pathlib.Path(tempfile.mkdtemp()) / "t.db")
    snapshot.save(conn, {"hour_start": HOUR, "generated_at": "T", "cov": 72})
    snapshot.save(conn, {"hour_start": HOUR, "generated_at": "T", "cov": 100})
    assert snapshot.load(conn, HOUR)["cov"] == 100
    assert snapshot.load(conn, HOUR, version=1)["cov"] == 72


# ------------------------------------------------------------- layering
def test_core_must_not_import_agent():
    for path in pathlib.Path("core").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agent"), path
            elif isinstance(node, ast.Import):
                for a in node.names:
                    assert not a.name.startswith("agent"), path


def test_absent_ranges_must_be_absentrange_objects():
    """传裸 dict 会在 boundary 深处 KeyError —— 这条守住契约。"""
    env = ToolEnvelope(ToolStatus.PARTIAL, {"kwh": 1}, 2, 1,
                       absent_ranges=[{"absent_reason": "wrong shape"}])
    with pytest.raises(KeyError):
        filter_outbound(env)


def test_tool_errors_never_enter_the_evidence_pool():
    """SDK runner 会把工具异常当普通结果交给模型，不能让它冒充证据。"""
    from agent.base import collect_payloads
    resp = {"role": "user", "content": [
        {"type": "tool_result", "content": '{"kwh": 8.09}'},
        {"type": "tool_result", "content": "ValueError('boundary: leak')",
         "is_error": True},
    ]}
    evidence, errors = collect_payloads(resp)
    assert evidence == ['{"kwh": 8.09}']
    assert len(errors) == 1
    assert collect_payloads(None) == ([], [])
