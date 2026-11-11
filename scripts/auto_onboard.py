"""Automatic T1 onboarding for a local game window (no game-specific code).

Workflow:
1. attach + activate the window;
2. OCR the menu and probe candidate keys;
3. infer a confirm key, press it, verify gameplay left the menu;
4. probe direction keys in gameplay and record the first effective action;
5. write a schema-v1 pack marked ``origin=auto`` and a T1 checklist.

It never claims T1 when menu/confirm/gameplay/first-action evidence is missing.
Local only; no ROM/asset data is written into the repository.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from dsh_game_core.onboarding import auto_pack_draft, find_dismiss_target, infer_auto_controls, t1_checklist  # noqa: E402
from dsh_game_core.probe import MENU_WORDS, frame_change, menu_options, menu_transition  # noqa: E402
from dsh_game_core.session import GameSession  # noqa: E402
from dsh_game_core.windows import focus_window, foreground_window, window_rect  # noqa: E402

CONFIRM_KEYS = ("ENTER", "Z", "SPACE", "X", "A")
MOVE_KEYS = ("LEFT", "RIGHT", "UP", "DOWN", "W", "A", "S", "D")


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


def _activate(hwnd: int) -> bool:
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)
    except Exception:  # noqa: BLE001
        pass
    focus_window(hwnd)
    time.sleep(0.4)
    try:
        if int((foreground_window() or {}).get("hwnd") or 0) == int(hwnd):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        rect = window_rect(hwnd)
        if rect:
            left, top, right, bottom = rect
            user32.SetCursorPos((left + right) // 2, (top + bottom) // 2)
            time.sleep(0.1)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
    except Exception:  # noqa: BLE001
        pass
    focus_window(hwnd)
    time.sleep(0.3)
    try:
        return int((foreground_window() or {}).get("hwnd") or 0) == int(hwnd)
    except Exception:  # noqa: BLE001
        return False


def _texts(snapshot: dict) -> list[str]:
    return [str(line.get("text") or "") for line in (snapshot.get("ocr") or [])]


def _is_menu(texts: list[str]) -> bool:
    if menu_options(texts):
        return True
    for text in texts:
        if re.search(r"PRESS\s+(SPACE|ENTER|ANY)|TAP\s+TO\s+START|CLICK\s+TO\s+START", text, re.IGNORECASE):
            return True
    return False


def _is_pause(texts: list[str]) -> bool:
    joined = " ".join(texts).upper()
    return any(word in joined for word in ("PAUSED", "PAUSE", "暂停", "退出世界", "重新开始", "RESUME"))


def _has_score(texts: list[str]) -> bool:
    return any(re.search(r"\d{3,}", text) for text in texts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatic T1 onboarding (no game-specific code)")
    parser.add_argument("--window", required=True)
    parser.add_argument("--out", default=str(REPO / "tmp" / "auto-onboard.json"))
    parser.add_argument("--pack-out", default="")
    parser.add_argument("--keys", default=",".join(CONFIRM_KEYS))
    parser.add_argument("--tap-ms", type=int, default=120)
    parser.add_argument("--settle-ms", type=int, default=280)
    args = parser.parse_args()

    keys = [item.strip().upper() for item in args.keys.split(",") if item.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pack_path = Path(args.pack_out) if args.pack_out else out.with_suffix(".pack.json")

    started = time.monotonic()
    session = GameSession(control_backend="keyboard")
    attached = session.attach({"window": args.window})
    hwnd = int((attached.get("attached") or {}).get("hwnd") or 0)
    activated = _activate(hwnd)
    attached_info = attached.get("attached") or {}
    # Some browser/embedded games focus the canvas only after a click; a
    # window-level activate alone leaves keyboard input in the page chrome.
    try:
        if attached_info:
            session.act(
                {
                    "x": int(int(attached_info.get("left") or 0) + 0.5 * int(attached_info.get("width") or 0)),
                    "y": int(int(attached_info.get("top") or 0) + 0.35 * int(attached_info.get("height") or 0)),
                    "mouse_button": "LEFT",
                }
            )
            time.sleep(0.35)
    except Exception:  # noqa: BLE001
        pass

    initial = session.snapshot(ocr=True)
    dismissed: list[dict] = []
    attached_info = attached.get("attached") or {}
    for _ in range(2):
        target = find_dismiss_target(
            initial.get("ocr"),
            width=int(attached_info.get("width") or 0),
            height=int(attached_info.get("height") or 0),
        )
        if not target:
            break
        try:
            click_x = int(int(attached_info.get("left") or 0) + float(target["x"]) * int(attached_info.get("width") or 0))
            click_y = int(int(attached_info.get("top") or 0) + float(target["y"]) * int(attached_info.get("height") or 0))
            session.act({"x": click_x, "y": click_y, "mouse_button": "LEFT"})
            dismissed.append(target)
            time.sleep(max(300, args.settle_ms) / 1000.0)
            initial = session.snapshot(ocr=True)
        except Exception:  # noqa: BLE001
            break
    menu_texts = _texts(initial)
    menu_observed = _is_menu(menu_texts)
    entry_mode = "menu" if menu_observed else "direct"
    base_frame = _decode(initial)
    records: list[dict] = []
    for key in keys:
        before = session.snapshot(ocr=False)
        first = _decode(before)
        if first is None:
            first = base_frame
        try:
            session.act({"button": key, "duration_ms": max(40, min(500, args.tap_ms))})
        except Exception as error:  # noqa: BLE001
            records.append({"key": key, "error": str(error), "change": {"changed": False, "ratio": 0.0}})
            continue
        time.sleep(max(50, args.settle_ms) / 1000.0)
        after = session.snapshot(ocr=True)
        texts = _texts(after)
        change = frame_change(first, _decode(after))
        transition = menu_transition(menu_texts, texts)
        records.append(
            {
                "key": key,
                "change": change,
                "ocr_changed": bool(transition.get("changed")),
                "menu_transition": transition,
                "ocr_after": texts[:20],
            }
        )
        print(f"{key}: changed={change.get('changed')} ratio={change.get('ratio')} menu={transition.get('changed')}", flush=True)

    inferred = infer_auto_controls(records)
    confirm = (inferred["controls"].get("confirm") or [None])[0]
    gameplay_observed = False
    first_action = None
    confirm_frame = None
    if confirm:
        confirmed = session.snapshot(ocr=True)
        confirm_frame = _decode(confirmed)
        try:
            session.act({"button": confirm, "duration_ms": max(60, args.tap_ms)})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(max(500, args.settle_ms) / 1000.0)
        after_confirm = session.snapshot(ocr=True)
        after_texts = _texts(after_confirm)
        after_frame = _decode(after_confirm)
        no_menu = not _is_menu(after_texts)
        frame_moved = bool((frame_change(confirm_frame, after_frame) or {}).get("changed"))
        gameplay_observed = bool((_has_score(after_texts) or (no_menu and frame_moved)) and not _is_pause(after_texts))
        if gameplay_observed:
            for key in MOVE_KEYS:
                before = session.snapshot(ocr=False)
                try:
                    session.act({"button": key, "duration_ms": max(60, args.tap_ms)})
                except Exception:  # noqa: BLE001
                    continue
                time.sleep(max(80, args.settle_ms) / 2000.0)
                after = session.snapshot(ocr=True)
                after_texts = _texts(after)
                change = frame_change(_decode(before), _decode(after))
                transition = menu_transition(menu_texts, after_texts)
                records.append(
                    {
                        "key": key,
                        "change": change,
                        "ocr_changed": bool(transition.get("changed")),
                        "menu_transition": transition,
                        "ocr_after": after_texts[:20],
                        "gameplay": True,
                    }
                )
                if change.get("changed") and float(change.get("ratio") or 0.0) >= 0.003:
                    first_action = key
                    break
            if first_action is None and gameplay_observed and _has_score(after_texts):
                first_action = confirm
            inferred = infer_auto_controls(records)

    checklist = t1_checklist(
        menu_observed=menu_observed,
        confirm_key=confirm,
        gameplay_observed=gameplay_observed,
        first_action_key=first_action,
        entry_mode=entry_mode,
    )
    window = {
        "title": (attached.get("attached") or {}).get("window") or args.window,
        "process": (attached.get("attached") or {}).get("process"),
        "width": (attached.get("attached") or {}).get("width"),
        "height": (attached.get("attached") or {}).get("height"),
    }
    pack = auto_pack_draft(
        window,
        records,
        ocr_texts=menu_texts,
        menu_observed=menu_observed,
        gameplay_observed=gameplay_observed,
        entry_mode=entry_mode,
    )
    pack["evidence"] = [str(out)]
    pack["probe"]["t1"] = checklist
    pack["probe"]["activated"] = activated
    pack["probe"]["first_action"] = first_action
    pack["probe"]["after_confirm_ocr"] = after_texts[:20] if confirm else []
    pack["probe"]["dismissed_overlays"] = dismissed
    pack["probe"]["time_to_control_s"] = round(time.monotonic() - started, 3)
    report = {
        "window": window,
        "activated": activated,
        "menu_observed": menu_observed,
        "inferred": inferred,
        "checklist": checklist,
        "entry_mode": entry_mode,
        "first_action": first_action,
        "dismissed_overlays": dismissed,
        "time_to_control_s": pack["probe"]["time_to_control_s"],
        "pack_draft": str(pack_path),
        "t1_pass": checklist["pass"],
    }
    if checklist["pass"]:
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    session.stop()
    session.close()
    return 0 if checklist["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
