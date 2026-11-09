"""Generic player self-tracker: auto template + predicted ROI + full-frame reacquire.

Why this exists: colour-only tracking loses the player after a dash/jump or an
occlusion, and then every threat/relative decision is wrong. This tracker keeps
an appearance template learned from the first reliable colour blob, predicts the
next position from velocity + action state, matches inside a small ROI, and only
falls back to a full-frame scan when it has been missing for several frames.

No game names, level data, or engine branches live here; the caller supplies a
profile with generic `player.colors` / `player.min_pixels` (optional template).
The templates are runtime crops and must never be committed to the repository.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np


@dataclass
class PlayerTemplate:
    gray: np.ndarray
    width: int
    height: int
    hits: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class TrackerConfig:
    max_templates: int = 6
    min_pixels: int = 20
    color_accept: float = 0.35
    template_accept: float = 0.40
    reacquire_accept: float = 0.35
    search_radius: float = 0.20
    lost_radius: float = 0.35
    max_missing_before_stale: int = 3
    max_missing_before_full: int = 5


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _crop_gray(gray: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    x0, y0, x1, y1 = box
    height, width = gray.shape[:2]
    x0 = max(0, min(width - 1, int(x0)))
    y0 = max(0, min(height - 1, int(y0)))
    x1 = max(x0 + 1, min(width, int(x1)))
    y1 = max(y0 + 1, min(height, int(y1)))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    patch = gray[y0:y1, x0:x1]
    return patch.copy() if patch.size else None


class PlayerTracker:
    def __init__(self, profile: dict | None = None, **overrides) -> None:
        self.profile = profile if isinstance(profile, dict) else {}
        player = self.profile.get("player") if isinstance(self.profile.get("player"), dict) else {}
        config = TrackerConfig(
            max_templates=int(player.get("max_templates") or 6),
            min_pixels=int(player.get("min_pixels") or 20),
            color_accept=float(player.get("color_accept") or 0.35),
            template_accept=float(player.get("template_accept") or 0.40),
            reacquire_accept=float(player.get("reacquire_accept") or 0.35),
            search_radius=float(player.get("search_radius") or 0.20),
            lost_radius=float(player.get("lost_radius") or 0.35),
            max_missing_before_stale=int(player.get("max_missing_before_stale") or 3),
            max_missing_before_full=int(player.get("max_missing_before_full") or 5),
        )
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.config = config
        self.templates: list[PlayerTemplate] = []
        self.last: tuple[float, float] | None = None
        self.velocity = (0.0, 0.0)
        self.missing = 0
        self.last_seen_at = 0.0
        self._candidate: tuple[float, float] | None = None
        self.last_source = "none"
        self.last_score = 0.0

    def reset(self, anchor: tuple[float, float] | None = None) -> None:
        self.last = anchor
        self.velocity = (0.0, 0.0)
        self.missing = 0
        self.last_seen_at = 0.0
        self._candidate = None
        self.last_source = "none"
        self.last_score = 0.0

    def status(self) -> dict:
        age_ms = None
        if self.last_seen_at:
            age_ms = round(max(0.0, time.monotonic() - self.last_seen_at) * 1000.0)
        return {
            "last": list(self.last) if self.last else None,
            "velocity": [round(self.velocity[0], 4), round(self.velocity[1], 4)],
            "missing": int(self.missing),
            "stale": self.missing >= self.config.max_missing_before_stale,
            "templates": len(self.templates),
            "source": self.last_source,
            "score": round(self.last_score, 4),
            "age_ms": age_ms,
        }

    # ── frame helpers ────────────────────────────────────────────────────
    @staticmethod
    def _gray(frame: np.ndarray) -> np.ndarray | None:
        try:
            import cv2

            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                return None
            if frame.ndim == 2:
                return frame.astype(np.uint8, copy=False)
            if frame.ndim != 3 or frame.shape[2] < 3:
                return None
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        except Exception:  # noqa: BLE001
            return None

    def _colour_candidates(self, frame: np.ndarray) -> list[dict]:
        try:
            import cv2

            player = self.profile.get("player") if isinstance(self.profile.get("player"), dict) else {}
            specs = player.get("colors")
            if not isinstance(specs, (list, tuple)):
                return []
            height, width = frame.shape[:2]
            mask = np.zeros((height, width), dtype=np.uint8)
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                lower = np.array(
                    [int(spec.get("b_min", 0)), int(spec.get("g_min", 0)), int(spec.get("r_min", 0))],
                    dtype=np.uint8,
                )
                upper = np.array(
                    [int(spec.get("b_max", 255)), int(spec.get("g_max", 255)), int(spec.get("r_max", 255))],
                    dtype=np.uint8,
                )
                mask = cv2.bitwise_or(mask, cv2.inRange(frame, lower, upper))
            if not mask.any():
                return []
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
            candidates = []
            for label in range(1, count):
                area = int(stats[label, cv2.CC_STAT_AREA])
                if area < self.config.min_pixels:
                    continue
                x = int(stats[label, cv2.CC_STAT_LEFT])
                y = int(stats[label, cv2.CC_STAT_TOP])
                w = int(stats[label, cv2.CC_STAT_WIDTH])
                h = int(stats[label, cv2.CC_STAT_HEIGHT])
                if h <= 0 or w <= 0:
                    continue
                cx, cy = centroids[label]
                candidates.append(
                    {
                        "x": round(float(cx) / width, 4),
                        "y": round(float(cy) / height, 4),
                        "w": w,
                        "h": h,
                        "area": area,
                        "box": (x, y, x + w, y + h),
                        "source": "colour",
                        "score": round(min(1.0, area / max(1.0, float(self.config.min_pixels) * 8)), 4),
                    }
                )
            return candidates
        except Exception:  # noqa: BLE001
            return []

    def _template_candidates(
        self,
        gray: np.ndarray,
        center: tuple[float, float],
        radius: float,
        *,
        multi_scale: bool = True,
    ) -> list[dict]:
        try:
            import cv2

            height, width = gray.shape[:2]
            cx = int(center[0] * width)
            cy = int(center[1] * height)
            reach_x = max(24, int(radius * width))
            reach_y = max(24, int(radius * height))
            x0 = max(0, cx - reach_x)
            y0 = max(0, cy - reach_y)
            x1 = min(width, cx + reach_x)
            y1 = min(height, cy + reach_y)
            roi = gray[y0:y1, x0:x1]
            if roi.size == 0:
                return []
            candidates = []
            scales = (1.0, 0.85, 1.15) if multi_scale else (1.0,)
            for template in self.templates:
                for scale in scales:
                    tw = max(6, int(template.width * scale))
                    th = max(6, int(template.height * scale))
                    if tw >= roi.shape[1] or th >= roi.shape[0]:
                        continue
                    tpl = cv2.resize(template.gray, (tw, th), interpolation=cv2.INTER_AREA)
                    result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
                    _min, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
                    if not math.isfinite(max_val):
                        continue
                    px = x0 + max_loc[0] + tw / 2.0
                    py = y0 + max_loc[1] + th / 2.0
                    candidates.append(
                        {
                            "x": round(_clamp(px / width, 0.0, 1.0), 4),
                            "y": round(_clamp(py / height, 0.0, 1.0), 4),
                            "w": tw,
                            "h": th,
                            "area": tw * th,
                            "box": (x0 + max_loc[0], y0 + max_loc[1], x0 + max_loc[0] + tw, y0 + max_loc[1] + th),
                            "source": "template",
                            "score": round(float(max_val), 4),
                        }
                    )
            return candidates
        except Exception:  # noqa: BLE001
            return []

    def _capture_template(self, gray: np.ndarray, candidate: dict) -> None:
        box = candidate.get("box")
        if not isinstance(box, tuple) or len(box) != 4:
            return
        x0, y0, x1, y1 = box
        pad_x = max(2, (x1 - x0) // 6)
        pad_y = max(2, (y1 - y0) // 6)
        patch = _crop_gray(gray, (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y))
        if patch is None:
            return
        for template in self.templates:
            if abs(template.width - patch.shape[1]) <= 2 and abs(template.height - patch.shape[0]) <= 2:
                template.hits += 1
                return
        self.templates.append(PlayerTemplate(gray=patch, width=patch.shape[1], height=patch.shape[0]))
        if len(self.templates) > self.config.max_templates:
            self.templates.pop(0)

    # ── public API ──────────────────────────────────────────────────────
    def bootstrap(self, frame: np.ndarray, anchor: tuple[float, float] | None = None) -> dict | None:
        gray = self._gray(frame)
        if gray is None:
            return None
        candidates = self._colour_candidates(frame)
        if not candidates:
            return None
        target = anchor or self.last or (0.5, 0.7)
        candidates.sort(key=lambda item: (math.hypot(item["x"] - target[0], item["y"] - target[1]), -item["area"]))
        chosen = candidates[0]
        self.last = (chosen["x"], chosen["y"])
        self.velocity = (0.0, 0.0)
        self.missing = 0
        self.last_seen_at = time.monotonic()
        self.last_source = "bootstrap"
        self.last_score = float(chosen["score"])
        self._capture_template(gray, chosen)
        return self._result(chosen, chosen["x"], chosen["y"], stale=False)

    def update(
        self,
        frame: np.ndarray,
        *,
        action_state: dict | None = None,
        now: float | None = None,
        dt: float = 1.0 / 30.0,
    ) -> dict | None:
        del action_state  # reserved for a future action model; prediction uses velocity
        gray = self._gray(frame)
        if gray is None:
            return None
        current = self.last
        if current is None:
            return self.bootstrap(frame)
        dt = max(1e-3, float(dt))
        predicted = (
            _clamp(current[0] + self.velocity[0] * dt, 0.0, 1.0),
            _clamp(current[1] + self.velocity[1] * dt, 0.0, 1.0),
        )
        candidates = self._template_candidates(gray, predicted, self.config.search_radius)
        if not candidates:
            candidates = self._colour_candidates(frame)
        chosen = self._choose(candidates, predicted, self.config.template_accept)
        if chosen is None and self.missing >= self.config.max_missing_before_full - 1:
            full_radius = 1.0 if self.missing >= self.config.max_missing_before_full else 0.55
            center = (0.5, 0.5) if full_radius >= 1.0 else predicted
            full = self._template_candidates(gray, center, full_radius, multi_scale=True)
            if not full:
                full = self._colour_candidates(frame)
            chosen = self._choose(full, predicted, self.config.reacquire_accept)
            if chosen is not None:
                chosen["source"] = "reacquire"
        if chosen is None:
            self.missing += 1
            self.last_source = "lost"
            self.last_score = 0.0
            return self._result({}, current[0], current[1], stale=True)
        self._accept(chosen, dt, predicted)
        self._capture_template(gray, chosen)
        return self._result(chosen, chosen["x"], chosen["y"], stale=False)

    def _choose(self, candidates: list[dict], predicted: tuple[float, float], threshold: float) -> dict | None:
        best = None
        best_score = -1.0
        for candidate in candidates:
            distance = math.hypot(candidate["x"] - predicted[0], candidate["y"] - predicted[1])
            score = float(candidate.get("score") or 0.0)
            score += max(0.0, 0.25 - distance) * 0.5
            if candidate.get("source") == "template":
                score += 0.15
            if score > best_score and (
                float(candidate.get("score") or 0.0) >= threshold or distance <= 0.12
            ):
                best = candidate
                best_score = score
        return best

    def _accept(self, candidate: dict, dt: float, predicted: tuple[float, float]) -> None:
        previous = self.last or (candidate["x"], candidate["y"])
        vx = (candidate["x"] - previous[0]) / dt
        vy = (candidate["y"] - previous[1]) / dt
        self.velocity = (0.6 * self.velocity[0] + 0.4 * vx, 0.6 * self.velocity[1] + 0.4 * vy)
        self.last = (candidate["x"], candidate["y"])
        self.missing = 0
        self.last_seen_at = time.monotonic()
        self.last_source = str(candidate.get("source") or "unknown")
        self.last_score = float(candidate.get("score") or 0.0)
        self._candidate = predicted

    def _result(self, candidate: dict, x: float, y: float, *, stale: bool) -> dict:
        return {
            "x": round(float(x), 4),
            "y": round(float(y), 4),
            "score": round(float(candidate.get("score") or self.last_score or 0.0), 4),
            "source": self.last_source if stale is False else "stale",
            "stale": bool(stale),
            "missing": int(self.missing),
            "templates": len(self.templates),
            "age_ms": round(max(0.0, time.monotonic() - self.last_seen_at) * 1000.0) if self.last_seen_at else None,
        }
