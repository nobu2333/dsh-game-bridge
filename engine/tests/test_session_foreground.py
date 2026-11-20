"""Batch A：会话层的前台/遮挡/后端就绪接线。

全部用注入的窗口与控制器替身，不导入 vgamepad、不碰真实输入。
"""

import time

import pytest

from dsh_game_core.engine import EngineError
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


class FakeEngine:
    def snapshot(self, **kwargs):
        return {
            "png_b64": "",
            "width": 10,
            "height": 10,
            "ocr": [],
            "captured_at_ms": 0,
            "region": kwargs.get("region"),
        }

    def close(self):
        pass

    def grab_diff(self, monitor=None):
        return {"event": "static"}


class FakeVGamepad:
    backend = "vgamepad"

    def __init__(self, *, ready=True, slot=0, detail=""):
        self.ready = ready
        self.slot = slot
        self.detail = detail
        self.pressed = []
        self.released = False
        self.closed = False

    def backend_info(self):
        return {
            "backend": "vgamepad",
            "ready": self.ready,
            "detail": self.detail,
            "xinput_slot": self.slot,
            "warnings": [],
        }

    def press(self, button, duration_ms):
        self.pressed.append((button, duration_ms))
        return {"backend": "vgamepad", "button": button.upper(), "duration_ms": duration_ms, "dry_run": False}

    def hold(self, button):
        return {"backend": "vgamepad", "button": button.upper(), "hold": True, "dry_run": False}

    def release(self, button):
        self.released = True
        return {"backend": "vgamepad", "button": button.upper(), "release": True, "dry_run": False}

    def release_all(self):
        self.released = True

    def close(self):
        self.closed = True


def window(hwnd=100, title="Game"):
    return {
        "hwnd": hwnd,
        "title": title,
        "process": "game.exe",
        "left": 0,
        "top": 0,
        "width": 800,
        "height": 600,
    }


def foreground(hwnd, title):
    return {
        "hwnd": hwnd,
        "title": title,
        "process": None,
        "left": 0,
        "top": 0,
        "width": 1920,
        "height": 1080,
    }


def allowed_gate():
    return SafetyGate(process_source=lambda: [], takeover_source=lambda: False, process_ttl_s=0)


def make_session(*, backend="dry-run", controller=None, fg_state=None, occlusion=None):
    fg_state = fg_state or {"value": None}

    def occlusion_source(hwnd):
        if occlusion is not None:
            return occlusion
        return {"available": True, "occluded_ratio": 0.0, "occluded": False, "covered_by": []}

    session = GameSession(
        engine=FakeEngine(),
        gate=allowed_gate(),
        control_backend=backend,
        window_resolver=lambda match: window(),
        window_by_hwnd_resolver=lambda hwnd: {**window(), "hwnd": hwnd} if hwnd == 100 else None,
        window_rect_source=lambda hwnd: (0, 0, 800, 600),
        window_monitor_source=lambda hwnd: {"left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
        foreground_source=lambda: fg_state["value"],
        occlusion_source=occlusion_source,
    )
    if controller is not None:
        session._controller = controller
    return session, fg_state


def test_attach_reports_control_and_foreground():
    session, fg_state = make_session()
    fg_state["value"] = foreground(999, "DSH")
    result = session.attach({"window": "Game"})
    assert result["attached"]["hwnd"] == 100
    assert result["control"]["backend"] == "dry-run"
    assert result["control"]["ready"] is True
    assert result["foreground"]["title"] == "DSH"


def test_attach_by_hwnd_pins_that_window():
    session, fg_state = make_session(fg_state={"value": foreground(999, "DSH")})
    result = session.attach({"hwnd": 100})
    assert result["attached"]["hwnd"] == 100

    with pytest.raises(EngineError) as error:
        session.attach({"hwnd": 555})
    assert error.value.code == "WINDOW_NOT_FOUND"


def test_attach_fails_fast_when_real_backend_unavailable():
    controller = FakeVGamepad(ready=False, detail="No module named 'vgamepad'")
    session, fg_state = make_session(backend="vgamepad", controller=controller)
    fg_state["value"] = foreground(999, "DSH")
    with pytest.raises(EngineError) as error:
        session.attach({"window": "Game"})
    assert error.value.code == "BACKEND_UNAVAILABLE"
    assert "vgamepad" in error.value.message
    assert session.attached is None


def test_dry_run_act_reports_delivery_without_blocking():
    session, fg_state = make_session()
    fg_state["value"] = foreground(999, "DSH")
    session.attach({"window": "Game"})
    result = session.act({"button": "A", "duration_ms": 10})
    assert result["delivery"]["checked"] is True
    assert result["delivery"]["foreground"] is False
    assert result["action"]["dry_run"] is True


def test_real_act_refuses_when_target_not_foreground():
    controller = FakeVGamepad()
    session, fg_state = make_session(backend="vgamepad", controller=controller)
    fg_state["value"] = foreground(999, "DSH")
    session.attach({"window": "Game"})
    with pytest.raises(EngineError) as error:
        session.act({"button": "A", "duration_ms": 10})
    assert error.value.code == "FOREGROUND_MISMATCH"
    assert controller.pressed == []

    fg_state["value"] = foreground(100, "Game")
    result = session.act({"button": "A", "duration_ms": 10})
    assert result["delivery"]["foreground"] is True
    assert controller.pressed == [("A", 10)]


def test_real_plan_aborts_when_foreground_lost():
    controller = FakeVGamepad()
    session, fg_state = make_session(backend="vgamepad", controller=controller)
    fg_state["value"] = foreground(100, "Game")
    session.attach({"window": "Game"})
    session.plan({"mode": "hold", "button": "DPAD_RIGHT", "duration_ms": 5000})
    time.sleep(0.2)
    fg_state["value"] = foreground(999, "DSH")
    time.sleep(0.4)

    plan = session.status()["plan"]
    assert plan["status"] == "aborted"
    assert plan["foreground_lost"] is True
    assert "foreground lost" in plan["stop_reason"]
    assert controller.released is True
    session.stop()


def test_stop_closes_real_controller():
    controller = FakeVGamepad()
    session, fg_state = make_session(backend="vgamepad", controller=controller)
    fg_state["value"] = foreground(100, "Game")
    session.attach({"window": "Game"})
    session.stop()
    assert controller.closed is True
    assert session._controller is None


def test_snapshot_marks_foreground_and_occlusion():
    session, fg_state = make_session(
        occlusion={
            "available": True,
            "occluded_ratio": 0.75,
            "occluded": True,
            "covered_by": [{"hwnd": 5, "title": "Chat", "ratio": 0.75}],
        }
    )
    fg_state["value"] = foreground(999, "DSH")
    session.attach({"window": "Game"})
    frame = session.snapshot(ocr=False)
    assert frame["foreground"]["title"] == "DSH"
    assert frame["occluded"]["occluded"] is True
    assert frame["occluded"]["occluded_ratio"] == 0.75
    assert frame["region"] == {"left": 0, "top": 0, "width": 800, "height": 600}


def test_status_includes_control_and_foreground():
    session, fg_state = make_session()
    fg_state["value"] = foreground(999, "DSH")
    status = session.status()
    assert status["control"]["backend"] == "dry-run"
    assert status["foreground"]["title"] == "DSH"
    assert status["attach_actions"] == 0
    assert status["auto_focus"] is False


def test_attach_actions_resets_per_attach_while_actions_total_accumulates():
    session, fg_state = make_session()
    fg_state["value"] = foreground(100, "Game")
    session.attach({"window": "Game"})
    r1 = session.act({"button": "A", "duration_ms": 10})
    r2 = session.act({"button": "B", "duration_ms": 10})
    assert r1["attach_actions"] == 1
    assert r2["attach_actions"] == 2
    assert r2["actions_total"] == 2
    assert session.status()["attach_actions"] == 2

    stopped = session.stop()
    assert stopped["attach_actions"] == 2
    assert stopped["actions_total"] == 2

    session.attach({"window": "Game"})
    assert session.status()["attach_actions"] == 0
    r3 = session.act({"button": "A", "duration_ms": 10})
    assert r3["attach_actions"] == 1
    assert r3["actions_total"] == 3


def test_relative_mouse_click_maps_normalized_coordinates_to_attached_rect():
    session = GameSession(
        engine=FakeEngine(),
        gate=allowed_gate(),
        control_backend="dry-run",
        window_resolver=lambda match: {"hwnd": 100, "title": "Game", "process": "game.exe", "left": 100, "top": 200, "width": 801, "height": 601},
        window_by_hwnd_resolver=lambda hwnd: {"hwnd": 100, "title": "Game", "process": "game.exe", "left": 100, "top": 200, "width": 801, "height": 601},
        window_rect_source=lambda hwnd: (100, 200, 901, 801),
        window_monitor_source=lambda hwnd: {"left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
        foreground_source=lambda: foreground(100, "Game"),
        occlusion_source=lambda hwnd: {"available": True, "occluded_ratio": 0.0, "occluded": False, "covered_by": []},
    )
    session.attach({"window": "Game"})
    result = session.act({"rx": 0.5, "ry": 0.25, "mouse_button": "RIGHT"})
    assert result["action"]["mouse_click"] is True
    assert result["action"]["x"] == 500
    assert result["action"]["y"] == 350
    assert result["action"]["rx"] == 0.5
    assert result["action"]["ry"] == 0.25
    assert result["action"]["button"] == "RIGHT"

    with pytest.raises(EngineError) as out_of_range:
        session.act({"rx": 1.2, "ry": 0.5})
    assert out_of_range.value.code == "BAD_MOUSE"

    with pytest.raises(EngineError) as missing_ry:
        session.act({"rx": 0.5})
    assert missing_ry.value.code == "BAD_MOUSE"


def test_auto_focus_restores_foreground_only_when_authorized_and_safe():
    fg_state = {"value": foreground(999, "DSH")}
    focus_calls = []
    takeover = {"active": False}
    gate = SafetyGate(process_source=lambda: [], takeover_source=lambda: takeover["active"], process_ttl_s=0)

    def focus_succeeds():
        focus_calls.append("focus")
        fg_state["value"] = foreground(100, "Game")
        return True

    controller = FakeVGamepad()
    session = GameSession(
        engine=FakeEngine(),
        gate=gate,
        control_backend="vgamepad",
        window_resolver=lambda match: window(),
        window_rect_source=lambda hwnd: (0, 0, 800, 600),
        window_monitor_source=lambda hwnd: {"left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
        foreground_source=lambda: fg_state["value"],
        occlusion_source=lambda hwnd: {"available": True, "occluded_ratio": 0.0, "occluded": False, "covered_by": []},
        focus_source=focus_succeeds,
    )
    session._controller = controller

    # Default auto_focus=False keeps refusal behavior and never steals focus.
    attached_default = session.attach({"window": "Game"})
    assert attached_default["auto_focus"] is False
    with pytest.raises(EngineError) as err:
        session.act({"button": "A", "duration_ms": 10})
    assert err.value.code == "FOREGROUND_MISMATCH"
    assert focus_calls == []

    # Explicit auto_focus=True restores focus when SafetyGate allows.
    attached_auto = session.attach({"window": "Game", "auto_focus": True})
    assert attached_auto["auto_focus"] is True
    ok = session.act({"button": "A", "duration_ms": 10})
    assert focus_calls == ["focus"]
    assert ok["delivery"]["foreground"] is True
    assert controller.pressed == [("A", 10)]

    # F12 takeover must block BEFORE auto_focus can run.
    fg_state["value"] = foreground(999, "DSH")
    takeover["active"] = True
    with pytest.raises(EngineError) as blocked:
        session.act({"button": "B", "duration_ms": 10})
    assert blocked.value.code == "SAFETY_BLOCKED"
    assert focus_calls == ["focus"]

    # If focus restoration fails, real backend still refuses with FOREGROUND_MISMATCH.
    takeover["active"] = False
    session._focus_source = lambda: False
    fg_state["value"] = foreground(999, "DSH")
    session.attach({"window": "Game", "auto_focus": True})
    with pytest.raises(EngineError) as still_wrong:
        session.act({"button": "B", "duration_ms": 10})
    assert still_wrong.value.code == "FOREGROUND_MISMATCH"
