"""帧差分事件：baseline / static / changed / scene_cut 的分类与基线重置。

用确定性的合成帧，不碰真实屏幕。
"""

import numpy as np

from dsh_game_core.engine import GameEngine


class SeqCapturer:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def grab(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame

    def close(self):
        pass


def solid(value: int, height: int = 120, width: int = 160):
    return np.full((height, width, 3), value, dtype=np.uint8)


def with_patch(base: int, patch: int, size: int = 40, height: int = 120, width: int = 160):
    frame = solid(base, height, width)
    frame[20 : 20 + size, 20 : 20 + size] = patch
    return frame


def test_first_call_is_baseline_then_static_then_scene_cut():
    engine = GameEngine(capturer=SeqCapturer([solid(10), solid(10), solid(220)]))

    first = engine.grab_diff()
    assert first["event"] == "baseline"
    assert first["changed_ratio"] == 0.0

    second = engine.grab_diff()
    assert second["event"] == "static"
    assert second["elapsed_ms"] is not None

    third = engine.grab_diff()
    assert third["event"] == "scene_cut"
    assert third["changed_ratio"] > 0.35


def test_local_change_is_changed_not_scene_cut():
    engine = GameEngine(capturer=SeqCapturer([solid(10), with_patch(10, 240)]))

    engine.grab_diff()
    event = engine.grab_diff()
    assert event["event"] == "changed"
    assert 0.01 <= event["changed_ratio"] < 0.35


def test_reset_diff_forces_a_new_baseline():
    engine = GameEngine(capturer=SeqCapturer([solid(10), solid(200)]))
    engine.grab_diff()
    engine.reset_diff()
    assert engine.grab_diff()["event"] == "baseline"
