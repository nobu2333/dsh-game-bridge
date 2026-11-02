"""游戏冷启动扫描：读游戏目录/配置文件，推断引擎与键位候选。

这是 AI-native 方案 P0：不启动游戏、不注入输入，只读文件系统。
输出带 evidence/source 的候选，供后续按键探测与 profile 合并。

安全：只读；不执行游戏/脚本；不跟随符号链接；限制深度/文件大小。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

MAX_DEPTH = 4
MAX_FILES = 4000
MAX_CONFIG_BYTES = 512 * 1024

_UNITY_DATA = re.compile(r"_Data$")
_KEY_LINE = re.compile(
    r"(?i)(jump|attack|shoot|confirm|cancel|back|dash|interact|move|left|right|up|down|pause|start|menu)"
)
_INI_MAPPING = re.compile(r"(?i)^\s*\+?(?:Action|Axis)Mappings=\((.+)\)\s*$")
_UNITY_NAME = re.compile(r"^\s*m_Name:\s*(\S+)")
_UNITY_POS = re.compile(r"^\s*(positiveButton|negativeButton|altPositiveButton|altNegativeButton):\s*(\S+)")


def _walk(root: Path):
    """Yield files with depth/file-count limits, skipping symlinks."""
    count = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        depth = len(Path(current).relative_to(root).parts)
        if depth >= MAX_DEPTH:
            dirs[:] = []
        for name in files:
            count += 1
            if count > MAX_FILES:
                return
            yield Path(current) / name


def detect_engine(root: str | os.PathLike[str]) -> dict:
    """Read-only engine detection with evidence."""
    try:
        base = Path(root)
        if not base.is_dir():
            return {"engine": "unknown", "evidence": [], "root": str(base)}
        evidence: list[str] = []
        engine = "unknown"
        files = list(_walk(base))
        names = {path.name.lower(): path for path in files}

        if any(path.is_dir() and _UNITY_DATA.search(path.name) for path in base.iterdir()):
            data_dirs = [path for path in base.iterdir() if path.is_dir() and _UNITY_DATA.search(path.name)]
            for data_dir in data_dirs:
                if (data_dir / "Managed" / "Assembly-CSharp.dll").exists() or (data_dir / "globalgamemanagers").exists():
                    engine = "unity"
                    evidence.append(str(data_dir / "Managed" / "Assembly-CSharp.dll"))
                    break
            else:
                engine = "unity"
                evidence.append(str(data_dirs[0]))

        if engine == "unknown":
            if any(path.suffix == ".uproject" for path in files):
                engine = "unreal"
                evidence.extend([str(path) for path in files if path.suffix == ".uproject"][:2])
            elif any(path.name.lower() == "content" and path.is_dir() for path in base.iterdir()):
                if any((base / "Content" / "Paks").exists() for _ in [0]):
                    engine = "unreal"
                    evidence.append(str(base / "Content" / "Paks"))
            elif any(path.name.lower() == "engine" and path.is_dir() for path in base.iterdir()):
                engine = "unreal"
                evidence.append(str(base / "Engine"))

        if engine == "unknown":
            if any(path.suffix.lower() == ".pck" for path in files):
                engine = "godot"
                evidence.extend([str(path) for path in files if path.suffix.lower() == ".pck"][:2])
            elif "data.win" in names:
                engine = "gamemaker"
                evidence.append(str(names["data.win"]))

        return {"engine": engine, "evidence": evidence[:5], "root": str(base)}
    except Exception:  # noqa: BLE001
        return {"engine": "unknown", "evidence": [], "root": str(root)}


def _safe_read(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None


def parse_unreal_input(path: str | os.PathLike[str]) -> list[dict]:
    text = _safe_read(Path(path))
    if not text:
        return []
    results: list[dict] = []
    for line in text.splitlines():
        match = _INI_MAPPING.match(line)
        if not match:
            continue
        body = match.group(1)
        name = re.search(r'ActionName="?([^",]+)"?', body)
        key = re.search(r'Key=([^,]+)', body)
        if name and key:
            results.append({"action": name.group(1), "key": key.group(1), "source": "unreal_ini"})
    return results


def parse_unity_inputmanager(path: str | os.PathLike[str]) -> list[dict]:
    text = _safe_read(Path(path))
    if not text:
        return []
    results: list[dict] = []
    current = None
    for line in text.splitlines():
        name = _UNITY_NAME.match(line)
        if name:
            current = name.group(1)
            continue
        key = _UNITY_POS.match(line)
        if key and current:
            results.append(
                {
                    "action": current,
                    "key": key.group(2),
                    "variant": key.group(1),
                    "source": "unity_inputmanager",
                }
            )
    return results


def find_config_candidates(root: str | os.PathLike[str]) -> list[str]:
    """Return plausible input/config files (read-only discovery)."""
    try:
        base = Path(root)
        found: list[str] = []
        for path in _walk(base):
            if path.suffix.lower() not in (".ini", ".cfg", ".json", ".asset", ".txt"):
                continue
            if path.stat().st_size > MAX_CONFIG_BYTES:
                continue
            lower = path.name.lower()
            if any(token in lower for token in ("input", "setting", "config", "control", "keybind")):
                found.append(str(path))
            if len(found) >= 20:
                break
        return found
    except Exception:  # noqa: BLE001
        return []


def scan_game(root: str | os.PathLike[str]) -> dict:
    """Full cold-start scan: engine + config files + parsed keybind candidates."""
    engine = detect_engine(root)
    configs = find_config_candidates(root)
    keybinds: list[dict] = []
    for config in configs:
        name = Path(config).name.lower()
        if "input.ini" in name or "defaultinput" in name:
            keybinds.extend(parse_unreal_input(config))
        if "inputmanager" in name:
            keybinds.extend(parse_unity_inputmanager(config))
    dedup: dict[tuple[str, str], dict] = {}
    for item in keybinds:
        dedup[(item.get("action", "").lower(), str(item.get("key", "")).lower())] = item
    return {
        "root": str(root),
        "engine": engine["engine"],
        "evidence": engine["evidence"],
        "configs": configs,
        "keybinds": list(dedup.values())[:100],
        "source": "file_scan",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read-only game directory/engine/keybind scan.")
    parser.add_argument("root")
    args = parser.parse_args(argv)
    print(json.dumps(scan_game(args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
