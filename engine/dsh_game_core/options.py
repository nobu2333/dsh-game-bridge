"""Option 库 + UtilityArbiter（shadow）。

Option 是“有前置/效果/冷却/最短承诺”的技能；Arbiter 只选 option，不直接发按键。
这个模块是策略 v2 的骨架，先 shadow，经由 status 暴露，供后续 canary。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .world_model import WorldModel


@dataclass
class OptionSpec:
    id: str
    description: str = ""
    preconditions: tuple[str, ...] = ()
    effect: str = ""
    cooldown_ms: int = 0
    min_commit_ms: int = 200
    base_utility: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "preconditions": list(self.preconditions),
            "effect": self.effect,
            "cooldown_ms": self.cooldown_ms,
            "min_commit_ms": self.min_commit_ms,
            "base_utility": self.base_utility,
        }


def default_options() -> list[OptionSpec]:
    return [
        OptionSpec("advance", "hold advance + shoot", ("not_hurt",), "advance", 0, 250, 0.50),
        OptionSpec("strafe_left", "move left with space", ("space_left", "not_hurt"), "tap left", 150, 180, 0.30),
        OptionSpec("strafe_right", "move right with space", ("space_right", "not_hurt"), "tap right", 150, 180, 0.30),
        OptionSpec("jump_over", "jump over threat/gap (executor waits for ground)", ("threat_or_gap",), "tap jump", 250, 350, 0.40),
        OptionSpec("dash_through", "dash through imminent threat", ("not_hurt", "threat_imminent"), "tap dash", 500, 180, 0.35),
        OptionSpec("stop_shoot", "stop advancing and shoot", ("threat_near",), "release advance + shoot", 0, 250, 0.40),
    ]


def _precondition_ok(name: str, world: WorldModel) -> bool:
    space = world.space
    action = world.self_state.action or {}
    threats = world.threats
    primary = threats[0] if threats else None
    ttc = primary.ttc if primary and primary.ttc is not None else None
    if name == "not_hurt":
        return not bool(action.get("hurt"))
    if name == "grounded":
        return bool(space.ground)
    if name == "space_left":
        return space.left >= 0.15 and not space.left_edge
    if name == "space_right":
        return space.right >= 0.15 and not space.right_edge
    if name == "threat_or_gap":
        return bool(space.gap_ahead) or (primary is not None)
    if name == "threat_imminent":
        return ttc is not None and ttc <= 0.5
    if name == "threat_near":
        return primary is not None and (primary.distance is None or primary.distance <= 0.35)
    return True


def score_option(option: OptionSpec, world: WorldModel) -> float:
    space = world.space
    primary = world.threats[0] if world.threats else None
    ttc = primary.ttc if primary and primary.ttc is not None else None
    score = option.base_utility
    if option.id == "advance":
        score += 0.30
        if primary is not None:
            score -= 0.25
        if space.gap_ahead:
            score -= 0.50
    elif option.id.startswith("strafe"):
        score += 0.10
        if primary is not None and primary.side in ("left", "right"):
            score += 0.15 if option.id.endswith(primary.side) else 0.0
    elif option.id == "jump_over":
        if space.gap_ahead:
            score += 0.55
        if ttc is not None and ttc <= 0.8:
            score += 0.40
    elif option.id == "dash_through":
        if ttc is not None and ttc <= 0.5:
            score += 0.55
    elif option.id == "stop_shoot":
        if primary is not None:
            score += 0.15
    hp = world.self_state.hp
    if hp is not None and int(hp) <= 1:
        if option.id == "advance":
            score -= 0.20
        elif option.id in ("strafe_left", "strafe_right", "stop_shoot"):
            score += 0.15
    if option.id == "strafe_left" and space.left_edge:
        score -= 1.0
    if option.id == "strafe_right" and space.right_edge:
        score -= 1.0
    return round(max(0.0, min(2.0, score)), 4)


class UtilityArbiter:
    """Selects one option with safety veto, cooldowns and minimum commitment. Shadow-only."""

    def __init__(self, options: list[OptionSpec] | None = None, *, hysteresis: float = 0.12) -> None:
        self.options = options or default_options()
        self.hysteresis = max(0.0, float(hysteresis))
        self.active_id: str | None = None
        self.active_since = 0.0
        self.last_used: dict[str, float] = {}

    def _available(self, option: OptionSpec, world: WorldModel, now_ms: float) -> tuple[bool, str]:
        if not self._enabled(option, world):
            return False, "safety_veto"
        for precondition in option.preconditions:
            if not _precondition_ok(precondition, world):
                return False, f"precondition:{precondition}"
        last = self.last_used.get(option.id)
        if last is not None and now_ms - last < option.cooldown_ms:
            return False, "cooldown"
        return True, "ok"

    def _enabled(self, option: OptionSpec, world: WorldModel) -> bool:
        # Hard safety vetoes: never pick an option that commits into a pit/edge.
        if option.id == "advance" and world.space.gap_ahead and not world.space.ground:
            return False
        if option.id == "strafe_left" and world.space.left_edge:
            return False
        if option.id == "strafe_right" and world.space.right_edge:
            return False
        return True

    def select(self, world: WorldModel, now_ms: float | None = None) -> dict:
        now = float(now_ms if now_ms is not None else world.ts)
        if self.active_id is not None:
            active = next((item for item in self.options if item.id == self.active_id), None)
            if active is not None and now - self.active_since < active.min_commit_ms:
                return {
                    "option": active.id,
                    "scores": {active.id: score_option(active, world)},
                    "reason": "commit",
                    "shadow": True,
                }
        ranked = []
        reasons = {}
        for option in self.options:
            ok, reason = self._available(option, world, now)
            reasons[option.id] = reason
            if ok:
                ranked.append((score_option(option, world), option.id))
        ranked.sort(reverse=True)
        if not ranked:
            # Still return a safe read-only fallback; caller must not execute it blindly.
            return {"option": "wait", "scores": {}, "reason": "no_available_option", "shadow": True, "rejected": reasons}
        top_score, top_id = ranked[0]
        if self.active_id == top_id:
            chosen = top_id
            reason = "continue"
        elif self.active_id is not None and ranked:
            active_score = next((score for score, oid in ranked if oid == self.active_id), None)
            if active_score is not None and top_score - active_score <= self.hysteresis:
                chosen = self.active_id
                reason = "hysteresis"
            else:
                chosen = top_id
                reason = "switch"
        else:
            chosen = top_id
            reason = "initial"
        self.active_id = chosen
        self.active_since = now
        self.last_used[chosen] = now
        return {
            "option": chosen,
            "scores": {oid: score for score, oid in ranked},
            "reason": reason,
            "shadow": True,
            "rejected": reasons,
        }
