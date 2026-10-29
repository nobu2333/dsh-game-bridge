"""引擎核心：一次 snapshot = 抓一帧 → 缩放 → PNG 编码 → OCR。

对外契约（插件侧只依赖这一份形状）：
    {"png_b64": str, "width": int, "height": int, "scale": float,
     "ocr": [{"text", "score", "left", "top", "right", "bottom"}],
     "captured_at_ms": int}

错误一律抛 EngineError，由 stdio 层翻译成 {"ok": false, "error": {...}}。
"""

from __future__ import annotations

import base64
import time
from typing import Any

import numpy as np


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class GameEngine:
    """一台显示器 = 一个引擎实例。capturer/ocr 可注入，便于单测。"""

    def __init__(self, capturer: Any = None, ocr: Any = None, max_width: int = 1280):
        self._capturer = capturer
        self._ocr = ocr
        self._max_width = max_width

    def _ensure(self) -> None:
        if self._capturer is None:
            from .capture import ScreenCapturer

            self._capturer = ScreenCapturer()
        if self._ocr is None:
            from .ocr import Ocr

            self._ocr = Ocr()

    def snapshot(self, *, ocr: bool = True, max_width: int | None = None, region: dict | None = None) -> dict:
        import cv2

        self._ensure()
        frame = self._capturer.grab()
        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            raise EngineError("BAD_FRAME", f"抓到的不是三通道图像：{type(frame)}")

        crop = None
        if region:
            try:
                left = max(0, int(region["left"]))
                top = max(0, int(region["top"]))
                right = min(frame.shape[1], left + int(region["width"]))
                bottom = min(frame.shape[0], top + int(region["height"]))
            except (KeyError, TypeError, ValueError) as error:
                raise EngineError("BAD_REGION", f"region 参数不合法：{region!r}") from error
            if right - left < 8 or bottom - top < 8:
                raise EngineError("BAD_REGION", f"region 裁剪后太小：{region!r}")
            frame = frame[top:bottom, left:right]
            crop = {"left": left, "top": top, "width": right - left, "height": bottom - top}

        height, width = frame.shape[:2]
        limit = max_width or self._max_width
        scale = 1.0
        if limit and width > limit:
            scale = limit / float(width)
            frame = cv2.resize(
                frame,
                (int(round(width * scale)), int(round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise EngineError("ENCODE_FAILED", "PNG 编码失败")

        lines = []
        if ocr:
            try:
                lines = [line.to_dict() for line in self._ocr.read(frame)]
            except Exception as error:  # noqa: BLE001 - OCR 挂了不该让截图一起失败
                lines = []
                lines_error = f"{type(error).__name__}: {error}"
            else:
                lines_error = None
        else:
            lines_error = None

        result = {
            "png_b64": base64.b64encode(encoded.tobytes()).decode("ascii"),
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "scale": round(scale, 4),
            "ocr": lines,
            "captured_at_ms": int(time.time() * 1000),
        }
        if crop:
            result["region"] = crop
        if lines_error:
            result["ocr_error"] = lines_error
        return result

    def close(self) -> None:
        capturer, self._capturer = self._capturer, None
        if capturer is not None and hasattr(capturer, "close"):
            try:
                capturer.close()
            except Exception:  # noqa: BLE001 - 释放失败不掩盖主流程
                pass
        # DXcam 内部是 COM 对象；显式回收能避免解释器退出时 comtypes 在
        # 已反初始化的 COM 上再 Release 一次（实测会打印 access violation）。
        try:
            import gc

            gc.collect()
        except Exception:  # noqa: BLE001
            pass
