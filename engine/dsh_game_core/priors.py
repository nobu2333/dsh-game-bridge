"""通用游戏先验库：genre / controls / UI 的假设，不是硬规则。

每条先验都带 source/confidence/exceptions；进游戏后必须实测验证。
"""

from __future__ import annotations

from copy import deepcopy

PRIOR_VERSION = 1

GENRE_PRIORS: dict[str, dict] = {
    "platformer": {
        "advance": "right",
        "core_skills": ["jump", "attack", "dash"],
        "hazards": ["pit", "projectile", "contact"],
        "ui_expectations": ["hud_hp", "pause_menu"],
        "exceptions": ["auto-scroll left", "vertical levels"],
    },
    "run_and_gun": {
        "advance": "right",
        "core_skills": ["shoot", "jump", "dash", "duck"],
        "hazards": ["projectile", "pit", "contact"],
        "ui_expectations": ["hud_hp", "hud_ammo"],
        "exceptions": ["backtracking sections"],
    },
    "topdown": {
        "advance": "toward objective",
        "core_skills": ["move", "attack", "interact"],
        "hazards": ["contact", "projectile"],
        "ui_expectations": ["hud_hp", "minimap"],
        "exceptions": ["twin-stick aiming"],
    },
    "shooter": {
        "advance": "toward objective",
        "core_skills": ["aim", "shoot", "reload", "cover"],
        "hazards": ["projectile", "line_of_sight"],
        "ui_expectations": ["hud_ammo", "crosshair"],
        "exceptions": ["third-person lock-on"],
    },
    "turn_based": {
        "advance": "menu",
        "core_skills": ["select", "confirm", "cancel"],
        "hazards": ["resource_loss"],
        "ui_expectations": ["menu", "turn_order"],
        "exceptions": ["real-time with pause"],
    },
    "menu_heavy": {
        "advance": "menu",
        "core_skills": ["navigate", "confirm", "cancel"],
        "hazards": ["save overwrite"],
        "ui_expectations": ["menu"],
        "exceptions": [],
    },
}

CONTROL_CONVENTIONS: dict[str, list[str]] = {
    "platformer": ["arrows/WASD move", "Z/space jump", "X/attack", "shift dash"],
    "menu": ["up/down select", "confirm/enter", "cancel/esc"],
    "shooter": ["WASD move", "mouse aim", "mouse1 fire", "R reload"],
}


def prior_for(genre: str) -> dict:
    """Return a copy of the genre prior with source/confidence; unknown genre is empty."""
    key = str(genre or "").strip().lower()
    data = GENRE_PRIORS.get(key)
    if data is None:
        return {"genre": key or "unknown", "prior": {}, "source": "generic_prior", "confidence": 0.0, "version": PRIOR_VERSION}
    return {
        "genre": key,
        "prior": deepcopy(data),
        "source": "generic_prior",
        "confidence": 0.45,
        "version": PRIOR_VERSION,
        "verified_in_game": False,
    }


def controls_hints(genre: str) -> list[str]:
    key = str(genre or "").strip().lower()
    return list(CONTROL_CONVENTIONS.get(key, []))


def all_priors() -> dict:
    return {"version": PRIOR_VERSION, "genres": deepcopy(GENRE_PRIORS), "controls": deepcopy(CONTROL_CONVENTIONS)}
