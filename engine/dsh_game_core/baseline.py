"""M5 baseline helpers: deterministic input policies, OCR score reading, run records.

These are the non-model comparison arms for the play protocol in docs/PLAY.md:
random keys and a fixed key cycle. Nothing here touches the screen; the caller
supplies OCR lines and executes the chosen key through the engine.

No game names and no screen coordinates live here: labels and end phrases are
arguments, so the same code works for any game that shows a numeric score.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_KEYS = ("UP", "RIGHT", "DOWN", "LEFT")


@dataclass
class RandomPolicy:
    """Pick one key uniformly at random (seeded, so a run is reproducible)."""

    keys: Sequence[str] = DEFAULT_KEYS
    seed: int = 0
    mode: str = "random"

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def choose(self) -> str:
        return self._rng.choice(list(self.keys))


@dataclass
class CyclePolicy:
    """Walk the key list in order, one key per step."""

    keys: Sequence[str] = DEFAULT_KEYS
    seed: int = 0
    mode: str = "cycle"

    def __post_init__(self) -> None:
        self._index = 0

    def choose(self) -> str:
        if not self.keys:
            raise ValueError("cycle policy needs at least one key")
        key = self.keys[self._index % len(self.keys)]
        self._index += 1
        return key


def make_policy(mode: str, keys: Sequence[str] = DEFAULT_KEYS, seed: int = 0):
    normalized = str(mode or "").strip().lower()
    if normalized == "random":
        return RandomPolicy(keys=keys, seed=seed)
    if normalized == "cycle":
        return CyclePolicy(keys=keys, seed=seed)
    raise ValueError(f"unknown mode {mode!r}; expected 'random' or 'cycle'")


def _center(line: Mapping[str, Any]) -> tuple[float, float]:
    try:
        left = float(line.get("left"))
        right = float(line.get("right"))
        top = float(line.get("top"))
        bottom = float(line.get("bottom"))
        return (left + right) / 2.0, (top + bottom) / 2.0
    except (TypeError, ValueError):
        return (float("nan"), float("nan"))


def parse_labeled_numbers(
    lines: Iterable[Mapping[str, Any]] | None,
    labels: Sequence[str],
    *,
    max_dy: float = 80.0,
    max_dx: float = 90.0,
) -> dict[str, int]:
    """Read ``LABEL`` + number pairs from OCR lines (e.g. SCORE / BEST).

    A value line is the nearest line whose center sits below the label and
    horizontally near it. Returns ``{label: int}`` for labels that were found
    and parsed; missing labels are simply absent, never guessed.
    """

    rows = [line for line in (lines or []) if isinstance(line, Mapping)]
    wanted = {str(label).strip().upper() for label in labels if str(label).strip()}
    out: dict[str, int] = {}
    for row in rows:
        text = str(row.get("text") or "").strip().upper()
        label = None
        for candidate in wanted:
            # OCR sometimes glues the label to the number ("SCORE 120").
            if text == candidate or text.startswith(candidate + " "):
                label = candidate
                break
        if label is None:
            continue
        glued = text[len(label):].strip()
        if glued.isdigit():
            out[label] = int(glued)
            continue
        lx, ly = _center(row)
        best: tuple[float, int] | None = None
        for other in rows:
            if other is row:
                continue
            other_text = str(other.get("text") or "").strip()
            if not other_text.isdigit():
                continue
            ox, oy = _center(other)
            dy = oy - ly
            dx = abs(ox - lx)
            if 0 <= dy <= max_dy and dx <= max_dx:
                score = dy + dx
                if best is None or score < best[0]:
                    best = (score, int(other_text))
        if best is not None and label not in out:
            out[label] = best[1]
    return out


def find_phrase(lines: Iterable[Mapping[str, Any]] | None, phrases: Sequence[str]) -> str | None:
    """Return the first phrase found (case-insensitive substring) or None."""

    wanted = [str(phrase).strip().lower() for phrase in phrases if str(phrase).strip()]
    for line in lines or []:
        text = str(line.get("text") or "").lower()
        for phrase in wanted:
            if phrase in text:
                return phrase
    return None


@dataclass
class RunRecord:
    """One run in the docs/PLAY.md run-log shape."""

    run_id: str
    date: str
    player: str
    game: str
    build: str
    steps: int
    wall_s: float
    score: int | None = None
    best: int | None = None
    end_reason: str = ""
    errors: int = 0
    seed: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def write_jsonl(path: str | Path, records: Sequence[RunRecord]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
    return target


def summarize_records(records: Sequence[RunRecord]) -> dict:
    """Medians and extremes per numeric metric (score, best, steps, wall_s)."""

    scores = [r.score for r in records if isinstance(r.score, int)]
    bests = [r.best for r in records if isinstance(r.best, int)]
    steps = [r.steps for r in records]
    walls = [r.wall_s for r in records]

    def _stats(values: list[float]) -> dict | None:
        if not values:
            return None
        return {
            "n": len(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }

    return {
        "score": _stats(scores),
        "best": _stats(bests),
        "steps": _stats(steps),
        "wall_s": _stats(walls),
    }


def make_run_id(prefix: str, index: int, *, now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now if now is not None else time.time()))
    return f"{prefix}-{stamp}-{index:02d}"
