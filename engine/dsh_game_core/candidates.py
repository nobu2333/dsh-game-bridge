"""候选动作评分（shadow）：通用 observation + LevelMemory -> 排序候选。

只输出建议/分数，不控制按键。后续可把 top1 交给仲裁器，先 shadow 收集证据。

候选：advance / attack / jump / dash / retreat / wait。
特征：hp、enemy_ttc、enemy_side、gap、space、LevelMemory hotspot/preferred。
"""

from __future__ import annotations

from typing import Any

BASE = {
    "advance": 0.50,
    "attack": 0.55,
    "jump": 0.40,
    "dash": 0.42,
    "retreat": 0.30,
    "wait": 0.20,
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score_actions(observation: dict, *, level_memory: Any = None, scroll_s: float = 0.0, hotspot_bonus: float = 0.12) -> dict:
    obs = observation or {}
    scores = dict(BASE)
    reasons: dict[str, list[str]] = {name: [] for name in scores}

    hp = obs.get("hp")
    threat = bool(obs.get("enemy_ahead"))
    ttc = obs.get("enemy_ttc")
    side = str(obs.get("enemy_side") or "")
    gap = bool(obs.get("gap_ahead"))

    if threat:
        scores["attack"] += 0.12
        scores["advance"] -= 0.08
        reasons["attack"].append("threat_ahead")
    if ttc is not None and _num(ttc) <= 0.6:
        scores["jump"] += 0.30
        scores["dash"] += 0.25
        scores["advance"] -= 0.20
        scores["attack"] -= 0.15
        reasons["jump"].append(f"ttc={round(_num(ttc), 2)}")
        reasons["dash"].append(f"ttc={round(_num(ttc), 2)}")
    if gap:
        scores["jump"] += 0.3
        scores["advance"] -= 0.3
        reasons["jump"].append("gap_ahead")
    if hp is not None and int(hp) <= 1:
        scores["retreat"] += 0.45
        scores["attack"] -= 0.15
        scores["advance"] -= 0.10
        reasons["retreat"].append("low_hp")
    if side in ("left", "right"):
        # 无法知道左右空间时，仅给“后退/位移”轻微权重。
        scores["retreat"] += 0.03
        reasons["retreat"].append(f"threat_{side}")

    memory_status = {"hotspot": False, "preferred": None}
    if level_memory is not None:
        try:
            memory_status["hotspot"] = bool(level_memory.hotspot(float(scroll_s)))
            memory_status["preferred"] = level_memory.preferred_action(float(scroll_s))
        except Exception:  # noqa: BLE001
            pass
        if memory_status["preferred"] in scores:
            scores[memory_status["preferred"]] += 0.15
            reasons[memory_status["preferred"]].append("level_memory_preferred")
        if memory_status["hotspot"]:
            scores["jump"] += hotspot_bonus
            scores["dash"] += hotspot_bonus
            scores["retreat"] += hotspot_bonus
            scores["advance"] -= hotspot_bonus
            for name in ("jump", "dash", "retreat"):
                reasons[name].append("hotspot")

    ranked = [
        {"action": name, "score": round(max(0.0, min(1.5, score)), 3), "reasons": reasons[name]}
        for name, score in scores.items()
    ]
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return {
        "ranked": ranked,
        "top": ranked[0] if ranked else None,
        "level_memory": memory_status,
        "shadow": True,
    }
