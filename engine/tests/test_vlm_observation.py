
from dsh_game_core.vlm_observation import merge_with_algorithmic, validate_vlm_observation


def test_validate_vlm_observation():
    valid = validate_vlm_observation(
        {
            "scene": "gameplay",
            "goal": "reach exit",
            "player_visible": True,
            "entities": [{"kind": "projectile", "role": "threat", "x": 0.7, "y": 0.4, "threat": True}],
            "hazards": ["pit"],
            "confidence": 0.8,
        }
    )
    assert valid is not None
    assert valid["scene"] == "gameplay"
    assert valid["entities"][0]["threat"] is True
    assert valid["source"] == "vlm"
    assert validate_vlm_observation("nope") is None
    assert validate_vlm_observation({}) is None


def test_merge_keeps_geometry_and_adds_threat():
    obs = {"scene": "unknown", "enemy_ahead": False, "player": {"x": 0.3, "y": 0.8}}
    vlm = validate_vlm_observation(
        {"scene": "gameplay", "entities": [{"role": "chaser", "threat": True}], "player_visible": True}
    )
    merged = merge_with_algorithmic(obs, vlm)
    assert merged["scene"] == "gameplay"
    assert merged["enemy_ahead"] is True
    assert merged["player"]["x"] == 0.3
    assert "vlm" in merged["sources"]
