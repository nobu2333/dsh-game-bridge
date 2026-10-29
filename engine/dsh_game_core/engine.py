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
    """引擎实例。capturer/ocr 可注入；多显示器时按 output 缓存抓屏器。"""

    def __init__(self, capturer: Any = None, ocr: Any = None, max_width: int = 1280, capturer_factory: Any = None):
        self._capturer = capturer
        self._capturers: dict[int, Any] = {}
        self._capturer_factory = capturer_factory
        self._ocr = ocr
        self._max_width = max_width
        self._last_gray = None
        self._last_grab_at = None

    def _ensure_ocr(self) -> None:
        if self._ocr is None:
            from .ocr import Ocr

            self._ocr = Ocr()

    def _capturer_for(self, output_idx: int):
        # 注入的 capturer（单测）永远优先，且不区分 output。
        if self._capturer is not None:
            return self._capturer
        if output_idx not in self._capturers:
            if self._capturer_factory is not None:
                self._capturers[output_idx] = self._capturer_factory(output_idx)
            else:
                from .capture import ScreenCapturer

                self._capturers[output_idx] = ScreenCapturer(output_idx=output_idx)
        return self._capturers[output_idx]

    def _resolve_output(self, monitor: dict | None) -> int:
        if not monitor:
            return 0
        from .capture import list_monitors, match_output_index

        index = match_output_index(monitor, list_monitors())
        if index is None:
            raise EngineError(
                "MONITOR_UNSUPPORTED",
                f"没有与窗口所在显示器匹配的抓屏输出（{monitor.get('width')}x{monitor.get('height')}）",
            )
        return index

    def snapshot(
        self,
        *,
        ocr: bool = True,
        max_width: int | None = None,
        region: dict | None = None,
        monitor: dict | None = None,
    ) -> dict:
        import cv2

        output_idx = self._resolve_output(monitor)
        frame = self._capturer_for(output_idx).grab()
        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            raise EngineError("BAD_FRAME", f"抓到的不是三通道图像：{type(frame)}")

        crop = None
        if region:  # 有 monitor 时 region 已换算成该显示器的相对坐标
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
            self._ensure_ocr()
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

    def grab_diff(self, monitor: dict | None = None) -> dict:
        """抓一帧并和上一帧做差分，返回廉价事件（不跑 OCR）。

        这是观测层最便宜的信号：不调模型、不做识别，只回答「画面刚才变了没有、
        变得多剧烈」。阈值**未按具体游戏校准**，所以输出原始指标 + 粗分类，
        由模型自己判断，不假装能识别「掉血」这种语义。
        """
        import cv2

        output_idx = self._resolve_output(monitor)
        frame = self._capturer_for(output_idx).grab()
        if not isinstance(frame, np.ndarray) or frame.ndim != 3:
            raise EngineError("BAD_FRAME", f"抓到的不是三通道图像：{type(frame)}")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        target_width = 160
        scale = target_width / float(width) if width > target_width else 1.0
        small = cv2.resize(
            gray,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        ).astype(np.int16)

        now = time.time()
        elapsed_ms = None if self._last_grab_at is None else int((now - self._last_grab_at) * 1000)
        previous, self._last_gray = self._last_gray, small
        self._last_grab_at = now

        if previous is None:
            return {
                "event": "baseline",
                "mean_diff": 0.0,
                "changed_ratio": 0.0,
                "elapsed_ms": elapsed_ms,
                "width": int(small.shape[1]),
                "height": int(small.shape[0]),
            }

        delta = np.abs(small - previous)
        mean_diff = float(delta.mean())
        changed_ratio = float((delta > 12).mean())
        if changed_ratio >= 0.35:
            event = "scene_cut"
        elif changed_ratio >= 0.01:
            event = "changed"
        else:
            event = "static"
        return {
            "event": event,
            "mean_diff": round(mean_diff, 2),
            "changed_ratio": round(changed_ratio, 4),
            "elapsed_ms": elapsed_ms,
            "width": int(small.shape[1]),
            "height": int(small.shape[0]),
        }

    def reset_diff(self) -> None:
        """丢掉差分基线：重新 attach 时调用，避免拿旧画面误判。"""
        self._last_gray = None
        self._last_grab_at = None

    def close(self) -> None:
        capturers, self._capturers = self._capturers, {}
        injected, self._capturer = self._capturer, None
        for capturer in [injected, *capturers.values()]:
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
