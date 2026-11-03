
import json

from dsh_game_core.memory_loader import MemoryLoader


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loader_loads_game_then_level_on_demand(tmp_path):
    _write(tmp_path / "general.json", {"genre": "platformer"})
    _write(tmp_path / "games" / "game1" / "game.json", {"controls": {"jump": "Z"}})
    _write(tmp_path / "games" / "game1" / "entities.json", {"types": []})
    _write(
        tmp_path / "games" / "game1" / "levels" / "level1.json",
        {"game": "game1", "level": "level1", "segments": {"s:0": {"deaths": 2}}},
    )
    loader = MemoryLoader(tmp_path)
    data = loader.load_game("game1")
    assert data["general"]["genre"] == "platformer"
    assert data["game"]["controls"]["jump"] == "Z"
    assert loader.level_memory is None
    assert loader.scope() == "game"

    memory = loader.load_level("game1", "level1")
    assert memory.hotspot(0.0) is True
    assert loader.scope() == "level"
    loader.unload_level()
    assert loader.level_memory is None
    assert loader.scope() == "game"


def test_loader_rejects_traversal(tmp_path):
    loader = MemoryLoader(tmp_path)
    loader.load_level("game1", "../evil")
    # safe_id maps traversal to unknown; no exception, no escape
    assert loader.level_id == "unknown"
    assert loader.level_memory is not None
