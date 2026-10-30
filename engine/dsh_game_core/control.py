"""输出通道：虚拟手柄 / 键盘。

安全边界：本模块**不判断该不该输出**——那是 safety.SafetyGate 的职责。
这里只负责「给一个已获准的动作，把它变成设备输入」。

默认后端是 `dry-run`：只记录动作、不碰任何设备。真实后端必须由用户显式
选择（`DSH_GAME_BRIDGE_CONTROL=vgamepad|keyboard`），且插件会在 attach 时
要求一次性审批；开发/自测永远不会误触键鼠。
"""

from __future__ import annotations

import ctypes
import gc
import time
from collections.abc import Iterable
from typing import Protocol

# 键盘后端支持的按键（模型传这些名字；大小写不敏感）。
VK_CODES: dict[str, int] = {
    # 字母（A–Z）：VK 码与 ASCII 一致。覆盖 Cuphead 等游戏的默认键位
    # （跳跃 Z、射击 X、锁定 C、大招 V、冲刺 Shift…），也方便按游戏键位表自由组合。
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
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
    **{str(digit): 0x30 + digit for digit in range(10)},
}

_KEYEVENTF_KEYUP = 0x0002

# ── XInput：只读探测「虚拟手柄被枚举到哪个槽位」 ────────────────────────
# 用途：ViGEmBus 创建的虚拟手柄在 Windows 上占用一个 XInput 用户槽位；只有
# 槽位 0 才是大多数游戏默认读取的那一个。这里只调用只读的 XInputGetState，
# 不发送任何输入。DLL 缺失（非 Windows / 未装 DirectX 运行时）时全部降级为空。
XINPUT_MAX_SLOTS = 4
XINPUT_SCAN_RETRIES = 3  # 初次扫描没发现新槽位时的重试次数（每次间隔 ~100ms）
XINPUT_SCAN_DELAY_S = 0.1
VGPAD_RECREATE_LIMIT = 2  # 虚拟手柄被枚举到非 0 槽位时最多重建几次

_XINPUT_DLL_NAMES = ("xinput1_4", "xinput1_3", "xinput9_1_0")
_ERROR_SUCCESS = 0

_xinput_dll = None
_xinput_loaded = False


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _XINPUT_GAMEPAD)]


def _load_xinput():
    """懒加载 XInput DLL（xinput1_4 → xinput1_3 → xinput9_1_0）；都不可用则 None。

    失败是软失败：非 Windows、精简系统或没有 Xbox 控制器支持时，探测直接返回空，
    绝不能因此让引擎启动失败。
    """
    global _xinput_dll, _xinput_loaded
    if _xinput_loaded:
        return _xinput_dll
    _xinput_loaded = True
    if not hasattr(ctypes, "windll"):
        return None
    for name in _XINPUT_DLL_NAMES:
        try:
            dll = getattr(ctypes.windll, name)
            dll.XInputGetState.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XINPUT_STATE)]
            dll.XInputGetState.restype = ctypes.c_ulong
        except (AttributeError, OSError):
            continue
        _xinput_dll = dll
        return dll
    return None


def _reset_xinput_cache() -> None:
    """测试用：忘掉已加载的 DLL，让下一次探测重新走加载逻辑。"""
    global _xinput_dll, _xinput_loaded
    _xinput_dll = None
    _xinput_loaded = False


def _xinput_get_state(slot: int) -> dict | None:
    """读一个槽位；未连接 / DLL 不可用 / 调用失败都返回 None（不抛）。"""
    dll = _load_xinput()
    if dll is None:
        return None
    state = _XINPUT_STATE()
    try:
        result = dll.XInputGetState(int(slot), ctypes.byref(state))
    except Exception:  # noqa: BLE001 - 探测失败按「没连」处理
        return None
    if result != _ERROR_SUCCESS:
        return None
    return {"connected": True, "packet": int(state.dwPacketNumber), "buttons": int(state.Gamepad.wButtons)}


def xinput_connected_slots() -> list[int]:
    """当前已连接的 XInput 槽位（0..3）；无 DLL 时返回 []。"""
    slots: list[int] = []
    for slot in range(XINPUT_MAX_SLOTS):
        state = _xinput_get_state(slot)
        if state and state.get("connected"):
            slots.append(slot)
    return slots


def xinput_slot_state(slot: int) -> dict | None:
    """单个槽位的状态；DLL 不可用时 None，槽位空着时 connected=False。"""
    try:
        index = int(slot)
    except (TypeError, ValueError):
        return None
    if not 0 <= index < XINPUT_MAX_SLOTS:
        return None
    state = _xinput_get_state(index)
    if state is not None:
        return state
    if _load_xinput() is None:
        return None
    return {"connected": False, "packet": 0, "buttons": 0}


def pick_new_slot(before: Iterable[int], after: Iterable[int]) -> int | None:
    """`after` 里新增的最小槽位；没有新增返回 None（纯函数，方便单测）。"""
    known = {int(slot) for slot in before}
    for slot in sorted({int(slot) for slot in after}):
        if slot not in known:
            return slot
    return None


class Controller(Protocol):
    backend: str

    def backend_info(self) -> dict: ...

    def press(self, button: str, duration_ms: int) -> dict: ...

    def hold(self, button: str) -> dict: ...

    def release(self, button: str) -> dict: ...

    def release_all(self) -> None: ...


class DryRunController:
    """只记录，不发送。返回值里 dry_run=True，模型能看出没真的按。"""

    backend = "dry-run"

    def __init__(self) -> None:
        self.actions: list[dict] = []

    def backend_info(self) -> dict:
        return {
            "backend": self.backend,
            "ready": True,
            "detail": "records actions only",
            "xinput_slot": None,
            "warnings": [],
        }

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
    """Xbox 360 虚拟手柄（ViGEmBus）。只有用户显式选择时才加载。

    创建后会对比「创建前后」的 XInput 槽位：虚拟手柄通常应该落在槽位 0；落到
    别的槽位时（例如机器上已有实体手柄）游戏可能收不到按键。这里会重试探测、
    必要时重建虚拟手柄，但**永远不会**因为槽位不是 0 而抛错——输出能力仍在，
    只是通过 `backend_info()["warnings"]` 提醒用户。
    """

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

    def __init__(self, *, pad_factory=None, xinput_connected=None) -> None:
        try:
            import vgamepad as vg  # 延迟导入：没有 ViGEmBus 的机器上模块仍可被 import
        except Exception as error:  # noqa: BLE001 - 统一翻译成可操作的错误
            raise RuntimeError(
                "vgamepad 后端不可用：请先安装 ViGEmBus 驱动，并用 "
                "`pip install dsh-game-core[gamepad]` 安装依赖"
                f"（原始错误：{type(error).__name__}: {error}）"
            ) from error
        self._vg = vg
        self._pad_factory = pad_factory or vg.VX360Gamepad
        self._xinput_connected = xinput_connected or xinput_connected_slots
        self._pad = None
        self.xinput_slot: int | None = None
        self.warnings: list[str] = []
        self._connect()

    # ── 槽位探测 ──────────────────────────────────────────────────────
    def _connected_slots(self) -> list[int]:
        try:
            return [int(slot) for slot in self._xinput_connected()]
        except Exception:  # noqa: BLE001 - 探测是附加信息，失败不能影响输出
            return []

    def _scan_for_new_slot(self, before: list[int]) -> int | None:
        # 虚拟手柄枚举到 XInput 有延迟：第一次没看到就等 ~100ms 再试，避免误判。
        for attempt in range(XINPUT_SCAN_RETRIES + 1):
            if attempt:
                time.sleep(XINPUT_SCAN_DELAY_S)
            slot = pick_new_slot(before, self._connected_slots())
            if slot is not None:
                return slot
        return None

    def _create_pad(self):
        try:
            return self._pad_factory()
        except Exception as error:  # noqa: BLE001 - 统一翻译成可操作的错误
            raise RuntimeError(
                "无法创建虚拟手柄（vgamepad / ViGEmBus）：请确认 ViGEmBus 驱动已安装且版本匹配"
                f"（原始错误：{type(error).__name__}: {error}）"
            ) from error

    def _connect(self) -> None:
        before = self._connected_slots()
        self._pad = self._create_pad()
        slot = self._scan_for_new_slot(before)
        self.xinput_slot = slot
        recreates = 0
        while slot != 0 and recreates < VGPAD_RECREATE_LIMIT:
            recreates += 1
            self.warnings.append(
                f"虚拟手柄未落在 XInput 槽位 0（当前：{slot if slot is not None else '未检测到'}）；"
                f"重建第 {recreates}/{VGPAD_RECREATE_LIMIT} 次"
            )
            self._drop_pad()
            before = self._connected_slots()
            self._pad = self._create_pad()
            slot = self._scan_for_new_slot(before)
            self.xinput_slot = slot
        if slot is None:
            self.warnings.append("未检测到新的 XInput 槽位：虚拟手柄可能还没被系统枚举；继续尝试输出")
        elif slot != 0:
            self.warnings.append(
                f"虚拟手柄仍被枚举到 XInput 槽位 {slot}（期望 0）；继续输出，但按键可能落到别的手柄"
            )

    def _drop_pad(self) -> None:
        """尽力「拔掉」当前虚拟手柄：reset/update、丢引用、gc 回收。"""
        pad, self._pad = self._pad, None
        if pad is not None:
            try:
                pad.reset()
                pad.update()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        del pad
        gc.collect()

    def close(self) -> None:
        """关闭后端并尽量让系统回收虚拟设备（重复 attach/stop 不累积幽灵手柄）。"""
        self._drop_pad()

    def backend_info(self) -> dict:
        if self._pad is None:
            detail = "virtual pad closed"
        elif self.xinput_slot is None:
            detail = "virtual pad created; XInput slot not detected"
        else:
            detail = f"virtual pad created; XInput slot {self.xinput_slot}"
        return {
            "backend": self.backend,
            "ready": self._pad is not None,
            "detail": detail,
            "xinput_slot": self.xinput_slot,
            "warnings": list(self.warnings),
        }

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

    def backend_info(self) -> dict:
        return {
            "backend": self.backend,
            "ready": True,
            "detail": "SendInput",
            "xinput_slot": None,
            "warnings": [],
        }

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
