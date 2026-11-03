
from dsh_game_core.candidates import score_actions
from dsh_game_core.level_memory import LevelMemory


def test_shadow_no_threat_prefers_attack_or_advance():
    result = score_actions({"hp": 3})
    top = result["top"]["action"]
    assert top in ("attack", "advance")
    assert result["shadow"] is True


def test_shadow_ttc_boosts_jump_dash():
    result = score_actions({"hp": 3, "enemy_ahead": True, "enemy_ttc": 0.25, "enemy_side": "right"})
    top = result["top"]["action"]
    assert top in ("jump", "dash")


def test_shadow_low_hp_retreats():
    result = score_actions({"hp": 1, "enemy_ahead": True, "enemy_ttc": 0.3})
    assert result["top"]["action"] == "retreat"


def test_shadow_level_memory_preferred_and_hotspot():
    memory = LevelMemory("game", "level", bucket=0.5)
    for _ in range(2):
        memory.record_death(-1.0)
        memory.record_action(-1.0, "jump", good=True)
    result = score_actions({"hp": 3}, level_memory=memory, scroll_s=-1.0)
    assert result["level_memory"]["hotspot"] is True
    assert result["level_memory"]["preferred"] == "jump"
    jump = next(item for item in result["ranked"] if item["action"] == "jump")
    assert "level_memory_preferred" in jump["reasons"]
    assert "hotspot" in jump["reasons"]
