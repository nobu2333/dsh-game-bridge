"""Vision-based WorldState extraction (game-agnostic).

The engine only has eyes: a BGR frame plus optional OCR lines. This module turns
them into the public WorldState dict described in ``docs/STATE.md``. Everything
game-specific (HUD box, OCR prefix, color thresholds, keywords, controls) comes
from a profile dict supplied by the caller; with no profile the defaults below
still produce a usable state.

Design rules:
- extractors never raise: garbage input degrades to the "unknown" defaults;
- the cheap path (:func:`cheap_entities`, no OCR) must stay well under ~3 ms
  for a 962x567 frame so a 60 Hz policy loop can call it every tick;
- coordinates are normalized 0..1 relative to the captured frame, unknown is
  ``None``;
- no game data, memory offsets or local paths live in this file.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Mapping

import numpy as np

STATE_SCHEMA = 1

# ── defaults (all overridable from the profile) ────────────────────────────────
DEFAULT_LOADING_MAX_TEXTS = 1
DEFAULT_NEAR_BLACK_MEAN = 12.0

DEFAULT_DEATH_KEYWORDS = ("GAME OVER", "YOU DIED", "DEAD", "RETRY")
DEFAULT_MENU_KEYWORDS = ("START", "OPTIONS", "EXIT", "CONTINUE")

DEFAULT_PARRY = {
    "r_min": 175,
    "b_min": 175,
    "rb_minus_g_min": 25,
    "min_pixels": 6,
}

# Parry color detection runs on a downsampled copy for speed; min_pixels is
# scaled by the area ratio so the profile threshold keeps its meaning.
PARRY_MAX_DIM = 640

# Cheap moving-threat detector: size of the downsampled working frame, the grid
# cell size (in downsampled pixels) and the minimum normalized motion per cell.
THREAT_MAX_WIDTH = 240
THREAT_MAX_HEIGHT = 135
THREAT_CELL = 8
THREAT_CELL_MIN = 0.06
THREAT_MAX_ENTITIES = 10

DEFAULT_SELF_RADIUS = 0.10

MAX_TEXT_LINES = 64
MAX_ENTITIES = 12

_PROMPT_VERBS = ("PRESS", "CONFIRM", "CLICK", "TAP", "SELECT", "HOLD", "ENTER", "CONTINUE")


# ── small coercion helpers (never raise) ──────────────────────────────────────
def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _section(profile: Any, name: str) -> Mapping:
    return _mapping(_mapping(profile).get(name))


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _coerce_frame(frame: Any) -> np.ndarray | None:
    """Normalize a frame to a contiguous (H, W, 3) uint8 BGR array, or None."""
    try:
        if not isinstance(frame, np.ndarray):
            return None
        if frame.ndim == 2:
            frame = np.repeat(frame[:, :, None], 3, axis=2)
        if frame.ndim != 3:
            return None
        height, width = int(frame.shape[0]), int(frame.shape[1])
        if height < 2 or width < 2:
            return None
        if frame.shape[2] == 4:
            frame = frame[:, :, :3]
        elif frame.shape[2] != 3:
            return None
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        return np.ascontiguousarray(frame)
    except Exception:  # noqa: BLE001 - a bad frame must never raise
        return None


def _line_from_item(item: Any) -> dict | None:
    if isinstance(item, Mapping):
        getter = item.get
    else:
        getter = lambda key, default=None: getattr(item, key, default)  # noqa: E731 - lazily fetched OCR fields

    text = getter("text")
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    score = _clamp(_number(getter("score"), 0.0), 0.0, 1.0)
    line: dict[str, Any] = {"text": text, "score": score}
    for key in ("left", "top", "right", "bottom"):
        raw = getter(key)
        if raw is None:
            line[key] = None
            continue
        try:
            line[key] = float(raw)
        except (TypeError, ValueError):
            line[key] = None
    return line


def _coerce_lines(ocr_lines: Any) -> list[dict]:
    """Coerce OCR lines (dicts or TextLine-like objects) into plain dicts."""
    if ocr_lines is None:
        return []
    if isinstance(ocr_lines, Mapping):
        items: list[Any] = [ocr_lines]
    else:
        try:
            items = list(ocr_lines)
        except TypeError:
            return []
    lines: list[dict] = []
    for item in items:
        try:
            line = _line_from_item(item)
        except Exception:  # noqa: BLE001 - skip unreadable lines
            line = None
        if line is not None:
            lines.append(line)
        if len(lines) >= MAX_TEXT_LINES:
            break
    return lines


def _box(value: Any) -> tuple[float, float, float, float] | None:
    """Normalized [x, y, w, h] -> tuple, or None when absent/invalid."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    numbers = []
    for item in value:
        if isinstance(item, bool):
            return None
        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            return None
    x, y, width, height = numbers
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _line_center_norm(
    line: Mapping,
    frame_size: tuple[int, int] | None,
) -> tuple[float, float] | None:
    """Normalized center of an OCR line, or None when it cannot be derived."""
    left, top = line.get("left"), line.get("top")
    right, bottom = line.get("right"), line.get("bottom")
    if left is None or top is None or right is None or bottom is None:
        return None
    try:
        center_x = (float(left) + float(right)) / 2.0
        center_y = (float(top) + float(bottom)) / 2.0
    except (TypeError, ValueError):
        return None
    if frame_size is not None:
        width, height = frame_size
        if width <= 0 or height <= 0:
            return None
        return center_x / width, center_y / height
    # No frame size available: accept coordinates that already look normalized.
    if all(0.0 <= float(value) <= 1.0 for value in (left, top, right, bottom)):
        return center_x, center_y
    return None


def _inside_box(line: Mapping, box: tuple[float, float, float, float] | None, frame_size: tuple[int, int] | None) -> bool:
    if box is None:
        return True
    center = _line_center_norm(line, frame_size)
    if center is None:
        return False
    x, y, width, height = box
    return x <= center[0] <= x + width and y <= center[1] <= y + height


def _texts_norm(lines: list[dict], frame_size: tuple[int, int] | None) -> list[dict]:
    texts: list[dict] = []
    for line in lines[:MAX_TEXT_LINES]:
        center = _line_center_norm(line, frame_size)
        texts.append(
            {
                "text": line["text"],
                "score": round(float(line["score"]), 4),
                "x": None if center is None else round(_clamp(center[0], 0.0, 1.0), 4),
                "y": None if center is None else round(_clamp(center[1], 0.0, 1.0), 4),
            }
        )
    return texts


# ── HP ────────────────────────────────────────────────────────────────────────
def _hp_config(profile: Any) -> tuple[tuple[float, float, float, float] | None, str | None, int | None]:
    hp = _mapping(_section(profile, "hud").get("hp"))
    box = _box(hp.get("box"))
    prefix = hp.get("prefix")
    prefix = prefix.strip() if isinstance(prefix, str) and prefix.strip() else None
    return box, prefix, _int_or_none(hp.get("max_hp"))


def _parse_hp_text(text: str, prefix: str | None) -> tuple[int | None, str | None]:
    """Return (current HP, numeric hp_text) parsed from one OCR line."""
    if prefix is not None:
        pattern = rf"(?<![A-Za-z]){re.escape(prefix)}\s*[.:\-_=]?\s*(\d{{1,4}})(?:\s*/\s*(\d{{1,4}}))?"
    else:
        pattern = r"(\d{1,4})(?:\s*/\s*(\d{1,4}))?"
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None, None
    hp = int(match.group(1))
    maximum = match.group(2)
    hp_text = f"{hp}/{int(maximum)}" if maximum is not None else str(hp)
    return hp, hp_text


def extract_hp(
    ocr_lines: Any,
    *,
    profile: Any = None,
    frame_size: tuple[int, int] | None = None,
) -> tuple[int | None, str | None]:
    """Extract (hp, hp_text) from OCR lines.

    Only lines whose center falls inside the profile's normalized ``hud.hp.box``
    are candidates; when a ``prefix`` is configured the line must contain it.
    ``frame_size`` is an optional extension used by :func:`extract_visual_state`
    so pixel coordinates can be normalized; without it the box filter only works
    for already-normalized coordinates. Never raises.
    """
    try:
        lines = _coerce_lines(ocr_lines)
        box, prefix, _unused = _hp_config(profile)
        best: tuple[float, int, int, str] | None = None
        for index, line in enumerate(lines):
            if not _inside_box(line, box, frame_size):
                continue
            hp, hp_text = _parse_hp_text(line["text"], prefix)
            if hp is None or hp_text is None:
                continue
            candidate = (float(line["score"]), -index, hp, hp_text)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        if best is None:
            return None, None
        return int(best[2]), best[3]
    except Exception:  # noqa: BLE001 - extractors never raise
        return None, None


def _max_hp(hp: int | None, hp_text: str | None, profile: Any) -> int | None:
    if hp_text is not None and "/" in hp_text:
        _current, _slash, maximum = hp_text.partition("/")
        parsed = _int_or_none(maximum)
        if parsed is not None and parsed > 0:
            return parsed
    _box_unused, _prefix_unused, configured = _hp_config(profile)
    if configured is not None and configured > 0:
        return configured
    return None


# ── scene ────────────────────────────────────────────────────────────────────
def _keywords(profile: Any, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _section(profile, "scene").get(key)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return default
    values = tuple(str(item).strip().upper() for item in raw if str(item).strip())
    return values or default


def _keyword_match(lines: list[dict], keywords: tuple[str, ...]) -> float | None:
    """Highest OCR score among lines containing any keyword, or None."""
    best: float | None = None
    for line in lines:
        upper = line["text"].upper()
        if any(keyword in upper for keyword in keywords):
            score = float(line["score"])
            if best is None or score > best:
                best = score
    return best


def _keyword_confidence(score: float | None, fallback: float) -> float:
    if score is None:
        return fallback
    return round(_clamp(0.6 + 0.35 * score, 0.6, 0.95), 3)


def detect_scene(
    ocr_lines: Any,
    *,
    profile: Any = None,
    hp: int | None = None,
) -> tuple[str, float]:
    """Classify the scene from OCR text (pure; no frame needed).

    Precedence: death keywords -> death; menu keywords -> menu; HP found ->
    gameplay; ``0 < len(lines) <= loading_max_texts`` -> loading; other OCR text
    -> dialogue; no OCR text -> unknown. Never raises.
    """
    try:
        lines = _coerce_lines(ocr_lines)
        death_score = _keyword_match(lines, _keywords(profile, "death_keywords", DEFAULT_DEATH_KEYWORDS))
        if death_score is not None:
            return "death", _keyword_confidence(death_score, 0.85)
        menu_score = _keyword_match(lines, _keywords(profile, "menu_keywords", DEFAULT_MENU_KEYWORDS))
        if menu_score is not None:
            return "menu", _keyword_confidence(menu_score, 0.8)
        if hp is not None:
            return "gameplay", 0.7
        max_texts = _int_or_none(_section(profile, "scene").get("loading_max_texts"))
        if max_texts is None:
            max_texts = DEFAULT_LOADING_MAX_TEXTS
        max_texts = max(0, max_texts)
        if 0 < len(lines) <= max_texts:
            return "loading", 0.55
        if lines:
            return "dialogue", 0.5
        return "unknown", 0.0
    except Exception:  # noqa: BLE001 - extractors never raise
        return "unknown", 0.0


def _near_black_threshold(profile: Any) -> float:
    configured = _section(profile, "scene").get("near_black_mean")
    if configured is None:
        configured = _section(profile, "scene").get("near_black")
    return _clamp(_number(configured, DEFAULT_NEAR_BLACK_MEAN), 0.0, 255.0)


def _is_near_black(frame: np.ndarray, profile: Any) -> bool:
    try:
        return float(frame.mean()) < _near_black_threshold(profile)
    except Exception:  # noqa: BLE001
        return False


# ── prompt (generic heuristic, profile-overridable) ──────────────────────────
def _prompt_keywords(profile: Any) -> tuple[str, ...]:
    for section in ("scene", "hud"):
        raw = _section(profile, section).get("prompt_keywords")
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple)):
            values = tuple(str(item).strip().upper() for item in raw if str(item).strip())
            if values:
                return values
    return ()


def _extract_prompt(lines: list[dict], profile: Any) -> str | None:
    try:
        keywords = _prompt_keywords(profile)
        ordered = sorted(lines, key=lambda line: float(line["score"]), reverse=True)
        if keywords:
            for line in ordered:
                upper = line["text"].upper()
                if any(keyword in upper for keyword in keywords):
                    return line["text"]
            return None
        for line in ordered:
            upper = line["text"].upper()
            if any(verb in upper for verb in _PROMPT_VERBS):
                return line["text"]
        return None
    except Exception:  # noqa: BLE001
        return None


# ── cheap entity detectors ───────────────────────────────────────────────────
def _parry_config(profile: Any) -> dict:
    configured = _mapping(_section(profile, "colors").get("parry"))
    config = dict(DEFAULT_PARRY)
    for key in config:
        if key in configured:
            config[key] = _number(configured[key], config[key])
    config["r_min"] = int(_clamp(config["r_min"], 0, 255))
    config["b_min"] = int(_clamp(config["b_min"], 0, 255))
    config["rb_minus_g_min"] = int(_clamp(config["rb_minus_g_min"], 0, 255))
    config["min_pixels"] = int(max(1, _clamp(config["min_pixels"], 1, 100_000)))
    return config


def _detect_parry(frame: np.ndarray, profile: Any) -> list[dict]:
    """Magenta-ish color blobs (parry objects), normalized centers."""
    import cv2

    config = _parry_config(profile)
    height, width = frame.shape[:2]
    work = frame
    # pyrDown is much cheaper than a full INTER_AREA resize of a color frame;
    # the min_pixels threshold is scaled by the resulting area ratio.
    while max(work.shape[0], work.shape[1]) > PARRY_MAX_DIM:
        work = cv2.pyrDown(work)
    area_ratio = (work.shape[0] * work.shape[1]) / float(height * width)
    min_pixels = max(1, int(round(config["min_pixels"] * area_ratio)))

    blue = cv2.extractChannel(work, 0)
    green = cv2.extractChannel(work, 1)
    red = cv2.extractChannel(work, 2)
    threshold = config["rb_minus_g_min"]
    # "rb_minus_g_min" = minimum of (R-G) and (B-G): min(R, B) - G >= T is
    # exactly that, so one min/subtract/inRange covers both channel diffs.
    magenta_gap = cv2.subtract(cv2.min(red, blue), green)
    lower = np.array([config["b_min"], 0, config["r_min"]], dtype=np.uint8)
    upper = np.full(3, 255, dtype=np.uint8)
    mask = cv2.inRange(work, lower, upper)
    mask = cv2.bitwise_and(mask, cv2.inRange(magenta_gap, threshold, 255))
    if cv2.countNonZero(mask) < min_pixels:
        return []

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    work_height, work_width = work.shape[:2]
    entities: list[dict] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_pixels:
            continue
        # Confidence from blob size: a bigger solid magenta blob is a stronger
        # parry candidate than a threshold-grazing speck.
        score = _clamp(0.5 + 0.5 * min(1.0, area / float(min_pixels * 8)), 0.0, 1.0)
        center_x, center_y = centroids[label]
        entities.append(
            {
                "kind": "parry",
                "x": round(_clamp(float(center_x) / work_width, 0.0, 1.0), 4),
                "y": round(_clamp(float(center_y) / work_height, 0.0, 1.0), 4),
                "score": round(score, 4),
            }
        )
    entities.sort(key=lambda entity: (-entity["score"], entity["x"], entity["y"]))
    return entities[:MAX_ENTITIES]


def _self_area(profile: Any) -> tuple[tuple[float, float] | None, float]:
    """(normalized self position, drop radius) from the profile, best effort."""
    position: tuple[float, float] | None = None
    candidates = (
        _mapping(profile).get("self_pos"),
        _section(profile, "combat").get("self_pos"),
        _section(profile, "player").get("self_pos"),
    )
    for candidate in candidates:
        position = _position(candidate)
        if position is not None:
            break
    if position is None:
        player = _section(profile, "player")
        x, y = player.get("x"), player.get("y")
        if x is not None and y is not None:
            position = _position((x, y))
    radius = _number(_section(profile, "combat").get("self_radius"), DEFAULT_SELF_RADIUS)
    return position, _clamp(radius, 0.0, 1.0)


def _position(value: Any) -> tuple[float, float] | None:
    if isinstance(value, Mapping):
        x, y = value.get("x"), value.get("y")
        if x is None or y is None:
            return None
        return _clamp(_number(x, 0.5), 0.0, 1.0), _clamp(_number(y, 0.5), 0.0, 1.0)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return _clamp(float(value[0]), 0.0, 1.0), _clamp(float(value[1]), 0.0, 1.0)
        except (TypeError, ValueError):
            return None
    return None


def _drop_self_area(entities: list[dict], profile: Any) -> list[dict]:
    position, radius = _self_area(profile)
    if position is None or radius <= 0.0:
        return entities
    kept = []
    for entity in entities:
        distance = math.hypot(entity["x"] - position[0], entity["y"] - position[1])
        if distance >= radius:
            kept.append(entity)
    return kept


def _detect_threats(frame: np.ndarray, prev_frame: np.ndarray, profile: Any) -> list[dict]:
    """Downsample -> frame diff -> background percentile -> grid cells."""
    import cv2

    if frame.shape[:2] != prev_frame.shape[:2]:
        return []
    # Grayscale first, then pyrDown, then diff, then one final small resize:
    # two full-res color resizes cost ~2 ms, while this whole path is cheap.
    current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    previous = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    while current.shape[1] > 2 * THREAT_MAX_WIDTH or current.shape[0] > 2 * THREAT_MAX_HEIGHT:
        current = cv2.pyrDown(current)
        previous = cv2.pyrDown(previous)
    height, width = current.shape[:2]
    diff = cv2.absdiff(current, previous)
    scale = min(THREAT_MAX_WIDTH / float(width), THREAT_MAX_HEIGHT / float(height), 1.0)
    if scale < 1.0:
        size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        diff = cv2.resize(diff, size, interpolation=cv2.INTER_LINEAR)

    # Global motion (camera pan / scrolling) shows up as a nonzero floor in the
    # frame diff; subtracting the 75th percentile keeps only local motion. The
    # percentile is estimated on a subsample: the value is a floor, not precise.
    sample = diff[::2, ::2] if diff.size > 8000 else diff
    background = float(np.percentile(sample, 75))
    residual = diff - int(round(background))
    np.clip(residual, 0, 255, out=residual)

    small_height, small_width = residual.shape
    grid_height = max(1, int(round(small_height / float(THREAT_CELL))))
    grid_width = max(1, int(round(small_width / float(THREAT_CELL))))
    # cv2.resize(INTER_AREA) computes the per-cell means in one SIMD pass.
    cell_scores = cv2.resize(residual, (grid_width, grid_height), interpolation=cv2.INTER_AREA) / 255.0

    grid_mask = (cell_scores >= THREAT_CELL_MIN).astype(np.uint8)
    if cv2.countNonZero(grid_mask) == 0:
        return []

    count, labels, _stats, _centroids = cv2.connectedComponentsWithStats(grid_mask, connectivity=8)
    entities: list[dict] = []
    for label in range(1, count):
        component = labels == label
        weights = cell_scores[component]
        total = float(weights.sum())
        if total <= 0.0:
            continue
        ys, xs = np.nonzero(component)
        center_x = float((weights * (xs + 0.5)).sum() / total / grid_width)
        center_y = float((weights * (ys + 0.5)).sum() / total / grid_height)
        score = float(weights.mean())
        if score < THREAT_CELL_MIN:
            continue
        entities.append(
            {
                "kind": "threat",
                "x": round(_clamp(center_x, 0.0, 1.0), 4),
                "y": round(_clamp(center_y, 0.0, 1.0), 4),
                "score": round(_clamp(score, 0.0, 1.0), 4),
            }
        )
    entities = _drop_self_area(entities, profile)
    entities.sort(key=lambda entity: (-entity["score"], entity["x"], entity["y"]))
    return entities[:THREAT_MAX_ENTITIES]


def cheap_entities(frame_bgr: Any, prev_frame: Any, profile: Any = None) -> list[dict]:
    """60 Hz path: parry color blobs + moving-threat clusters, no OCR.

    Returns entity dicts ``{"kind": "parry" | "threat", "x", "y", "score"}`` with
    normalized coordinates, sorted by score descending. Never raises; returns []
    for unusable input. Threats need ``prev_frame`` (None only yields parries).
    """
    try:
        frame = _coerce_frame(frame_bgr)
        if frame is None:
            return []
        entities: list[dict] = []
        try:
            entities.extend(_detect_parry(frame, profile))
        except Exception:  # noqa: BLE001 - color detector failure must not raise
            pass
        previous = _coerce_frame(prev_frame)
        if previous is not None:
            try:
                entities.extend(_detect_threats(frame, previous, profile))
            except Exception:  # noqa: BLE001 - motion detector failure must not raise
                pass
        entities.sort(key=lambda entity: (-entity["score"], entity["x"], entity["y"]))
        return entities[:MAX_ENTITIES]
    except Exception:  # noqa: BLE001 - extractors never raise
        return []


# ── WorldState assembly ──────────────────────────────────────────────────────
def _profile_id(profile: Any) -> str | None:
    value = _mapping(profile).get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _timestamp(now: Any) -> float:
    if now is None:
        return round(time.time(), 3)
    try:
        value = float(now)
    except (TypeError, ValueError):
        return round(time.time(), 3)
    if math.isnan(value) or math.isinf(value):
        return round(time.time(), 3)
    return round(value, 3)


def _unknown_state(profile: Any, now: float) -> dict:
    return {
        "schema": STATE_SCHEMA,
        "t": now,
        "scene": "unknown",
        "confidence": 0.0,
        "player": {"x": None, "y": None, "hp": None, "max_hp": None, "state": "unknown"},
        "entities": [],
        "ui": {"texts": [], "prompt": None, "hp_text": None},
        "game": {"profile": _profile_id(profile), "provider": "vision", "stale": False},
        # Session wiring replaces these with foreground/occlusion metadata.
        "foreground": None,
        "occluded": None,
    }


def extract_visual_state(
    frame_bgr: Any,
    ocr_lines: Any = (),
    *,
    profile: Any = None,
    prev_frame: Any = None,
    now: Any = None,
) -> dict:
    """Extract the full WorldState dict for one captured frame.

    Never raises: unusable input yields the unknown defaults. Scene/HP come from
    OCR + profile, entities from the cheap detectors, coordinates are normalized.
    """
    timestamp = _timestamp(now)
    try:
        lines = _coerce_lines(ocr_lines)
        frame = _coerce_frame(frame_bgr)
        previous = _coerce_frame(prev_frame)
        frame_size = None if frame is None else (int(frame.shape[1]), int(frame.shape[0]))

        hp, hp_text = extract_hp(lines, profile=profile, frame_size=frame_size)
        scene, confidence = detect_scene(lines, profile=profile, hp=hp)
        if frame is not None and scene in ("unknown", "dialogue") and _is_near_black(frame, profile):
            scene, confidence = "loading", 0.5
        max_hp = _max_hp(hp, hp_text, profile)
        state = _unknown_state(profile, timestamp)
        state.update(
            {
                "scene": scene,
                "confidence": round(float(confidence), 3),
                "player": {"x": None, "y": None, "hp": hp, "max_hp": max_hp, "state": "unknown"},
                "entities": cheap_entities(frame, previous, profile) if frame is not None else [],
                "ui": {
                    "texts": _texts_norm(lines, frame_size),
                    "prompt": _extract_prompt(lines, profile),
                    "hp_text": hp_text,
                },
            }
        )
        return state
    except Exception:  # noqa: BLE001 - extractors never raise
        return _unknown_state(profile, timestamp)
