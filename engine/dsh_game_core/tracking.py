"""轻量实体跟踪：把逐帧「运动簇」变成带 ID / 速度 / 年龄的轨迹（通用层）。

不依赖游戏：输入是 `state.cheap_entities` 的检测框（kind/x/y/score），
输出是稳定 ID 的轨迹。策略层据此判断「敌人是在靠近还是远离、在玩家前面还是背后」，
并过滤掉持续射击产生的己方子弹。

设计取舍：
- 最近邻关联 + 线性预测，先不上 Kalman（数据量小、实现简单、可解释）；
- 检测丢失最多保留 `max_miss` 拍，避免闪烁导致 ID 抖动；
- 速度用「归一化坐标/秒」，与分辨率无关；
- 纯 Python + dataclass，不做任何 I/O，不抛异常（垃圾输入返回空）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Track:
    id: int
    kind: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    age: int = 1
    missed: int = 0
    last_t: float = 0.0
    score: float = 0.0

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "vx": round(self.vx, 4),
            "vy": round(self.vy, 4),
            "speed": round(self.speed, 4),
            "age": self.age,
            "score": round(self.score, 4),
        }


class EntityTracker:
    """最近邻关联的实体跟踪器。``update`` 每拍调用一次。"""

    def __init__(self, *, match_radius: float = 0.08, max_miss: int = 3) -> None:
        self.match_radius = max(0.01, float(match_radius))
        self.max_miss = max(1, int(max_miss))
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._tracks = {}
        self._next_id = 1

    def tracks(self) -> list[Track]:
        return [track for track in self._tracks.values() if track.missed == 0]

    def update(self, detections, now: float) -> list[Track]:
        try:
            now = float(now)
        except (TypeError, ValueError):
            now = 0.0
        items = []
        for detection in detections or ():
            if not isinstance(detection, dict):
                continue
            try:
                x = float(detection.get("x"))
                y = float(detection.get("y"))
            except (TypeError, ValueError):
                continue
            items.append(
                {
                    "kind": str(detection.get("kind") or "threat"),
                    "x": x,
                    "y": y,
                    "score": float(detection.get("score") or 0.0),
                }
            )

        unmatched = list(self._tracks.values())
        matched_ids: set[int] = set()
        for item in items:
            best = None
            best_distance = self.match_radius
            for track in unmatched:
                distance = math.hypot(track.x - item["x"], track.y - item["y"])
                if distance <= best_distance:
                    best = track
                    best_distance = distance
            if best is None:
                track = Track(
                    id=self._next_id,
                    kind=item["kind"],
                    x=item["x"],
                    y=item["y"],
                    last_t=now,
                    score=item["score"],
                )
                self._next_id += 1
                self._tracks[track.id] = track
                matched_ids.add(track.id)
                continue
            dt = max(1e-3, now - best.last_t) if best.last_t else 0.05
            # 速度用指数平滑，避免单帧关联噪声造成闪避抖动。
            new_vx = (item["x"] - best.x) / dt
            new_vy = (item["y"] - best.y) / dt
            best.vx = best.vx * 0.5 + new_vx * 0.5
            best.vy = best.vy * 0.5 + new_vy * 0.5
            best.x = item["x"]
            best.y = item["y"]
            best.kind = item["kind"]
            best.score = item["score"]
            best.last_t = now
            best.age += 1
            best.missed = 0
            unmatched.remove(best)
            matched_ids.add(best.id)

        for track in unmatched:
            track.missed += 1
        for track_id in list(self._tracks):
            if self._tracks[track_id].missed > self.max_miss:
                del self._tracks[track_id]
        return self.tracks()


def relative_relation(track: Track, anchor: tuple[float, float], *, behind_band: float = 0.04) -> str:
    """实体相对玩家锚点的方位：ahead / behind / above / below / same。"""
    dx = track.x - anchor[0]
    dy = track.y - anchor[1]
    if abs(dx) <= behind_band and abs(dy) <= behind_band:
        return "same"
    if abs(dx) >= abs(dy):
        return "ahead" if dx > 0 else "behind"
    return "below" if dy > 0 else "above"


def approaching_speed(track: Track, anchor: tuple[float, float]) -> float:
    """速度朝玩家方向的分量（归一化/秒）；负值表示远离。"""
    dx = anchor[0] - track.x
    dy = anchor[1] - track.y
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0.0
    return (track.vx * dx + track.vy * dy) / length
