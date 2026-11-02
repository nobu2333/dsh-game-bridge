"""低频观察与技能选择。

把 WorldState/entities/terrain 整理成一份稳定 observation，再用通用规则选择技能。
VLM 将来只负责补充语义字段；没有 VLM 时这层也能工作。

不控制游戏；纯数据 + 决策。
"""

from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_observation(
    *,
    scene: str | None = None,
    hp: int | None = None,
    player: dict | None = None,
    entities: list[dict] | None = None,
    prompt: str | None = None,
    scroll_s: float | None = None,
    ledges: list[dict] | None = None,
    terrain_gap: bool | None = None,
) -> dict:
    """Normalize raw state into an observation used by skill selection."""
    player = player or {}
    tracks = [item for item in (entities or []) if isinstance(item, dict)]
    enemies = [
        item
        for item in tracks
        if str(item.get("role") or "").lower() in ("harmful", "chaser", "approaching", "projectile", "enemy")
    ]
    ahead = []
    for enemy in enemies:
        distance = _num(enemy.get("distance"), 1.0)
        behind = bool(enemy.get("behind"))
        if not behind and distance <= 0.35:
            ahead.append(enemy)
    ahead.sort(key=lambda item: _num(item.get("distance"), 1.0))
    nearest = ahead[0] if ahead else None
    behind_enemies = [item for item in enemies if item.get("behind")]

    gap = terrain_gap
    if gap is None:
        gap = False
    observation = {
        "scene": str(scene or "unknown"),
        "hp": hp,
        "player": {"x": _num(player.get("x"), 0.5), "y": _num(player.get("y"), 0.8)},
        "prompt": prompt,
        "scroll_s": scroll_s,
        "counts": {"entities": len(tracks), "enemies": len(enemies)},
        "enemy_ahead": bool(nearest),
        "enemy_distance": round(_num(nearest.get("distance"), 1.0), 3) if nearest else None,
        "enemy_role": str(nearest.get("role")) if nearest else None,
        "enemy_ttc": nearest.get("ttc") if nearest else None,
        "enemy_side": nearest.get("side") if nearest else None,
        "enemy_vx": nearest.get("vx") if nearest else None,
        "enemy_behind": bool(behind_enemies),
        "gap_ahead": bool(gap),
        "ledges": len(ledges or []),
    }
    return observation


def choose_skill(observation: dict, *, low_hp: int = 1) -> dict:
    """Generic priority: recover > confirm > jump gap > attack > retreat > advance."""
    if not isinstance(observation, dict):
        return {"skill": "hold", "reason": "no observation"}
    scene = str(observation.get("scene") or "").lower()
    if scene in ("menu", "death", "equip", "cutscene", "unknown"):
        return {"skill": "recover", "reason": f"scene={scene}"}
    if observation.get("prompt"):
        return {"skill": "confirm", "reason": f"prompt={observation.get('prompt')}"}
    if observation.get("gap_ahead"):
        return {"skill": "jump", "reason": "gap ahead"}
    if observation.get("enemy_ahead"):
        return {"skill": "attack", "reason": f"enemy ahead role={observation.get('enemy_role')}"}
    hp = observation.get("hp")
    if hp is not None and int(hp) <= int(low_hp) and observation.get("enemy_behind"):
        return {"skill": "retreat", "reason": "low hp + enemy behind"}
    return {"skill": "advance", "reason": "default"}
