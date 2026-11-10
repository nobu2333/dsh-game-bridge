import json

import pytest

from dsh_game_core.gamepack import (
    GamePackError,
    capability_level,
    load_pack,
    profile_from_pack,
    validate_pack,
)


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


def test_profile_from_pack_maps_generic_fields():
    pack = validate_pack(
        {
            **_pack(),
            "controls": {"confirm": ["ENTER"], "move": {"right": "D"}},
            "hud": {"hp": {"box": [0.0, 0.8, 0.2, 0.1], "prefix": "HP"}},
            "profile": {"combat": {"advance": "RIGHT"}},
        }
    )
    profile = profile_from_pack(pack)
    assert profile["id"] == "pc.example"
    assert profile["pack_id"] == "pc.example"
    assert profile["pack_controls"]["move"]["right"] == "D"
    assert profile["hud"]["hp"]["prefix"] == "HP"
    assert profile["combat"]["advance"] == "RIGHT"
    assert profile["pack_capabilities"]["observe.screen"]["level"] == 0


def test_profile_from_pack_rejects_non_object_profile():
    pack = validate_pack({**_pack(), "profile": "bad"})
    with pytest.raises(GamePackError):
        profile_from_pack(pack)

from dsh_game_core.gamepack import GamePackError, validate_pack

def test_origin_and_interventions_are_validated():
    pack = validate_pack({"schema": 1, "id": "x", "title": "X", "trust": {"anti_cheat": "none"}})
    assert pack["origin"] == "human"
    assert pack["interventions"] == 0
    assisted = validate_pack({"schema": 1, "id": "x", "title": "X", "trust": {"anti_cheat": "none"}, "origin": "auto", "interventions": 2, "probe": {"keys": ["SPACE"]}})
    assert assisted["origin"] == "auto"
    assert assisted["interventions"] == 2
    assert assisted["probe"]["keys"] == ["SPACE"]
    with pytest.raises(GamePackError):
        validate_pack({"schema": 1, "id": "x", "title": "X", "trust": {"anti_cheat": "none"}, "origin": "magic"})
    with pytest.raises(GamePackError):
        validate_pack({"schema": 1, "id": "x", "title": "X", "trust": {"anti_cheat": "none"}, "interventions": -1})
