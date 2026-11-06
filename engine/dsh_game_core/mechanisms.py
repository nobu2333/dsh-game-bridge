"""机制注册表与运行时计数：每个机制必须能证明自己是否被评估/触发/执行。

设计目标：
- 不是“代码存在”，而是运行时能回答：evaluated/triggered/applied/vetoed/noop/error；
- 开关关闭时 applied=0，可据此验证配置真的生效；
- 与游戏无关，机制 id/说明由调用方注册。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

EVENTS = ("evaluated", "triggered", "applied", "vetoed", "noop", "error")


@dataclass
class MechanismSpec:
    id: str
    description: str = ""
    enabled: bool = True
    expected_trigger: str = ""
    preconditions: tuple[str, ...] = ()
    effect: str = ""
    owner_test: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "enabled": self.enabled,
            "expected_trigger": self.expected_trigger,
            "preconditions": list(self.preconditions),
            "effect": self.effect,
            "owner_test": self.owner_test,
        }


@dataclass
class MechanismCounter:
    spec: MechanismSpec
    counts: dict[str, int] = field(default_factory=lambda: {name: 0 for name in EVENTS})
    last_reason: str = ""
    last_at: float = 0.0

    def record(self, event: str, reason: str = "") -> None:
        if event not in self.counts:
            self.counts["error"] += 1
            self.last_reason = f"unknown_event:{event}"
            self.last_at = time.time()
            return
        self.counts[event] += 1
        if reason:
            self.last_reason = str(reason)[:80]
        self.last_at = time.time()

    def snapshot(self) -> dict:
        return {
            "enabled": bool(self.spec.enabled),
            "counts": dict(self.counts),
            "last_reason": self.last_reason,
            "last_at": self.last_at,
            "description": self.spec.description,
        }


class MechanismRegistry:
    def __init__(self, specs: list[MechanismSpec] | None = None) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, MechanismCounter] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: MechanismSpec | dict) -> MechanismCounter:
        if isinstance(spec, dict):
            spec = MechanismSpec(**spec)
        with self._lock:
            counter = MechanismCounter(spec=spec)
            self._items[spec.id] = counter
            return counter

    def get(self, mechanism_id: str) -> MechanismCounter | None:
        return self._items.get(mechanism_id)

    def enabled(self, mechanism_id: str) -> bool:
        counter = self._items.get(mechanism_id)
        return bool(counter and counter.spec.enabled)

    def set_enabled(self, mechanism_id: str, enabled: bool) -> None:
        with self._lock:
            counter = self._items.get(mechanism_id)
            if counter is not None:
                counter.spec.enabled = bool(enabled)

    def record(self, mechanism_id: str, event: str, reason: str = "") -> None:
        with self._lock:
            counter = self._items.get(mechanism_id)
            if counter is None:
                return
            if event in ("triggered", "applied") and not counter.spec.enabled:
                counter.record("noop", "disabled")
                return
            counter.record(event, reason)

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {mechanism_id: counter.snapshot() for mechanism_id, counter in self._items.items()}


def default_specs() -> list[MechanismSpec]:
    """Current active mechanisms worth proving. Game-agnostic."""
    return [
        MechanismSpec(
            id="periodic_jump",
            description="periodic jump while advancing",
            expected_trigger="is_advancing and jump_every_ms elapsed",
            preconditions=("gameplay", "advancing"),
            effect="tap jump key",
            owner_test="tests/test_policy.py",
        ),
        MechanismSpec(
            id="periodic_dash",
            description="periodic dash while advancing",
            expected_trigger="is_advancing and dash_every_ms elapsed",
            preconditions=("gameplay", "advancing"),
            effect="tap dash key",
            owner_test="tests/test_policy.py",
        ),
        MechanismSpec(
            id="edge_escape",
            description="left-edge escape",
            expected_trigger="anchor_x < 0.10 for 0.5s",
            preconditions=("gameplay", "near_left_edge"),
            effect="release advance, jump/dash, resume",
            owner_test="tests/test_policy.py",
        ),
        MechanismSpec(
            id="shadow_advice",
            description="candidate scoring from observation + LevelMemory (read-only)",
            expected_trigger="every observation update",
            preconditions=("level_memory",),
            effect="status only; never keys",
            owner_test="tests/test_candidates.py",
        ),
        MechanismSpec(
            id="memory_context",
            description="scoped memory/guide context",
            expected_trigger="every 30 ticks",
            preconditions=("memory_loader",),
            effect="status only; never keys",
            owner_test="tests/test_policy.py",
        ),
        MechanismSpec(
            id="world_model",
            description="structured space/threat/self model",
            expected_trigger="every observation update",
            preconditions=("observation",),
            effect="status only; never keys",
            owner_test="tests/test_world_options.py",
        ),
        MechanismSpec(
            id="option_shadow",
            description="utility option selection (shadow)",
            expected_trigger="every observation update",
            preconditions=("world_model",),
            effect="status only; never keys",
            owner_test="tests/test_world_options.py",
        ),
        MechanismSpec(
            id="option_canary",
            description="single-option execution canary (default off)",
            enabled=False,
            expected_trigger="shadow option equals profile options.canary",
            preconditions=("grounded_or_safe", "cooldown"),
            effect="one jump/dash/strafe action",
            owner_test="tests/test_policy.py",
        ),
        MechanismSpec(
            id="reactive_control",
            description="reactive control replaces periodic blind jump/dash (default off)",
            enabled=False,
            expected_trigger="world_model has a close/imminent threat or gap",
            preconditions=("reactive_mode", "not_hurt", "cooldown"),
            effect="one jump/dash or short stop",
            owner_test="tests/test_policy.py",
        ),
    ]
