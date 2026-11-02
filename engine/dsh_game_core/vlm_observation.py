"""VLM 低频观察 schema 与合并规则。

VLM 只负责语义字段（场景/目标/危险/可用交互），不直接给 60Hz 按键。
所有字段都要校验，非法值丢弃，并与算法 observation 合并；算法几何字段优先。
"""

from __future__ import annotations

from typing import Any

VLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene": {"type": "string", "enum": ["menu", "gameplay", "death", "equip", "cutscene", "loading", "unknown"]},
        "goal": {"type": "string", "maxLength": 120},
        "player_visible": {"type": "boolean"},
        "entities": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "maxLength": 32},
                    "role": {"type": "string", "maxLength": 32},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "threat": {"type": "boolean"},
                },
            },
        },
        "hazards": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 40}},
        "ui_prompt": {"type": "string", "maxLength": 60},
        "confidence": {"type": "number"},
    },
}

_SAFE_SCENES = {"menu", "gameplay", "death", "equip", "cutscene", "loading", "unknown"}


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def validate_vlm_observation(payload: Any) -> dict | None:
    """Return a sanitized VLM observation or None if unusable."""
    if not isinstance(payload, dict):
        return None
    scene = str(payload.get("scene") or "unknown").strip().lower()
    if scene not in _SAFE_SCENES:
        scene = "unknown"
    entities = []
    for raw in payload.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        entities.append(
            {
                "kind": str(raw.get("kind") or "")[:32],
                "role": str(raw.get("role") or "")[:32],
                "x": _clamp01(raw.get("x", 0.5)),
                "y": _clamp01(raw.get("y", 0.5)),
                "threat": bool(raw.get("threat")),
            }
        )
        if len(entities) >= 8:
            break
    hazards = [str(item)[:40] for item in (payload.get("hazards") or [])][:8]
    result = {
        "scene": scene,
        "goal": str(payload.get("goal") or "")[:120],
        "player_visible": bool(payload.get("player_visible")),
        "entities": entities,
        "hazards": hazards,
        "ui_prompt": str(payload.get("ui_prompt") or "")[:60],
        "confidence": _clamp01(payload.get("confidence", 0.5)),
        "source": "vlm",
    }
    if not result["player_visible"] and not entities and not hazards and not result["goal"]:
        return None
    return result


def merge_with_algorithmic(observation: dict, vlm: dict | None) -> dict:
    """Merge VLM semantics into algorithmic observation; geometry stays algorithmic."""
    merged = dict(observation or {})
    if not vlm:
        merged["vlm"] = None
        return merged
    merged["vlm"] = vlm
    # VLM scene 只在算法未知时补充
    if str(merged.get("scene") or "unknown").lower() == "unknown" and vlm.get("scene"):
        merged["scene"] = vlm["scene"]
    merged["goal"] = vlm.get("goal") or merged.get("goal")
    merged["hazards"] = list(vlm.get("hazards") or [])
    merged["ui_prompt"] = vlm.get("ui_prompt") or merged.get("prompt")
    if not merged.get("enemy_ahead"):
        threats = [item for item in vlm.get("entities") or [] if item.get("threat")]
        if threats:
            merged["enemy_ahead"] = True
            merged["enemy_role"] = threats[0].get("role") or "vlm_threat"
    merged["sources"] = sorted({str(merged.get("source") or "algorithmic"), "vlm"})
    return merged
