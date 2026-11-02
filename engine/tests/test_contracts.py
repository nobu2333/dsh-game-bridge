
from dsh_game_core.contracts import (
    ActionResult,
    Intent,
    SituationReport,
    WorldState,
)


def test_world_state_clamps_and_truncates():
    raw = {
        "scene": "gameplay",
        "player": {"x": 2.0, "y": -1.0, "vx": 9.0, "vy": -9.0, "hp": 2},
        "threats": [
            {"id": "3", "role": "approaching", "dx": 5, "dy": -5, "vx": 9, "ttc": 0.3, "confidence": 2},
            {"bad": "ignored"},
        ]
        * 10,
        "hazards": [{"type": "gap"}] * 20,
        "progress": {"scroll_s": -2.7, "stalled_ms": 99999},
        "actions": {"held": ["X", "RIGHT"], "last": "jump"},
    }
    state = WorldState.from_raw(raw)
    assert state.player["x"] == 1.0
    assert state.player["y"] == 0.0
    assert state.player["vx"] == 2.0
    assert state.threats[0].dx == 1.0
    assert state.threats[0].confidence == 1.0
    assert len(state.threats) == 8
    assert len(state.hazards) == 8
    assert state.progress["stalled_ms"] == 60000
    assert state.actions["held"] == ["X", "RIGHT"]


def test_situation_report_events_and_options():
    report = SituationReport.from_raw(
        {
            "scene": "gameplay",
            "events": [
                {"type": "threat_charging", "text": "flower from left", "side": "left", "threat_id": 3, "ttc": 0.3},
                {"nope": 1},
            ],
            "options": ["dodge_right", "jump"],
            "player_state": {"hp": 2, "cornered": True},
            "uncertainty": ["small_projectile"],
        }
    )
    assert report.events[0].type == "threat_charging"
    assert report.events[0].ttc == 0.3
    assert report.options == ["dodge_right", "jump"]
    assert report.player_state["cornered"] is True


def test_intent_validation_and_clamp():
    intent = Intent.from_raw(
        {"goal": "nonsense", "skill": "dodge_right", "risk": "extreme", "ttl_ms": 99999, "priority": 99}
    )
    assert intent is not None
    assert intent.goal == "advance"
    assert intent.risk == "medium"
    assert intent.ttl_ms == 5000
    assert intent.priority == 10
    assert Intent.from_raw({"goal": "advance"}) is None
    assert Intent.from_raw({"skill": "jump", "ttl_ms": 1}).ttl_ms == 100


def test_action_result_roundtrip():
    result = ActionResult.from_raw({"intent_id": "i-1", "executed": "dodge_right", "status": "ok"})
    assert result.to_dict()["intent_id"] == "i-1"
    assert result.to_dict()["status"] == "ok"
