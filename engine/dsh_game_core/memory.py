"""关卡记忆：危险账本（DangerCard）+ 关卡坐标（LevelLocator）。

这是「背板」的数据层：把一次受伤/死亡/险情，从「聊天里的印象」变成
带坐标、触发条件、证据、应对与验证状态的卡片。运行时按滚动坐标检索，
接近危险点时把卡片交给战术层；没有证据/未验证的卡片只是 candidate。

设计原则：
- 纯数据 + 文件 I/O，不依赖感知/控制，方便单测与回放；
- 所有外部输入都做白名单/范围校验，写入原子化（tmp + replace）；
- 存储目录由调用方注入（默认用户本地 cache），不进仓库；
- 方法尽力不抛异常；失败返回空值并保留原文件。
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

DANGER_SCHEMA = 1

DANGER_STATUS = ("candidate", "validated", "trusted", "stale")
_EVENT_TYPES = ("damage", "death", "near_miss", "stuck", "success", "unknown")
_SKILLS = (
    "jump_over",
    "evade",
    "retreat",
    "hold",
    "face_and_shoot",
    "parry",
    "advance",
    "unknown",
)
_RELATIONS = ("ahead", "behind", "above", "below", "same", "unknown")
_ID_SAFE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_CARD_ID_SAFE = re.compile(r"^(?!.*\.\.)[a-zA-Z0-9._/-]{1,160}$")


def _num(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    number = _num(value, default)
    return min(max(number, low), high)


def _safe_id(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if _ID_SAFE.match(text) else default


def _safe_card_id(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if _CARD_ID_SAFE.match(text) else default


def _now(value: Any = None) -> float:
    return round(_num(value, time.time()), 3)


def normalize_danger_card(raw: Any, *, now: Any = None) -> dict | None:
    """Validate/clamp one DangerCard dict; returns None for unusable input."""
    if not isinstance(raw, dict):
        return None
    level = _safe_id(raw.get("level"), "")
    if not level:
        return None
    game = _safe_id(raw.get("game"), "unknown")
    place = raw.get("place") if isinstance(raw.get("place"), dict) else {}
    trigger = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
    event = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    response = raw.get("response") if isinstance(raw.get("response"), dict) else {}
    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}

    event_type = str(event.get("type") or "unknown").lower()
    if event_type not in _EVENT_TYPES:
        event_type = "unknown"
    skill = str(response.get("skill") or "unknown").lower()
    if skill not in _SKILLS:
        skill = "unknown"
    relation = str(trigger.get("relation") or "unknown").lower()
    if relation not in _RELATIONS:
        relation = "unknown"
    status = str(raw.get("status") or "candidate").lower()
    if status not in DANGER_STATUS:
        status = "candidate"

    card_id = _safe_card_id(raw.get("id"), "")
    if not card_id:
        card_id = f"{game}/{level}/danger-{uuid.uuid4().hex[:8]}"
    evidence = raw.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence = [str(item)[:200] for item in evidence[:8] if str(item).strip()]

    card = {
        "schema": DANGER_SCHEMA,
        "id": card_id,
        "game": game,
        "level": level,
        "place": {
            "scroll_s": round(_num(place.get("scroll_s"), 0.0), 3),
            "segment": int(_num(place.get("segment"), 0)),
            "player_x": round(_clamp(place.get("player_x"), 0.0, 1.0, 0.5), 4),
            "player_y": round(_clamp(place.get("player_y"), 0.0, 1.0, 0.8), 4),
            "landmark": str(place.get("landmark") or "")[:80],
        },
        "trigger": {
            "kind": str(trigger.get("kind") or "unknown")[:32],
            "template": str(trigger.get("template") or "")[:64],
            "relation": relation,
        },
        "event": {
            "type": event_type,
            "cause": str(event.get("cause") or "unknown")[:32],
            "hp_before": None if event.get("hp_before") is None else int(_num(event.get("hp_before"), 0)),
            "hp_after": None if event.get("hp_after") is None else int(_num(event.get("hp_after"), 0)),
        },
        "response": {
            "skill": skill,
            "params": response.get("params") if isinstance(response.get("params"), dict) else {},
            "timing": str(response.get("timing") or "")[:80],
        },
        "response_history": [str(item)[:32] for item in raw.get("response_history", [])[:8]]
        if isinstance(raw.get("response_history"), list)
        else [],
        "evidence": evidence,
        "stats": {
            "encounters": max(0, int(_num(stats.get("encounters"), 0))),
            "damage_events": max(0, int(_num(stats.get("damage_events"), 0))),
            "avoided": max(0, int(_num(stats.get("avoided"), 0))),
            "response_tries": max(0, int(_num(stats.get("response_tries"), 0))),
            "response_failures": max(0, int(_num(stats.get("response_failures"), 0))),
        },
        "confidence": round(_clamp(raw.get("confidence"), 0.0, 1.0, 0.3), 3),
        "hazard_confidence": round(_clamp(raw.get("hazard_confidence", raw.get("confidence")), 0.0, 1.0, 0.3), 3),
        "response_efficacy": round(_clamp(raw.get("response_efficacy"), 0.0, 1.0, 0.5), 3),
        "status": status,
        "created_at": _now(raw.get("created_at") or now),
        "updated_at": _now(raw.get("updated_at") or now),
    }
    return card


def _card_distance(card: dict, scroll_s: float) -> float:
    return abs(float(card.get("place", {}).get("scroll_s", 0.0)) - float(scroll_s))


class KnowledgeStore:
    """Per-game/level DangerCard store on the local filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _path(self, game: str, level: str) -> Path:
        safe_game = _safe_id(game, "unknown")
        safe_level = _safe_id(level, "unknown")
        return self.root / safe_game / f"{safe_level}.json"

    def load(self, game: str, level: str) -> dict:
        path = self._path(game, level)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except Exception:  # noqa: BLE001 - 缺失/损坏都按空账本处理
            data = {}
        cards = []
        for raw in data.get("cards") or []:
            card = normalize_danger_card(raw)
            if card is not None:
                cards.append(card)
        return {"schema": DANGER_SCHEMA, "game": _safe_id(game, "unknown"), "level": _safe_id(level, "unknown"), "cards": cards}

    def save(self, game: str, level: str, cards: list[dict]) -> bool:
        path = self._path(game, level)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": DANGER_SCHEMA,
                "game": _safe_id(game, "unknown"),
                "level": _safe_id(level, "unknown"),
                "updated_at": _now(),
                "cards": [normalize_danger_card(card) for card in cards if normalize_danger_card(card) is not None],
            }
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except Exception:  # noqa: BLE001 - 记忆写失败不能影响游戏
            return False

    def upsert(self, card: Any) -> dict | None:
        normalized = normalize_danger_card(card)
        if normalized is None:
            return None
        game, level = normalized["game"], normalized["level"]
        book = self.load(game, level)
        cards = book["cards"]
        # 同一位置 + 同一触发条件视为同一张卡，只累加统计/提高置信度。
        replaced = False
        for index, existing in enumerate(cards):
            same_place = abs(existing["place"]["scroll_s"] - normalized["place"]["scroll_s"]) < 0.35
            same_trigger = (
                existing["trigger"]["kind"] == normalized["trigger"]["kind"]
                and existing["trigger"]["template"] == normalized["trigger"]["template"]
            )
            if existing["id"] == normalized["id"] or (same_place and same_trigger):
                merged = dict(existing)
                merged["updated_at"] = normalized["updated_at"]
                merged["stats"] = {
                    "encounters": max(existing["stats"]["encounters"], normalized["stats"]["encounters"]),
                    "damage_events": max(existing["stats"]["damage_events"], normalized["stats"]["damage_events"]),
                    "avoided": max(existing["stats"]["avoided"], normalized["stats"]["avoided"]),
                }
                merged["confidence"] = round(min(1.0, max(existing["confidence"], normalized["confidence"]) + 0.05), 3)
                if normalized["status"] in ("validated", "trusted"):
                    merged["status"] = normalized["status"]
                if normalized["evidence"]:
                    merged["evidence"] = (existing["evidence"] + normalized["evidence"])[-8:]
                cards[index] = merged
                replaced = True
                break
        if not replaced:
            cards.append(normalized)
        cards.sort(key=lambda item: item["place"]["scroll_s"])
        self.save(game, level, cards)
        return normalized

    def nearby(self, game: str, level: str, scroll_s: float, *, window: float = 1.2, limit: int = 5) -> list[dict]:
        cards = self.load(game, level)["cards"]
        window = max(0.0, float(window))
        candidates = [card for card in cards if _card_distance(card, scroll_s) <= window]
        candidates.sort(key=lambda card: _card_distance(card, scroll_s))
        return candidates[: max(1, int(limit))]


class LevelLocator:
    """Accumulate camera scroll into a level coordinate (screen widths).

    ``update`` takes a normalized horizontal shift per frame (positive = world
    moved right / camera moved left). The absolute sign is game-dependent; the
    important part is that a monotonic progress coordinate exists for retrieval.
    """

    def __init__(self, *, segment_width: float = 1.0) -> None:
        self.segment_width = max(0.1, float(segment_width))
        self.scroll_s = 0.0
        self._last_at = 0.0

    def reset(self) -> None:
        self.scroll_s = 0.0
        self._last_at = 0.0

    def update(self, dx_normalized: Any, *, now: Any = None) -> dict:
        shift = _num(dx_normalized, 0.0)
        if math.isfinite(shift):
            self.scroll_s += shift
        self._last_at = _now(now)
        return self.position()

    def position(self) -> dict:
        return {
            "scroll_s": round(self.scroll_s, 3),
            "segment": int(self.scroll_s // self.segment_width),
            "updated_at": self._last_at,
        }


GUIDE_SCHEMA = 1


def normalize_guide_card(raw: Any, *, now: Any = None) -> dict | None:
    """Optional external knowledge card (offline import, no network here)."""
    if not isinstance(raw, dict):
        return None
    game = _safe_id(raw.get("game"), "unknown")
    level = _safe_id(raw.get("level"), "")
    if not level:
        return None
    facts = raw.get("facts")
    if not isinstance(facts, list):
        facts = []
    clean_facts = []
    for fact in facts[:12]:
        if not isinstance(fact, dict):
            continue
        text = str(fact.get("text") or "").strip()
        if not text:
            continue
        clean_facts.append({"type": str(fact.get("type") or "note")[:24], "text": text[:240]})
    source = str(raw.get("source_url") or "").strip()
    if source and not source.lower().startswith(("http://", "https://")):
        source = ""
    status = str(raw.get("status") or "unverified").lower()
    if status not in ("unverified", "verified", "stale"):
        status = "unverified"
    card = {
        "schema": GUIDE_SCHEMA,
        "id": _safe_id(raw.get("id"), f"{game}/{level}/guide-{uuid.uuid4().hex[:8]}"),
        "game": game,
        "level": level,
        "title": str(raw.get("title") or "")[:120],
        "source_url": source[:300],
        "fetched_at": _now(raw.get("fetched_at") or now),
        "facts": clean_facts,
        "confidence": round(_clamp(raw.get("confidence"), 0.0, 1.0, 0.4), 3),
        "status": status,
        "verified_in_game": bool(raw.get("verified_in_game")),
    }
    return card


class GuideStore:
    """Local-only guide book. The caller (model/user) supplies fetched facts."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _path(self, game: str, level: str) -> Path:
        return self.root / _safe_id(game, "unknown") / f"{_safe_id(level, 'unknown')}.guides.json"

    def load(self, game: str, level: str) -> list[dict]:
        try:
            data = json.loads(self._path(game, level).read_text(encoding="utf-8"))
            cards = data.get("cards") if isinstance(data, dict) else []
        except Exception:  # noqa: BLE001
            cards = []
        result = []
        for raw in cards if isinstance(cards, list) else []:
            card = normalize_guide_card(raw)
            if card is not None:
                result.append(card)
        return result

    def upsert(self, card: Any) -> dict | None:
        normalized = normalize_guide_card(card)
        if normalized is None:
            return None
        try:
            path = self._path(normalized["game"], normalized["level"])
            path.parent.mkdir(parents=True, exist_ok=True)
            cards = self.load(normalized["game"], normalized["level"])
            cards = [existing for existing in cards if existing["id"] != normalized["id"]]
            cards.append(normalized)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"schema": GUIDE_SCHEMA, "cards": cards}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, path)
            return normalized
        except Exception:  # noqa: BLE001 - optional knowledge must never break play
            return None

