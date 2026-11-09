"""Window-level capture fallback for windows that full-screen DXcam misses.

The default engine path is "grab the monitor, crop the window rectangle". That
fails when the target window is covered, on another virtual desktop, or not
actually composited where its rect says it is. This module asks the window to
render itself with PrintWindow(PW_RENDERFULLCONTENT), which works for many
GDI/Unity/UE windows and is a useful fallback; it is not guaranteed for every
hardware-accelerated game.

Windows-only, never imported by the pure state/policy tests.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

import numpy as np


class WindowCaptureError(RuntimeError):
    pass


def _user32():
    return ctypes.windll.user32


def window_state(hwnd: int) -> dict:
    """Read-only visibility/foreground/cloaked diagnostics for one hwnd."""
    if not hwnd:
        return {"hwnd": 0, "valid": False}
    user32 = _user32()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    foreground = int(user32.GetForegroundWindow())
    cloaked = 0
    try:
        dwmapi = ctypes.windll.dwmapi
        # DWMWA_CLOAKED = 14
        cloaked_value = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked_value), ctypes.sizeof(cloaked_value))
        cloaked = int(cloaked_value.value)
    except Exception:  # noqa: BLE001
        pass
    return {
        "hwnd": int(hwnd),
        "valid": bool(user32.IsWindow(hwnd)),
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "iconic": bool(user32.IsIconic(hwnd)),
        "foreground": foreground == int(hwnd),
        "cloaked": bool(cloaked),
        "rect": [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)],
    }


def capture_window(hwnd: int, *, full_content: bool = True) -> np.ndarray:
    """Capture one window via PrintWindow; returns a BGR numpy frame.

    Raises WindowCaptureError on invalid hwnd / GDI failure. A black frame is
    returned as-is; callers can reject it with a pixel-variance check.
    """
    if not hwnd:
        raise WindowCaptureError("hwnd is required")
    user32 = _user32()
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise WindowCaptureError("GetWindowRect failed")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 8 or height < 8:
        raise WindowCaptureError(f"window too small: {width}x{height}")

    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        raise WindowCaptureError("GetWindowDC failed")
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    try:
        flag = 2 if full_content else 0  # PW_RENDERFULLCONTENT
        printed = bool(user32.PrintWindow(hwnd, memory_dc, flag))
        if not printed:
            raise WindowCaptureError("PrintWindow failed")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = width
        info.biHeight = -height  # top-down
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = 0  # BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
        if copied != height:
            raise WindowCaptureError(f"GetDIBits copied {copied}/{height} rows")
        array = np.frombuffer(buffer.raw, dtype=np.uint8).reshape(height, width, 4)
        return array[:, :, :3].copy()  # BGRA -> BGR
    finally:
        try:
            gdi32.SelectObject(memory_dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(hwnd, window_dc)
        except Exception:  # noqa: BLE001
            pass


def frame_is_black(frame: Any, *, max_std: float = 1.0) -> bool:
    """True when a captured frame has essentially no pixel variation."""
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return True
    try:
        return float(frame.std()) <= float(max_std)
    except Exception:  # noqa: BLE001
        return True
