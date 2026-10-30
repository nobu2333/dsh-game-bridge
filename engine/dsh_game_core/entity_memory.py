"""实体记忆：把匿名轨迹变成有外观身份、行为角色和统计的对象。

这是「看」从运动簇走向对象级理解的最小实现：
- 外观签名：轨迹附近的颜色直方图，余弦聚类成对象原型；
- 行为角色：approaching / harmful / chaser / projectile；由运动与 HP 结果推断；
- 统计：每个对象簇/轨迹的遭遇、伤害次数、是否追击；
- 纯数据，不依赖策略；策略只消费 observations。

设计取舍：
- 外观用 4x4x4 RGB 直方图（轻量、对动画有一定鲁棒性），不做深度 embedding；
- 角色是行为语义，不要求知道 sprite 名字；
- 所有方法尽力不抛异常；没有 frame 时仍可推断运动角色。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np

EMBED_BINS = 4
CLUSTER_SIMILARITY = 0.92
APPROACH_SPEED = 0.045
CHASER_AGE = 8
CHASER_DISTANCE = 0.55
PROJECTILE_SPEED = 0.65


def appearance_signature(frame: np.ndarray, track: Any, *, width_ratio: float = 0.09, height_ratio: float = 0.13) -> np.ndarray | None:
    """Color histogram around a track centre; L1-normalized, None if unusable."""
    try:
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
            return None
        height, width = frame.shape[:2]
        bw = max(6, int(width * width_ratio))
        bh = max(6, int(height * height_ratio))
        cx = int(float(track.x) * width)
        cy = int(float(track.y) * height)
        x0, x1 = max(0, cx - bw // 2), min(width, cx + bw // 2 + 1)
        y0, y1 = max(0, cy - bh // 2), min(height, cy + bh // 2 + 1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        crop = frame[y0:y1, x0:x1].astype(np.float32)
        # BGR -> quantize
        indices = np.clip((crop / 64.0).astype(np.int32), 0, EMBED_BINS - 1)
        flat = indices[:, :, 0] * (EMBED_BINS * EMBED_BINS) + indices[:, :, 1] * EMBED_BINS + indices[:, :, 2]
        histogram = np.bincount(flat.ravel(), minlength=EMBED_BINS**3).astype(np.float32)
        total = float(histogram.sum())
        if total <= 0:
            return None
        return histogram / total
    except Exception:  # noqa: BLE001
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 1e-8:
        return 0.0
    return float(np.dot(a, b) / denominator)


class EntityMemory:
    def __init__(
        self,
        *,
        similarity: float = CLUSTER_SIMILARITY,
        approach_speed: float = APPROACH_SPEED,
        chaser_age: int = CHASER_AGE,
        chaser_distance: float = CHASER_DISTANCE,
        projectile_speed: float = PROJECTILE_SPEED,
    ) -> None:
        self.similarity = similarity
        self.approach_speed = approach_speed
        self.chaser_age = chaser_age
        self.chaser_distance = chaser_distance
        self.projectile_speed = projectile_speed
        self._clusters: list[dict] = []
        self._tracks: dict[int, dict] = {}
        self._last_hp: int | None = None

    def clusters(self) -> list[dict]:
        return [dict(cluster) for cluster in self._clusters]

    def track_record(self, track_id: int) -> dict | None:
        record = self._tracks.get(track_id)
        return dict(record) if record else None

    def _assign_cluster(self, signature: np.ndarray, now: float) -> int:
        best = None
        best_similarity = self.similarity
        for cluster in self._clusters:
            similarity = _cosine(signature, cluster["signature"])
            if similarity >= best_similarity:
                best = cluster
                best_similarity = similarity
        if best is None:
            cluster = {
                "id": len(self._clusters) + 1,
                "signature": signature.copy(),
                "count": 0,
                "harmful_hits": 0,
                "approaching": 0,
                "last_seen": now,
            }
            self._clusters.append(cluster)
            return cluster["id"]
        best["signature"] = (best["signature"] * 0.85 + signature * 0.15).astype(np.float32)
        best["last_seen"] = now
        return best["id"]

    def update(
        self,
        tracks: list[Any],
        frame: np.ndarray | None,
        anchor: tuple[float, float],
        *,
        hp: int | None = None,
        now: float = 0.0,
    ) -> list[dict]:
        try:
            observations: list[dict] = []
            ax, ay = anchor
            hp_drop = hp is not None and self._last_hp is not None and hp < self._last_hp
            self._last_hp = hp if hp is not None else self._last_hp
            seen: set[int] = set()
            for track in tracks or []:
                try:
                    track_id = int(track.id)
                    distance = math.hypot(float(track.x) - ax, float(track.y) - ay)
                except Exception:  # noqa: BLE001
                    continue
                seen.add(track_id)
                record = self._tracks.setdefault(
                    track_id,
                    {"age": 0, "cluster": None, "approaching": 0, "chaser": False},
                )
                record["age"] += 1
                approach = _approach_speed(track, anchor)
                if approach > self.approach_speed:
                    record["approaching"] += 1
                    record["last_approach_at"] = now
                record["chaser"] = bool(
                    record["approaching"] >= 3
                    and record["age"] >= self.chaser_age
                    and distance <= self.chaser_distance
                )
                signature = appearance_signature(frame, track) if frame is not None else None
                cluster_id = record.get("cluster")
                if signature is not None:
                    cluster_id = self._assign_cluster(signature, now)
                    record["cluster"] = cluster_id
                if cluster_id is not None and 1 <= cluster_id <= len(self._clusters):
                    cluster = self._clusters[cluster_id - 1]
                    cluster["count"] += 1
                    if approach > self.approach_speed:
                        cluster["approaching"] += 1
                    if hp_drop and distance <= 0.25:
                        cluster["harmful_hits"] += 1
                if record.get("chaser"):
                    role = "chaser"
                elif record["approaching"] > 0:
                    role = "approaching"
                elif float(getattr(track, "speed", 0.0)) >= self.projectile_speed:
                    role = "projectile"
                else:
                    role = "unknown"
                observations.append(
                    {
                        "id": track_id,
                        "cluster": cluster_id,
                        "role": role,
                        "distance": round(distance, 3),
                        "behind": float(track.x) < ax - 0.04,
                        "approaching": approach > self.approach_speed,
                        "harmful_hits": self._clusters[cluster_id - 1]["harmful_hits"]
                        if cluster_id and 1 <= cluster_id <= len(self._clusters)
                        else 0,
                    }
                )
            for track_id in list(self._tracks):
                if track_id not in seen:
                    self._tracks[track_id]["age"] += 0
            return observations
        except Exception:  # noqa: BLE001 - 记忆失败不能影响玩法
            return []

    def role_counts(self) -> dict:
        return {"clusters": len(self._clusters), "tracks": len(self._tracks)}


def _approach_speed(track: Any, anchor: tuple[float, float]) -> float:
    try:
        dx = anchor[0] - float(track.x)
        dy = anchor[1] - float(track.y)
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            return 0.0
        return (float(track.vx) * dx + float(track.vy) * dy) / length
    except Exception:  # noqa: BLE001
        return 0.0
