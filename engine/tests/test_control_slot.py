"""XInput 槽位探测，以及 VGamepadController 的槽位 / 重试 / close 行为。

全部用替身：假的 vgamepad 模块、假的虚拟手柄、假的 XInput 槽位来源。
测试既不需要安装 vgamepad，也不会创建真实虚拟设备或发送任何输入。
"""

import sys
import types

import pytest

from dsh_game_core import control
from dsh_game_core.control import (
    DryRunController,
    SendInputController,
    VGamepadController,
    pick_new_slot,
    xinput_connected_slots,
    xinput_slot_state,
)


class FakePad:
    """虚拟手柄替身：只记录调用，绝不发送真实输入。"""

    def __init__(self):
        self.calls: list[str] = []
        self.buttons: list[object] = []
        self.on_reset = None

    def press_button(self, button=None, **_kwargs):
        self.calls.append("press_button")
        self.buttons.append(button)

    def release_button(self, button=None, **_kwargs):
        self.calls.append("release_button")

    def reset(self):
        self.calls.append("reset")
        if self.on_reset is not None:
            self.on_reset()

    def update(self):
        self.calls.append("update")


class SlotWorld:
    """假的 XInput 世界。

    `physical` 是常驻（真实）手柄占用的槽位；`new_slots` 是每次创建虚拟手柄时
    系统分配到的槽位。虚拟手柄被重建时分配下一个值，模拟「重建后可能换槽位」；
    reset（即关闭/丢弃手柄）会把它占用的槽位释放掉。
    """

    def __init__(self, physical=(), new_slots=()):
        self.physical = set(physical)
        self._new_slots = list(new_slots)
        self.current: int | None = None
        self.calls = 0
        self.pads: list[FakePad] = []

    def connected(self):
        self.calls += 1
        slots = set(self.physical)
        if self.current is not None:
            slots.add(self.current)
        return sorted(slots)

    def _release(self):
        self.current = None

    def factory(self):
        pad = FakePad()
        pad.on_reset = self._release
        self.pads.append(pad)
        self.current = self._new_slots.pop(0) if self._new_slots else None
        return pad


@pytest.fixture
def fake_vgamepad(monkeypatch):
    module = types.ModuleType("vgamepad")
    module.VX360Gamepad = FakePad
    module.XUSB_BUTTON = types.SimpleNamespace(XUSB_GAMEPAD_A=1)
    monkeypatch.setitem(sys.modules, "vgamepad", module)
    return module


@pytest.fixture
def sleeps(monkeypatch):
    """拦下探测重试的 sleep（避免单测真的等），并记录每次时长。"""
    recorded: list[float] = []
    monkeypatch.setattr(control, "time", types.SimpleNamespace(sleep=recorded.append))
    return recorded


# ── 纯函数 / XInput 助手 ─────────────────────────────────────────────


def test_pick_new_slot_returns_smallest_new_slot():
    assert pick_new_slot([0, 1], [1, 2]) == 2
    assert pick_new_slot([], [0, 1]) == 0
    assert pick_new_slot([2], [0, 2]) == 0
    assert pick_new_slot([0, 1], [0, 1]) is None
    assert pick_new_slot([], []) is None


def test_xinput_helpers_soft_fail_when_dll_missing(monkeypatch):
    """没有 XInput DLL（非 Windows / 精简系统）时探测必须降级为空，而不是抛错。"""
    monkeypatch.setattr(control, "_XINPUT_DLL_NAMES", ())
    control._reset_xinput_cache()
    try:
        assert xinput_connected_slots() == []
        assert xinput_slot_state(0) is None
    finally:
        control._reset_xinput_cache()


def test_xinput_helpers_read_through_get_state(monkeypatch):
    states = {
        0: {"connected": True, "packet": 7, "buttons": 0},
        2: {"connected": True, "packet": 9, "buttons": 16},
    }
    monkeypatch.setattr(control, "_xinput_get_state", lambda slot: states.get(slot))
    assert xinput_connected_slots() == [0, 2]


def test_xinput_slot_state_reports_disconnected_slot(monkeypatch):
    monkeypatch.setattr(control, "_load_xinput", lambda: object())
    monkeypatch.setattr(control, "_xinput_get_state", lambda slot: None)
    assert xinput_slot_state(1) == {"connected": False, "packet": 0, "buttons": 0}
    assert xinput_slot_state(4) is None  # 越界
    assert xinput_slot_state("not-a-slot") is None


# ── 简单后端的 readiness ─────────────────────────────────────────────


def test_dry_run_backend_info():
    assert DryRunController().backend_info() == {
        "backend": "dry-run",
        "ready": True,
        "detail": "records actions only",
        "xinput_slot": None,
        "warnings": [],
    }


def test_keyboard_backend_info():
    controller = SendInputController(inject=lambda vk, down: None)
    assert controller.backend_info() == {
        "backend": "keyboard",
        "ready": True,
        "detail": "SendInput",
        "xinput_slot": None,
        "warnings": [],
    }


# ── VGamepadController 槽位探测 ──────────────────────────────────────


def test_controller_accepts_slot_zero_without_warnings(fake_vgamepad):
    world = SlotWorld(physical=(), new_slots=(0,))
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=world.connected)

    assert controller.xinput_slot == 0
    assert controller.warnings == []
    info = controller.backend_info()
    assert info == {
        "backend": "vgamepad",
        "ready": True,
        "detail": "virtual pad created; XInput slot 0",
        "xinput_slot": 0,
        "warnings": [],
    }
    assert len(world.pads) == 1
    # 槽位探测阶段绝不能碰任何按键。
    assert world.pads[0].buttons == []
    assert "press_button" not in world.pads[0].calls


def test_controller_retries_scan_then_accepts_slot_zero(fake_vgamepad, sleeps):
    calls: list[int] = []

    def connected():
        calls.append(1)
        return [] if len(calls) <= 2 else [0]

    world = SlotWorld(physical=(), new_slots=())
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=connected)

    assert controller.xinput_slot == 0
    assert controller.warnings == []
    assert len(world.pads) == 1
    # 第一次扫描（创建后）没看到新槽位 -> 睡一次再试 -> 看到槽位 0。
    assert sleeps == [control.XINPUT_SCAN_DELAY_S]


def test_controller_retry_cap_for_missing_slot(fake_vgamepad, sleeps):
    world = SlotWorld(physical=(), new_slots=())
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=world.connected)

    scans = 1 + control.VGPAD_RECREATE_LIMIT
    calls_per_scan = 1 + control.XINPUT_SCAN_RETRIES + 1  # 创建前 1 次 + 初次扫描 + 重试
    assert world.calls == scans * calls_per_scan
    assert len(world.pads) == 1 + control.VGPAD_RECREATE_LIMIT
    assert len(sleeps) == scans * control.XINPUT_SCAN_RETRIES

    # 拿不到槽位只警告、不抛错，手柄本身还是可用的。
    assert controller.xinput_slot is None
    assert controller.warnings
    assert controller.backend_info()["ready"] is True
    assert controller.backend_info()["xinput_slot"] is None


def test_controller_recreates_until_slot_zero(fake_vgamepad, sleeps):
    # 第一次创建被枚举到槽位 1，重建后拿到槽位 0（槽位 0 空闲）。
    world = SlotWorld(physical=(), new_slots=(1, 0))
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=world.connected)

    assert controller.xinput_slot == 0
    assert len(world.pads) == 2
    assert len(controller.warnings) == 1
    assert "重建" in controller.warnings[0]


def test_controller_gives_up_when_slot_stays_non_zero(fake_vgamepad, sleeps):
    world = SlotWorld(physical=(0,), new_slots=(1, 2, 3))
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=world.connected)

    # 槽位不是 0 只警告：重建到上限后照常工作，绝不抛错。
    assert controller.xinput_slot == 3
    assert len(world.pads) == 1 + control.VGPAD_RECREATE_LIMIT
    info = controller.backend_info()
    assert info["ready"] is True
    assert info["xinput_slot"] == 3
    assert any("槽位 3" in warning for warning in info["warnings"])
    assert info["warnings"][-1].startswith("虚拟手柄仍被枚举到")


def test_controller_creation_failure_raises_actionable_runtime_error(fake_vgamepad):
    def factory():
        raise RuntimeError("ViGEmBus driver not installed")

    with pytest.raises(RuntimeError, match="ViGEmBus"):
        VGamepadController(pad_factory=factory, xinput_connected=lambda: [])


def test_controller_import_failure_raises_actionable_runtime_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "vgamepad", None)
    with pytest.raises(RuntimeError, match="vgamepad"):
        VGamepadController()


# ── close：尽力「拔掉」虚拟手柄 ──────────────────────────────────────


def test_close_resets_updates_and_drops_pad(fake_vgamepad, sleeps):
    world = SlotWorld(physical=(), new_slots=(0,))
    controller = VGamepadController(pad_factory=world.factory, xinput_connected=world.connected)
    pad = world.pads[0]

    controller.close()
    assert pad.calls[-2:] == ["reset", "update"]
    assert controller._pad is None
    assert controller.backend_info()["ready"] is False
    assert controller.backend_info()["detail"] == "virtual pad closed"

    # 可重复 close：收尾流程不能被二次调用搞崩。
    controller.close()
    assert controller._pad is None
    assert pad.buttons == []
