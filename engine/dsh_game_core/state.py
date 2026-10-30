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
DEFAULT_EQUIP_KEYWORDS = ("UNEQUIP", "EQUIP CARD")

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

    Precedence: equip keywords -> equip; death keywords -> death; menu keywords ->
    menu; HP found -> gameplay; ``0 < len(lines) <= loading_max_texts`` -> loading;
    other OCR text -> dialogue; no OCR text -> unknown. Never raises.
    """
    try:
        lines = _coerce_lines(ocr_lines)
        equip_score = _keyword_match(lines, _keywords(profile, "equip_keywords", DEFAULT_EQUIP_KEYWORDS))
        if equip_score is not None:
            return "equip", _keyword_confidence(equip_score, 0.85)
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


def _player_section(profile: Any) -> Mapping:
    return _section(profile, "player")


_PLAYER_TEMPLATE_CACHE: dict[int, np.ndarray] = {}


def _player_template(profile: Any) -> np.ndarray | None:
    """Decode/cached player template PNG from profile (base64), if provided."""
    section = _player_section(profile)
    encoded = section.get("template_png_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        return None
    key = hash(encoded)
    cached = _PLAYER_TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        import base64

        import cv2

        raw = base64.b64decode(encoded, validate=True)
        array = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is not None and image.ndim == 3 and image.size:
            _PLAYER_TEMPLATE_CACHE[key] = image
            return image
    except Exception:  # noqa: BLE001 - bad template just disables tracking
        return None
    return None


def _player_color_mask(frame: np.ndarray, specs: Any) -> np.ndarray | None:
    """Union of profile r/g/b ranges as a boolean mask (None if unusable)."""
    if not isinstance(specs, (list, tuple)) or not specs:
        return None
    try:
        h, w = frame.shape[:2]
        bgr = frame.astype(np.int16)
        b, g, r = bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2]
        mask = np.zeros((h, w), dtype=bool)
        for spec in specs:
            if not isinstance(spec, Mapping):
                continue
            current = np.ones((h, w), dtype=bool)
            for channel, values in (("r", r), ("g", g), ("b", b)):
                low = spec.get(f"{channel}_min")
                high = spec.get(f"{channel}_max")
                if low is not None:
                    current &= values >= _number(low, 0)
                if high is not None:
                    current &= values <= _number(high, 255)
            mask |= current
        return mask
    except Exception:  # noqa: BLE001
        return None


def _player_color_valid(frame: np.ndarray, section: Mapping, found: dict) -> bool:
    """Check that a template hit has the player's colors inside its bbox."""
    specs = section.get("validate_colors")
    mask = _player_color_mask(frame, specs)
    if mask is None:
        return True
    try:
        h, w = frame.shape[:2]
        size = section.get("template_size")
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            bw = int(w * _number(size[0], 0.15))
            bh = int(h * _number(size[1], 0.3))
        else:
            bw = max(12, int(w * 0.15))
            bh = max(12, int(h * 0.3))
        cx = int(float(found["x"]) * w)
        cy = int(float(found["y"]) * h)
        x0, x1 = max(0, cx - bw // 2), min(w, cx + bw // 2 + 1)
        y0, y1 = max(0, cy - bh // 2), min(h, cy + bh // 2 + 1)
        if x1 <= x0 or y1 <= y0:
            return False
        fraction = float(mask[y0:y1, x0:x1].mean())
        return fraction >= _number(section.get("validate_min_fraction"), 0.02)
    except Exception:  # noqa: BLE001
        return True


def _find_player_color(frame: np.ndarray, profile: Any) -> dict | None:
    """Color-blob fallback: profile.player.colors = [{r_min,g_min,b_min,...}], largest blob."""
    section = _player_section(profile)
    mask = _player_color_mask(frame, section.get("colors"))
    if mask is None:
        return None
    try:
        import cv2

        h, w = frame.shape[:2]
        gray = (mask.astype(np.uint8) * 255)
        min_pixels = int(_number(section.get("min_pixels"), 40))
        if cv2.countNonZero(gray) < min_pixels:
            return None
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(gray, connectivity=8)
        best = None
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < min_pixels or (best is not None and area <= best[0]):
                continue
            cx, cy = centroids[label]
            best = (area, float(cx) / w, float(cy) / h)
        if best is None:
            return None
        area, cx, cy = best
        return {
            "x": round(_clamp(cx, 0.0, 1.0), 4),
            "y": round(_clamp(cy, 0.0, 1.0), 4),
            "score": round(min(1.0, _number(section.get("color_score"), 0.55)), 4),
            "method": "color",
        }
    except Exception:  # noqa: BLE001
        return None


def _previous_point(previous: Any) -> tuple[float, float] | None:
    if isinstance(previous, Mapping):
        x = _number(previous.get("x"), float("nan"))
        y = _number(previous.get("y"), float("nan"))
    elif isinstance(previous, (list, tuple)) and len(previous) >= 2:
        x = _number(previous[0], float("nan"))
        y = _number(previous[1], float("nan"))
    else:
        return None
    if math.isnan(x) or math.isnan(y):
        return None
    return (_clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0))


def _match_player_template(
    frame: np.ndarray,
    section: Mapping,
    template: np.ndarray,
    *,
    previous: tuple[float, float] | None,
) -> dict | None:
    """Template match, preferring a crop around the previous position (continuity)."""
    import cv2

    h, w = frame.shape[:2]
    search_width = max(120, min(int(_number(section.get("search_width"), 480)), w))
    scale = search_width / float(w)
    size = section.get("template_size")
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        tw = max(8, int(round(w * _number(size[0], 0.15) * scale)))
        th = max(8, int(round(h * _number(size[1], 0.3) * scale)))
    else:
        tw = max(8, int(round(template.shape[1] * scale)))
        th = max(8, int(round(template.shape[0] * scale)))
    threshold = _number(section.get("match_threshold"), 0.6)
    radius = _number(section.get("search_radius"), 0.30)

    def match(image: np.ndarray) -> tuple[float, int, int, int, int] | None:
        if image.size == 0 or image.shape[0] <= th or image.shape[1] <= tw:
            return None
        resized = cv2.resize(
            image, (max(1, int(round(image.shape[1] * scale))), max(1, int(round(image.shape[0] * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        if resized.shape[0] <= th or resized.shape[1] <= tw:
            return None
        scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(resized, scaled, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if not math.isfinite(max_val):
            return None
        return float(max_val), int(max_loc[0]), int(max_loc[1]), resized, image

    if previous is not None:
        px, py = previous
        x0 = max(0, int((px - radius) * w))
        y0 = max(0, int((py - radius) * h))
        x1 = min(w, int((px + radius) * w))
        y1 = min(h, int((py + radius) * h))
        if x1 - x0 >= 32 and y1 - y0 >= 32:
            found = match(frame[y0:y1, x0:x1])
            if found is not None:
                score, loc_x, loc_y, resized, crop = found
                if score >= threshold:
                    center_x = (x0 + (loc_x + tw / 2.0) / scale) / w
                    center_y = (y0 + (loc_y + th / 2.0) / scale) / h
                    return {
                        "x": round(_clamp(center_x, 0.0, 1.0), 4),
                        "y": round(_clamp(center_y, 0.0, 1.0), 4),
                        "score": round(score, 4),
                        "method": "template-track",
                    }

    found = match(frame)
    if found is None:
        return None
    score, loc_x, loc_y, resized, _crop = found
    if score < threshold:
        return None
    center_x = (loc_x + tw / 2.0) / resized.shape[1]
    center_y = (loc_y + th / 2.0) / resized.shape[0]
    return {
        "x": round(_clamp(center_x, 0.0, 1.0), 4),
        "y": round(_clamp(center_y, 0.0, 1.0), 4),
        "score": round(score, 4),
        "method": "template",
    }


def find_player(frame_bgr: Any, profile: Any = None, previous: Any = None) -> dict | None:
    """Locate the controllable character in one BGR frame (profile-driven, never raises).

    Two generic modes:
    - template: ``profile.player.template_png_base64`` + optional ``template_size``
      (normalized width/height ratios), ``search_width``, ``match_threshold``,
      ``search_radius`` (prefer a crop around ``previous`` to avoid false positives);
    - color: ``profile.player.colors`` (list of r/g/b min/max ranges), largest blob.
    Returns ``{"x","y","score","method"}`` normalized to the frame, or None.
    """
    try:
        frame = _coerce_frame(frame_bgr)
        if frame is None:
            return None
        section = _player_section(profile)
        if section.get("track") is False:
            return None
        template = _player_template(profile)
        if template is not None:
            found = _match_player_template(frame, section, template, previous=_previous_point(previous))
            if found is not None and _player_color_valid(frame, section, found):
                return found
        return _find_player_color(frame, profile)
    except Exception:  # noqa: BLE001 - perception must never raise
        return None


def detect_static_hazards(frame_bgr: Any, profile: Any = None) -> list[dict]:
    """Profile-driven static hazard blobs (ground mushrooms/spikes) via colour ranges.

    Frame-difference threat detection is blind to stationary hazards; this is the
    cheap visual floor for them. Profile:
      hazards: [{kind, colors:[{r_min,...}], region:[l,t,w,h], min_pixels}]
    Returns normalized {kind,x,y,area,score}.
    """
    try:
        frame = _coerce_frame(frame_bgr)
        if frame is None:
            return []
        specs = _mapping(profile).get("hazards")
        if not isinstance(specs, (list, tuple)):
            return []
        import cv2

        height, width = frame.shape[:2]
        found: list[dict] = []
        for spec in specs:
            if not isinstance(spec, Mapping):
                continue
            region = spec.get("region")
            if isinstance(region, (list, tuple)) and len(region) >= 4:
                left = int(max(0.0, min(1.0, _number(region[0], 0.0))) * width)
                top = int(max(0.0, min(1.0, _number(region[1], 0.0))) * height)
                rw = int(max(0.0, min(1.0, _number(region[2], 1.0))) * width)
                rh = int(max(0.0, min(1.0, _number(region[3], 1.0))) * height)
                crop = frame[top : top + rh, left : left + rw]
            else:
                left = top = 0
                crop = frame
            mask = _player_color_mask(crop, spec.get("colors"))
            if mask is None:
                continue
            gray = (mask.astype(np.uint8) * 255)
            min_pixels = int(_number(spec.get("min_pixels"), 24))
            if cv2.countNonZero(gray) < min_pixels:
                continue
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(gray, connectivity=8)
            for label in range(1, count):
                area = int(stats[label, cv2.CC_STAT_AREA])
                if area < min_pixels:
                    continue
                cx, cy = centroids[label]
                found.append(
                    {
                        "kind": str(spec.get("kind") or "hazard")[:32],
                        "x": round(_clamp((left + float(cx)) / width, 0.0, 1.0), 4),
                        "y": round(_clamp((top + float(cy)) / height, 0.0, 1.0), 4),
                        "area": area,
                        "score": round(min(1.0, area / 500.0), 4),
                    }
                )
        found.sort(key=lambda item: (-item["area"], item["x"]))
        return found[:8]
    except Exception:  # noqa: BLE001 - 静态危险检测失败只损失本拍信息
        return []


# ── WorldState assembly ──────────────────────────────────────────────────────
_PROMPT_ICON_CACHE: dict[int, np.ndarray] = {}


def _prompt_icons(profile: Any) -> list[dict]:
    """Return decoded prompt-icon templates from profile.ui.prompt_icons."""
    ui = _section(profile, "ui")
    icons = ui.get("prompt_icons")
    if not isinstance(icons, (list, tuple)):
        return []
    decoded: list[dict] = []
    for icon in icons:
        if not isinstance(icon, Mapping):
            continue
        encoded = icon.get("template_png_base64")
        if not isinstance(encoded, str) or not encoded.strip():
            continue
        key = hash(encoded)
        template = _PROMPT_ICON_CACHE.get(key)
        if template is None:
            try:
                import base64

                import cv2

                raw = base64.b64decode(encoded, validate=True)
                template = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            except Exception:  # noqa: BLE001 - bad template disables that icon
                template = None
            if template is None:
                continue
            _PROMPT_ICON_CACHE[key] = template
        decoded.append({"spec": icon, "template": template})
    return decoded


def detect_prompt_icon(frame_bgr: Any, profile: Any = None) -> dict | None:
    """Detect an on-screen key/interaction prompt icon via profile templates.

    Returns ``{"key": str, "x": float, "y": float, "score": float}`` or None.
    This is the general "you can interact now" signal; OCR text is not required.
    """
    try:
        frame = _coerce_frame(frame_bgr)
        if frame is None:
            return None
        icons = _prompt_icons(profile)
        if not icons:
            return None
        import cv2

        h, w = frame.shape[:2]
        best: dict | None = None
        for entry in icons:
            spec = entry["spec"]
            template = entry["template"]
            search_width = int(_number(spec.get("search_width"), 480))
            search_width = max(120, min(search_width, w))
            scale = search_width / float(w)
            search = cv2.resize(
                frame, (search_width, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA
            )
            size = spec.get("size")
            if isinstance(size, (list, tuple)) and len(size) >= 2:
                tw = max(6, int(round(w * _number(size[0], 0.05) * scale)))
                th = max(6, int(round(h * _number(size[1], 0.08) * scale)))
            else:
                tw = max(6, int(round(template.shape[1] * scale)))
                th = max(6, int(round(template.shape[0] * scale)))
            if tw >= search.shape[1] or th >= search.shape[0]:
                continue
            scaled = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
            threshold = _number(spec.get("match_threshold"), 0.55)
            if not math.isfinite(max_val) or max_val < threshold:
                continue
            candidate = {
                "key": str(spec.get("key") or "?"),
                "x": round(_clamp((max_loc[0] + tw / 2.0) / search_width, 0.0, 1.0), 4),
                "y": round(_clamp((max_loc[1] + th / 2.0) / search.shape[0], 0.0, 1.0), 4),
                "score": round(float(max_val), 4),
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
        return best
    except Exception:  # noqa: BLE001 - perception must never raise
        return None


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
        "player": {"x": None, "y": None, "hp": None, "max_hp": None, "state": "unknown", "confidence": None},
        "entities": [],
        "ui": {"texts": [], "prompt": None, "icon_prompt": None, "hp_text": None},
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
        found = find_player(frame, profile) if frame is not None else None
        player_x = found["x"] if isinstance(found, dict) else None
        player_y = found["y"] if isinstance(found, dict) else None
        state = _unknown_state(profile, timestamp)
        state.update(
            {
                "scene": scene,
                "confidence": round(float(confidence), 3),
                "player": {
                    "x": player_x,
                    "y": player_y,
                    "hp": hp,
                    "max_hp": max_hp,
                    "state": "unknown",
                    "confidence": (found or {}).get("score") if isinstance(found, dict) else None,
                },
                "entities": cheap_entities(frame, previous, profile) if frame is not None else [],
                "ui": {
                    "texts": _texts_norm(lines, frame_size),
                    "prompt": _extract_prompt(lines, profile),
                    "icon_prompt": detect_prompt_icon(frame, profile) if frame is not None else None,
                    "hp_text": hp_text,
                },
            }
        )
        return state
    except Exception:  # noqa: BLE001 - extractors never raise
        return _unknown_state(profile, timestamp)
