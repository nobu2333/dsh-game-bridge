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


def _window_title(hwnd: int) -> str:
    """窗口标题（去首尾空白）；取不到时返回空串。"""
    try:
        user32 = _user32()
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()
    except Exception:  # noqa: BLE001 - 标题只是附加信息
        return ""


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


def foreground_window() -> dict | None:
    """当前前台窗口（只读，不抢焦点）。

    返回 ``{"hwnd", "title", "process", "left", "top", "width", "height"}``；
    没有前台窗口 / 非 Windows / API 失败时返回 None，调用方降级为「不知道」。
    """
    if not IS_WINDOWS:
        return None
    try:
        user32 = _user32()
        # ctypes 默认 restype 是 c_int，64 位下会截断 HWND，这里显式声明。
        user32.GetForegroundWindow.restype = wintypes.HWND
        raw = user32.GetForegroundWindow()
        if not raw:
            return None
        hwnd = int(raw)
        rect = window_rect(hwnd)
        if rect is None:
            return None
        return {
            "hwnd": hwnd,
            "title": _window_title(hwnd),
            "process": _process_name(hwnd),
            "left": rect[0],
            "top": rect[1],
            "width": rect[2] - rect[0],
            "height": rect[3] - rect[1],
        }
    except Exception:  # noqa: BLE001 - 只读探针，失败即降级
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
            title = _window_title(hwnd)
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


def focus_window(hwnd: int) -> bool:
    """尽力把目标窗口调到前台（只改变窗口激活状态，不注入输入）。

    本地策略环需要它：SendInput 只送前台窗口，而 DSH 窗口可能在工具调用期间
    抢回前台；逐拍校验 + 重新聚焦能让长闭环在后台继续。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = _user32()
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        if user32.SetForegroundWindow(hwnd):
            return True
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(foreground_thread, target_thread, True)
        try:
            return bool(user32.SetForegroundWindow(hwnd))
        finally:
            user32.AttachThreadInput(foreground_thread, target_thread, False)
    except Exception:  # noqa: BLE001 - 聚焦失败由调用方降级处理
        return False


# ── 遮挡判定（纯函数 + 只读枚举）─────────────────────────────────────────
# attach 之后模型看到的是「窗口截图」，但目标窗口可能被聊天窗/浏览器盖住。
# 这里用 z-order 判断目标之上压了哪些可见顶层窗口，只读枚举、不改变窗口状态。

OCCLUSION_TOP_N = 3  # covered_by 只保留比例最高的前几个
OCCLUSION_THRESHOLD = 0.5  # 遮挡超过一半视为「被盖住」


def _unavailable_occlusion() -> dict:
    """降级结果：无法判断遮挡（非 Windows / API 失败 / 目标无效）。"""
    return {"available": False, "occluded_ratio": 0.0, "occluded": False, "covered_by": []}


def _normalize_rect(value) -> tuple[int, int, int, int] | None:
    """纯函数：把矩形归一成 (left, top, right, bottom)；无效或零面积返回 None。

    支持两种形状：``(left, top, right, bottom)`` 元组，以及
    ``{"left", "top", "width", "height"}`` 字典（与 list_windows 输出一致）。
    """
    try:
        if isinstance(value, dict):
            left = int(value["left"])
            top = int(value["top"])
            right = left + int(value["width"])
            bottom = top + int(value["height"])
        else:
            left, top, right, bottom = (int(part) for part in value)
    except (KeyError, TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def rect_intersection_area(rect_a, rect_b) -> int:
    """纯函数：两个矩形的交集面积；无交集或解析失败返回 0，不抛异常。"""
    first = _normalize_rect(rect_a)
    second = _normalize_rect(rect_b)
    if first is None or second is None:
        return 0
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    if width <= 0 or height <= 0:
        return 0
    return width * height


def covered_ratio(target_rect, window_rect) -> float:
    """纯函数：单个窗口对目标的遮挡比例 = min(1, 交集 / 目标面积)。

    窗口比目标大时比例封顶 1.0；目标无效或与窗口无交集返回 0.0。
    """
    target = _normalize_rect(target_rect)
    if target is None:
        return 0.0
    target_area = (target[2] - target[0]) * (target[3] - target[1])
    return min(1.0, rect_intersection_area(target, window_rect) / target_area)


def occlusion_from_windows(target_rect, windows) -> dict:
    """纯函数：根据目标矩形与「压在上面的窗口」列表算遮挡，测试无需真实桌面。

    ``target_rect`` 为目标矩形（LTRB 元组或 list_windows 形状的字典）；
    ``windows`` 为 z-order 在目标之上的可见顶层窗口（上 -> 下），每项是
    ``{"hwnd", "title", "left", "top", "width", "height"}`` 字典。

    单窗口比例 = min(1, 交集 / 目标面积)，全部求和后截到 1.0；``covered_by``
    按比例降序取前 3 个（比例相同按 hwnd 升序，保证结果稳定）。
    任何输入异常都降级为 ``available=False``，不抛异常。
    """
    target = _normalize_rect(target_rect)
    if target is None:
        return _unavailable_occlusion()
    try:
        candidates = list(windows)
    except TypeError:
        return _unavailable_occlusion()
    target_area = (target[2] - target[0]) * (target[3] - target[1])
    total = 0.0
    covering: list[dict] = []
    for window in candidates:
        if not isinstance(window, dict):
            continue
        rect = _normalize_rect(window)
        if rect is None:
            continue
        ratio = round(min(1.0, rect_intersection_area(target, rect) / target_area), 4)
        if ratio <= 0.0:
            continue
        total += ratio
        try:
            hwnd = int(window.get("hwnd") or 0)
        except (TypeError, ValueError):
            hwnd = 0
        covering.append({"hwnd": hwnd, "title": str(window.get("title") or ""), "ratio": ratio})
    ratio = round(min(1.0, total), 4)
    covering.sort(key=lambda item: (-item["ratio"], item["hwnd"]))
    return {
        "available": True,
        "occluded_ratio": ratio,
        "occluded": ratio >= OCCLUSION_THRESHOLD,
        "covered_by": covering[:OCCLUSION_TOP_N],
    }


def _windows_above(hwnd: int) -> list[dict] | None:
    """按 z-order（上 -> 下）列出目标窗口之上的可见顶层窗口。

    EnumWindows 从最上层开始枚举，遇到目标 hwnd 即停止，所以返回的窗口都压在
    目标之上。目标不在枚举结果里（无效 hwnd / 子窗口）返回 None。
    最小化的窗口不算遮挡（它不占屏幕像素），因此跳过。
    """
    user32 = _user32()
    results: list[dict] = []
    found = False

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(current, _lparam):
        nonlocal found
        try:
            if int(current) == int(hwnd):
                found = True
                return False  # 目标之下的窗口不参与遮挡
            if not user32.IsWindowVisible(current) or user32.IsIconic(current):
                return True
            rect = window_rect(current)
            if rect is None:
                return True
            results.append(
                {
                    "hwnd": int(current),
                    "title": _window_title(current),
                    "left": rect[0],
                    "top": rect[1],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1],
                }
            )
        except Exception:  # noqa: BLE001 - 单个窗口失败不影响整体
            pass
        return True

    try:
        user32.EnumWindows(callback, 0)
    except Exception:  # noqa: BLE001
        return None
    return results if found else None


def window_occlusion(hwnd: int) -> dict:
    """目标窗口相对其它顶层窗口的遮挡情况（只读，不改变窗口状态）。

    返回 ``{"available", "occluded_ratio", "occluded", "covered_by"}``；
    非 Windows / hwnd 无效 / 枚举失败时返回 ``available=False`` 的空结果，
    从不抛异常。``occluded_ratio`` 封顶 1.0，``occluded`` 阈值为 0.5。
    """
    if not IS_WINDOWS:
        return _unavailable_occlusion()
    try:
        target_rect = window_rect(hwnd)
        if target_rect is None:
            return _unavailable_occlusion()
        above = _windows_above(hwnd)
        if above is None:
            return _unavailable_occlusion()
        return occlusion_from_windows(target_rect, above)
    except Exception:  # noqa: BLE001 - 遮挡只是附加信息，失败即降级
        return _unavailable_occlusion()