"""L1 短时缓冲：从最近 ~600ms 的位置序列估计速度、接近速度与到接触时间。

输入是每拍的 player anchor 与 threats（id/x/y/role），输出带 dx/dy/vx/vy/ttc/side
的瞬时描述。纯数据，不控制游戏。
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _side(dx: float, dy: float) -> str:
    if abs(dy) > 0.18 and abs(dy) > abs(dx) * 0.8:
        return "above" if dy < 0 else "below"
    if dx < -0.04:
        return "left"
    if dx > 0.04:
        return "right"
    return "center"


class TemporalState:
    def __init__(self, history_ms: float = 600.0) -> None:
        self.history_ms = max(120.0, float(history_ms))
        self._player: deque[tuple[float, float, float]] = deque()
        self._threats: dict[int, deque[tuple[float, float, float, str]]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.history_ms / 1000.0
        while self._player and self._player[0][0] < cutoff:
            self._player.popleft()
        for track_id in list(self._threats):
            samples = self._threats[track_id]
            while samples and samples[0][0] < cutoff:
                samples.popleft()
            if not samples:
                del self._threats[track_id]

    def update(self, now: float, player: dict, threats: list[dict]) -> dict:
        now = float(now)
        self._prune(now)
        px = _clamp(_num(player.get("x"), 0.5), 0.0, 1.0)
        py = _clamp(_num(player.get("y"), 0.8), 0.0, 1.0)
        self._player.append((now, px, py))

        active: set[int] = set()
        for raw in threats or []:
            if not isinstance(raw, dict):
                continue
            try:
                track_id = int(raw.get("id"))
            except (TypeError, ValueError):
                continue
            x = _clamp(_num(raw.get("x"), px), 0.0, 1.0)
            y = _clamp(_num(raw.get("y"), py), 0.0, 1.0)
            self._threats.setdefault(track_id, deque()).append((now, x, y, str(raw.get("role") or "")))
            active.add(track_id)
        for track_id in list(self._threats):
            if track_id not in active and self._threats[track_id]:
                # 本拍没检测到：保留历史，但标记为不可见，由调用方决定是否降权。
                pass

        player_velocity = self._velocity(self._player)
        output = []
        for track_id, samples in self._threats.items():
            if not samples:
                continue
            x, y = samples[-1][1], samples[-1][2]
            vx, vy = self._velocity(samples, index=1, index2=2)
            dx, dy = x - px, y - py
            distance = math.hypot(dx, dy)
            closing = -(dx * vx + dy * vy) / max(distance, 1e-6)
            ttc = round(distance / closing, 3) if closing > 0.02 else None
            output.append(
                {
                    "id": track_id,
                    "role": samples[-1][3],
                    "x": round(x, 4),
                    "y": round(y, 4),
                    "dx": round(dx, 4),
                    "dy": round(dy, 4),
                    "vx": round(vx, 4),
                    "vy": round(vy, 4),
                    "distance": round(distance, 4),
                    "closing": round(closing, 4),
                    "ttc": ttc,
                    "side": _side(dx, dy),
                    "visible": track_id in active,
                    "age_ms": round(max(0.0, now - samples[-1][0]) * 1000.0),
                }
            )
        output.sort(key=lambda item: (item["ttc"] is None, item["ttc"] or 9.0, item["distance"]))
        return {
            "player": {"x": round(px, 4), "y": round(py, 4), "vx": player_velocity[0], "vy": player_velocity[1]},
            "threats": output[:8],
        }

    @staticmethod
    def _velocity(samples, index: int = 1, index2: int = 2) -> tuple[float, float]:
        try:
            if len(samples) < 2:
                return 0.0, 0.0
            first = samples[0]
            last = samples[-1]
            dt = max(1e-3, last[0] - first[0])
            return (
                round((last[index] - first[index]) / dt, 3),
                round((last[index2] - first[index2]) / dt, 3),
            )
        except (IndexError, TypeError, ValueError):
            return 0.0, 0.0
