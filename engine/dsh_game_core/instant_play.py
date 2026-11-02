"""冷启动 profile → 引擎 profile。

冷启动得到的是通用动作候选（move_right/jump/attack...），引擎 PolicyRunner 需要
具体的 controls 名称与 combat 参数。本模块做这层映射，并保留来源/置信度。

纯数据，不控制游戏。
"""

from __future__ import annotations

from typing import Any

DEFAULT_PLATFORMER = {
    "jump_every_ms": 800,
    "engage_radius": 0.0,
    "dodge": {"threat_radius": 0.18, "cooldown_ms": 350, "press_ms": 160},
    "stuck": {"scroll_min_px": 0.8, "after_ms": 600, "probe_ms": 350, "probe_keys": ["Z"]},
}


def _action_key(profile: dict, action: str) -> str | None:
    controls = (profile or {}).get("controls") or {}
    entry = controls.get(action)
    if isinstance(entry, dict):
        return str(entry.get("key") or "").upper() or None
    if isinstance(entry, str):
        return entry.upper()
    return None


def to_engine_profile(coldstart_profile: dict, *, profile_id: str = "coldstart", genre: str = "platformer") -> dict:
    """Map generic coldstart actions to the existing engine profile schema."""
    move = {
        "left": _action_key(coldstart_profile, "move_left") or "LEFT",
        "right": _action_key(coldstart_profile, "move_right") or "RIGHT",
        "up": _action_key(coldstart_profile, "move_up") or "UP",
        "down": _action_key(coldstart_profile, "move_down") or "DOWN",
        "jump": _action_key(coldstart_profile, "jump") or "Z",
        "shoot": _action_key(coldstart_profile, "attack") or "X",
        "dash": _action_key(coldstart_profile, "dash") or "SHIFT",
        "confirm": _action_key(coldstart_profile, "confirm") or _action_key(coldstart_profile, "jump") or "Z",
    }
    combat = dict(DEFAULT_PLATFORMER)
    combat.update(
        {
            "hold": [move["shoot"]],
            "advance": move["right"],
            "dodge": dict(DEFAULT_PLATFORMER["dodge"], keys=[move["jump"]]),
            "stuck": dict(DEFAULT_PLATFORMER["stuck"], probe_keys=[move["jump"]]),
        }
    )
    profile = {
        "id": profile_id,
        "name": f"{profile_id} (coldstart)",
        "controls": move,
        "combat": combat,
        "scene": {"refresh_ms": 2000, "recover_interval_ms": 700},
        "coldstart": {
            "genre": genre,
            "source": "coldstart",
            "verified_in_game": bool((coldstart_profile or {}).get("verified_in_game")),
            "sources": (coldstart_profile or {}).get("sources") or [],
        },
    }
    return profile


def summary(profile: dict) -> dict:
    controls = (profile or {}).get("controls") or {}
    return {
        "id": profile.get("id"),
        "controls": {name: value for name, value in controls.items()},
        "hold": ((profile.get("combat") or {}).get("hold") or []),
        "advance": (profile.get("combat") or {}).get("advance"),
        "coldstart": profile.get("coldstart"),
    }
