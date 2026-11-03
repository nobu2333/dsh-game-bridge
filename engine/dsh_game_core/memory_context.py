"""把按需加载的记忆压成小上下文，供模型/决策层使用。

输入 MemoryLoader（当前 scope）+ 可选 guide cards；输出紧凑 dict：
- game: 只保留少量关键字段；
- level: hotspot/preferred/summary + 当前 segment 统计；
- guides: 只取与当前 scope 匹配的 top facts；
- 总字符预算，避免上下文膨胀。
"""

from __future__ import annotations

from typing import Any


def _clip(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def build_memory_context(
    loader: Any,
    *,
    scroll_s: float = 0.0,
    guide_cards: list[dict] | None = None,
    max_chars: int = 2000,
) -> dict:
    budget = max(200, int(max_chars))
    data = {"scope": "general", "game": None, "level": None, "guides": [], "truncated": False}
    if loader is not None:
        try:
            data["scope"] = loader.scope()
            data["game"] = loader.game_id
            data["level"] = loader.level_id
        except Exception:  # noqa: BLE001
            pass
        game_data = getattr(loader, "game_data", None) or {}
        for key in ("game", "entities", "ui", "general", "guides"):
            payload = game_data.get(key)
            if isinstance(payload, dict) and payload:
                data[key] = payload
        memory = getattr(loader, "level_memory", None)
        if memory is not None:
            try:
                segment = memory.query(float(scroll_s)) or {}
                data["level_memory"] = {
                    "summary": memory.summary(),
                    "hotspot": memory.hotspot(float(scroll_s)),
                    "preferred": memory.preferred_action(float(scroll_s)),
                    "segment": {
                        "key": segment.get("key"),
                        "deaths": segment.get("deaths", 0),
                        "damage": segment.get("damage", 0),
                        "actions": segment.get("actions", {}),
                    },
                }
            except Exception:  # noqa: BLE001
                pass

    facts = []
    guide_source = guide_cards
    if not guide_source and isinstance(data.get("guides"), dict):
        guide_source = list(data["guides"].get("game") or []) + list(data["guides"].get("level") or [])
    for card in guide_source or []:
        if not isinstance(card, dict):
            continue
        scope = str(card.get("scope") or "level")
        if scope not in ("general", "game", data.get("scope")):
            continue
        for fact in card.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            text = _clip(fact.get("text"), 240)
            if text:
                facts.append({"type": _clip(fact.get("type") or "note", 24), "text": text, "source": _clip(card.get("source_url"), 120)})
    data["guides"] = facts[:12]

    # 粗略字符预算：超了就逐步裁掉 guides -> entities/ui。
    def size(obj) -> int:
        try:
            import json

            return len(json.dumps(obj, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            return 0

    if size(data) > budget:
        data["guides"] = data["guides"][:4]
        data["truncated"] = True
    if size(data) > budget and isinstance(data.get("entities"), dict):
        data["entities"] = {"note": "truncated"}
        data["truncated"] = True
    if size(data) > budget and isinstance(data.get("game"), dict):
        keep = {key: data["game"][key] for key in ("id", "name", "controls") if key in data["game"]}
        data["game"] = keep
        data["truncated"] = True
    return data
