"""M2 安全闸与输出通道的单测：不碰真实键鼠、不需要 Windows。

规则必须能被这些测试钉死：
- 命中反作弊 → 拒绝；
- F12 夺权闩锁 → 拒绝，重新 attach 才解除；
- 「无人不自娱」已移除 → 没有输入遥测也必须放行（只剩反作弊与 F12）；
- 默认 dry-run → 只记录动作，不调用任何设备 API。
"""

import pytest

from dsh_game_core.control import DryRunController
from dsh_game_core.engine import EngineError
from dsh_game_core.safety import SafetyGate, scan_processes
from dsh_game_core.session import GameSession


class FakeEngine:
    def snapshot(self, **_kwargs):
        return {"png_b64": "", "width": 1, "height": 1, "ocr": [], "captured_at_ms": 0}

    def close(self):
        pass


def make_gate(*, processes=(), takeover=False):
    return SafetyGate(
        process_source=lambda: list(processes),
        takeover_source=lambda: takeover,
    )


def test_scan_processes_matches_known_anticheat_prefixes():
    hits = scan_processes(["EasyAntiCheat.exe", "notepad.exe", "vgc.exe", "explorer.exe"])
    assert len(hits) == 2
    assert any("EasyAntiCheat" in hit for hit in hits)
    assert any("Vanguard" in hit for hit in hits)


def test_anticheat_blocks_output():
    report = make_gate(processes=["EasyAntiCheat.exe"]).evaluate()
    assert report.allowed is False
    assert report.anticheat
    assert any("anti-cheat" in reason for reason in report.reasons)


def test_unattended_gate_is_gone():
    """「无人不自娱」已移除：只靠反作弊与 F12，无输入遥测也放行。"""
    report = SafetyGate(process_source=lambda: [], takeover_source=lambda: False).evaluate()
    assert report.allowed is True
    assert report.reasons == []
    # 报告形状里也不再有 idle_seconds（插件 schema 已同步删掉）。
    assert "idle_seconds" not in report.to_dict()


def test_takeover_latches_until_reset():
    state = {"pressed": True}
    gate = SafetyGate(
        process_source=lambda: [],
        takeover_source=lambda: state["pressed"],
    )
    assert gate.evaluate().allowed is False
    state["pressed"] = False
    # 闩锁：热键松开后仍然拒绝，直到显式 reset（重新 attach 时调用）。
    assert gate.evaluate().allowed is False
    gate.reset_takeover()
    assert gate.evaluate().allowed is True


def test_allowed_without_anticheat_or_takeover():
    report = make_gate().evaluate()
    assert report.allowed is True
    assert report.reasons == []


def test_dry_run_controller_records_without_touching_devices():
    controller = DryRunController()
    action = controller.press("A", 80)
    assert action["dry_run"] is True
    assert controller.actions[-1]["button"] == "A"


def make_session(gate):
    return GameSession(engine=FakeEngine(), gate=gate, control_backend="dry-run")


def test_act_requires_attach():
    session = make_session(make_gate())
    with pytest.raises(EngineError) as error:
        session.act({"button": "A"})
    assert error.value.code == "NOT_ATTACHED"


def test_act_is_blocked_by_safety_gate():
    session = make_session(make_gate(processes=["vgk.exe"]))
    session.attach({"window": "unspecified"})
    with pytest.raises(EngineError) as error:
        session.act({"button": "A", "duration_ms": 50})
    assert error.value.code == "SAFETY_BLOCKED"


def test_act_runs_on_dry_run_backend_and_counts_actions():
    session = make_session(make_gate())
    session.attach({"window": "unspecified"})
    result = session.act({"button": "A", "duration_ms": 50})
    assert result["action"]["dry_run"] is True
    assert result["actions_total"] == 1
    assert result["safety"]["allowed"] is True
    assert session.status()["last_action"]["button"] == "A"


def test_stop_releases_and_detaches():
    session = make_session(make_gate())
    session.attach({"window": "unspecified"})
    session.act({"button": "B", "duration_ms": 10})
    stopped = session.stop()
    assert stopped["stopped"] is True
    assert session.attached is None
    assert session.status()["attached"] is None
