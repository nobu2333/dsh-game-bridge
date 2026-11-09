
import numpy as np

from dsh_game_core.player_tracker import PlayerTracker

PROFILE = {
    "player": {
        "colors": [{"r_min": 150, "r_max": 255, "g_min": 0, "g_max": 90, "b_min": 0, "b_max": 90}],
        "min_pixels": 30,
        "search_radius": 0.25,
    }
}


def _frame(blocks):
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for (x, y, w, h) in blocks:
        frame[y:y + h, x:x + w] = (0, 0, 220)
    return frame


def test_bootstrap_and_track_moving_player():
    tracker = PlayerTracker(PROFILE)
    result = tracker.bootstrap(_frame([(50, 180, 18, 30)]), anchor=(0.3, 0.8))
    assert result is not None
    assert not result["stale"]
    assert abs(result["x"] - (50 + 9) / 320) < 0.03
    assert result["templates"] >= 1

    moved = tracker.update(_frame([(80, 180, 18, 30)]), dt=1 / 30)
    assert moved is not None
    assert not moved["stale"]
    assert abs(moved["x"] - (80 + 9) / 320) < 0.05


def test_occlusion_marks_stale_then_reacquires():
    tracker = PlayerTracker(PROFILE)
    tracker.bootstrap(_frame([(50, 180, 18, 30)]), anchor=(0.3, 0.8))
    for _ in range(7):
        result = tracker.update(_frame([]), dt=1 / 30)
        assert result["stale"] is True
    reappeared = tracker.update(_frame([(250, 100, 18, 30)]), dt=1 / 30)
    assert reappeared["stale"] is False
    assert reappeared["source"] in ("template", "reacquire", "colour")


def test_near_candidate_wins_over_large_decoy():
    tracker = PlayerTracker(PROFILE)
    tracker.bootstrap(_frame([(50, 180, 18, 30)]), anchor=(0.3, 0.8))
    # player moves a little; a much larger red block appears far away
    result = tracker.update(_frame([(62, 180, 18, 30), (270, 40, 40, 40)]), dt=1 / 30)
    assert result is not None
    assert abs(result["x"] - (62 + 9) / 320) < 0.06


def test_status_shape():
    tracker = PlayerTracker(PROFILE)
    status = tracker.status()
    assert {"last", "velocity", "missing", "stale", "templates", "source", "score", "age_ms"} <= set(status)
