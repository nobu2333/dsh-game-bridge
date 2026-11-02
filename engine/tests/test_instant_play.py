
from dsh_game_core.instant_play import summary, to_engine_profile


def coldstart_profile():
    return {
        "engine": "unity",
        "verified_in_game": True,
        "sources": ["probe", "prior"],
        "controls": {
            "move_right": {"key": "RIGHT", "source": "prior", "confidence": 0.5},
            "move_left": {"key": "LEFT", "source": "prior", "confidence": 0.5},
            "move_up": {"key": "UP", "source": "prior", "confidence": 0.5},
            "move_down": {"key": "DOWN", "source": "prior", "confidence": 0.5},
            "jump": {"key": "Z", "source": "probe", "confidence": 0.88},
            "dash": {"key": "SHIFT", "source": "probe", "confidence": 0.71},
            "attack": {"key": "X", "source": "prior", "confidence": 0.5},
        },
    }


def test_to_engine_profile_maps_actions():
    profile = to_engine_profile(coldstart_profile(), profile_id="cuphead-cold")
    assert profile["controls"]["right"] == "RIGHT"
    assert profile["controls"]["jump"] == "Z"
    assert profile["controls"]["shoot"] == "X"
    assert profile["controls"]["dash"] == "SHIFT"
    assert profile["combat"]["hold"] == ["X"]
    assert profile["combat"]["advance"] == "RIGHT"
    assert profile["combat"]["dodge"]["keys"] == ["Z"]
    assert profile["coldstart"]["verified_in_game"] is True
    assert "probe" in profile["coldstart"]["sources"]


def test_to_engine_profile_defaults():
    profile = to_engine_profile({})
    assert profile["controls"]["right"] == "RIGHT"
    assert profile["controls"]["jump"] == "Z"
    assert profile["controls"]["shoot"] == "X"
    assert profile["controls"]["confirm"] == "Z"
    info = summary(profile)
    assert info["advance"] == "RIGHT"
    assert info["hold"] == ["X"]
