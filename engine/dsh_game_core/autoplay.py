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
    actions: int | None = None,
    min_actions: int = 0,
    resets: int | None = None,
    max_resets: int | None = None,
    progressed: bool | None = None,
) -> dict:
    """Decide whether a bounded play session is valid evidence.

    Invalid reasons: too short, stop phrase, too few actions, too many resets,
    or explicit no-progress. Resets are allowed by default (some games restart);
    a caller that wants strict single-run T2 passes ``max_resets``.
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
    if actions is not None and int(actions) < int(min_actions):
        return {"valid": False, "reason": f"too_few_actions:{actions}<{min_actions}"}
    if resets is not None and max_resets is not None and int(resets) > int(max_resets):
        return {"valid": False, "reason": f"too_many_resets:{resets}>{max_resets}"}
    if progressed is False:
        return {"valid": False, "reason": "no_progress"}
    result = {"valid": True, "reason": "ok"}
    if actions is not None:
        result["actions"] = int(actions)
    if resets is not None:
        result["resets"] = int(resets)
    return result
