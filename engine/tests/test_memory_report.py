
import json

from dsh_game_core.memory_report import scan_memory


def test_scan_memory_lists_hotspots(tmp_path):
    game = tmp_path / "games" / "g1"
    levels = game / "levels"
    levels.mkdir(parents=True)
    (levels / "l1.json").write_text(
        json.dumps({"game": "g1", "level": "l1", "segments": {
            "s:0": {"key": "s:0", "deaths": 3, "damage": 2},
            "s:1": {"key": "s:1", "deaths": 0, "damage": 0},
        }}),
        encoding="utf-8",
    )
    result = scan_memory(tmp_path)
    assert result["games"][0]["game"] == "g1"
    assert result["games"][0]["levels"][0]["summary"]["deaths"] == 3
    assert result["games"][0]["levels"][0]["hotspots"][0]["segment"] == "s:0"
    assert scan_memory(tmp_path, game="missing")["games"] == []
