"""DXcam 抓屏（L0 层）。

设计选择沿用已实测的结论：
- **一次性 grab，不开连续捕获线程**：采样率只有 2–5 Hz，grab < 10ms；
  起线程只会抢游戏帧数。
- 抓的是「此刻的最新帧」（new_frame_only=False），不是帧率对齐。
- dxcam 延迟导入：没有装的机器上，本模块仍可被 import（单测用假实现）。

抓屏是只读操作，不抢焦点、不注入输入，符合「不打扰用户」的前提。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class MonitorInfo:
    index: int
    width: int
    height: int
    primary: bool = False


class ScreenCapturer:
    """一台显示器 = 一个实例（dxcam 的模型）。"""

    def __init__(self, output_idx: int = 0, output_color: str = "BGR"):
        import dxcam  # 延迟导入

        self._cam = dxcam.create(output_idx=output_idx, output_color=output_color)
        if self._cam is None:
            raise RuntimeError(
                f"DXcam 无法创建输出 {output_idx}：显示器不存在、被独占或处于远程桌面会话"
            )

    def grab(self) -> np.ndarray:
        """抓当前最新一帧，(H, W, 3) uint8 BGR。"""
        frame = self._cam.grab(new_frame_only=False)
        if frame is None:
            frame = self._cam.grab()
        if frame is None:
            raise RuntimeError("DXcam 抓不到帧：显示器是不是被独占/拔了/远程桌面断了？")
        return frame

    def close(self) -> None:
        try:
            self._cam.release()
        except Exception:  # noqa: BLE001 - 释放失败不应掩盖真实错误
            pass

    def __enter__(self) -> "ScreenCapturer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def list_monitors() -> list[MonitorInfo]:
    """列出可抓的显示器。

    dxcam 没有结构化 API，这里解析它的文本输出，实测格式为：
        Device[0] Output[0]: Res:(1920, 1200) Rot:0 Primary:True
    """
    import re

    import dxcam

    info: list[MonitorInfo] = []
    try:
        text = dxcam.output_info() or ""
    except Exception:  # noqa: BLE001 - 老版本 dxcam 没有 output_info
        return info
    pattern = re.compile(r"Output\[(\d+)\]:\s*Res:\((\d+),\s*(\d+)\)(.*)$", re.MULTILINE)
    for match in pattern.finditer(str(text)):
        index, width, height, rest = match.groups()
        info.append(
            MonitorInfo(index=int(index), width=int(width), height=int(height), primary="Primary:True" in rest)
        )
    return info
