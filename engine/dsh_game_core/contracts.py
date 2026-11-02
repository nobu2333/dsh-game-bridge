"""五层分工的四份接口契约。

L1 -> L2/L3: WorldState
L2 -> L3:    SituationReport
L3 -> L1:    Intent
L1 -> L3:    ActionResult

纯数据/校验，不控制游戏。所有跨层数据都经过 normalize/clamp，避免坏字段
直接进入执行层。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

RISK_LEVELS = ("low", "medium", "high")
GOALS = ("advance", "retreat", "avoid", "attack", "survive", "explore")
INTENT_TTL_MIN = 100
INTENT_TTL_MAX = 5000


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _now() -> float:
    return round(time.time(), 3)


@dataclass
class ThreatState:
    id: int | None
    role: str
    dx: float
    dy: float
    vx: float
    vy: float
    distance: float
    ttc: float | None
    confidence: float
    side: str = ""
    age_ms: float = 0.0

    @classmethod
    def from_raw(cls, raw: dict) -> "ThreatState | None":
        if not isinstance(raw, dict):
            return None
        try:
            threat_id = int(raw["id"]) if raw.get("id") is not None else None
        except (TypeError, ValueError):
            threat_id = None
        return cls(
            id=threat_id,
            role=_text(raw.get("role"), 32),
            dx=round(_clamp(_num(raw.get("dx")), -1.0, 1.0), 4),
            dy=round(_clamp(_num(raw.get("dy")), -1.0, 1.0), 4),
            vx=round(_clamp(_num(raw.get("vx")), -2.0, 2.0), 4),
            vy=round(_clamp(_num(raw.get("vy")), -2.0, 2.0), 4),
            distance=round(_clamp(_num(raw.get("distance")), 0.0, 2.0), 4),
            ttc=(round(_clamp(_num(raw.get("ttc")), 0.0, 5.0), 4) if raw.get("ttc") is not None else None),
            confidence=round(_clamp(_num(raw.get("confidence"), 0.5), 0.0, 1.0), 3),
            side=_text(raw.get("side"), 12),
            age_ms=round(_clamp(_num(raw.get("age_ms")), 0.0, 10000.0), 0),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "dx": self.dx,
            "dy": self.dy,
            "vx": self.vx,
            "vy": self.vy,
            "distance": self.distance,
            "ttc": self.ttc,
            "confidence": self.confidence,
            "side": self.side,
            "age_ms": self.age_ms,
        }


@dataclass
class WorldState:
    ts: float
    scene: str
    player: dict
    threats: list[ThreatState] = field(default_factory=list)
    hazards: list[dict] = field(default_factory=list)
    progress: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)
    uncertainty: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict) -> "WorldState":
        raw = raw if isinstance(raw, dict) else {}
        threats = [item for item in (ThreatState.from_raw(item) for item in raw.get("threats") or []) if item]
        player = raw.get("player") if isinstance(raw.get("player"), dict) else {}
        return cls(
            ts=round(_num(raw.get("ts"), time.time()), 3),
            scene=_text(raw.get("scene") or "unknown", 24),
            player={
                "x": round(_clamp(_num(player.get("x"), 0.5), 0.0, 1.0), 4),
                "y": round(_clamp(_num(player.get("y"), 0.8), 0.0, 1.0), 4),
                "vx": round(_clamp(_num(player.get("vx")), -2.0, 2.0), 4),
                "vy": round(_clamp(_num(player.get("vy")), -2.0, 2.0), 4),
                "hp": player.get("hp"),
            },
            threats=threats[:8],
            hazards=[item for item in (raw.get("hazards") or []) if isinstance(item, dict)][:8],
            progress={
                "scroll_s": round(_num((raw.get("progress") or {}).get("scroll_s")), 3),
                "stalled_ms": round(_clamp(_num((raw.get("progress") or {}).get("stalled_ms")), 0.0, 60000.0), 0),
            },
            actions={
                "held": [str(item)[:16] for item in (raw.get("actions") or {}).get("held") or []][:8],
                "last": _text((raw.get("actions") or {}).get("last"), 24),
            },
            uncertainty=[str(item)[:40] for item in raw.get("uncertainty") or []][:8],
        )

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "scene": self.scene,
            "player": dict(self.player),
            "threats": [item.to_dict() for item in self.threats],
            "hazards": list(self.hazards),
            "progress": dict(self.progress),
            "actions": dict(self.actions),
            "uncertainty": list(self.uncertainty),
        }


@dataclass
class SituationEvent:
    type: str
    text: str
    side: str = ""
    threat_id: int | None = None
    ttc: float | None = None
    confidence: float = 0.5
    evidence: str = ""

    @classmethod
    def from_raw(cls, raw: dict) -> "SituationEvent | None":
        if not isinstance(raw, dict) or not raw.get("type"):
            return None
        try:
            threat_id = int(raw["threat_id"]) if raw.get("threat_id") is not None else None
        except (TypeError, ValueError):
            threat_id = None
        return cls(
            type=_text(raw.get("type"), 40),
            text=_text(raw.get("text"), 160),
            side=_text(raw.get("side"), 12),
            threat_id=threat_id,
            ttc=(round(_clamp(_num(raw.get("ttc")), 0.0, 5.0), 3) if raw.get("ttc") is not None else None),
            confidence=round(_clamp(_num(raw.get("confidence"), 0.5), 0.0, 1.0), 3),
            evidence=_text(raw.get("evidence"), 120),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "side": self.side,
            "threat_id": self.threat_id,
            "ttc": self.ttc,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass
class SituationReport:
    ts: float
    scene: str
    events: list[SituationEvent]
    options: list[str]
    player_state: dict
    uncertainty: list[str]
    source: str = "python"

    @classmethod
    def from_raw(cls, raw: dict) -> "SituationReport":
        raw = raw if isinstance(raw, dict) else {}
        events = [item for item in (SituationEvent.from_raw(item) for item in raw.get("events") or []) if item]
        player = raw.get("player_state") if isinstance(raw.get("player_state"), dict) else {}
        return cls(
            ts=round(_num(raw.get("ts"), time.time()), 3),
            scene=_text(raw.get("scene") or "unknown", 24),
            events=events[:12],
            options=[str(item)[:32] for item in raw.get("options") or []][:8],
            player_state={
                "hp": player.get("hp"),
                "cornered": bool(player.get("cornered")),
                "x": round(_clamp(_num(player.get("x"), 0.5), 0.0, 1.0), 3) if player.get("x") is not None else None,
                "space_left": round(_clamp(_num(player.get("space_left")), 0.0, 1.0), 3) if player.get("space_left") is not None else None,
                "space_right": round(_clamp(_num(player.get("space_right")), 0.0, 1.0), 3) if player.get("space_right") is not None else None,
            },
            uncertainty=[str(item)[:40] for item in raw.get("uncertainty") or []][:8],
            source=_text(raw.get("source") or "python", 16),
        )

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "scene": self.scene,
            "events": [item.to_dict() for item in self.events],
            "options": list(self.options),
            "player_state": dict(self.player_state),
            "uncertainty": list(self.uncertainty),
            "source": self.source,
        }


@dataclass
class Intent:
    intent_id: str
    goal: str
    skill: str
    risk: str
    ttl_ms: int
    priority: int
    target_id: int | None
    reason: str
    source: str = "model"

    @classmethod
    def from_raw(cls, raw: dict) -> "Intent | None":
        if not isinstance(raw, dict):
            return None
        goal = _text(raw.get("goal"), 24).lower() or "advance"
        if goal not in GOALS:
            goal = "advance"
        skill = _text(raw.get("skill"), 32)
        if not skill:
            return None
        risk = _text(raw.get("risk") or "medium", 12).lower()
        if risk not in RISK_LEVELS:
            risk = "medium"
        ttl = int(_clamp(_num(raw.get("ttl_ms"), 1500), INTENT_TTL_MIN, INTENT_TTL_MAX))
        priority = int(_clamp(_num(raw.get("priority"), 5), 0, 10))
        try:
            target_id = int(raw["target_id"]) if raw.get("target_id") is not None else None
        except (TypeError, ValueError):
            target_id = None
        return cls(
            intent_id=_text(raw.get("intent_id") or f"i-{int(time.time() * 1000) % 1000000}", 40),
            goal=goal,
            skill=skill,
            risk=risk,
            ttl_ms=ttl,
            priority=priority,
            target_id=target_id,
            reason=_text(raw.get("reason"), 200),
            source=_text(raw.get("source") or "model", 16),
        )

    def to_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "goal": self.goal,
            "skill": self.skill,
            "risk": self.risk,
            "ttl_ms": self.ttl_ms,
            "priority": self.priority,
            "target_id": self.target_id,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class ActionResult:
    intent_id: str
    executed: str
    status: str
    outcome: str = ""
    detail: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict) -> "ActionResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            intent_id=_text(raw.get("intent_id"), 40),
            executed=_text(raw.get("executed"), 40),
            status=_text(raw.get("status") or "unknown", 24),
            outcome=_text(raw.get("outcome"), 160),
            detail=raw.get("detail") if isinstance(raw.get("detail"), dict) else {},
        )

    def to_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "executed": self.executed,
            "status": self.status,
            "outcome": self.outcome,
            "detail": dict(self.detail),
        }
