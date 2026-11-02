"""按键效果分类：把探测到的画面/玩家运动签名映射成通用动作候选。

输入是 probe_controls 的 results（画面变化）或 probe_motion 的轨迹统计：
- 跳跃：短时垂直位移显著；
- 冲刺：短时水平位移显著；
- 射击/交互：画面变化但玩家位移小（仅作弱候选，需上下文确认）；
- 菜单：场景/画面大切换（仅标记，不直接当游戏动作）。

这是先验分类，不代替实测；输出 source=probe、confidence。
"""

from __future__ import annotations

JUMP_DY = 0.10
DASH_DX = 0.06
MENU_DIFF = 40.0


def classify_motion(record: dict) -> dict | None:
    """Classify one probe_motion record into a control candidate."""
    if not isinstance(record, dict) or not record.get("key"):
        return None
    key = str(record["key"])
    max_dy = abs(float(record.get("max_abs_dy") or 0.0))
    max_dx = abs(float(record.get("max_abs_dx") or 0.0))
    if max_dy >= JUMP_DY and max_dy >= max_dx:
        return {
            "action": "jump",
            "key": key,
            "source": "probe",
            "confidence": min(0.95, 0.6 + max_dy),
            "evidence": f"max_abs_dy={max_dy}",
        }
    if max_dx >= DASH_DX and max_dx > max_dy:
        return {
            "action": "dash",
            "key": key,
            "source": "probe",
            "confidence": min(0.95, 0.55 + max_dx),
            "evidence": f"max_abs_dx={max_dx}",
        }
    return None


def classify_visual(record: dict) -> dict | None:
    """Classify one probe_controls record (screen diff) into a weak candidate."""
    if not isinstance(record, dict) or not record.get("key"):
        return None
    key = str(record["key"])
    diff = float(record.get("diff") or 0.0)
    if not record.get("changed"):
        return None
    if diff >= MENU_DIFF:
        action = "menu"
    else:
        action = f"effect_{key.lower()}"
    return {
        "action": action,
        "key": key,
        "source": "probe",
        "confidence": round(min(0.9, 0.4 + diff / 100.0), 3),
        "evidence": f"frame_diff={diff}",
    }


def motion_to_candidates(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for record in records or []:
        candidate = classify_motion(record)
        if candidate:
            out.append(candidate)
    return out


def visual_to_candidates(records: dict[str, dict] | list[dict]) -> list[dict]:
    items = records.values() if isinstance(records, dict) else records
    out: list[dict] = []
    for record in items or []:
        candidate = classify_visual(record)
        if candidate:
            out.append(candidate)
    return out
