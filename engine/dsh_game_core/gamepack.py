"""GamePack contract: game-agnostic data packs for the general plugin.

A pack describes *what the engine may observe/control* and *how to verify it*.
It contains data only, never executable code, and the engine must not branch on
game names. Packs with anti-cheat are rejected outright (fail closed).

This module is intentionally small: schema v0 is the contract the rest of the
v3 work (auto-probe, T1/T2 checks, recipes) builds on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
CAPABILITY_LEVELS = (0, 1, 2, 3)
SAFE_ANTI_CHEAT = "none"


class GamePackError(ValueError):
    """Raised when a pack is missing required data or unsafe to load."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GamePackError(f"{field} must be an object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GamePackError(f"{field} must be a non-empty string")
    return value.strip()


def _level(value: Any, field: str) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError) as error:
        raise GamePackError(f"{field}.level must be an integer") from error
    if level not in CAPABILITY_LEVELS:
        raise GamePackError(f"{field}.level must be one of {CAPABILITY_LEVELS}")
    return level


def validate_pack(data: Any) -> dict:
    """Validate and normalize one GamePack dict.

    The returned dict is a shallow normalized copy. The input is not mutated.
    Unknown extra keys are preserved so schema v0 can grow without breaking
    older callers.
    """
    source = _mapping(data, "pack")
    pack = dict(source)

    try:
        schema = int(pack.get("schema"))
    except (TypeError, ValueError) as error:
        raise GamePackError("pack.schema must be an integer") from error
    if schema != SCHEMA_VERSION:
        raise GamePackError(f"pack.schema must be {SCHEMA_VERSION}")

    pack["schema"] = schema
    pack["id"] = _string(pack.get("id"), "pack.id")
    pack["title"] = _string(pack.get("title"), "pack.title")

    trust = _mapping(pack.get("trust", {}), "pack.trust")
    anti_cheat = str(trust.get("anti_cheat") or "unknown").strip().lower()
    if anti_cheat != SAFE_ANTI_CHEAT:
        raise GamePackError(f"pack.trust.anti_cheat must be '{SAFE_ANTI_CHEAT}' (got '{anti_cheat}')")
    pack["trust"] = {**dict(trust), "anti_cheat": anti_cheat}

    capabilities = _mapping(pack.get("capabilities", {}), "pack.capabilities")
    normalized_capabilities: dict[str, dict] = {}
    for name, raw in capabilities.items():
        if not isinstance(name, str) or not name.strip():
            raise GamePackError("pack.capabilities keys must be non-empty strings")
        spec = dict(_mapping(raw, f"pack.capabilities.{name}"))
        spec["level"] = _level(spec.get("level", 0), f"pack.capabilities.{name}")
        normalized_capabilities[name] = spec
    pack["capabilities"] = normalized_capabilities

    controls = _mapping(pack.get("controls", {}), "pack.controls")
    pack["controls"] = dict(controls)

    recipes = pack.get("recipes", [])
    if not isinstance(recipes, list):
        raise GamePackError("pack.recipes must be a list")
    normalized_recipes: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(recipes):
        recipe = dict(_mapping(raw, f"pack.recipes[{index}]"))
        recipe_id = _string(recipe.get("id"), f"pack.recipes[{index}].id")
        if recipe_id in seen:
            raise GamePackError(f"duplicate recipe id '{recipe_id}'")
        seen.add(recipe_id)
        steps = recipe.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise GamePackError(f"pack.recipes[{index}].steps must be a non-empty list")
        recipe["id"] = recipe_id
        recipe["steps"] = steps
        normalized_recipes.append(recipe)
    pack["recipes"] = normalized_recipes

    for field in ("evidence", "eval"):
        values = pack.get(field, [])
        if not isinstance(values, list):
            raise GamePackError(f"pack.{field} must be a list")
        pack[field] = [str(value) for value in values]

    if "level" in pack:
        pack["level"] = _level(pack["level"], "pack")
    return pack


def load_pack(path: str | Path) -> dict:
    """Load one JSON pack from disk and validate it."""
    file_path = Path(path)
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GamePackError(f"invalid JSON in {file_path}: {error}") from error
    return validate_pack(payload)


def capability_level(pack: Mapping[str, Any], name: str) -> int:
    """Return the declared level for a capability (0 when absent)."""
    capabilities = pack.get("capabilities") or {}
    if not isinstance(capabilities, Mapping):
        return 0
    spec = capabilities.get(name) or {}
    if not isinstance(spec, Mapping):
        return 0
    try:
        return _level(spec.get("level", 0), f"pack.capabilities.{name}")
    except GamePackError:
        return 0
