"""Win32 窗口解析（只读）。

为什么需要：整屏截图把桌面、聊天窗口、其它游戏的像素一起喂给模型，既贵又容易
干扰判断。attach 之后应该只截目标窗口。

这里只用只读 API：EnumWindows / GetWindowText / GetWindowRect / 进程名查询。
不注入、不抢焦点、不改变窗口状态。非 Windows 上全部返回空/None，调用方降级整屏。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

IS_WINDOWS = hasattr(ctypes, "windll")

DWMWA_EXTENDED_FRAME_BOUNDS = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def list_display_monitors() -> list[dict]:
    """列出物理显示器（Win32 枚举，含虚拟桌面坐标与主屏标记）。

    与 `capture.list_monitors()`（DXcam 的输出列表）不同：这里的坐标是
    虚拟桌面坐标系，用来把窗口矩形换算成「相对某台显示器」的裁剪区。
    """
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    monitors: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def callback(hmonitor, _hdc, _rect, _lparam):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        try:
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                rect = info.rcMonitor
                monitors.append(
                    {
                        "left": rect.left,
                        "top": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                        "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    }
                )
        except Exception:  # noqa: BLE001 - 单个显示器失败不影响其它
            pass
        return True

    try:
        user32.EnumDisplayMonitors(None, None, callback, 0)
    except Exception:  # noqa: BLE001
        return []
    return monitors


def monitor_for_window(hwnd: int) -> dict | None:
    """窗口所在的显示器（取最近的一块）。"""
    if not IS_WINDOWS:
        return None
    try:
        hmonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not hmonitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        return {
            "left": rect.left,
            "top": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        }
    except Exception:  # noqa: BLE001
        return None


def _user32():
    return ctypes.windll.user32


def _process_name(hwnd: int) -> str | None:
    try:
        pid = wintypes.DWORD()
        _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value.split("\\")[-1]
            return None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - 进程名只是附加信息
        return None


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """返回 (left, top, right, bottom)；优先用 DWM 的可见边框。"""
    if not IS_WINDOWS:
        return None
    rect = wintypes.RECT()
    try:
        hresult = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if hresult != 0:
            if not _user32().GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:  # noqa: BLE001
        return None


def list_windows(min_width: int = 80, min_height: int = 60) -> list[dict]:
    """列出可见、带标题、尺寸合理的顶层窗口。"""
    if not IS_WINDOWS:
        return []
    results: list[dict] = []
    user32 = _user32()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            rect = window_rect(hwnd)
            if rect is None:
                return True
            width, height = rect[2] - rect[0], rect[3] - rect[1]
            if width < min_width or height < min_height:
                return True
            results.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "process": _process_name(hwnd),
                    "left": rect[0],
                    "top": rect[1],
                    "width": width,
                    "height": height,
                }
            )
        except Exception:  # noqa: BLE001 - 单个窗口解析失败不影响其它窗口
            pass
        return True

    try:
        user32.EnumWindows(callback, 0)
    except Exception:  # noqa: BLE001
        return []
    return results


def find_window(windows: list[dict], match: str) -> dict | None:
    """纯函数：在窗口列表里按标题子串找目标（大小写不敏感）。

    优先精确等于，其次前缀，最后子串；同一优先级取面积最大的窗口（通常是游戏
    本体，而不是它的启动器或弹窗）。
    """
    needle = match.strip().lower()
    if not needle:
        return None
    candidates = [window for window in windows if needle in str(window.get("title", "")).lower()]
    if not candidates:
        return None

    def rank(window: dict) -> tuple[int, int]:
        title = str(window.get("title", "")).lower()
        if title == needle:
            tier = 0
        elif title.startswith(needle):
            tier = 1
        else:
            tier = 2
        return (tier, -int(window.get("width", 0)) * int(window.get("height", 0)))

    return sorted(candidates, key=rank)[0]


def resolve_window(match: str) -> dict | None:
    return find_window(list_windows(), match)
