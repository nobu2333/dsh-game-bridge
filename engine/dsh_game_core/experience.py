"""每游戏经验学习：通用情境 → 动作 → 结果。

不写游戏名/怪物名/关卡坐标。Context 只包含通用特征：
scene/hp/threat side/ttc/distance/space/move_type。

SkillStats 用 UCB 在已记录的情境里选动作；没有数据时按给定顺序先探索。
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any

CONTEXT_VERSION = 1


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket(value: float, *, scale: float = 0.25) -> int:
    """Coarse bucket so nearby situations share statistics."""
    return int(round(_num(value) / max(1e-6, scale)))


def _symbol(value: Any, limit: int = 24) -> str:
    text = str(value or "").strip().lower()
    return text[:limit]


@dataclass
class Context:
    scene: str = "unknown"
    hp: int | None = None
    threat_side: str = ""
    threat_ttc: float | None = None
    threat_distance: float | None = None
    space_left: float | None = None
    space_right: float | None = None
    move_type: str = ""
    version: int = CONTEXT_VERSION

    def key(self, *, coarse: bool = False) -> str:
        if coarse:
            payload = {
                "v": self.version,
                "scene": _symbol(self.scene),
                "hp": None if self.hp is None else int(self.hp),
                "side": _symbol(self.threat_side, 8),
                "left": None if self.space_left is None else _bucket(self.space_left, scale=0.34),
                "right": None if self.space_right is None else _bucket(self.space_right, scale=0.34),
            }
        else:
            payload = {
                "v": self.version,
                "scene": _symbol(self.scene),
                "hp": None if self.hp is None else int(self.hp),
                "side": _symbol(self.threat_side, 8),
                "ttc": None if self.threat_ttc is None else _bucket(self.threat_ttc, scale=0.25),
                "distance": None if self.threat_distance is None else _bucket(self.threat_distance, scale=0.15),
                "left": None if self.space_left is None else _bucket(self.space_left, scale=0.25),
                "right": None if self.space_right is None else _bucket(self.space_right, scale=0.25),
                "move": _symbol(self.move_type),
            }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "scene": self.scene,
            "hp": self.hp,
            "threat_side": self.threat_side,
            "threat_ttc": self.threat_ttc,
            "threat_distance": self.threat_distance,
            "space_left": self.space_left,
            "space_right": self.space_right,
            "move_type": self.move_type,
            "version": self.version,
        }


@dataclass
class Outcome:
    damage: int = 0
    progress_delta: float = 0.0
    died: bool = False
    frames: int = 0

    def reward(self) -> float:
        return round(-1.0 * max(0, int(self.damage)) + 0.2 * _num(self.progress_delta) - (5.0 if self.died else 0.0), 4)

    def to_dict(self) -> dict:
        return {
            "damage": self.damage,
            "progress_delta": self.progress_delta,
            "died": self.died,
            "frames": self.frames,
            "reward": self.reward(),
        }


@dataclass
class ExperienceStep:
    ts: float
    context: Context
    action: str
    outcome: Outcome
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "context": self.context.to_dict(),
            "context_key": self.context.key(),
            "action": self.action,
            "outcome": self.outcome.to_dict(),
            "meta": dict(self.meta),
        }


class SkillStats:
    """context_key -> action -> (n, total_reward); UCB selection."""

    def __init__(self) -> None:
        self._stats: dict[str, dict[str, dict[str, float]]] = {}
        self._total: dict[str, int] = {}

    def update(self, context_key: str, action: str, reward: float) -> None:
        key = str(context_key)
        action = str(action)
        bucket = self._stats.setdefault(key, {}).setdefault(action, {"n": 0.0, "total": 0.0})
        bucket["n"] += 1.0
        bucket["total"] += _num(reward)
        self._total[key] = self._total.get(key, 0) + 1

    def choose(self, context_key: str, actions: list[str], *, epsilon: float = 0.1, c: float = 0.6, min_tries: int = 2, rng=None) -> str:
        candidates = [str(action) for action in actions if action]
        if not candidates:
            return "advance"
        key = str(context_key)
        rng = rng or random.Random()
        if rng.random() < max(0.0, min(1.0, epsilon)):
            return rng.choice(candidates)
        stats = self._stats.get(key, {})
        # 强制轮询：每个动作至少试 min_tries 次，避免 advance 一统天下。
        for action in candidates:
            bucket = stats.get(action)
            if not bucket or bucket["n"] < max(1, int(min_tries)):
                return action
        total = max(1, self._total.get(key, 0))
        best_action = candidates[0]
        best_score = float("-inf")
        for action in candidates:
            bucket = stats.get(action)
            mean = bucket["total"] / bucket["n"]
            bonus = c * math.sqrt(math.log(total + 1.0) / bucket["n"])
            score = mean + bonus
            if score > best_score:
                best_score = score
                best_action = action
        return best_action

    def mean(self, context_key: str, action: str) -> float | None:
        bucket = (self._stats.get(str(context_key)) or {}).get(str(action))
        if not bucket or bucket["n"] <= 0:
            return None
        return round(bucket["total"] / bucket["n"], 4)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "stats": {
                key: {action: {"n": int(value["n"]), "total": round(value["total"], 4)} for action, value in actions.items()}
                for key, actions in self._stats.items()
            },
            "total": dict(self._total),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SkillStats":
        obj = cls()
        for key, actions in (payload or {}).get("stats", {}).items():
            for action, value in (actions or {}).items():
                obj._stats.setdefault(str(key), {})[str(action)] = {
                    "n": float(value.get("n") or 0),
                    "total": float(value.get("total") or 0),
                }
        obj._total = {str(key): int(value) for key, value in ((payload or {}).get("total") or {}).items()}
        return obj

    def summary(self) -> dict:
        keys = len(self._stats)
        samples = sum(int(bucket["n"]) for actions in self._stats.values() for bucket in actions.values())
        return {"contexts": keys, "samples": samples}
