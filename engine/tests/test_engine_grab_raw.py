"""GameEngine.grab_raw：只抓一帧原始 BGR，region 裁剪语义与 snapshot 一致。"""

import numpy as np
import pytest

from dsh_game_core.engine import EngineError, GameEngine


_UNSET = object()


class FakeCapturer:
    """确定性渐变帧：不依赖随机数，失败可复现。"""

    def __init__(self, frame=_UNSET, height=400, width=800):
        if frame is _UNSET:
            rows = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
            frame = np.repeat(np.repeat(rows[:, :, None], width, axis=1), 3, axis=2)
        self.frame = frame
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return self.frame

    def close(self):
        pass


def test_grab_raw_returns_full_frame_without_encoding():
    capturer = FakeCapturer()
    engine = GameEngine(capturer=capturer)

    frame = engine.grab_raw()

    assert isinstance(frame, np.ndarray)
    assert frame.shape == (400, 800, 3)
    assert frame.dtype == np.uint8
    assert np.array_equal(frame, capturer.frame)
    assert capturer.grabs == 1


def test_grab_raw_region_crops_pixels():
    capturer = FakeCapturer()
    engine = GameEngine(capturer=capturer)

    raw = engine.grab_raw(region={"left": 10, "top": 20, "width": 100, "height": 50})

    assert raw.shape == (50, 100, 3)
    assert np.array_equal(raw, capturer.frame[20:70, 10:110])


def test_grab_raw_region_is_clamped_to_frame():
    capturer = FakeCapturer()
    engine = GameEngine(capturer=capturer)

    raw = engine.grab_raw(region={"left": 780, "top": 380, "width": 100, "height": 100})

    assert raw.shape == (20, 20, 3)
    assert np.array_equal(raw, capturer.frame[380:400, 780:800])


@pytest.mark.parametrize(
    "region",
    [
        {"left": 0, "top": 0, "width": 4, "height": 4},  # 裁完太小
        {"left": 0, "top": 0, "width": 100},  # 缺字段
        {"left": "x", "top": 0, "width": 100, "height": 50},  # 非数字
        {"top": 0, "width": 100, "height": 50},  # 缺 left
    ],
)
def test_grab_raw_bad_region_raises(region):
    engine = GameEngine(capturer=FakeCapturer())

    with pytest.raises(EngineError) as caught:
        engine.grab_raw(region=region)
    assert caught.value.code == "BAD_REGION"


@pytest.mark.parametrize("bad_frame", [None, "not-a-frame", np.zeros((10, 10), dtype=np.uint8)])
def test_grab_raw_bad_frame_raises(bad_frame):
    engine = GameEngine(capturer=FakeCapturer(frame=bad_frame))

    with pytest.raises(EngineError) as caught:
        engine.grab_raw()
    assert caught.value.code == "BAD_FRAME"


def test_grab_raw_does_not_touch_diff_baseline():
    """grab_raw 是纯读取：不能把 grab_diff 的基线弄脏。"""
    engine = GameEngine(capturer=FakeCapturer())

    engine.grab_raw()

    assert engine.grab_diff()["event"] == "baseline"
