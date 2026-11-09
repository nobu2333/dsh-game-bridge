import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATRIX = REPO / "experiments" / "games" / "matrix.json"


def test_game_matrix_is_consistent():
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["target"]["t1"] == 3
    assert data["target"]["t2"] == 2

    games = data["games"]
    ids = [game["id"] for game in games]
    assert len(ids) == len(set(ids))
    known = set(ids)

    primary = data["selection"]["primary_t1"]
    assert len(primary) == data["target"]["t1"]
    assert set(primary) <= known

    candidates = data["selection"]["t2_candidates"]
    assert len(candidates) == data["target"]["t2"]
    assert set(candidates) <= known


def test_game_matrix_does_not_include_anti_cheat_games_as_primary():
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    excluded = {item["id"] for item in data["selection"]["excluded"]}
    primary = set(data["selection"]["primary_t1"])
    assert not (primary & excluded)
