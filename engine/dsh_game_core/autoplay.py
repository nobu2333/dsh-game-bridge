"""Generic validity checks for bounded autoplay sessions.

The engine must not turn "the loop ran for 5 minutes" into a T2 claim when the
game was on an ad, a game-over screen, or a menu. These helpers are pure and
game-agnostic; packs supply the stop phrases.
"""

from __future__ import annotations

from typing import Any, Mapping


def ocr_contains(sample: Mapping[str, Any], phrases: list[str] | tuple[str, ...]) -> str | None:
    """Return the first stop phrase found in one sample's OCR, else None."""
    text = " ".join(str(item) for item in (sample.get("ocr") or [])).upper()
    for phrase in phrases:
        needle = str(phrase or "").strip().upper()
        if needle and needle in text:
            return needle
    return None


def evaluate_session(
    *,
    requested_s: float,
    elapsed_s: float,
    samples: list[Mapping[str, Any]],
    stop_phrases: list[str] | tuple[str, ...] | None = None,
    tolerance_s: float = 2.0,
) -> dict:
    """Decide whether a bounded play session is valid evidence.

    Invalid reasons: too short, or a stop phrase (game over/ad/menu) appeared in
    any sample. A long session with no stop phrase is valid even if the game
    involved deaths/restarts; the caller must still document that semantics.
    """
    requested = max(0.0, float(requested_s))
    elapsed = max(0.0, float(elapsed_s))
    if elapsed + max(0.0, float(tolerance_s)) < requested:
        return {"valid": False, "reason": f"too_short:{elapsed:.1f}<{requested:.1f}"}
    phrases = [str(phrase) for phrase in (stop_phrases or [])]
    for sample in samples:
        hit = ocr_contains(sample, phrases)
        if hit:
            return {"valid": False, "reason": f"stop_phrase:{hit}"}
    return {"valid": True, "reason": "ok"}
