"""按游戏/关卡作用域加载记忆：游戏级常驻，关卡级按需加载/卸载。

目录结构（root 由调用方决定，engine 不写死路径）：
root/
  general.json
  games/<game_id>/game.json
  games/<game_id>/entities.json
  games/<game_id>/ui.json
  games/<game_id>/levels/<level_id>.json
  user/preferences.json
  meta/manifest.json

game_id/level_id 必须由 session 传入；所有 id 经过安全校验，防路径穿越。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .level_memory import LevelMemory, safe_id


def _read_json(path: Path) -> dict:
    try:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001
        pass
    return {}


class MemoryLoader:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.game_id: str | None = None
        self.game_data: dict[str, dict] = {}
        self.level_id: str | None = None
        self.level_memory: LevelMemory | None = None

    # ── 游戏级（attach 时加载） ───────────────────────────────────────
    def load_game(self, game_id: str) -> dict:
        game = safe_id(game_id)
        base = self.root / "games" / game
        self.game_id = game
        self.level_id = None
        self.level_memory = None
        self.game_data = {
            "general": _read_json(self.root / "general.json"),
            "game": _read_json(base / "game.json"),
            "entities": _read_json(base / "entities.json"),
            "ui": _read_json(base / "ui.json"),
            "user": _read_json(self.root / "user" / "preferences.json"),
        }
        return self.game_data

    # ── 关卡级（进入关卡时加载，离开时卸载） ─────────────────────────
    def load_level(self, game_id: str, level_id: str) -> LevelMemory:
        game = safe_id(game_id)
        level = safe_id(level_id)
        if self.game_id != game:
            self.load_game(game)
        path = self.root / "games" / game / "levels" / f"{level}.json"
        self.level_id = level
        self.level_memory = LevelMemory.load(path, game_id=game, level_id=level)
        return self.level_memory

    def save_level(self) -> None:
        if self.game_id is None or self.level_id is None or self.level_memory is None:
            return
        path = self.root / "games" / self.game_id / "levels" / f"{self.level_id}.json"
        self.level_memory.save(path)

    def unload_level(self) -> None:
        self.save_level()
        self.level_id = None
        self.level_memory = None

    # ── 查询 ──────────────────────────────────────────────────────────
    def scope(self) -> str:
        if self.level_id is not None:
            return "level"
        if self.game_id is not None:
            return "game"
        return "general"

    def facts(self) -> dict:
        """Return currently loaded memory only (no cross-level leakage)."""
        data = {"scope": self.scope(), "game": self.game_id, "level": self.level_id}
        data.update(self.game_data)
        if self.level_memory is not None:
            data["level_memory"] = self.level_memory.to_dict()
        return data

    def manifest(self) -> dict:
        entries = []
        for path in (sorted(self.root.rglob("*.json")) if self.root.is_dir() else []):
            entries.append(str(path.relative_to(self.root)))
        return {"root": str(self.root), "scope": self.scope(), "entries": entries[:500]}
