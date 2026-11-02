"""L1 ← L3 的意图仲裁：模型 Intent + 本地默认/安全动作。

规则：
- 本地默认 intent 永远存在（安全/兜底）；
- 模型 intent 带 TTL/优先级；
- 过期自动回退本地；
- 安全暂停/急停可以否决所有模型 intent；
- 同优先级本地优先（避免模型覆盖安全兜底）。
"""

from __future__ import annotations

import time
from typing import Any

from .contracts import Intent


class IntentArbiter:
    def __init__(self, local_intent: dict | Intent | None = None, *, now_fn=None) -> None:
        self._now = now_fn or time.time
        self._local = Intent.from_raw(local_intent or {"goal": "advance", "skill": "advance", "priority": 1}) or Intent.from_raw(
            {"goal": "advance", "skill": "advance", "priority": 1}
        )
        self._entries: list[dict] = []
        self._blocked = False
        self._blocked_reason = ""

    def set_local(self, intent: dict | Intent) -> None:
        parsed = intent if isinstance(intent, Intent) else Intent.from_raw(intent)
        if parsed is not None:
            self._local = parsed

    def block(self, reason: str) -> None:
        self._blocked = True
        self._blocked_reason = str(reason)[:120]

    def unblock(self) -> None:
        self._blocked = False
        self._blocked_reason = ""

    def submit(self, intent: dict | Intent, *, origin: str = "model") -> bool:
        parsed = intent if isinstance(intent, Intent) else Intent.from_raw(intent)
        if parsed is None:
            return False
        expires_at = float(self._now()) + parsed.ttl_ms / 1000.0
        self._entries.append({"intent": parsed, "expires_at": expires_at, "origin": str(origin)[:16]})
        self._entries.sort(key=lambda item: (item["intent"].priority, item["expires_at"]), reverse=True)
        return True

    def current(self) -> dict:
        if self._blocked:
            blocked = dict(self._local.to_dict())
            blocked.update({"skill": "halt", "goal": "survive", "reason": self._blocked_reason, "source": "safety"})
            return blocked
        now = float(self._now())
        self._entries = [item for item in self._entries if item["expires_at"] > now]
        for item in self._entries:
            if item["intent"].priority > self._local.priority:
                result = dict(item["intent"].to_dict())
                result["arbiter"] = item["origin"]
                return result
        result = dict(self._local.to_dict())
        result["arbiter"] = "local"
        return result

    def active_entries(self) -> list[dict]:
        now = float(self._now())
        self._entries = [item for item in self._entries if item["expires_at"] > now]
        return [{"intent": item["intent"].to_dict(), "expires_at": item["expires_at"], "origin": item["origin"]} for item in self._entries]


def local_intent_from_skill(skill: str, *, reason: str = "", target_id: int | None = None) -> dict:
    """Convert choose_skill output into a local Intent."""
    mapping = {
        "advance": "advance",
        "attack": "attack",
        "jump": "avoid",
        "retreat": "retreat",
        "confirm": "advance",
        "recover": "survive",
        "hold": "survive",
    }
    goal = mapping.get(str(skill), "advance")
    return {
        "goal": goal,
        "skill": str(skill),
        "priority": 1,
        "ttl_ms": 1200,
        "risk": "low",
        "reason": reason,
        "target_id": target_id,
        "source": "local",
    }
