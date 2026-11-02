
from dsh_game_core.effect_classifier import (
    classify_motion,
    classify_visual,
    motion_to_candidates,
    visual_to_candidates,
)


def test_classify_motion_jump_and_dash():
    jump = classify_motion({"key": "Z", "max_abs_dy": 0.28, "max_abs_dx": 0.01})
    assert jump["action"] == "jump"
    assert jump["key"] == "Z"
    dash = classify_motion({"key": "SHIFT", "max_abs_dx": 0.10, "max_abs_dy": 0.01})
    assert dash["action"] == "dash"
    assert classify_motion({"key": "X", "max_abs_dx": 0.01, "max_abs_dy": 0.01}) is None


def test_classify_visual_menu_vs_effect():
    menu = classify_visual({"key": "ESC", "diff": 63.9, "changed": True})
    assert menu["action"] == "menu"
    effect = classify_visual({"key": "X", "diff": 4.1, "changed": True})
    assert effect["action"] == "effect_x"
    assert classify_visual({"key": "Q", "diff": 0.0, "changed": False}) is None


def test_converters():
    motion = motion_to_candidates([
        {"key": "Z", "max_abs_dy": 0.28},
        {"key": "SHIFT", "max_abs_dx": 0.10},
    ])
    assert {item["action"] for item in motion} == {"jump", "dash"}
    visual = visual_to_candidates({"ESC": {"key": "ESC", "diff": 50, "changed": True}})
    assert visual[0]["action"] == "menu"
