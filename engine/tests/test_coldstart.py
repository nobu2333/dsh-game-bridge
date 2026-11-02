
from dsh_game_core.coldstart import (
    build_profile,
    merge_controls,
    probe_to_candidates,
    scan_to_candidates,
)


def test_merge_prefers_probe_and_records_conflict():
    merged = merge_controls(
        [
            {"action": "Jump", "key": "Space", "source": "file"},
            {"action": "jump", "key": "Z", "source": "probe", "confidence": 0.95},
            {"action": "shoot", "key": "X", "source": "web", "confidence": 0.6},
        ]
    )
    assert merged["controls"]["jump"]["key"] == "z"
    assert merged["controls"]["jump"]["source"] == "probe"
    assert any(item["action"] == "jump" for item in merged["conflicts"])
    assert merged["alternatives"]["jump"][0]["key"] == "space"
    assert "probe" in merged["sources"]


def test_scan_and_probe_converters():
    scan = {"keybinds": [{"action": "Jump", "key": "Space", "source": "unity_inputmanager"}]}
    candidates = scan_to_candidates(scan)
    assert candidates[0]["source"] == "file"
    probe = {"Z": {"changed": True, "diff": 5.0}, "Q": {"changed": False, "diff": 0.0}}
    probe_candidates = probe_to_candidates(probe)
    assert len(probe_candidates) == 1
    assert probe_candidates[0]["key"] == "Z"


def test_build_profile_shape():
    profile = build_profile(
        engine="unity",
        scan_candidates=[{"action": "jump", "key": "space", "source": "file"}],
        probe_candidates=[{"action": "jump", "key": "z", "source": "probe", "confidence": 0.95}],
    )
    assert profile["engine"] == "unity"
    assert profile["controls"]["jump"]["source"] == "probe"
    assert profile["verified_in_game"] is True
    assert profile["conflicts"]

def test_keyname_candidates_map_directions():
    from dsh_game_core.coldstart import keyname_candidates

    candidates = keyname_candidates(["RIGHT", "a", "DOWN", "Z", "SPACE"])
    actions = {item["key"]: item["action"] for item in candidates}
    assert actions["RIGHT"] == "move_right"
    assert actions["a"] == "move_left"
    assert actions["DOWN"] == "move_down"
    assert actions["SPACE"] == "jump"
    assert "Z" not in actions
