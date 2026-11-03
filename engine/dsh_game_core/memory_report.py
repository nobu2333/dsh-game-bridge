"""离线检查记忆库：按游戏/关卡列出 LevelMemory 摘要与热点。

用法：
  python -m dsh_game_core.memory_report --root <memory-root>
  python -m dsh_game_core.memory_report --root <memory-root> --game cuphead --level forest-follies
不启动游戏，不读屏幕。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .level_memory import LevelMemory


def scan_memory(root: str | Path, *, game: str | None = None, level: str | None = None) -> dict:
    base = Path(root)
    games = []
    games_root = base / "games"
    if not games_root.is_dir():
        return {"root": str(base), "games": []}
    for game_dir in sorted(games_root.iterdir()):
        if not game_dir.is_dir():
            continue
        if game and game_dir.name != game:
            continue
        levels = []
        level_dir = game_dir / "levels"
        if level_dir.is_dir():
            for path in sorted(level_dir.glob("*.json")):
                if level and path.stem != level:
                    continue
                memory = LevelMemory.load(path, game_id=game_dir.name, level_id=path.stem)
                hotspots = [
                    {"segment": seg.get("key"), "deaths": seg.get("deaths", 0), "damage": seg.get("damage", 0)}
                    for seg in memory.segments.values()
                    if int(seg.get("deaths") or 0) >= 2
                ]
                hotspots.sort(key=lambda item: item["deaths"], reverse=True)
                levels.append(
                    {
                        "level": path.stem,
                        "path": str(path.relative_to(base)),
                        "summary": memory.summary(),
                        "hotspots": hotspots[:12],
                    }
                )
        games.append({"game": game_dir.name, "levels": levels})
    return {"root": str(base), "games": games}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect LevelMemory files (offline).")
    parser.add_argument("--root", required=True)
    parser.add_argument("--game")
    parser.add_argument("--level")
    args = parser.parse_args(argv)
    print(json.dumps(scan_memory(args.root, game=args.game, level=args.level), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
