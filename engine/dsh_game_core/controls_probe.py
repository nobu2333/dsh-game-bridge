"""按键探测状态机（纯逻辑，不碰游戏）。

调用方负责：抓 before 帧 → 按 next_action().key → 等待 → 抓 after 帧 → submit()。
本模块只做：
- 逐个候选键的调度；
- 画面变化判定；
- 输出 changing keys / probe profile 候选。

真正把 key 映射成 jump/attack 需要后续场景/菜单上下文；这里先回答“这个键有没有效果”。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_KEYS = (
    "RIGHT",
    "LEFT",
    "UP",
    "DOWN",
    "Z",
    "X",
    "C",
    "V",
    "SHIFT",
    "SPACE",
    "ENTER",
    "ESC",
)
DEFAULT_PRESS_MS = 160
DEFAULT_CHANGE_THRESHOLD = 0.8


def frame_diff(before: np.ndarray, after: np.ndarray, *, width: int = 160) -> float:
    """Downscaled mean abs difference (0..255 scale); never raises."""
    try:
        if before is None or after is None or before.shape != after.shape:
            return 0.0
        step = max(1, int(before.shape[1]) // max(20, width))
        small_before = before[::step, ::step].astype(np.float32)
        small_after = after[::step, ::step].astype(np.float32)
        if small_before.ndim == 3:
            small_before = small_before.mean(axis=2)
            small_after = small_after.mean(axis=2)
        return float(np.abs(small_after - small_before).mean())
    except Exception:  # noqa: BLE001
        return 0.0


@dataclass
class ProbeAction:
    key: str
    press_ms: int
    index: int


class ControlsProbe:
    def __init__(
        self,
        keys: tuple[str, ...] | list[str] = DEFAULT_KEYS,
        *,
        press_ms: int = DEFAULT_PRESS_MS,
        change_threshold: float = DEFAULT_CHANGE_THRESHOLD,
    ) -> None:
        self.keys = [str(key) for key in keys]
        self.press_ms = max(20, int(press_ms))
        self.change_threshold = max(0.0, float(change_threshold))
        self._next_index = 0
        self._current: ProbeAction | None = None
        self._results: dict[str, dict] = {}

    def next_action(self) -> ProbeAction | None:
        """Return the next key to press, or None when the probe is finished."""
        if self._current is not None:
            return self._current
        if self._next_index >= len(self.keys):
            return None
        action = ProbeAction(key=self.keys[self._next_index], press_ms=self.press_ms, index=self._next_index)
        self._next_index += 1
        self._current = action
        return action

    def submit(self, before: np.ndarray, after: np.ndarray) -> dict:
        """Record the result for the action returned by next_action()."""
        if self._current is None:
            return {}
        action = self._current
        self._current = None
        difference = frame_diff(before, after)
        record = {
            "key": action.key,
            "diff": round(difference, 3),
            "changed": difference >= self.change_threshold,
        }
        self._results[action.key] = record
        return record

    def results(self) -> dict[str, dict]:
        return dict(self._results)

    def changed_keys(self) -> list[str]:
        return [key for key, record in self._results.items() if record.get("changed")]

    def profile_candidates(self) -> list[dict]:
        """Non-semantic candidates: key had a visible effect (source=probe)."""
        return [
            {
                "key": key,
                "effect": "screen_change",
                "diff": record["diff"],
                "source": "probe",
                "confidence": min(0.95, 0.4 + record["diff"] / 10.0),
            }
            for key, record in self._results.items()
            if record.get("changed")
        ]

    def done(self) -> bool:
        return self._current is None and self._next_index >= len(self.keys)
