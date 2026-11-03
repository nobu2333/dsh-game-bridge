"""每游戏学习器：经验日志、信用分配、SkillStats 持久化。

设计原则：
- 只存通用 context / action / outcome；
- 死亡时把负信用回传给最近几步，而不是只记最后一步；
- 持久化按游戏/关卡路径调用方决定，引擎不写死路径；
- 所有统计带版本，可删除/回退。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .experience import Context, ExperienceStep, Outcome, SkillStats


@dataclass
class EpisodeTrace:
    steps: list[ExperienceStep] = field(default_factory=list)
    died: bool = False

    def add(self, context: Context, action: str, outcome: Outcome, *, meta: dict | None = None) -> ExperienceStep:
        step = ExperienceStep(ts=round(time.time(), 3), context=context, action=str(action), outcome=outcome, meta=meta or {})
        self.steps.append(step)
        return step


class Learner:
    def __init__(self, stats: SkillStats | None = None) -> None:
        self.stats = stats or SkillStats()
        self.version = 1

    def apply(self, trace: EpisodeTrace, *, credit_window: int = 3, death_penalty: float = -2.0) -> int:
        """Update stats from a trace; returns number of steps learned."""
        if not trace.steps:
            return 0
        rewards = [step.outcome.reward() for step in trace.steps]
        if trace.died:
            for index in range(max(0, len(rewards) - max(1, credit_window)), len(rewards)):
                rewards[index] += death_penalty
        for step, reward in zip(trace.steps, rewards):
            self.stats.update(step.context.key(coarse=True), step.action, reward)
        return len(trace.steps)

    def choose(self, context: Context, actions: list[str], *, epsilon: float = 0.1, min_tries: int = 2) -> str:
        return self.stats.choose(context.key(coarse=True), actions, epsilon=epsilon, min_tries=min_tries)

    def to_dict(self) -> dict:
        return {"version": self.version, "stats": self.stats.to_dict()}

    @classmethod
    def from_dict(cls, payload: dict) -> "Learner":
        learner = cls(SkillStats.from_dict((payload or {}).get("stats") or {}))
        learner.version = int((payload or {}).get("version") or 1)
        return learner

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Learner":
        target = Path(path)
        if not target.is_file():
            return cls()
        return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))


def load_jsonl(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.is_file():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_jsonl(path: str | Path, record: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def trace_from_dicts(rows: list[dict], *, died: bool = False) -> EpisodeTrace:
    """Convert stored step dicts back into a trace (best-effort)."""
    trace = EpisodeTrace(died=bool(died))
    for row in rows:
        if not isinstance(row, dict):
            continue
        ctx = row.get("context") or {}
        context = Context(
            scene=str(ctx.get("scene") or "unknown"),
            hp=ctx.get("hp"),
            threat_side=str(ctx.get("threat_side") or ""),
            threat_ttc=ctx.get("threat_ttc"),
            threat_distance=ctx.get("threat_distance"),
            space_left=ctx.get("space_left"),
            space_right=ctx.get("space_right"),
            move_type=str(ctx.get("move_type") or ""),
        )
        outcome = row.get("outcome") or {}
        trace.steps.append(
            ExperienceStep(
                ts=float(row.get("ts") or 0.0),
                context=context,
                action=str(row.get("action") or "advance"),
                outcome=Outcome(
                    damage=int(outcome.get("damage") or 0),
                    progress_delta=float(outcome.get("progress_delta") or 0.0),
                    died=bool(outcome.get("died")),
                    frames=int(outcome.get("frames") or 0),
                ),
                meta=row.get("meta") if isinstance(row.get("meta"), dict) else {},
            )
        )
    return trace

def context_from_observation(observation: dict) -> Context:
    """Map a generic observation to a learning Context (no game-specific names)."""
    obs = observation or {}
    threat = {}
    if obs.get("enemy_ahead") or obs.get("enemy_behind"):
        threat = {
            "side": obs.get("enemy_side") or ("behind" if obs.get("enemy_behind") else ""),
            "ttc": obs.get("enemy_ttc"),
            "distance": obs.get("enemy_distance"),
        }
    return Context(
        scene=str(obs.get("scene") or "unknown"),
        hp=obs.get("hp"),
        threat_side=str(threat.get("side") or ""),
        threat_ttc=threat.get("ttc"),
        threat_distance=threat.get("distance"),
        space_left=(obs.get("player") or {}).get("x"),
        space_right=None,
        move_type="",
    )
