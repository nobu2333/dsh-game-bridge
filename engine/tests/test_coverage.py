
from dsh_game_core.coverage import summarize_coverage

MATRIX = {
    "games": [
        {"id": "pc.a", "status": "t1_pass", "pack": "packs/a.json"},
        {"id": "pc.b", "status": "t1_pass", "pack": "packs/b.json"},
        {"id": "web.c", "status": "t1_pass", "pack": "packs/c.json"},
        {"id": "web.d", "status": "t2_pass", "pack": "packs/d.json", "strict_t2": {"valid": True}},
    ]
}
ORIGINS = {
    "packs/a.json": {"origin": "auto", "interventions": 0, "evidence": ["e"]},
    "packs/b.json": {"origin": "assisted", "interventions": 1, "evidence": ["e"]},
    "packs/c.json": {"origin": "human", "interventions": 2, "evidence": []},
    "packs/d.json": {"origin": "assisted", "interventions": 0, "evidence": ["e"]},
}


def test_coverage_splits_t1_by_origin():
    result = summarize_coverage(MATRIX, ORIGINS)
    assert result["t1_total"] == 4
    assert result["t1_packs"] == 4
    assert result["t1_auto"] == 1
    assert result["t1_assisted"] == 2
    assert result["t1_human"] == 1
    assert result["t2_total"] == 1
    assert result["strict_t2"] == ["web.d"]
    assert result["interventions"] == 3
    assert result["missing_evidence"] == ["web.c"]
    assert result["target_met"] is False


def test_coverage_deduplicates_packs_for_the_same_game():
    matrix = {
        "games": [
            {"id": "web.dino", "game_key": "web.dino", "status": "t1_pass", "pack": "assisted.json"},
            {"id": "web.dino.auto", "game_key": "web.dino", "status": "t1_pass", "pack": "auto.json"},
        ]
    }
    origins = {
        "assisted.json": {"origin": "assisted", "interventions": 1, "evidence": ["e"]},
        "auto.json": {"origin": "auto", "interventions": 0, "evidence": ["e"]},
    }
    result = summarize_coverage(matrix, origins)
    assert result["t1_total"] == 1
    assert result["t1_packs"] == 2
    assert result["t1_auto"] == 1
    assert result["t1_assisted"] == 0
    assert result["interventions"] == 1
