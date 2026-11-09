import numpy as np

from dsh_game_core.probe import (
    frame_change,
    infer_controls,
    menu_options,
    menu_transition,
    pack_draft,
    summarize_effects,
)


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
    assert pack["probe"]["menu"]["START"] == ["START"]
    assert pack["probe"]["suggested_controls"]["confirm"] == ["ENTER"]


def test_menu_and_control_suggestions_are_evidence_only():
    texts = ["PRESS START", "OPTIONS", "QUIT GAME"]
    assert set(menu_options(texts)) == {"START", "OPTIONS", "QUIT"}
    records = [
        {"key": "ENTER", "change": {"changed": True, "ratio": 0.3}},
        {"key": "DOWN", "change": {"changed": True, "ratio": 0.01}},
        {"key": "ESC", "change": {"changed": True, "ratio": 0.2}},
        {"key": "SPACE", "change": {"changed": False, "ratio": 0.0}},
    ]
    suggestions = infer_controls(records)
    assert suggestions["confirm"] == ["ENTER"]
    assert suggestions["cancel"] == ["ESC"]
    assert suggestions["move"] == {"down": ["DOWN"]}
    assert suggestions["ranked"][0]["key"] == "ENTER"


def test_menu_transition_and_verified_confirm():
    before = ["PRESS START", "OPTIONS"]
    after = ["START", "OPTIONS", "CONTINUE"]
    transition = menu_transition(before, after)
    assert transition["added"] == ["CONTINUE"]
    assert transition["removed"] == []
    assert transition["changed"] is True
    records = [
        {"key": "ENTER", "change": {"changed": True, "ratio": 0.3}, "ocr_changed": True},
        {"key": "Z", "change": {"changed": True, "ratio": 0.2}, "ocr_changed": False},
    ]
    suggestions = infer_controls(records)
    assert suggestions["confirm"] == ["ENTER", "Z"]
    assert suggestions["verified_confirm"] == ["ENTER"]
