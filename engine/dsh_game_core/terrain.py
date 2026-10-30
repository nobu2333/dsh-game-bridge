"""平台/地面几何：把地面颜色分割成可站立区域，供落点/边缘判断使用。

当前策略只有「前方变暗就跳」的亮度启发式；这不够做「站到低台再跳高台」。
本模块提供最小几何原语：
- ground_mask: 按 profile 的地面颜色范围分割可站立像素；
- find_ledges: 连通域 → 平台框（归一化）；
- ledge_under_player: 玩家脚下/前方是否还有地面，以及平台边缘位置。

纯 numpy/cv2，不依赖策略；失败返回空/None。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .state import _coerce_frame, _mapping, _number, _clamp  # type: ignore[attr-defined]


def ground_mask(frame_bgr: Any, profile: Any = None) -> np.ndarray | None:
    try:
        frame = _coerce_frame(frame_bgr)
        if frame is None:
            return None
        terrain = _mapping(profile).get("terrain") if isinstance(_mapping(profile), dict) else None
        terrain = terrain if isinstance(terrain, dict) else {}
        colors = terrain.get("ground_colors")
        if not isinstance(colors, (list, tuple)) or not colors:
            return None
        bgr = frame.astype(np.int16)
        b, g, r = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
        mask = np.zeros(frame.shape[:2], dtype=bool)
        for spec in colors:
            if not isinstance(spec, dict):
                continue
            current = np.ones(frame.shape[:2], dtype=bool)
            for channel, values in (("r", r), ("g", g), ("b", b)):
                low = spec.get(f"{channel}_min")
                high = spec.get(f"{channel}_max")
                if low is not None:
                    current &= values >= _number(low, 0)
                if high is not None:
                    current &= values <= _number(high, 255)
            mask |= current
        return mask
    except Exception:  # noqa: BLE001
        return None


def find_ledges(frame_bgr: Any, profile: Any = None, *, min_area: int = 300) -> list[dict]:
    """Return normalized bounding boxes of ground/ledge components, top-left order."""
    try:
        frame = _coerce_frame(frame_bgr)
        mask = ground_mask(frame, profile)
        if frame is None or mask is None:
            return []
        import cv2

        height, width = frame.shape[:2]
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            (mask.astype(np.uint8) * 255), connectivity=8
        )
        ledges: list[dict] = []
        for label in range(1, count):
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            ledges.append(
                {
                    "x": round(x / width, 4),
                    "y": round(y / height, 4),
                    "w": round(w / width, 4),
                    "h": round(h / height, 4),
                    "area": area,
                }
            )
        ledges.sort(key=lambda item: (item["y"], item["x"]))
        return ledges[:12]
    except Exception:  # noqa: BLE001
        return []


def ledge_under_player(frame_bgr: Any, profile: Any = None, anchor: Any = None) -> dict | None:
    """是否有一块可站立地面位于玩家脚下/前方，返回其归一化框与边缘 x。"""
    try:
        if not isinstance(anchor, (list, tuple)) or len(anchor) < 2:
            return None
        ax = _clamp(_number(anchor[0], 0.4), 0.0, 1.0)
        ay = _clamp(_number(anchor[1], 0.8), 0.0, 1.0)
        for ledge in find_ledges(frame_bgr, profile):
            if ledge["x"] <= ax <= ledge["x"] + ledge["w"] and ledge["y"] >= ay - 0.25:
                ledge = dict(ledge)
                ledge["edge_x"] = round(ledge["x"] + ledge["w"], 4)
                return ledge
        return None
    except Exception:  # noqa: BLE001
        return None
