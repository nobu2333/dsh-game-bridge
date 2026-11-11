"""Automatic T1 onboarding: infer controls from probe evidence and build a pack.

The probe already measures what each key changed on screen. This module turns
that evidence into semantic controls only where the evidence supports it:
confirm is a confirm-shaped key that changed OCR/menu; movement is a known
direction key that changed the gameplay frame; jump is Space/Up when it changed.
Uncertain roles are left out rather than guessed. A pack built here is marked
``origin=auto`` and ``interventions=0``; a human-reviewed pack is ``assisted``.
"""

from __future__ import annotations

from typing import Any, Mapping

from .probe import CANCEL_KEYS, CONFIRM_KEYS, MOVE_KEYS, infer_controls, menu_options, pack_draft

MIN_MOVE_RATIO = 0.003
MIN_CONFIRM_RATIO = 0.002
CLOSE_WORDS = ("CLOSE", "关闭", "关闭广告", "跳过", "SKIP", "DISMISS")


def find_dismiss_target(
    ocr_lines: list[Mapping[str, Any]] | None,
    *,
    width: int,
    height: int,
) -> dict | None:
    """Find a generic close/skip overlay target from OCR boxes.

    Returns normalized center + label, or None. This is only for dismissing an
    overlay before probing; it never grants game permissions or accepts a
    sign-in/consent prompt.
    """
    if not width or not height:
        return None
    for line in ocr_lines or []:
        if not isinstance(line, Mapping):
            continue
        text = str(line.get("text") or "").strip().upper()
        if not text or not any(word in text for word in CLOSE_WORDS):
            continue
        try:
            left = float(line.get("left"))
            right = float(line.get("right"))
            top = float(line.get("top"))
            bottom = float(line.get("bottom"))
        except (TypeError, ValueError):
            continue
        if right <= left or bottom <= top:
            continue
        return {
            "x": round(((left + right) / 2.0) / width, 4),
            "y": round(((top + bottom) / 2.0) / height, 4),
            "label": text[:40],
        }
    return None


def _record_key(record: Mapping[str, Any]) -> str:
    return str(record.get("key") or "").strip().upper()


def _ratio(record: Mapping[str, Any]) -> float:
    change = record.get("change") or {}
    try:
        return float(change.get("ratio") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _changed(record: Mapping[str, Any]) -> bool:
    change = record.get("change") or {}
    return bool(change.get("changed"))


def infer_auto_controls(records: list[Mapping[str, Any]]) -> dict:
    """Infer semantic controls and report confidence/uncertainty.

    Returns ``{"controls": {...}, "confidence": 0..1, "reasons": [...],
    "uncertain": [...]}``. No key is assigned without frame/OCR evidence.
    """
    records = [record for record in records if isinstance(record, Mapping)]
    by_key = {_record_key(record): record for record in records if _record_key(record)}
    suggestions = infer_controls(records)
    reasons: list[str] = []
    uncertain: list[str] = []

    controls: dict[str, Any] = {}
    confirm_scores: list[tuple[float, str]] = []
    for key in CONFIRM_KEYS:
        record = by_key.get(key)
        if not record or not _changed(record):
            continue
        score = 0.0
        if bool(record.get("ocr_changed")):
            score += 2.0
            reasons.append(f"{key}:ocr_changed")
        transition = record.get("menu_transition") or {}
        if isinstance(transition, Mapping) and transition.get("changed"):
            score += 1.0
            reasons.append(f"{key}:menu_transition")
        score += min(1.0, _ratio(record) * 10.0)
        if score > 0:
            confirm_scores.append((score, key))
    confirm_scores.sort(reverse=True)
    if confirm_scores:
        best_score, best_key = confirm_scores[0]
        controls["confirm"] = [best_key]
        if len(confirm_scores) > 1 and abs(confirm_scores[1][0] - best_score) < 0.3:
            uncertain.append("confirm")
        if best_score < 1.0:
            uncertain.append("confirm_low_evidence")
    else:
        uncertain.append("confirm")

    cancel = [key for key in CANCEL_KEYS if key in by_key and _changed(by_key[key])]
    if cancel:
        controls["cancel"] = cancel

    move: dict[str, list[str]] = {}
    for direction, keys in MOVE_KEYS.items():
        hits = [
            key
            for key in keys
            if key in by_key and _changed(by_key[key]) and _ratio(by_key[key]) >= MIN_MOVE_RATIO
        ]
        if hits:
            move[direction] = hits
    if move:
        controls["move"] = move
    else:
        uncertain.append("move")

    jump = [key for key in ("SPACE", "UP") if key in by_key and _changed(by_key[key])]
    if jump:
        controls["jump"] = jump

    # Confidence: confirm + move are the T1 essentials; conflicting keys lower it.
    confidence = 0.0
    if controls.get("confirm"):
        confidence += 0.5
    if controls.get("move"):
        confidence += 0.4
    if controls.get("jump"):
        confidence += 0.1
    if uncertain:
        confidence = max(0.0, confidence - 0.15 * len(set(uncertain)))
    confidence = round(min(1.0, confidence), 3)

    return {
        "controls": controls,
        "confidence": confidence,
        "reasons": reasons,
        "uncertain": sorted(set(uncertain)),
        "suggested": suggestions,
    }


def auto_pack_draft(
    window: Mapping[str, Any],
    records: list[Mapping[str, Any]],
    *,
    ocr_texts: list[str] | None = None,
    game_id: str | None = None,
    menu_observed: bool = False,
    gameplay_observed: bool = False,
    entry_mode: str = "menu",
) -> dict:
    """Build a schema-v1 pack with auto-inferred controls and provenance."""
    inferred = infer_auto_controls(records)
    pack = pack_draft(window, records, ocr_texts=ocr_texts, game_id=game_id)
    pack["origin"] = "auto"
    pack["interventions"] = 0
    pack["controls"] = inferred["controls"]
    pack["capabilities"]["control.keyboard"] = {"level": 1}
    inferred_meta = {
        "confidence": inferred["confidence"],
        "reasons": inferred["reasons"],
        "uncertain": inferred["uncertain"],
        "menu_observed": bool(menu_observed),
        "gameplay_observed": bool(gameplay_observed),
        "entry_mode": entry_mode,
    }
    pack["probe"]["inferred"] = inferred_meta
    if menu_observed:
        pack["probe"]["menu_options"] = sorted(menu_options(ocr_texts))
    if inferred["controls"].get("confirm"):
        pack["recipes"] = [
            {
                "id": "auto_start",
                "intent": "Start from the observed menu with the inferred confirm key",
                "steps": [{"press": inferred["controls"]["confirm"][0]}, {"wait_ms": 800}],
                "verify": {"gameplay_observed": True},
            }
        ]
    return pack


def t1_checklist(
    *,
    menu_observed: bool,
    confirm_key: str | None,
    gameplay_observed: bool,
    first_action_key: str | None,
    entry_mode: str = "menu",
) -> dict:
    """T1 evidence checklist; no game names or score thresholds.

    ``entry_mode="direct"`` supports games that start immediately (no menu);
    then a confirm key is not required, but gameplay and first action still are.
    """
    checks = {
        "entry_screen": bool(menu_observed) or entry_mode == "direct",
        "confirm_inferred": bool(confirm_key) or entry_mode == "direct",
        "gameplay_observed": bool(gameplay_observed),
        "first_action": bool(first_action_key),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "entry_mode": entry_mode,
        "missing": [name for name, ok in checks.items() if not ok],
    }
