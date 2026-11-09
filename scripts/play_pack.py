"""Play a GamePack's data-only autoplay loop for a bounded duration.

This is the T2 harness: the pack supplies a key cycle and interval; the engine
supplies capture, foreground, safety, and action logging. No game names or
per-game branches live here.

  python scripts/play_pack.py --pack experiments/games/packs/web.dino.t1.json --duration 300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from dsh_game_core.autoplay import evaluate_session  # noqa: E402
from dsh_game_core.gamepack import load_pack  # noqa: E402
from dsh_game_core.session import GameSession  # noqa: E402
from dsh_game_core.windows import force_foreground, foreground_window, window_rect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Play a bounded autoplay loop from a GamePack")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--duration", type=float, default=300.0, help="seconds to play")
    parser.add_argument("--window", default="", help="override window title")
    parser.add_argument("--out", default="")
    parser.add_argument("--sample-s", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pack = load_pack(args.pack)
    autoplay = pack.get("autoplay") or {}
    keys = [str(key).upper() for key in (autoplay.get("keys") or []) if str(key).strip()]
    if not keys:
        raise SystemExit("pack.autoplay.keys is required")
    interval_ms = max(40, int(autoplay.get("interval_ms") or 800))
    restart = dict(autoplay.get("restart") or {})
    restart_every = max(0.0, float(restart.get("every_s") or 0.0))
    restart_click = restart.get("click")
    restart_next = restart_every if restart_every > 0 else 0.0
    restarts = 0
    stop_phrases = [str(item) for item in (autoplay.get("stop_phrases") or [])]
    out = Path(args.out) if args.out else REPO / "tmp" / f"{pack['id']}.play.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    session = GameSession(
        control_backend="dry-run" if args.dry_run else "keyboard",
        capture_mode="window",
    )
    attached = session.attach({"pack": pack, "window": args.window or pack.get("title") or "unspecified"})
    hwnd = int((attached.get("attached") or {}).get("hwnd") or 0)
    if hwnd and not args.dry_run:
        force_foreground(hwnd)

    started = time.monotonic()
    last_sample = 0.0
    samples: list[dict] = []
    actions = 0
    errors: list[str] = []
    index = 0
    try:
        while time.monotonic() - started < args.duration:
            now = time.monotonic()
            if now - last_sample >= max(1.0, args.sample_s):
                last_sample = now
                try:
                    snap = session.snapshot(ocr=True)
                    samples.append(
                        {
                            "t": round(now - started, 2),
                            "ocr": [str(line.get("text") or "") for line in (snap.get("ocr") or [])][:30],
                            "size": [snap.get("width"), snap.get("height")],
                        }
                    )
                except Exception as error:  # noqa: BLE001
                    errors.append(f"sample: {type(error).__name__}: {error}")
            if (
                restart_every > 0
                and now - started >= restart_next
                and isinstance(restart_click, (list, tuple))
                and len(restart_click) >= 2
            ):
                restart_next += restart_every
                if hwnd and not args.dry_run:
                    try:
                        rect = window_rect(hwnd)
                        if rect:
                            left, top, right, bottom = rect
                            x = left + int(float(restart_click[0]) * (right - left))
                            y = top + int(float(restart_click[1]) * (bottom - top))
                            force_foreground(hwnd)
                            session.act({"x": x, "y": y, "mouse_button": "LEFT"})
                            restarts += 1
                    except Exception as error:  # noqa: BLE001
                        errors.append(f"restart: {type(error).__name__}: {error}")
            key = keys[index % len(keys)]
            index += 1
            if hwnd and not args.dry_run:
                fg = foreground_window() or {}
                if int(fg.get("hwnd") or 0) != hwnd:
                    force_foreground(hwnd)
            try:
                session.act({"button": key, "duration_ms": 60})
                actions += 1
            except Exception as error:  # noqa: BLE001 - record and continue a bounded run
                errors.append(f"act {key}: {type(error).__name__}: {error}")
                time.sleep(0.1)
            time.sleep(interval_ms / 1000.0)
    finally:
        try:
            final = session.snapshot(ocr=True)
            samples.append(
                {
                    "t": round(time.monotonic() - started, 2),
                    "ocr": [str(line.get("text") or "") for line in (final.get("ocr") or [])][:30],
                    "size": [final.get("width"), final.get("height")],
                }
            )
        except Exception:
            pass
        session.stop()
        session.close()

    elapsed = round(time.monotonic() - started, 2)
    validity = evaluate_session(
        requested_s=args.duration,
        elapsed_s=elapsed,
        samples=samples,
        stop_phrases=stop_phrases,
    )
    report = {
        "pack": pack["id"],
        "title": pack.get("title"),
        "duration_s": elapsed,
        "actions": actions,
        "restarts": restarts,
        "valid": validity["valid"],
        "invalid_reason": None if validity["valid"] else validity["reason"],
        "hz": round(actions / elapsed, 2) if elapsed else 0.0,
        "keys": keys,
        "interval_ms": interval_ms,
        "samples": samples,
        "errors": errors[:20],
        "clear": False,
        "evidence": str(out),
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PLAY_DONE {out} actions={actions} duration={elapsed}s errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
