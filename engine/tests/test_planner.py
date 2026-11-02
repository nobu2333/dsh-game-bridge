
from dsh_game_core.planner import choose_intent


def report(events, hp=3):
    return {"scene": "gameplay", "events": events, "options": [], "player_state": {"hp": hp}, "uncertainty": []}


def test_planner_charging_left_dodges_right():
    intent = choose_intent(report([
        {"type": "threat_charging", "side": "left", "ttc": 0.3, "threat_id": 3, "confidence": 0.8}
    ]))
    assert intent["skill"] == "dodge_right"
    assert intent["goal"] == "avoid"
    assert intent["priority"] == 9
    assert intent["target_id"] == 3


def test_planner_gap_near_low_hp_and_default():
    gap = choose_intent(report([{"type": "gap_ahead"}]))
    assert gap["skill"] == "jump" and gap["priority"] == 9
    near = choose_intent(report([{"type": "threat_near", "threat_id": 2}], hp=1))
    assert near["skill"] == "retreat"
    advance = choose_intent(report([{"type": "no_immediate_threat"}]))
    assert advance["skill"] == "advance"
    assert advance["ttl_ms"] == 1500
