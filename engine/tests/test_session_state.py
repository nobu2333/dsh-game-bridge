"""Session wiring for the general baseline: state() and policy_start/stop()."""

import base64

import cv2
import numpy as np
import pytest

from dsh_game_core.engine import EngineError
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


def _png_b64():
    image = np.zeros((100, 200, 3), np.uint8)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


class FakeEngine:
    def __init__(self):
        self.grab_calls = 0

    def snapshot(self, **kwargs):
        return {
            "png_b64": _png_b64(),
            "width": 200,
            "height": 100,
            "ocr": [{"text": "HP.3", "score": 0.99, "left": 10, "top": 78, "right": 45, "bottom": 95}],
            "captured_at_ms": 0,
        }

    def grab_raw(self, monitor=None, region=None):
        self.grab_calls += 1
        return np.zeros((100, 200, 3), np.uint8)

    def close(self):
        pass


class FakeController:
    backend = "dry-run"

    def __init__(self):
        self.events = []
        self.released = False

    def backend_info(self):
        return {"backend": self.backend, "ready": True, "detail": "", "xinput_slot": None, "warnings": []}

    def hold(self, button):
        self.events.append(("hold", button))
        return {}

    def release(self, button):
        self.events.append(("release", button))
        return {}

    def press(self, button, duration_ms):
        self.events.append(("press", button))
        return {}

    def release_all(self):
        self.released = True


class FakeVGamepad(FakeController):
    backend = "vgamepad"


class FakePolicy:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stopped = False
        FakePolicy.instances.append(self)

    def start(self):
        return self.status()

    def stop(self):
        self.stopped = True
        return self.status()

    def status(self):
        return {
            "running": not self.stopped,
            "ticks": 0,
            "hz": 0.0,
            "actions": 0,
            "escapes": 0,
            "stop_reason": None,
            "scene": None,
            "last_entities": 0,
        }


def _foreground(hwnd=999, title="DSH"):
    return {"hwnd": hwnd, "title": title, "process": None, "left": 0, "top": 0, "width": 100, "height": 100}


def _make_session(*, backend="dry-run", controller=None, foreground=None):
    state = {"fg": foreground or _foreground(999, "DSH")}
    session = GameSession(
        engine=FakeEngine(),
        gate=SafetyGate(process_source=lambda: [], takeover_source=lambda: False, process_ttl_s=0),
        control_backend=backend,
        window_resolver=lambda match: {
            "hwnd": 100,
            "title": "Game",
            "process": "game.exe",
            "left": 0,
            "top": 0,
            "width": 200,
            "height": 100,
        },
        window_rect_source=lambda hwnd: (0, 0, 200, 100),
        window_monitor_source=lambda hwnd: {"left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True},
        foreground_source=lambda: state["fg"],
        occlusion_source=lambda hwnd: {
            "available": True,
            "occluded_ratio": 0.0,
            "occluded": False,
            "covered_by": [],
        },
    )
    if controller is not None:
        session._controller = controller
    return session, state


def test_state_builds_worldstate_from_capture_and_profile():
    session, fg_state = _make_session()
    fg_state["fg"] = _foreground(999, "DSH")
    session.attach({"window": "Game"})
    profile = {"id": "cuphead", "hud": {"hp": {"box": [0.0, 0.7, 0.35, 0.3], "prefix": "HP"}}}
    state = session.state({"profile": profile})
    assert state["schema"] == 1
    assert state["scene"] == "gameplay"
    assert state["player"]["hp"] == 3
    assert state["ui"]["hp_text"] == "3"
    assert state["game"]["profile"] == "cuphead"
    assert state["game"]["provider"] == "vision"
    assert state["foreground"]["title"] == "DSH"
    assert state["backend"] == "dry-run"


def test_state_tolerates_bad_profile_and_missing_foreground():
    session, fg_state = _make_session()
    fg_state["fg"] = None
    session.attach({"window": "Game"})
    state = session.state({"profile": "not-a-dict"})
    assert state["foreground"] is None
    assert state["scene"] in ("gameplay", "unknown", "dialogue")


def test_policy_start_status_and_stop(monkeypatch):
    import dsh_game_core.policy as policy_module

    FakePolicy.instances.clear()
    monkeypatch.setattr(policy_module, "PolicyRunner", FakePolicy)
    session, fg_state = _make_session()
    session.attach({"window": "Game"})

    started = session.policy_start({"profile": {"id": "cuphead"}})
    assert started["policy"]["running"] is True
    first = FakePolicy.instances[-1]
    assert first.kwargs["tick_hz"] == 60
    assert callable(first.kwargs["capture"])

    assert session.status()["policy"]["running"] is True
    again = session.policy_start({"profile": {"id": "cuphead"}})
    assert again["policy"]["running"] is True
    assert first.stopped is True

    stopped = session.policy_stop()
    assert stopped["stopped"] is True
    assert session.status()["policy"] is None
    assert session.policy_stop()["stopped"] is False


def test_policy_requires_attach():
    session, _state = _make_session()
    with pytest.raises(EngineError) as error:
        session.policy_start({})
    assert error.value.code == "NOT_ATTACHED"


def test_policy_start_refuses_when_real_backend_target_not_foreground(monkeypatch):
    import dsh_game_core.policy as policy_module

    monkeypatch.setattr(policy_module, "PolicyRunner", FakePolicy)
    controller = FakeVGamepad()
    session, fg_state = _make_session(backend="vgamepad", controller=controller)
    fg_state["fg"] = _foreground(999, "DSH")
    session.attach({"window": "Game"})
    with pytest.raises(EngineError) as error:
        session.policy_start({"profile": {}})
    assert error.value.code == "FOREGROUND_MISMATCH"
