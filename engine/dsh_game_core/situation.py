"""L2 情境描述（Python 版）：把 WorldState 压缩成动态事件 SituationReport。

只描述，不决策。输出事件例如：
- threat_charging: "花妖从左侧接近，约0.3秒接触"
- gap_ahead: "前方有坑"
- low_hp / cornered
- threat_near

L3 根据 events/options 选择 Intent；L2 不碰按键。
"""

from __future__ import annotations

from typing import Any

from .contracts import SituationEvent, SituationReport, WorldState


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _side_text(side: str) -> str:
    return {
        "left": "左侧",
        "right": "右侧",
        "above": "上方",
        "below": "下方",
        "center": "正前方",
    }.get(side, "前方")


def describe(world: WorldState | dict, *, hp: int | None = None) -> dict:
    state = world if isinstance(world, WorldState) else WorldState.from_raw(world or {})
    events: list[SituationEvent] = []
    options: list[str] = ["advance", "attack"]
    uncertainty: list[str] = []

    threats = sorted(
        state.threats,
        key=lambda item: (item.ttc is None, item.ttc if item.ttc is not None else 9.0, item.distance),
    )
    for threat in threats[:4]:
        age_ms = threat.age_ms if hasattr(threat, "age_ms") else None
        if age_ms is not None and age_ms > 400:
            continue
        if threat.ttc is not None and threat.ttc <= 1.2 and threat.distance <= 0.45:
            side = _side_text(threat.side)
            events.append(
                SituationEvent(
                    type="threat_charging",
                    text=f"{side}有威胁接近，约{threat.ttc:.1f}秒接触",
                    side=threat.side,
                    threat_id=threat.id,
                    ttc=threat.ttc,
                    confidence=threat.confidence,
                    evidence=f"distance={threat.distance}, vx={threat.vx}",
                )
            )
            if threat.side in ("left", "right"):
                options.append(f"dodge_{'right' if threat.side == 'left' else 'left'}")
            options.append("jump")
        elif threat.distance <= 0.22:
            events.append(
                SituationEvent(
                    type="threat_near",
                    text=f"{_side_text(threat.side)}有威胁贴脸",
                    side=threat.side,
                    threat_id=threat.id,
                    ttc=threat.ttc,
                    confidence=threat.confidence,
                    evidence=f"distance={threat.distance}",
                )
            )
            options.append("retreat")

    for hazard in state.hazards[:2]:
        kind = str((hazard or {}).get("type") or "hazard")
        if kind in ("gap", "pit", "spike"):
            events.append(
                SituationEvent(
                    type="gap_ahead",
                    text="前方有坑/危险地形",
                    confidence=0.6,
                    evidence=kind,
                )
            )
            options.append("jump")

    player_hp = hp if hp is not None else state.player.get("hp")
    if player_hp is not None and int(player_hp) <= 1:
        events.append(
            SituationEvent(type="low_hp", text="血量很低", confidence=0.95, evidence=f"hp={player_hp}")
        )
        options.append("retreat")

    px = _f(state.player.get("x"), 0.5)
    space_left = px
    space_right = 1.0 - px
    if px <= 0.12 or px >= 0.88:
        events.append(
            SituationEvent(type="cornered", text="接近屏幕边缘，空间受限", confidence=0.5, evidence=f"x={px}")
        )
        options.append("jump")

    if not events:
        events.append(
            SituationEvent(type="no_immediate_threat", text="当前无近距离威胁", confidence=0.7)
        )
    if any(threat.confidence < 0.4 for threat in threats[:2]):
        uncertainty.append("low_threat_confidence")
    if not threats:
        uncertainty.append("no_threat_tracks")
    player_confidence = state.player.get("confidence")
    player_age_ms = state.player.get("age_ms")
    if player_confidence is not None and float(player_confidence) < 0.5:
        uncertainty.append("low_player_confidence")
    if player_age_ms is not None and float(player_age_ms) > 400:
        uncertainty.append("player_stale")

    report = SituationReport(
        ts=state.ts,
        scene=state.scene,
        events=events[:10],
        options=list(dict.fromkeys(options))[:8],
        player_state={
            "hp": player_hp,
            "cornered": px <= 0.12 or px >= 0.88,
            "x": round(px, 3),
            "space_left": round(space_left, 3),
            "space_right": round(space_right, 3),
            "confidence": player_confidence,
            "age_ms": player_age_ms,
        },
        uncertainty=uncertainty[:5],
        source="python",
    )
    return report.to_dict()
