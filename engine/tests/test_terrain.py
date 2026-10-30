
import numpy as np

from dsh_game_core.terrain import find_ledges, ground_mask, ledge_under_player


def test_ground_mask_and_ledges():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[70:100, 20:120] = (30, 180, 60)  # green ground in BGR
    profile = {"terrain": {"ground_colors": [{"g_min": 120, "r_max": 120, "b_max": 120}]}}
    mask = ground_mask(frame, profile)
    assert mask is not None
    assert mask.sum() > 0
    ledges = find_ledges(frame, profile, min_area=100)
    assert ledges
    ledge = ledge_under_player(frame, profile, (0.3, 0.6))
    assert ledge is not None
    assert ledge["edge_x"] > 0.3


def test_terrain_tolerates_bad_input():
    assert ground_mask(None, {}) is None
    assert find_ledges(None, {}) == []
    assert find_ledges(np.zeros((10, 10, 3), dtype=np.uint8), {}) == []

def test_ground_region_limits_mask():
    from dsh_game_core.terrain import ground_mask

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[10:30, 20:100] = (30, 180, 60)
    frame[70:100, 20:100] = (30, 180, 60)
    profile = {
        "terrain": {
            "ground_colors": [{"g_min": 120, "r_max": 120, "b_max": 120}],
            "ground_region": [0.0, 0.5, 1.0, 0.5],
        }
    }
    mask = ground_mask(frame, profile)
    assert mask is not None
    assert not mask[10:30, 20:100].any()
    assert mask[70:100, 20:100].any()
