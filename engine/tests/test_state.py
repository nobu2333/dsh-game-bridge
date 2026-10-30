"""state.py 单元测试：HP / 场景 / 廉价实体（parry + 移动威胁）/ 容错 / 归一化坐标。

全部用确定性合成帧，不碰真实屏幕、真实游戏或本地路径。
"""

from __future__ import annotations

import time

import numpy as np

from dsh_game_core import state as state_module
from dsh_game_core.state import (
    STATE_SCHEMA,
    cheap_entities,
    detect_scene,
    extract_hp,
    extract_visual_state,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_frame(height=120, width=160, color=(0, 0, 0)):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def ocr_line(text, score=0.9, left=0, top=0, right=10, bottom=10):
    return {"text": text, "score": score, "left": left, "top": top, "right": right, "bottom": bottom}


HP_PROFILE = {
    "id": "fixture",
    "hud": {"hp": {"box": [0.0, 0.8, 0.3, 0.2], "prefix": "HP"}},
}

# 200x100 frame -> normalized box [0.0, 0.8, 0.3, 0.2] covers x=0..60, y=80..100.
HP_INSIDE = ocr_line("HP.3", score=0.95, left=4, top=84, right=40, bottom=96)
HP_OUTSIDE = ocr_line("HP.9", score=0.99, left=120, top=10, right=160, bottom=20)


def parry_frame(height=120, width=160):
    frame = make_frame(height, width)
    # BGR: high red + high blue, low green -> magenta-ish.
    frame[40:60, 60:100] = (200, 30, 200)
    return frame


def moving_patches(height=90, width=160, previous_rect=(20, 20, 40, 40), current_rect=(100, 20, 120, 40)):
    previous = make_frame(height, width)
    current = make_frame(height, width)
    previous[previous_rect[1] : previous_rect[3], previous_rect[0] : previous_rect[2]] = 255
    current[current_rect[1] : current_rect[3], current_rect[0] : current_rect[2]] = 255
    return current, previous


# ---------------------------------------------------------------------------
# HP extraction: box filtering + prefix
# ---------------------------------------------------------------------------


def test_extract_hp_uses_box_and_prefix():
    lines = [HP_INSIDE, HP_OUTSIDE]
    assert extract_hp(lines, profile=HP_PROFILE, frame_size=(200, 100)) == (3, "3")


def test_extract_hp_ignores_lines_outside_hp_box():
    assert extract_hp([HP_OUTSIDE], profile=HP_PROFILE, frame_size=(200, 100)) == (None, None)


def test_extract_hp_prefix_is_required_when_configured():
    plain = ocr_line("3", score=0.99, left=4, top=84, right=20, bottom=96)
    assert extract_hp([plain], profile=HP_PROFILE, frame_size=(200, 100)) == (None, None)


def test_extract_hp_picks_highest_score_candidate():
    low = ocr_line("HP.2", score=0.60, left=4, top=84, right=40, bottom=96)
    high = ocr_line("HP.4", score=0.95, left=4, top=84, right=40, bottom=96)
    assert extract_hp([low, high], profile=HP_PROFILE, frame_size=(200, 100)) == (4, "4")


def test_extract_hp_parses_fraction_and_max_hp():
    profile = {"hud": {"hp": {"box": [0.0, 0.8, 0.3, 0.2]}}}
    line = ocr_line("3/5", score=0.9, left=4, top=84, right=40, bottom=96)
    assert extract_hp([line], profile=profile, frame_size=(200, 100)) == (3, "3/5")

    frame = make_frame(100, 200, color=(90, 90, 90))
    state = extract_visual_state(frame, [line], profile=profile)
    assert state["player"]["hp"] == 3
    assert state["player"]["max_hp"] == 5
    assert state["ui"]["hp_text"] == "3/5"


def test_extract_hp_profile_max_hp_fallback():
    profile = {"hud": {"hp": {"max_hp": 4}}}
    line = ocr_line("HP.2", score=0.9)
    frame = make_frame(100, 200, color=(90, 90, 90))
    state = extract_visual_state(frame, [line], profile=profile)
    assert state["player"]["hp"] == 2
    assert state["player"]["max_hp"] == 4


def test_extract_hp_accepts_already_normalized_coordinates():
    profile = {"hud": {"hp": {"box": [0.0, 0.8, 0.3, 0.2], "prefix": "HP"}}}
    line = ocr_line("HP.2", score=0.9, left=0.05, top=0.85, right=0.15, bottom=0.95)
    assert extract_hp([line], profile=profile) == (2, "2")


def test_extract_visual_state_without_frame_size_does_not_crash_on_pixel_coords():
    # No frame size and pixel coords: box filtering degrades to "unknown", no raise.
    assert extract_hp([HP_INSIDE], profile=HP_PROFILE) == (None, None)


# ---------------------------------------------------------------------------
# Scene classification: precedence
# ---------------------------------------------------------------------------


def test_scene_death_beats_menu_and_hp():
    scene, confidence = detect_scene([ocr_line("GAME OVER"), ocr_line("START")], hp=3)
    assert scene == "death"
    assert 0.0 <= confidence <= 1.0


def test_scene_menu_beats_hp():
    scene, _ = detect_scene([ocr_line("START"), ocr_line("OPTIONS")], hp=3)
    assert scene == "menu"


def test_scene_hp_means_gameplay():
    scene, _ = detect_scene([ocr_line("HP.3")], hp=3)
    assert scene == "gameplay"


def test_scene_few_lines_means_loading():
    assert detect_scene([ocr_line("LOADING...")])[0] == "loading"
    assert detect_scene([ocr_line("LOADING...")], profile={"scene": {"loading_max_texts": 2}})[0] == "loading"


def test_scene_many_lines_without_hp_means_dialogue():
    assert detect_scene([ocr_line("ONE"), ocr_line("TWO")])[0] == "dialogue"


def test_scene_no_ocr_means_unknown():
    assert detect_scene([]) == ("unknown", 0.0)
    assert detect_scene(None) == ("unknown", 0.0)


def test_scene_profile_keywords_override_defaults():
    profile = {"scene": {"death_keywords": ["YOU DIED"], "menu_keywords": ["PAUSE"]}}
    assert detect_scene([ocr_line("YOU DIED")], profile=profile)[0] == "death"
    assert detect_scene([ocr_line("PAUSE")], profile=profile)[0] == "menu"
    # Custom lists replace the defaults: with only "PAUSE" configured, the
    # built-in "GAME OVER" keyword no longer applies (single line -> loading).
    assert detect_scene([ocr_line("GAME OVER")], profile=profile)[0] == "loading"


def test_visual_state_near_black_frame_is_loading():
    frame = make_frame(120, 160)  # pure black
    state = extract_visual_state(frame)
    assert state["scene"] == "loading"

    bright = make_frame(120, 160, color=(120, 120, 120))
    assert extract_visual_state(bright)["scene"] == "unknown"


def test_visual_state_dark_dialogue_is_loading_but_death_wins():
    dark = make_frame(120, 160)
    state = extract_visual_state(dark, [ocr_line("ONE"), ocr_line("TWO")])
    assert state["scene"] == "loading"

    death = extract_visual_state(dark, [ocr_line("GAME OVER")])
    assert death["scene"] == "death"


# ---------------------------------------------------------------------------
# parry detection: synthetic pink image
# ---------------------------------------------------------------------------


def test_cheap_entities_detects_pink_parry_blob():
    entities = cheap_entities(parry_frame(), None)
    parries = [entity for entity in entities if entity["kind"] == "parry"]
    assert parries, "没有检出粉色 parry 色块"
    blob = parries[0]
    assert abs(blob["x"] - 0.5) < 0.03
    assert abs(blob["y"] - (50 / 120)) < 0.03
    assert blob["score"] > 0.5


def test_cheap_entities_ignores_weak_or_black_frames():
    assert cheap_entities(make_frame(120, 160), None) == []
    weak = make_frame(120, 160)
    weak[40:60, 60:100] = (120, 30, 120)  # too dark for the default thresholds
    assert [entity for entity in cheap_entities(weak, None) if entity["kind"] == "parry"] == []


def test_cheap_entities_parry_thresholds_are_profile_driven():
    weak = make_frame(120, 160)
    weak[40:60, 60:100] = (120, 30, 120)
    profile = {"colors": {"parry": {"r_min": 100, "b_min": 100, "rb_minus_g_min": 20, "min_pixels": 4}}}
    parries = [entity for entity in cheap_entities(weak, None, profile) if entity["kind"] == "parry"]
    assert parries


# ---------------------------------------------------------------------------
# moving-threat detection: synthetic moving patches
# ---------------------------------------------------------------------------


def test_cheap_entities_detects_moving_threat_patches():
    current, previous = moving_patches()
    entities = cheap_entities(current, previous)
    threats = [entity for entity in entities if entity["kind"] == "threat"]
    assert len(threats) >= 2
    for entity in threats:
        assert 0.0 <= entity["x"] <= 1.0
        assert 0.0 <= entity["y"] <= 1.0
        assert entity["score"] > 0.0
    # old location (~0.19, 0.33) and new location (~0.69, 0.33)
    assert any(abs(entity["x"] - 0.19) < 0.10 and abs(entity["y"] - 0.33) < 0.10 for entity in threats)
    assert any(abs(entity["x"] - 0.69) < 0.10 and abs(entity["y"] - 0.33) < 0.10 for entity in threats)


def test_cheap_entities_ignores_static_and_missing_previous_frames():
    current, previous = moving_patches()
    assert [entity for entity in cheap_entities(current, current) if entity["kind"] == "threat"] == []
    assert [entity for entity in cheap_entities(current, None) if entity["kind"] == "threat"] == []


def test_moving_threats_on_large_frame_are_normalized():
    height, width = 567, 962
    previous = make_frame(height, width)
    current = make_frame(height, width)
    previous[250:350, 100:200] = 255
    current[250:350, 500:600] = 255
    threats = [entity for entity in cheap_entities(current, previous) if entity["kind"] == "threat"]
    assert threats
    assert any(abs(entity["x"] - 150 / width) < 0.10 for entity in threats)
    assert any(abs(entity["x"] - 550 / width) < 0.10 for entity in threats)


def test_cheap_entities_drops_self_area_when_profile_provides_self_pos():
    # Both patches sit around the screen center where the player sprite lives.
    current, previous = moving_patches(
        previous_rect=(65, 35, 85, 55),
        current_rect=(85, 35, 105, 55),
    )
    without = [entity for entity in cheap_entities(current, previous) if entity["kind"] == "threat"]
    assert without, "没有 self_pos 时应该检出威胁"
    with_self = [
        entity
        for entity in cheap_entities(current, previous, {"self_pos": [0.5, 0.5]})
        if entity["kind"] == "threat"
    ]
    assert with_self == []


def test_cheap_entities_sorted_by_score_desc():
    entities = cheap_entities(parry_frame(), parry_frame())
    scores = [entity["score"] for entity in entities]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# normalized coordinates / WorldState shape
# ---------------------------------------------------------------------------


def test_ocr_text_coordinates_are_normalized_to_frame():
    frame = make_frame(100, 200, color=(90, 90, 90))
    line = ocr_line("HELLO", score=0.8, left=10, top=50, right=30, bottom=60)
    state = extract_visual_state(frame, [line], now=1234.5)
    text = state["ui"]["texts"][0]
    assert text["text"] == "HELLO"
    assert abs(text["x"] - 0.10) < 1e-6
    assert abs(text["y"] - 0.55) < 1e-6
    assert state["t"] == 1234.5


def test_world_state_default_shape():
    frame = make_frame(100, 200, color=(90, 90, 90))
    state = extract_visual_state(frame)
    assert state["schema"] == STATE_SCHEMA == 1
    assert state["scene"] == "unknown"
    assert state["confidence"] == 0.0
    assert state["player"] == {
        "x": None,
        "y": None,
        "hp": None,
        "max_hp": None,
        "state": "unknown",
        "confidence": None,
    }
    assert state["entities"] == []
    assert state["ui"] == {"texts": [], "prompt": None, "icon_prompt": None, "hp_text": None}
    assert state["game"] == {"profile": None, "provider": "vision", "stale": False}
    assert state["foreground"] is None
    assert state["occluded"] is None
    assert isinstance(state["t"], float)


def test_profile_id_is_reported():
    frame = make_frame(100, 200, color=(90, 90, 90))
    state = extract_visual_state(frame, profile={"id": "fixture", "name": "Fixture"})
    assert state["game"]["profile"] == "fixture"


def test_prompt_heuristic_and_profile_override():
    frame = make_frame(100, 200, color=(90, 90, 90))
    lines = [ocr_line("HP.3", score=0.95), ocr_line("CONFIRM Z", score=0.8)]
    assert extract_visual_state(frame, lines, profile=HP_PROFILE)["ui"]["prompt"] == "CONFIRM Z"

    profile = {"scene": {"prompt_keywords": ["PRESS"]}}
    assert extract_visual_state(frame, lines, profile=profile)["ui"]["prompt"] is None
    assert (
        extract_visual_state(frame, [ocr_line("PRESS X", score=0.7)], profile=profile)["ui"]["prompt"]
        == "PRESS X"
    )


# ---------------------------------------------------------------------------
# garbage input: never raise
# ---------------------------------------------------------------------------


def test_garbage_inputs_never_raise():
    for frame in (None, "not a frame", 42, [], np.zeros((0, 0, 3), np.uint8), np.zeros((1, 1, 3), np.uint8)):
        state = extract_visual_state(frame)
        assert isinstance(state, dict)
        assert state["schema"] == STATE_SCHEMA

    for lines in (None, "garbage", 42, [None, 42, {}, {"text": ""}], {"text": "HP.3"}):
        state = extract_visual_state(make_frame(), lines)
        assert isinstance(state, dict)

    assert cheap_entities(None, None) == []
    assert cheap_entities([], []) == []
    assert cheap_entities("frame", "previous") == []
    assert cheap_entities(np.zeros((10, 10), np.uint8), None) == []
    assert extract_hp(None) == (None, None)
    assert extract_hp([{"text": None}]) == (None, None)
    assert detect_scene(None) == ("unknown", 0.0)
    assert detect_scene("garbage") == ("unknown", 0.0)


def test_garbage_profile_never_raises():
    frame = make_frame(100, 200, color=(90, 90, 90))
    line = ocr_line("HP.3", score=0.9, left=4, top=84, right=40, bottom=96)
    for profile in ("bad", 42, [], {"hud": "bad", "scene": 5, "colors": [], "combat": None}):
        state = extract_visual_state(frame, [line], profile=profile)
        assert isinstance(state, dict)
        assert state["game"]["provider"] == "vision"


def test_non_uint8_and_non_contiguous_frames_are_normalized():
    float_frame = np.full((40, 80, 3), 128.5, dtype=np.float64)
    entities = cheap_entities(float_frame, float_frame)
    assert isinstance(entities, list)

    base = make_frame(120, 160)
    base[40:60, 60:100] = (200, 30, 200)
    cropped = base[:, ::2]  # non-contiguous view
    parries = [entity for entity in cheap_entities(cropped, None) if entity["kind"] == "parry"]
    assert parries


# ---------------------------------------------------------------------------
# cheap-path budget (generous bound; the contract target is <3 ms locally)
# ---------------------------------------------------------------------------


def test_cheap_path_performance_budget():
    assert hasattr(state_module, "cheap_entities")
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 256, (567, 962, 3), dtype=np.uint8)
    previous = rng.integers(0, 256, (567, 962, 3), dtype=np.uint8)
    cheap_entities(frame, previous)  # warm up lazy imports

    started = time.perf_counter()
    for _ in range(5):
        cheap_entities(frame, previous)
    elapsed_ms = (time.perf_counter() - started) / 5.0 * 1000.0
    assert elapsed_ms < 25.0, f"cheap path too slow: {elapsed_ms:.2f} ms"

import base64

import cv2


def _png_b64(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def test_find_player_finds_template():
    rng = np.random.default_rng(3)
    frame = rng.integers(0, 80, (200, 320, 3), dtype=np.uint8)
    template = np.zeros((40, 30, 3), dtype=np.uint8)
    template[:, :] = (240, 240, 240)
    template[10:30, 8:22] = (30, 30, 200)
    frame[100:140, 150:180] = template
    profile = {
        "player": {
            "template_png_base64": _png_b64(template),
            "template_size": [30 / 320.0, 40 / 200.0],
            "search_width": 320,
            "match_threshold": 0.5,
        }
    }
    found = state_module.find_player(frame, profile)
    assert found is not None
    assert found["method"] == "template"
    assert abs(found["x"] - 165 / 320.0) < 0.05
    assert abs(found["y"] - 120 / 200.0) < 0.05


def test_find_player_color_fallback_and_garbage():
    frame = np.zeros((120, 240, 3), dtype=np.uint8)
    frame[50:90, 100:160] = (20, 20, 220)
    profile = {"player": {"colors": [{"r_min": 180, "g_max": 80, "b_max": 80}], "min_pixels": 30}}
    found = state_module.find_player(frame, profile)
    assert found is not None
    assert found["method"] == "color"
    assert abs(found["x"] - 130 / 240.0) < 0.08
    assert state_module.find_player(None, profile) is None
    assert state_module.find_player(frame, {"player": {"template_png_base64": "not-base64!!"}}) is None

def test_detect_prompt_icon_template():
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    icon = np.zeros((40, 36, 3), dtype=np.uint8)
    icon[4:36, 4:32] = (250, 250, 250)
    icon[10:30, 12:24] = (10, 10, 10)
    frame[80:120, 200:236] = icon
    profile = {
        "ui": {
            "prompt_icons": [
                {
                    "key": "Z",
                    "template_png_base64": _png_b64(icon),
                    "size": [36 / 320.0, 40 / 180.0],
                    "search_width": 320,
                    "match_threshold": 0.6,
                }
            ]
        }
    }
    found = state_module.detect_prompt_icon(frame, profile)
    assert found is not None
    assert found["key"] == "Z"
    assert abs(found["x"] - 218 / 320.0) < 0.05
    assert abs(found["y"] - 100 / 180.0) < 0.06
    assert state_module.detect_prompt_icon(None, profile) is None
    assert state_module.detect_prompt_icon(frame, {}) is None

def test_detect_scene_equip_precedes_death_keywords():
    lines = [
        {"text": "DEAD", "score": 0.99, "left": 0, "top": 0, "right": 1, "bottom": 1},
        {"text": "UNEQUIP SHIFT", "score": 0.99, "left": 0, "top": 0, "right": 1, "bottom": 1},
    ]
    scene, _confidence = state_module.detect_scene(lines)
    assert scene == "equip"

def test_detect_static_hazards_color_blob():
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    frame[80:100, 120:150] = (20, 20, 220)  # red in BGR
    profile = {
        "hazards": [
            {
                "kind": "red_mushroom",
                "colors": [{"r_min": 170, "g_max": 100, "b_max": 100}],
                "region": [0.0, 0.5, 1.0, 0.5],
                "min_pixels": 20,
            }
        ]
    }
    found = state_module.detect_static_hazards(frame, profile)
    assert len(found) == 1
    assert found[0]["kind"] == "red_mushroom"
    assert abs(found[0]["x"] - 135 / 200.0) < 0.05
    assert state_module.detect_static_hazards(None, profile) == []

def test_detect_gap_ahead():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[50:100, 40:80] = (220, 220, 220)  # bright ground under player
    profile = {
        "terrain": {
            "gap_enabled": True,
            "gap_lookahead": 0.2,
            "gap_min_brightness": 20,
            "gap_ratio": 0.6,
        }
    }
    assert state_module.detect_gap_ahead(frame, profile, (0.3, 0.5)) is True
    uniform = np.full((100, 200, 3), 120, dtype=np.uint8)
    assert state_module.detect_gap_ahead(uniform, profile, (0.3, 0.5)) is False
