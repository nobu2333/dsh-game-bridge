import numpy as np

from dsh_game_core.probe import frame_change, pack_draft, summarize_effects


def _square(frame, x, y, size=12, value=255):
    frame[y : y + size, x : x + size] = value
    return frame


def test_frame_change_detects_a_moved_square():
    before = np.zeros((100, 200, 3), np.uint8)
    after = before.copy()
    _square(after, 40, 20)
    report = frame_change(before, after)
    assert report["valid"] is True
    assert report["changed"] is True
    assert report["ratio"] > 0
    assert report["center"][0] == 0.23
    assert report["center"][1] == 0.26


def test_frame_change_identical_and_shape_mismatch():
    frame = np.zeros((100, 200, 3), np.uint8)
    same = frame_change(frame, frame.copy())
    assert same == {"valid": True, "changed": False, "pixels": 0, "ratio": 0.0, "bbox": None, "center": None}
    mismatch = frame_change(frame, np.zeros((90, 200, 3), np.uint8))
    assert mismatch["valid"] is False


def test_summarize_effects_ranks_keys():
    records = [
        {"key": "LEFT", "change": {"changed": False, "ratio": 0.0}},
        {"key": "ENTER", "change": {"changed": True, "ratio": 0.2, "center": [0.5, 0.5]}},
    ]
    summary = summarize_effects(records)
    assert summary[0]["key"] == "ENTER"
    assert summary[0]["ratio"] == 0.2


def test_pack_draft_is_valid_and_does_not_guess_controls():
    window = {"title": "Example Game", "process": "game.exe", "width": 800, "height": 600}
    records = [{"key": "ENTER", "change": {"changed": True, "ratio": 0.2, "center": [0.5, 0.5]}}]
    pack = pack_draft(window, records, ocr_texts=["START", "OPTIONS"])
    assert pack["schema"] == 1
    assert pack["id"] == "probe.example-game"
    assert pack["controls"] == {}
    assert pack["capabilities"]["observe.ui"]["level"] == 1
    assert pack["probe"]["key_effects"][0]["key"] == "ENTER"
    assert pack["probe"]["ocr_texts"] == ["START", "OPTIONS"]
