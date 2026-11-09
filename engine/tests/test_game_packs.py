import json
from pathlib import Path

from dsh_game_core.gamepack import load_pack, validate_pack

PACKS = Path(__file__).resolve().parents[2] / "experiments" / "games" / "packs"


def test_all_game_packs_validate():
    files = sorted(PACKS.glob("*.json"))
    assert files, "expected at least one GamePack"
    for path in files:
        pack = load_pack(path)
        assert pack["trust"]["anti_cheat"] == "none"
        assert pack["id"]
        assert pack["level"] in (0, 1, 2, 3)


def test_cuphead_t1_pack_has_menu_recipe_and_evidence():
    pack = validate_pack(json.loads((PACKS / "pc.cuphead.t1.json").read_text(encoding="utf-8")))
    assert pack["level"] == 1
    assert pack["controls"]["confirm"]
    assert pack["recipes"][0]["id"] == "start_from_title"
    assert pack["evidence"]
