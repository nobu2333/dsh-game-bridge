import json

import pytest

from dsh_game_core.gamepack import GamePackError, capability_level, load_pack, validate_pack


def _pack(**overrides):
    pack = {
        "schema": 1,
        "id": "pc.example",
        "title": "Example",
        "trust": {"anti_cheat": "none"},
        "capabilities": {
            "observe.screen": {"level": 0},
            "control.keyboard": {"level": 1},
        },
        "controls": {"confirm": ["ENTER"]},
        "recipes": [{"id": "start", "intent": "start", "steps": [{"press": "ENTER"}]}],
    }
    pack.update(overrides)
    return pack


def test_validate_pack_normalizes_and_keeps_data():
    pack = validate_pack(_pack())
    assert pack["schema"] == 1
    assert pack["id"] == "pc.example"
    assert pack["capabilities"]["control.keyboard"]["level"] == 1
    assert pack["recipes"][0]["id"] == "start"
    assert pack["evidence"] == []


def test_load_pack_from_disk(tmp_path):
    path = tmp_path / "example.pack.json"
    path.write_text(json.dumps(_pack()), encoding="utf-8")
    assert load_pack(path)["title"] == "Example"


def test_anti_cheat_is_rejected():
    with pytest.raises(GamePackError):
        validate_pack(_pack(trust={"anti_cheat": "eac"}))
    with pytest.raises(GamePackError):
        validate_pack(_pack(trust={}))


def test_invalid_capability_level_is_rejected():
    with pytest.raises(GamePackError):
        validate_pack(_pack(capabilities={"control.mouse": {"level": 4}}))


def test_missing_id_and_duplicate_recipe_are_rejected():
    with pytest.raises(GamePackError):
        validate_pack(_pack(id=""))
    with pytest.raises(GamePackError):
        validate_pack(
            _pack(
                recipes=[
                    {"id": "start", "steps": [{"press": "ENTER"}]},
                    {"id": "start", "steps": [{"press": "ESC"}]},
                ]
            )
        )


def test_empty_t0_pack_and_capability_level_helper():
    pack = validate_pack({"schema": 1, "id": "x", "title": "X", "trust": {"anti_cheat": "none"}})
    assert pack["capabilities"] == {}
    assert capability_level(pack, "observe.screen") == 0
    assert capability_level(pack, "control.keyboard") == 0
