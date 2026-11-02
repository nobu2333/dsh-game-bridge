"""game_probe：只读引擎/配置/键位扫描。"""

import json
from pathlib import Path

from dsh_game_core.game_probe import (
    detect_engine,
    find_config_candidates,
    parse_unity_inputmanager,
    parse_unreal_input,
    scan_game,
)


def test_detect_unity_and_parse_inputmanager(tmp_path):
    data = tmp_path / "Game_Data"
    (data / "Managed").mkdir(parents=True)
    (data / "Managed" / "Assembly-CSharp.dll").write_bytes(b"fake")
    (data / "InputManager.asset").write_text(
        "InputManager:\n  m_Name: Jump\n  positiveButton: space\n  m_Name: Fire1\n  positiveButton: mouse 0\n",
        encoding="utf-8",
    )
    assert detect_engine(tmp_path)["engine"] == "unity"
    parsed = parse_unity_inputmanager(data / "InputManager.asset")
    assert any(item["action"] == "Jump" and item["key"] == "space" for item in parsed)
    result = scan_game(tmp_path)
    assert result["engine"] == "unity"
    assert result["keybinds"]


def test_detect_unreal_and_parse_input_ini(tmp_path):
    (tmp_path / "Game.uproject").write_text("{}", encoding="utf-8")
    config = tmp_path / "Config"
    config.mkdir()
    (config / "DefaultInput.ini").write_text(
        '+ActionMappings=(ActionName="Jump",Key=SpaceBar)\n'
        '+ActionMappings=(ActionName="Fire",Key=LeftMouseButton)\n',
        encoding="utf-8",
    )
    assert detect_engine(tmp_path)["engine"] == "unreal"
    parsed = parse_unreal_input(config / "DefaultInput.ini")
    assert any(item["action"] == "Jump" and item["key"] == "SpaceBar" for item in parsed)
    result = scan_game(tmp_path)
    assert result["engine"] == "unreal"


def test_scan_unknown_and_config_candidates(tmp_path):
    (tmp_path / "readme.txt").write_text("no game", encoding="utf-8")
    assert detect_engine(tmp_path)["engine"] == "unknown"
    (tmp_path / "settings.json").write_text(json.dumps({"key": "value"}), encoding="utf-8")
    candidates = find_config_candidates(tmp_path)
    assert any(path.endswith("settings.json") for path in candidates)
    assert scan_game(tmp_path)["engine"] == "unknown"
