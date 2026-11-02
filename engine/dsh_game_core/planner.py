"""L3 最小战术规划器（Python 占位，未来替换为模型/子 agent）。

输入 SituationReport，输出 Intent。只做高层选择（goal/skill/TTL），不碰按键。
优先级：安全类（gap/cornered）> 逼近威胁 > 贴脸 > 低血 > 默认推进。
"""

from __future__ import annotations

from typing import Any

from .contracts import Intent, SituationReport


def _events_by_type(report: dict, event_type: str) -> list[dict]:
    return [event for event in report.get("events") or [] if event.get("type") == event_type]


def choose_intent(report: SituationReport | dict, *, hp: int | None = None) -> dict:
    raw = report if isinstance(report, SituationReport) else SituationReport.from_raw(report or {})
    event_list = [event.to_dict() for event in raw.events]
    player_hp = hp if hp is not None else raw.player_state.get("hp")

    def make(goal: str, skill: str, reason: str, *, risk: str = "medium", ttl: int = 800, priority: int = 7, target_id=None):
        intent = Intent.from_raw(
            {
                "goal": goal,
                "skill": skill,
                "risk": risk,
                "ttl_ms": ttl,
                "priority": priority,
                "target_id": target_id,
                "reason": reason,
                "source": "local_planner",
            }
        )
        return intent.to_dict() if intent else {"goal": "advance", "skill": "advance", "source": "local_planner"}

    gaps = _events_by_type(raw.to_dict(), "gap_ahead")
    if gaps:
        return make("avoid", "jump", "gap ahead", risk="high", ttl=700, priority=9)

    charging = _events_by_type(raw.to_dict(), "threat_charging")
    if charging:
        event = min(charging, key=lambda item: item.get("ttc") if item.get("ttc") is not None else 9.9)
        side = str(event.get("side") or "center")
        ttc = event.get("ttc")
        if side == "left":
            return make("avoid", "dodge_right", "left threat charging", risk="high", ttl=650, priority=9, target_id=event.get("threat_id"))
        if side == "right":
            return make("avoid", "dodge_left", "right threat charging", risk="high", ttl=650, priority=9, target_id=event.get("threat_id"))
        if side == "above":
            return make("avoid", "move_down", "above threat", risk="high", ttl=650, priority=9, target_id=event.get("threat_id"))
        return make("avoid", "jump", f"charging ttc={ttc}", risk="high", ttl=600, priority=9, target_id=event.get("threat_id"))

    near = _events_by_type(raw.to_dict(), "threat_near")
    if near:
        event = near[0]
        if player_hp is not None and int(player_hp) <= 1:
            return make("retreat", "retreat", "low hp + near threat", risk="high", ttl=900, priority=8, target_id=event.get("threat_id"))
        return make("attack", "attack", "threat near", risk="medium", ttl=700, priority=7, target_id=event.get("threat_id"))

    if _events_by_type(raw.to_dict(), "low_hp"):
        return make("retreat", "retreat", "low hp", risk="medium", ttl=1200, priority=6)

    if _events_by_type(raw.to_dict(), "cornered"):
        return make("avoid", "jump", "cornered", risk="medium", ttl=700, priority=6)

    return make("advance", "advance", "no immediate threat", risk="low", ttl=1500, priority=3)
