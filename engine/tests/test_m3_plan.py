"""M3 闭环单测：20 Hz 本地循环、每拍安全复检、stop 立即松手。

全部在 dry-run 后端上跑，不注入任何真实输入；时间断言留足余量避免 CI 抖动。
"""

import time

import pytest

from dsh_game_core.engine import EngineError
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


class FakeEngine:
    def snapshot(self, **_kwargs):
        return {"png_b64": "", "width": 1, "height": 1, "ocr": [], "captured_at_ms": 0}

    def close(self):
        pass


class DiffEngine(FakeEngine):
    """按脚本返回帧差事件，用来测 advance 的撞墙脱困。"""

    def __init__(self, events):
        self.events = list(events)
        self.index = 0

    def grab_diff(self, monitor=None):
        event = self.events[min(self.index, len(self.events) - 1)]
        self.index += 1
        return {"event": event}


def allowed_gate(*, process_source=None):
    return SafetyGate(
        process_source=process_source or (lambda: []),
        takeover_source=lambda: False,
        process_ttl_s=0,
    )


def make_session(gate=None):
    return GameSession(engine=FakeEngine(), gate=gate or allowed_gate(), control_backend="dry-run")


def test_plan_requires_attach():
    session = make_session()
    with pytest.raises(EngineError) as error:
        session.plan({"mode": "hold", "button": "DPAD_RIGHT"})
    assert error.value.code == "NOT_ATTACHED"


def test_plan_rejects_unknown_mode():
    session = make_session()
    session.attach({"window": "unspecified"})
    with pytest.raises(EngineError) as error:
        session.plan({"mode": "wiggle", "button": "A"})
    assert error.value.code == "BAD_PLAN_MODE"


def test_hold_plan_runs_near_20hz_and_releases():
    session = make_session()
    session.attach({"window": "unspecified"})
    started = session.plan({"mode": "hold", "button": "DPAD_RIGHT", "duration_ms": 300})
    assert started["plan"]["status"] == "running"

    time.sleep(0.6)
    plan = session.status()["plan"]
    assert plan["status"] == "completed"
    assert plan["ticks"] >= 3, f"too few ticks: {plan}"
    assert plan["hz"] >= 10, f"loop too slow: {plan['hz']} Hz"
    actions = session._controller.actions
    assert any(action.get("hold") for action in actions)
    assert any(action.get("release") for action in actions)


def test_tap_plan_records_repeated_presses():
    session = make_session()
    session.attach({"window": "unspecified"})
    session.plan({"mode": "tap", "button": "A", "duration_ms": 300, "tap_interval_ms": 50})
    time.sleep(0.6)
    plan = session.status()["plan"]
    assert plan["status"] == "completed"
    assert plan["actions"] >= 3
    assert any(action.get("duration_ms") == 30 for action in session._controller.actions)


def test_plan_aborts_within_a_tick_when_anticheat_appears():
    state = {"clean": True}

    def processes():
        return [] if state["clean"] else ["EasyAntiCheat.exe"]

    session = make_session(allowed_gate(process_source=processes))
    session.attach({"window": "unspecified"})
    session.plan({"mode": "hold", "button": "A", "duration_ms": 4000})
    time.sleep(0.25)
    state["clean"] = False
    time.sleep(0.4)

    plan = session.status()["plan"]
    assert plan["status"] == "aborted"
    assert "anti-cheat" in plan["stop_reason"]
    assert any(action.get("release") for action in session._controller.actions), "hold was not released after abort"


def test_stop_mid_plan_releases_and_detaches():
    session = make_session()
    session.attach({"window": "unspecified"})
    session.plan({"mode": "hold", "button": "A", "duration_ms": 5000})
    time.sleep(0.15)
    result = session.stop()
    assert result["plan"]["status"] == "stopped"
    assert session.attached is None
    assert session._controller.actions[-1].get("release_all") or any(
        action.get("release") for action in session._controller.actions
    )


def make_diff_session(events):
    return GameSession(engine=DiffEngine(events), gate=allowed_gate(), control_backend="dry-run")


def test_advance_escapes_sideways_when_screen_is_static():
    session = make_diff_session(["static"] * 60)
    session.attach({"window": "unspecified"})
    session.plan(
        {
            "mode": "advance",
            "button": "DPAD_UP",
            "duration_ms": 600,
            "stuck_after_ms": 200,
            "escape_tap_ms": 60,
        }
    )
    time.sleep(0.9)

    plan = session.status()["plan"]
    assert plan["status"] == "completed"
    assert plan["escapes"] >= 1, f"expected at least one escape: {plan}"
    actions = session._controller.actions
    # 侧移是一次 60ms 的短按，方向来自垂直轴（左右）。
    assert any(action.get("duration_ms") == 60 and action.get("button") in ("DPAD_LEFT", "DPAD_RIGHT") for action in actions)
    # 脱困前必须松开原方向，避免两个方向叠着按。
    assert any(action.get("release") for action in actions)


def test_advance_does_not_escape_while_screen_moves():
    session = make_diff_session(["changed"] * 60)
    session.attach({"window": "unspecified"})
    session.plan({"mode": "advance", "button": "DPAD_UP", "duration_ms": 300, "stuck_after_ms": 200})
    time.sleep(0.6)

    plan = session.status()["plan"]
    assert plan["status"] == "completed"
    assert plan["escapes"] == 0

