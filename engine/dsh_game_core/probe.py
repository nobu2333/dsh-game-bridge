"""Generic onboarding probes: measure what a key press changes on screen.

No game names, no coordinates, no engine branches. The caller supplies frames
and key names; this module returns frame-difference evidence and a GamePack
draft that can be reviewed before it becomes a real pack.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

import numpy as np


def _gray(frame: Any) -> np.ndarray | None:
    try:
        import cv2

        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    except Exception:  # noqa: BLE001 - probes must never crash the caller
        return None


def frame_change(
    before: Any,
    after: Any,
    *,
    threshold: int = 18,
    min_pixels: int = 12,
) -> dict:
    """Return a normalized frame-difference report.

    ``ratio`` is the fraction of pixels whose absolute gray difference exceeds
    ``threshold``; ``bbox``/``center`` use normalized screen coordinates. Shape
    mismatches are reported as ``valid=False`` rather than raising.
    """
    first = _gray(before)
    second = _gray(after)
    if first is None or second is None or first.shape != second.shape:
        return {"valid": False, "changed": False, "pixels": 0, "ratio": 0.0, "bbox": None, "center": None}
    try:
        import cv2

        diff = cv2.absdiff(first, second)
        mask = (diff >= max(0, int(threshold))).astype(np.uint8)
        pixels = int(cv2.countNonZero(mask))
        height, width = mask.shape[:2]
        ratio = round(pixels / float(max(1, height * width)), 4)
        if pixels < max(0, int(min_pixels)):
            return {
                "valid": True,
                "changed": False,
                "pixels": pixels,
                "ratio": ratio,
                "bbox": None,
                "center": None,
            }
        ys, xs = np.nonzero(mask)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        return {
            "valid": True,
            "changed": True,
            "pixels": pixels,
            "ratio": ratio,
            "bbox": [
                round(x0 / float(width), 4),
                round(y0 / float(height), 4),
                round((x1 - x0 + 1) / float(width), 4),
                round((y1 - y0 + 1) / float(height), 4),
            ],
            "center": [
                round((x0 + x1 + 1) / 2.0 / width, 4),
                round((y0 + y1 + 1) / 2.0 / height, 4),
            ],
        }
    except Exception:  # noqa: BLE001
        return {"valid": False, "changed": False, "pixels": 0, "ratio": 0.0, "bbox": None, "center": None}


def summarize_effects(records: list[Mapping[str, Any]]) -> list[dict]:
    """Rank probe keys by their frame-change ratio (strongest first)."""
    summary: list[dict] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        change = record.get("change") or {}
        summary.append(
            {
                "key": str(record.get("key") or ""),
                "changed": bool(change.get("changed")),
                "ratio": float(change.get("ratio") or 0.0),
                "center": change.get("center"),
                "ocr_changed": bool(record.get("ocr_changed")),
            }
        )
    summary.sort(key=lambda item: (-item["ratio"], item["key"]))
    return summary


CONFIRM_KEYS = ("ENTER", "Z", "SPACE", "X", "A")
CANCEL_KEYS = ("ESC", "BACKSPACE")
MOVE_KEYS = {"up": ("UP", "W"), "down": ("DOWN", "S"), "left": ("LEFT", "A"), "right": ("RIGHT", "D")}
MENU_WORDS = (
    "START",
    "CONTINUE",
    "PLAY",
    "NEW GAME",
    "LOAD",
    "OPTIONS",
    "SETTINGS",
    "EXIT",
    "QUIT",
    "RESUME",
    "RETRY",
)


def menu_options(ocr_texts: list[str] | None) -> dict:
    """Extract generic menu words from OCR; never assumes a specific game."""
    found: dict[str, list[str]] = {}
    for raw in ocr_texts or []:
        text = str(raw or "").strip().upper()
        if not text or len(text) > 48:
            continue
        for word in MENU_WORDS:
            if word in text:
                found.setdefault(word, []).append(text[:60])
    return found


def menu_transition(before: list[str] | None, after: list[str] | None) -> dict:
    """Report menu-word changes between two OCR snapshots (evidence, not proof)."""
    before_words = set(menu_options(before))
    after_words = set(menu_options(after))
    return {
        "before": sorted(before_words),
        "after": sorted(after_words),
        "added": sorted(after_words - before_words),
        "removed": sorted(before_words - after_words),
        "changed": before_words != after_words,
    }


def infer_controls(
    records: list[Mapping[str, Any]],
    *,
    confirm_keys: tuple[str, ...] = CONFIRM_KEYS,
    cancel_keys: tuple[str, ...] = CANCEL_KEYS,
) -> dict:
    """Produce *suggestions* from key-effect evidence, not hard claims.

    A frame change proves the key did something; it does not prove the semantic
    role. Consumers should review these suggestions or verify the next state.
    """
    effects = summarize_effects(records)
    changed = {item["key"]: item for item in effects if item["changed"]}
    suggestions: dict[str, list[str]] = {
        "confirm": [key for key in confirm_keys if key in changed],
        "verified_confirm": [
            item["key"]
            for item in effects
            if item["key"] in confirm_keys and item["changed"] and item["ocr_changed"]
        ],
        "cancel": [key for key in cancel_keys if key in changed],
        "move": {},
    }
    move: dict[str, list[str]] = {}
    for direction, keys in MOVE_KEYS.items():
        hits = [key for key in keys if key in changed]
        if hits:
            move[direction] = hits
    suggestions["move"] = move
    suggestions["ranked"] = effects
    return suggestions


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:40] or "unknown"


def pack_draft(
    window: Mapping[str, Any],
    records: list[Mapping[str, Any]],
    *,
    ocr_texts: list[str] | None = None,
    game_id: str | None = None,
) -> dict:
    """Build a reviewable schema-v1 pack draft from probe evidence.

    The draft only claims screen + UI observation; it deliberately does not
    guess semantic controls. The next step (menu/keymap inference) can fill
    controls/recipes after reviewing the evidence.
    """
    from .gamepack import validate_pack

    title = str(window.get("title") or "unknown").strip()
    slug = _slug(title)
    if slug == "unknown":
        slug = _slug(str(window.get("process") or ""))
    identifier = game_id or f"probe.{slug}"
    status = summarize_effects(records)
    suggestions = infer_controls(records)
    pack = {
        "schema": 1,
        "id": identifier,
        "title": title,
        "platform": "pc",
        "process": window.get("process"),
        "trust": {"anti_cheat": "none"},
        "capabilities": {
            "observe.screen": {"level": 0},
            "observe.ui": {"level": 1},
        },
        "controls": {},
        "hud": {},
        "recipes": [],
        "evidence": [],
        "probe": {
            "window": {
                "title": title,
                "process": window.get("process"),
                "width": window.get("width"),
                "height": window.get("height"),
            },
            "ocr_texts": [str(text) for text in (ocr_texts or [])][:40],
            "menu": menu_options(ocr_texts),
            "key_effects": status,
            "suggested_controls": suggestions,
        },
    }
    return validate_pack(pack)
