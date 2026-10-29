"""键盘输出后端：按键映射与 hold/release 语义。

全部用注入的 `inject` 替身验证——**测试绝不调用真实 SendInput**，
否则会在跑测试的机器上真的按键。
"""

import pytest

from dsh_game_core.control import VK_CODES, SendInputController
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


class FakeEngine:
    def snapshot(self, **_kwargs):
        return {"png_b64": "", "width": 1, "height": 1, "ocr": [], "captured_at_ms": 0}

    def close(self):
        pass


def recorder():
    events = []
    controller = SendInputController(inject=lambda vk, down: events.append((vk, down)))
    return controller, events


def test_hold_and_release_use_key_down_and_up():
    controller, events = recorder()
    controller.hold("w")
    assert events == [(VK_CODES["W"], True)]
    controller.release("w")
    assert events[-1] == (VK_CODES["W"], False)


def test_press_is_down_then_up():
    controller, events = recorder()
    action = controller.press("ENTER", 5)
    assert events == [(VK_CODES["ENTER"], True), (VK_CODES["ENTER"], False)]
    assert action["backend"] == "keyboard"
    assert action["button"] == "ENTER"


def test_release_all_releases_held_keys_only():
    controller, events = recorder()
    controller.hold("SPACE")
    controller.hold("LEFT")
    controller.release_all()
    assert (VK_CODES["SPACE"], False) in events
    assert (VK_CODES["LEFT"], False) in events
    assert controller._held == set()


def test_unknown_key_is_rejected_before_injection():
    controller, events = recorder()
    with pytest.raises(ValueError):
        controller.press("NOT_A_KEY", 10)
    assert events == []


def test_session_accepts_keyboard_backend_alias():
    session = GameSession(
        engine=FakeEngine(),
        gate=SafetyGate(unattended_after_s=180, process_source=lambda: [], idle_source=lambda: 1.0, takeover_source=lambda: False, process_ttl_s=0),
        control_backend="keyboard",
    )
    controller = session._controller_instance()
    assert controller.backend == "keyboard"
    # 只构造、不调用 press/hold：不会有任何真实按键。
