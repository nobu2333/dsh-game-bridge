
from dsh_game_core.level_memory import LevelMemory, safe_id, segment_key


def test_segment_key_and_ids():
    assert segment_key(0.0) == "s:0"
    assert segment_key(-1.1) == "s:-2"
    assert safe_id("cuphead") == "cuphead"
    assert safe_id("../evil") == "unknown"
    assert safe_id("") == "unknown"


def test_deaths_hotspot_and_actions():
    memory = LevelMemory("cuphead", "forest-follies", bucket=0.5)
    memory.observe(-1.0)
    memory.record_death(-1.0)
    assert memory.hotspot(-1.0) is False
    memory.record_death(-1.0)
    assert memory.hotspot(-1.0) is True
    assert memory.hotspot(-5.0) is False
    memory.record_action(-1.0, "jump", good=True)
    memory.record_action(-1.0, "jump", good=True)
    memory.record_action(-1.0, "advance", good=False)
    assert memory.preferred_action(-1.0) == "jump"


def test_save_load(tmp_path):
    memory = LevelMemory("cuphead", "level-1")
    memory.record_damage(-2.0, 2)
    path = tmp_path / "level.json"
    memory.save(path)
    restored = LevelMemory.load(path)
    assert restored.game_id == "cuphead"
    assert restored.summary()["damage"] == 2
    assert restored.query(-2.0)["damage"] == 2

def test_zone_hotspot_aggregates_nearby_deaths():
    memory = LevelMemory("g", "l", bucket=0.5)
    for scroll in (-7.5, -6.8, -6.0, -5.2):
        memory.record_death(scroll)
    assert memory.hotspot(-6.5, radius=1.5) is True
    assert memory.hotspot(0.0, radius=1.5) is False
    assert memory.zone_deaths(-6.5, radius=1.5) == 4
