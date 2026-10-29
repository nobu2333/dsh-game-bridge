"""输出通道：虚拟手柄 / 键鼠。

安全边界：本模块**不判断该不该输出**——那是 safety.SafetyGate 的职责。
这里只负责「给一个已获准的动作，把它变成设备输入」。

默认后端是 `dry-run`：只记录动作、不碰任何设备。真实后端必须由用户显式
选择（`DSH_GAME_BRIDGE_CONTROL=vgamepad`），这样开发/自测永远不会误触键鼠。
"""

from __future__ import annotations

import time
from typing import Protocol


class Controller(Protocol):
    backend: str

    def press(self, button: str, duration_ms: int) -> dict: ...

    def release_all(self) -> None: ...


class DryRunController:
    """只记录，不发送。返回值里 action 带 dry_run=True，模型能看出没真的按。"""

    backend = "dry-run"

    def __init__(self) -> None:
        self.actions: list[dict] = []

    def press(self, button: str, duration_ms: int) -> dict:
        action = {"backend": self.backend, "button": button, "duration_ms": duration_ms, "dry_run": True}
        self.actions.append(action)
        return action

    def release_all(self) -> None:
        self.actions.append({"backend": self.backend, "release_all": True, "dry_run": True})


class VGamepadController:
    """Xbox 360 虚拟手柄（ViGEmBus）。只有用户显式选择时才加载。"""

    backend = "vgamepad"

    BUTTONS = {
        "A": "XUSB_GAMEPAD_A",
        "B": "XUSB_GAMEPAD_B",
        "X": "XUSB_GAMEPAD_X",
        "Y": "XUSB_GAMEPAD_Y",
        "START": "XUSB_GAMEPAD_START",
        "BACK": "XUSB_GAMEPAD_BACK",
        "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
        "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
        "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
        "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
        "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
        "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
    }

    def __init__(self) -> None:
        import vgamepad as vg  # 延迟导入：没有 ViGEmBus 的机器上模块仍可被 import

        self._vg = vg
        self._pad = vg.VX360Gamepad()

    def press(self, button: str, duration_ms: int) -> dict:
        name = self.BUTTONS.get(button.upper())
        if name is None:
            raise ValueError(f"unknown gamepad button: {button}")
        code = getattr(self._vg.XUSB_BUTTON, name)
        self._pad.press_button(button=code)
        self._pad.update()
        time.sleep(max(1, min(duration_ms, 2000)) / 1000.0)
        self._pad.release_button(button=code)
        self._pad.update()
        return {"backend": self.backend, "button": button.upper(), "duration_ms": duration_ms, "dry_run": False}

    def release_all(self) -> None:
        self._pad.reset()
        self._pad.update()
