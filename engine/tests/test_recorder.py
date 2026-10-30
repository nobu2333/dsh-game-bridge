"""EpisodeRecorder：环形缓冲、落盘结构、容错。"""

import json
from pathlib import Path

import numpy as np

from dsh_game_core.recorder import EpisodeRecorder


def frame(width=320, height=180):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 80
    return image


def test_recorder_saves_episode(tmp_path):
    recorder = EpisodeRecorder(tmp_path, max_frames=3, thumb_width=160)
    recorder.start({"game": "cuphead", "level": "forest-follies"})
    for index in range(5):
        recorder.add_frame(frame(), {"player": {"x": index / 10}}, at=index)
    recorder.add_event({"type": "damage", "hp_before": 3, "hp_after": 2}, at=5)
    saved = recorder.save("test")
    assert saved is not None
    directory = Path(saved)
    assert (directory / "meta.json").exists()
    assert (directory / "events.jsonl").exists()
    assert (directory / "frames.jsonl").exists()
    assert len(list((directory / "frames").glob("*.jpg"))) == 3  # ring buffer
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["game"] == "cuphead"
    assert meta["frame_count"] == 3
    assert meta["event_count"] == 1
    events = (directory / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[0])["type"] == "damage"


def test_recorder_tolerates_bad_input(tmp_path):
    recorder = EpisodeRecorder(tmp_path)
    recorder.start()
    recorder.add_frame(None)
    recorder.add_frame(np.zeros((0, 0, 3), dtype=np.uint8))
    recorder.add_event(None)
    assert recorder.snapshot()["frames"] == 0
    assert recorder.save("empty") is not None
