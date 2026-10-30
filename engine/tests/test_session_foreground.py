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
