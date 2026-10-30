"""EpisodeRecorder：15 秒级环形缓冲，把「一局/一次死亡」落成可复盘的数据。

只存缩略图（默认 240px 宽 JPEG）+ WorldState + 输入/事件，不存原始大图；
目录结构和字段保持稳定，方便之后做回放、死亡归因与 profile 补丁评测。

设计原则：
- 录制失败绝不影响游戏（所有方法吞异常）；
- 只在内存里保留环形缓冲，死亡/停止时一次落盘；
- 帧按 10–15Hz 采样即可，复盘看的是时间线，不是逐帧电影。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

EPISODE_SCHEMA = 1
DEFAULT_VERSION = "0.0.2"


def _now(value: Any = None) -> float:
    try:
        return round(float(value if value is not None else time.time()), 3)
    except (TypeError, ValueError):
        return round(time.time(), 3)


class EpisodeRecorder:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_frames: int = 180,
        thumb_width: int = 240,
        version: str = DEFAULT_VERSION,
    ) -> None:
        self.root = Path(root)
        self.max_frames = max(3, int(max_frames))
        self.thumb_width = max(80, int(thumb_width))
        self.version = version
        self._frames: list[dict] = []
        self._events: list[dict] = []
        self._meta: dict = {}
        self._started_at = 0.0

    def start(self, meta: dict | None = None) -> dict:
        self._frames = []
        self._events = []
        self._meta = dict(meta or {})
        self._meta.setdefault("started_at", _now())
        self._started_at = _now()
        return self.snapshot()

    def add_frame(self, frame: Any, state: dict | None = None, *, at: Any = None) -> None:
        try:
            import cv2
            import numpy as np

            if frame is None:
                return
            image = np.asarray(frame)
            if image.ndim != 3 or image.size == 0:
                return
            height, width = image.shape[:2]
            if width > self.thumb_width:
                scale = self.thumb_width / float(width)
                image = cv2.resize(
                    image, (self.thumb_width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA
                )
            ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            if not ok:
                return
            entry = {
                "t": _now(at),
                "jpeg": buffer.tobytes(),
                "state": state if isinstance(state, dict) else None,
            }
            self._frames.append(entry)
            if len(self._frames) > self.max_frames:
                self._frames = self._frames[-self.max_frames :]
        except Exception:  # noqa: BLE001 - 录制失败不影响游戏
            pass

    def add_event(self, event: dict, *, at: Any = None) -> None:
        if not isinstance(event, dict):
            return
        try:
            payload = dict(event)
            payload.setdefault("t", _now(at))
            self._events.append(payload)
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self) -> dict:
        return {
            "schema": EPISODE_SCHEMA,
            "version": self.version,
            "meta": dict(self._meta),
            "frames": len(self._frames),
            "events": len(self._events),
            "started_at": self._started_at,
        }

    def save(self, tag: str = "episode") -> str | None:
        """Write the ring buffer to disk; returns the episode path or None."""
        try:
            safe_tag = "".join(ch for ch in str(tag) if ch.isalnum() or ch in "-_.")[:48] or "episode"
            name = f"{safe_tag}-{int(_now() * 1000)}"
            directory = self.root / name
            (directory / "frames").mkdir(parents=True, exist_ok=True)
            meta = dict(self._meta)
            meta.update(
                {
                    "schema": EPISODE_SCHEMA,
                    "version": self.version,
                    "name": name,
                    "saved_at": _now(),
                    "frame_count": len(self._frames),
                    "event_count": len(self._events),
                }
            )
            (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            with (directory / "events.jsonl").open("w", encoding="utf-8") as handle:
                for event in self._events:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            for index, frame in enumerate(self._frames):
                (directory / "frames" / f"{index:04d}.jpg").write_bytes(frame["jpeg"])
            with (directory / "frames.jsonl").open("w", encoding="utf-8") as handle:
                for index, frame in enumerate(self._frames):
                    handle.write(
                        json.dumps(
                            {"index": index, "t": frame["t"], "state": frame["state"]},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            return str(directory)
        except Exception:  # noqa: BLE001 - 落盘失败不影响游戏
            return None

    def clear(self) -> None:
        self._frames = []
        self._events = []
        self._meta = {}
        self._started_at = 0.0
