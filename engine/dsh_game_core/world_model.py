"""通用 WorldModel：把 observation 组织成空间/威胁/自身三块。

只做结构化，不下游戏名/关卡名判断；字段全部来自通用 observation 或调用方注入。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class SpaceState:
    left: float = 0.5
    right: float = 0.5
    ground: bool = True
    left_edge: bool = False
    right_edge: bool = False
    gap_ahead: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThreatView:
    id: str = "primary"
    type: str = "unknown"
    side: str = "unknown"
    lane: str = "unknown"
    ttc: float | None = None
    telegraph: str = "unknown"
    distance: float | None = None
    targetable: bool = True
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SelfState:
    hp: int | None = None
    action: dict = field(default_factory=dict)
    cooldowns: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorldModel:
    ts: float = 0.0
    scroll_s: float = 0.0
    space: SpaceState = field(default_factory=SpaceState)
    threats: list[ThreatView] = field(default_factory=list)
    self_state: SelfState = field(default_factory=SelfState)
    enemy_count: int = 0
    level_memory: dict = field(default_factory=dict)
    source: str = "observation"

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "scroll_s": self.scroll_s,
            "space": self.space.to_dict(),
            "threats": [threat.to_dict() for threat in self.threats],
            "self_state": self.self_state.to_dict(),
            "enemy_count": self.enemy_count,
            "level_memory": dict(self.level_memory),
            "source": self.source,
        }


def build_world_model(
    observation: dict | None,
    *,
    action_state: dict | None = None,
    hp: int | None = None,
    level_memory: dict | None = None,
    scroll_s: float | None = None,
    tracks: list | None = None,
    ts: float = 0.0,
) -> WorldModel:
    obs = observation or {}
    player = obs.get("player") or {}
    x = max(0.0, min(1.0, _num(player.get("x"), 0.5)))
    state = action_state or {}
    ground = bool(state.get("grounded", True)) and not bool(state.get("jumping")) and not bool(state.get("hurt"))
    space = SpaceState(
        left=round(x, 4),
        right=round(1.0 - x, 4),
        ground=ground,
        left_edge=x < 0.10,
        right_edge=x > 0.90,
        gap_ahead=bool(obs.get("gap_ahead")),
    )

    threats: list[ThreatView] = []
    if obs.get("enemy_ahead") or obs.get("enemy_role") or obs.get("enemy_ttc") is not None:
        ttc = obs.get("enemy_ttc")
        threats.append(
            ThreatView(
                type=str(obs.get("enemy_role") or "unknown"),
                side=str(obs.get("enemy_side") or "unknown"),
                lane=str(obs.get("enemy_side") or "unknown"),
                ttc=round(_num(ttc), 3) if ttc is not None else None,
                telegraph="incoming" if ttc is not None and _num(ttc) <= 0.6 else "none",
                distance=round(_num(obs.get("enemy_distance"), 0.0), 3) if obs.get("enemy_distance") is not None else None,
                confidence=round(_num(obs.get("player_confidence"), 0.0), 3),
            )
        )
    # 跟踪器给出的对象比单个 enemy_* 更全；只取 threat，按距离/ttc 排前 3。
    anchor_x = _num(player.get("x"), 0.5)
    anchor_y = _num(player.get("y"), 0.5)
    tracked: list[ThreatView] = []
    for track in tracks or []:
        kind = getattr(track, "kind", None) if not isinstance(track, dict) else track.get("kind")
        if kind != "threat":
            continue
        tx = getattr(track, "x", None) if not isinstance(track, dict) else track.get("x")
        ty = getattr(track, "y", None) if not isinstance(track, dict) else track.get("y")
        speed = getattr(track, "speed", 0.0) if not isinstance(track, dict) else track.get("speed")
        if tx is None or ty is None:
            continue
        dx = _num(tx) - anchor_x
        dy = _num(ty) - anchor_y
        distance = round((dx * dx + dy * dy) ** 0.5, 4)
        speed = _num(speed)
        ttc = round(distance / (speed * 60.0), 3) if speed > 0.01 else None
        tracked.append(
            ThreatView(
                id=f"track-{getattr(track, 'id', '') if not isinstance(track, dict) else track.get('id', '')}",
                type="track",
                side="left" if dx < 0 else "right",
                lane="left" if dx < 0 else "right",
                ttc=ttc,
                telegraph="incoming" if ttc is not None and ttc <= 0.6 else "none",
                distance=distance,
                targetable=True,
                confidence=0.6,
            )
        )
    tracked.sort(key=lambda item: (item.ttc if item.ttc is not None else 99.0, item.distance or 99.0))
    for item in tracked[:3]:
        if not threats or item.distance is not None and (threats[0].distance is None or item.distance < threats[0].distance):
            threats = [item] + [threat for threat in threats if threat.id != item.id]
        else:
            threats.append(item)

    self_state = SelfState(
        hp=hp if hp is not None else obs.get("hp"),
        action=dict(state),
        cooldowns={},
    )
    counts = obs.get("counts") or {}
    return WorldModel(
        ts=float(ts),
        scroll_s=round(float(scroll_s if scroll_s is not None else _num(obs.get("scroll_s"))), 3),
        space=space,
        threats=threats,
        self_state=self_state,
        enemy_count=int(counts.get("enemies") or 0),
        level_memory=dict(level_memory or {}),
        source="observation",
    )
