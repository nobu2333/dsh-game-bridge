"""End-to-end OCR-box -> normalized (rx, ry) -> window-scaled click pipeline test.

Uses real cv2 rendering + real RapidOCR + GameEngine + GameSession without
touching the user's desktop, cursor, or foreground window.
"""

from __future__ import annotations

import cv2
import numpy as np

from dsh_game_core.engine import GameEngine
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


class _StaticCapturer:
    def __init__(self, frame: np.ndarray):
        self.frame = frame

    def grab(self) -> np.ndarray:
        return self.frame

    def close(self) -> None:
        pass


def test_real_ocr_normalized_coords_map_accurately_to_scaled_window():
    # Render a 1920x1080 screen with a 1280x720 window at (200, 150).
    frame = np.full((1080, 1920, 3), 25, dtype=np.uint8)
    # Button box in window coordinates: x in [240..540], y in [420..520] -> screen (440..740, 570..670)
    cv2.rectangle(frame, (200 + 240, 150 + 420), (200 + 540, 150 + 520), (220, 220, 220), -1)
    cv2.putText(frame, "PLAY", (200 + 295, 150 + 488), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 4, cv2.LINE_AA)

    engine = GameEngine(capturer=_StaticCapturer(frame), max_width=640)
    # Attach to a window positioned at (200, 150) with size 1280x720.
    fg = {"hwnd": 999, "title": "Other", "process": "other.exe", "left": 0, "top": 0, "width": 1920, "height": 1080}
    focus_calls = []

    def focus():
        focus_calls.append(True)
        fg["hwnd"] = 42
        fg["title"] = "Puzzle"
        return True

    clicks = []

    class _FakeClickController:
        backend = "keyboard"

        def backend_info(self):
            return {"backend": "keyboard", "ready": True, "detail": "SendInput", "xinput_slot": None, "warnings": []}

        def click(self, x, y, button="LEFT"):
            clicks.append((x, y, button))
            return {"backend": "keyboard", "mouse_click": True, "x": x, "y": y, "button": button, "duration_ms": 0, "dry_run": False}

        def release_all(self):
            pass

    session = GameSession(
        engine=engine,
        gate=SafetyGate(process_source=lambda: [], takeover_source=lambda: False, process_ttl_s=0),
        control_backend="keyboard",
        window_resolver=lambda _: {"hwnd": 42, "title": "Puzzle", "process": "chrome.exe", "left": 200, "top": 150, "width": 1280, "height": 720},
        window_rect_source=lambda _: (200, 150, 1480, 870),
        window_monitor_source=lambda _: None,
        foreground_source=lambda: fg,
        occlusion_source=lambda _: {"available": True, "occluded_ratio": 0.0, "occluded": False, "covered_by": []},
        focus_source=focus,
        capture_mode="screen",
    )
    session._controller = _FakeClickController()

    attached = session.attach({"window": "Puzzle", "auto_focus": True})
    assert attached["auto_focus"] is True

    snap = session.snapshot(ocr=True, max_width=640)
    assert snap["width"] == 640
    assert snap["height"] == 360
    play_line = next((line for line in snap["ocr"] if "PLAY" in str(line.get("text", "")).upper()), None)
    assert play_line is not None, f"PLAY not found in OCR: {snap['ocr']}"

    rx = ((play_line["left"] + play_line["right"]) / 2.0) / snap["width"]
    ry = ((play_line["top"] + play_line["bottom"]) / 2.0) / snap["height"]
    acted = session.act({"rx": rx, "ry": ry, "mouse_button": "LEFT"})

    assert focus_calls == [True]
    assert len(clicks) == 1
    clicked_x, clicked_y, btn = clicks[0]
    assert btn == "LEFT"
    # Window left=200, top=150; button box in window is x=[240..540], y=[420..520]
    assert 200 + 240 <= clicked_x <= 200 + 540, f"x={clicked_x} missed button"
    assert 150 + 420 <= clicked_y <= 150 + 520, f"y={clicked_y} missed button"
    assert acted["attach_actions"] == 1
    assert session.status()["attach_actions"] == 1
