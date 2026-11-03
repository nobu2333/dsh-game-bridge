"""Level Memory：按关卡分段的死亡/受击/成功动作记忆。

引擎不认游戏名/关卡名；game_id/level_id 由 session 传入。segment 由 scroll 桶
生成，不是写死的坐标脚本。

用途：
- 反复死亡的 segment -> hotspot；
- 某个 segment 下 jump/dash/advance 的成功率；
- 下次进入时提高风险/选用更优动作（由调用方决定）。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
ACTIONS = ("advance", "jump", "dash", "retreat", "wait", "attack")


def safe_id(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text or not ID_RE.match(text):
        return default
    return text


def segment_key(scroll_s: float, *, bucket: float = 0.5) -> str:
    width = max(0.1, float(bucket))
    index = int(round(float(scroll_s) / width))
    return f"s:{index}"


class LevelMemory:
    def __init__(self, game_id: str, level_id: str, *, bucket: float = 0.5) -> None:
        self.game_id = safe_id(game_id)
        self.level_id = safe_id(level_id)
        self.bucket = max(0.1, float(bucket))
        self.updated_at = time.time()
        self.segments: dict[str, dict] = {}

    def _segment(self, scroll_s: float) -> dict:
        key = segment_key(scroll_s, bucket=self.bucket)
        segment = self.segments.get(key)
        if segment is None:
            segment = {
                "key": key,
                "visits": 0,
                "deaths": 0,
                "damage": 0,
                "causes": {},
                "actions": {},
                "last_success": [],
                "updated_at": time.time(),
            }
            self.segments[key] = segment
        segment["updated_at"] = time.time()
        return segment

    def observe(self, scroll_s: float) -> None:
        self._segment(scroll_s)["visits"] += 1

    def record_death(self, scroll_s: float, cause: str | None = None) -> dict:
        segment = self._segment(scroll_s)
        segment["deaths"] += 1
        label = str(cause or "unknown")[:24]
        segment.setdefault("causes", {})
        segment["causes"][label] = int(segment["causes"].get(label) or 0) + 1
        return segment

    def record_damage(self, scroll_s: float, amount: int = 1) -> dict:
        segment = self._segment(scroll_s)
        segment["damage"] += max(0, int(amount))
        return segment

    def record_action(self, scroll_s: float, action: str, *, good: bool) -> dict:
        action = safe_id(action, "unknown")
        segment = self._segment(scroll_s)
        bucket = segment["actions"].setdefault(action, {"n": 0, "good": 0})
        bucket["n"] += 1
        if good:
            bucket["good"] += 1
            segment["last_success"] = (segment["last_success"] + [action])[-8:]
        return segment

    def query(self, scroll_s: float) -> dict | None:
        return self.segments.get(segment_key(scroll_s, bucket=self.bucket))

    def _near_segments(self, scroll_s: float, radius: float) -> list[dict]:
        center = int(round(float(scroll_s) / self.bucket))
        width = max(1, int(round(float(radius) / self.bucket)))
        result = []
        for offset in range(-width, width + 1):
            key = f"s:{center + offset}"
            segment = self.segments.get(key)
            if segment:
                result.append(segment)
        return result

    def zone_deaths(self, scroll_s: float, *, radius: float = 1.5) -> int:
        return sum(int(seg.get("deaths") or 0) for seg in self._near_segments(scroll_s, radius))

    def zone_damage(self, scroll_s: float, *, radius: float = 1.5) -> int:
        return sum(int(seg.get("damage") or 0) for seg in self._near_segments(scroll_s, radius))

    def hotspot(self, scroll_s: float, *, min_deaths: int = 2, radius: float = 1.5) -> bool:
        return self.zone_deaths(scroll_s, radius=radius) >= min_deaths

    def preferred_action(self, scroll_s: float, *, min_samples: int = 2) -> str | None:
        segment = self.query(scroll_s)
        if not segment:
            return None
        best = None
        best_rate = -1.0
        for action, stats in (segment.get("actions") or {}).items():
            n = int(stats.get("n") or 0)
            if n < min_samples:
                continue
            rate = float(stats.get("good") or 0) / n
            if rate > best_rate:
                best_rate = rate
                best = action
        return best

    def summary(self) -> dict:
        segments = len(self.segments)
        deaths = sum(int(seg.get("deaths") or 0) for seg in self.segments.values())
        damage = sum(int(seg.get("damage") or 0) for seg in self.segments.values())
        hotspots = 0
        causes: dict[str, int] = {}
        for segment in self.segments.values():
            for name, count in (segment.get("causes") or {}).items():
                causes[name] = causes.get(name, 0) + int(count or 0)
        for key in self.segments:
            try:
                scroll = int(str(key).split(":", 1)[1]) * self.bucket
            except (ValueError, IndexError):
                continue
            if self.zone_deaths(scroll) >= 2:
                hotspots += 1
        return {"game": self.game_id, "level": self.level_id, "segments": segments, "deaths": deaths, "damage": damage, "hotspots": hotspots, "causes": causes}

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "game": self.game_id,
            "level": self.level_id,
            "bucket": self.bucket,
            "updated_at": self.updated_at,
            "segments": self.segments,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "LevelMemory":
        game = safe_id((payload or {}).get("game"))
        level = safe_id((payload or {}).get("level"))
        memory = cls(game, level, bucket=float((payload or {}).get("bucket") or 0.5))
        memory.updated_at = float((payload or {}).get("updated_at") or time.time())
        for key, raw in ((payload or {}).get("segments") or {}).items():
            if not isinstance(raw, dict):
                continue
            memory.segments[str(key)] = raw
        return memory

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, *, game_id: str = "unknown", level_id: str = "unknown") -> "LevelMemory":
        target = Path(path)
        if not target.is_file():
            return cls(game_id, level_id)
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))
