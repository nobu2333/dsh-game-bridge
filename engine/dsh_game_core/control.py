"""输出通道：虚拟手柄 / 键盘。

安全边界：本模块**不判断该不该输出**——那是 safety.SafetyGate 的职责。
这里只负责「给一个已获准的动作，把它变成设备输入」。

默认后端是 `dry-run`：只记录动作、不碰任何设备。真实后端必须由用户显式
选择（`DSH_GAME_BRIDGE_CONTROL=vgamepad|keyboard`），且插件会在 attach 时
要求一次性审批；开发/自测永远不会误触键鼠。
"""

from __future__ import annotations

import ctypes
import time
from typing import Protocol

# 键盘后端支持的按键（模型传这些名字；大小写不敏感）。
VK_CODES: dict[str, int] = {
    "W": 0x57,
    "A": 0x41,
    "S": 0x53,
    "D": 0x44,
    "Q": 0x51,
    "E": 0x45,
    "F": 0x46,
    "R": 0x52,
    "SPACE": 0x20,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "TAB": 0x09,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "ALT": 0x12,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
}

_KEYEVENTF_KEYUP = 0x0002


class Controller(Protocol):
    backend: str

    def press(self, button: str, duration_ms: int) -> dict: ...

    def hold(self, button: str) -> dict: ...

    def release(self, button: str) -> dict: ...

    def release_all(self) -> None: ...


class DryRunController:
    """只记录，不发送。返回值里 dry_run=True，模型能看出没真的按。"""

    backend = "dry-run"

    def __init__(self) -> None:
        self.actions: list[dict] = []

    def press(self, button: str, duration_ms: int) -> dict:
        action = {"backend": self.backend, "button": button, "duration_ms": duration_ms, "dry_run": True}
        self.actions.append(action)
        return action

    def hold(self, button: str) -> dict:
        action = {"backend": self.backend, "button": button, "hold": True, "dry_run": True}
        self.actions.append(action)
        return action

    def release(self, button: str) -> dict:
        action = {"backend": self.backend, "button": button, "release": True, "dry_run": True}
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

    def _code(self, button: str):
        name = self.BUTTONS.get(button.upper())
        if name is None:
            raise ValueError(f"unknown gamepad button: {button}")
        return getattr(self._vg.XUSB_BUTTON, name)

    def press(self, button: str, duration_ms: int) -> dict:
        code = self._code(button)
        self._pad.press_button(button=code)
        self._pad.update()
        time.sleep(max(1, min(duration_ms, 2000)) / 1000.0)
        self._pad.release_button(button=code)
        self._pad.update()
        return {"backend": self.backend, "button": button.upper(), "duration_ms": duration_ms, "dry_run": False}

    def hold(self, button: str) -> dict:
        code = self._code(button)
        self._pad.press_button(button=code)
        self._pad.update()
        return {"backend": self.backend, "button": button.upper(), "hold": True, "dry_run": False}

    def release(self, button: str) -> dict:
        code = self._code(button)
        self._pad.release_button(button=code)
        self._pad.update()
        return {"backend": self.backend, "button": button.upper(), "release": True, "dry_run": False}

    def release_all(self) -> None:
        self._pad.reset()
        self._pad.update()


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def send_virtual_key(vk: int, down: bool) -> None:
    """Win32 SendInput 注入一次按键（键盘后端专用；测试可注入替身）。"""
    flags = 0 if down else _KEYEVENTF_KEYUP
    event = _INPUT(type=1, u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))


class SendInputController:
    """键盘后端（SendInput）。只有用户显式选择 `keyboard` 并批准后才加载。

    注意：真实注入**尚未实机验证**；单测只验证按键映射与 hold/release 语义
    （通过注入 `inject` 替身，不碰任何设备）。
    """

    backend = "keyboard"

    def __init__(self, inject=None):
        self._inject = inject or send_virtual_key
        self._held: set[str] = set()

    @staticmethod
    def _vk(button: str) -> int:
        name = str(button).strip().upper()
        if name not in VK_CODES:
            raise ValueError(f"unknown keyboard key: {button} (supported: {', '.join(sorted(VK_CODES))})")
        return VK_CODES[name]

    def press(self, button: str, duration_ms: int) -> dict:
        vk = self._vk(button)
        self._inject(vk, True)
        time.sleep(max(1, min(duration_ms, 2000)) / 1000.0)
        self._inject(vk, False)
        return {"backend": self.backend, "button": button.upper(), "duration_ms": duration_ms, "dry_run": False}

    def hold(self, button: str) -> dict:
        vk = self._vk(button)
        self._inject(vk, True)
        self._held.add(str(button).strip().upper())
        return {"backend": self.backend, "button": button.upper(), "hold": True, "dry_run": False}

    def release(self, button: str) -> dict:
        vk = self._vk(button)
        self._inject(vk, False)
        self._held.discard(str(button).strip().upper())
        return {"backend": self.backend, "button": button.upper(), "release": True, "dry_run": False}

    def release_all(self) -> None:
        for name in list(self._held):
            try:
                self._inject(VK_CODES[name], False)
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        self._held.clear()
