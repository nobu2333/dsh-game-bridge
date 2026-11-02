
from dsh_game_core.situation import describe


def test_describe_charging_threat_and_options():
    report = describe(
        {
            "scene": "gameplay",
            "player": {"x": 0.5, "y": 0.8, "hp": 2},
            "threats": [
                {"id": 3, "role": "approaching", "dx": 0.2, "distance": 0.2, "ttc": 0.3,
                 "side": "left", "vx": 0.6, "confidence": 0.8}
            ],
        },
        hp=2,
    )
    assert report["events"][0]["type"] == "threat_charging"
    assert "左侧" in report["events"][0]["text"]
    assert "dodge_right" in report["options"]
    assert "jump" in report["options"]
    assert report["player_state"]["hp"] == 2


def test_describe_gap_low_hp_and_empty():
    report = describe(
        {
            "scene": "gameplay",
            "player": {"x": 0.5, "y": 0.8, "hp": 1},
            "threats": [],
            "hazards": [{"type": "gap"}],
        },
        hp=1,
    )
    types = {event["type"] for event in report["events"]}
    assert "gap_ahead" in types
    assert "low_hp" in types
    assert "jump" in report["options"]
    empty = describe({}, hp=3)
    assert empty["events"][0]["type"] == "no_immediate_threat"
    assert "no_threat_tracks" in empty["uncertainty"]

def test_situation_skips_stale_threats_and_reports_space():
    report = describe(
        {
            "scene": "gameplay",
            "player": {"x": 0.4, "y": 0.8},
            "threats": [
                {"id": 9, "distance": 0.1, "ttc": 0.2, "side": "left", "age_ms": 800, "confidence": 0.8}
            ],
        },
        hp=3,
    )
    assert all(event["type"] != "threat_charging" for event in report["events"])
    assert report["player_state"]["space_left"] == 0.4
    assert report["player_state"]["space_right"] == 0.6

def test_situation_flags_player_uncertainty():
    report = describe(
        {
            "scene": "gameplay",
            "player": {"x": 0.5, "y": 0.8, "confidence": 0.3, "age_ms": 800},
            "threats": [],
        },
        hp=3,
    )
    assert "low_player_confidence" in report["uncertainty"]
    assert "player_stale" in report["uncertainty"]
    assert report["player_state"]["confidence"] == 0.3
    assert report["player_state"]["age_ms"] == 800
