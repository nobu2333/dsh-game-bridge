"""Probe a game window without game-specific code and emit a GamePack draft.

Local only. Usage (PowerShell):
  engine\\.venv\\Scripts\\python.exe scripts\\probe_game.py --window "Block Blast" --out tmp/blockblast.pack.json

It taps a list of keys, measures normalized frame changes, records OCR text,
and writes a reviewable schema-v1 pack draft. It never runs a policy and never
guesses semantic controls; menu/keymap inference is a separate step.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from dsh_game_core.probe import frame_change, pack_draft  # noqa: E402
from dsh_game_core.session import GameSession  # noqa: E402
from dsh_game_core.windows import focus_window, foreground_window, window_rect  # noqa: E402


def _decode(snapshot: dict) -> np.ndarray | None:
    encoded = snapshot.get("png_b64")
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        raw = base64.b64decode(encoded)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        return image if isinstance(image, np.ndarray) else None
    except Exception:  # noqa: BLE001
        return None


def _activate(hwnd: int) -> None:
    """Focus a real window; click only if focus did not take (some windows are
    foreground-visible but the compositor routes the click elsewhere)."""
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)
    except Exception:  # noqa: BLE001
        pass
    focus_window(hwnd)
    time.sleep(0.5)
    try:
        if int((foreground_window() or {}).get("hwnd") or 0) == int(hwnd):
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        rect = window_rect(hwnd)
        if rect:
            left, top, right, bottom = rect
            user32.SetCursorPos((left + right) // 2, (top + bottom) // 2)
            time.sleep(0.15)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
    except Exception:  # noqa: BLE001
        pass
    focus_window(hwnd)
    time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a game window and emit a GamePack draft")
    parser.add_argument("--window", required=True, help="attached window title/identifier")
    parser.add_argument("--keys", default="UP,DOWN,LEFT,RIGHT,ENTER,ESC")
    parser.add_argument("--out", default="")
    parser.add_argument("--game-id", default="")
    parser.add_argument("--tap-ms", type=int, default=120)
    parser.add_argument("--settle-ms", type=int, default=250)
    parser.add_argument("--dry-run", action="store_true", help="record actions only; no real input")
    parser.add_argument("--window-capture", action="store_true", help="use PrintWindow instead of full-screen crop")
    args = parser.parse_args()

    keys = [item.strip().upper() for item in args.keys.split(",") if item.strip()]
    out = Path(args.out) if args.out else REPO / "tmp" / "probe-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    session = GameSession(
        control_backend="dry-run" if args.dry_run else "keyboard",
        capture_mode="window" if args.window_capture else None,
    )
    attached = session.attach({"window": args.window})
    hwnd = (attached.get("attached") or {}).get("hwnd")
    if not args.dry_run:
        _activate(int(hwnd or 0))
    initial = session.snapshot(ocr=True)
    ocr_texts = [str(line.get("text") or "") for line in (initial.get("ocr") or [])]
    before_frame = _decode(initial)
    records: list[dict] = []

    for key in keys:
        before = session.snapshot(ocr=False)
        first = _decode(before)
        error = None
        try:
            session.act({"button": key, "duration_ms": max(40, min(500, args.tap_ms))})
        except Exception as exc:  # noqa: BLE001 - report per-key failure, keep probing
            error = str(exc)
        time.sleep(max(50, args.settle_ms) / 1000.0)
        after = session.snapshot(ocr=False)
        second = _decode(after)
        change = frame_change(first if first is not None else before_frame, second)
        record = {"key": key, "change": change}
        if error:
            record["error"] = error
        records.append(record)
        print(f"{key}: changed={change.get('changed')} ratio={change.get('ratio')} center={change.get('center')}", flush=True)

    window = {
        "title": (attached.get("attached") or {}).get("window") or args.window,
        "process": (attached.get("attached") or {}).get("process"),
        "width": (attached.get("attached") or {}).get("width"),
        "height": (attached.get("attached") or {}).get("height"),
    }
    pack = pack_draft(window, records, ocr_texts=ocr_texts, game_id=args.game_id or None)
    pack["evidence"] = [str(out)]
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PACK_DRAFT {out}")
    session.stop()
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
