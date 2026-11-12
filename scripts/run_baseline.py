"""Run the non-model baseline arms from docs/PLAY.md against a local game window.

Two arms: ``random`` (seeded uniform keys) and ``cycle`` (fixed key order). Each
run records steps, wall time, final score/best and the end reason in the run-log
shape used by the play protocol. This is the comparison group for the M5 model
runs, so it deliberately uses the same engine path (`game_act` equivalent:
``GameSession.act``) and the same stop rules.

Two ways to use it:

  # Play against a window that is already open (human started the game)
  python scripts/run_baseline.py --window 2048 --mode random --runs 5

  # Let the script launch a fresh browser window per run (2048-style static games)
  python scripts/run_baseline.py --window 2048 --mode cycle --runs 5 \
      --url http://127.0.0.1:6218/ --build "gabrielecirulli/2048@master" \
      --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"

A fresh browser profile per run is used with ``--url`` so a game that persists
state in localStorage starts from scratch; the window is closed after the run.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from dsh_game_core.baseline import (  # noqa: E402
    make_policy,
    make_run_id,
    parse_labeled_numbers,
    find_phrase,
    summarize_records,
    write_jsonl,
    RunRecord,
)
from dsh_game_core.session import GameSession  # noqa: E402
from dsh_game_core.windows import force_foreground, foreground_window  # noqa: E402

DEFAULT_BROWSER = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _launch_browser(browser: str, url: str, profile_dir: Path, size: str) -> subprocess.Popen:
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        browser,
        f"--app={url}",
        f"--window-size={size}",
        "--window-position=80,80",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _close_browser(process: subprocess.Popen) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except Exception:  # noqa: BLE001 - cleanup must never fail the run
        pass


def _hwnds_for_process(process_id: int, title: str) -> list[int]:
    """Visible windows owned by ``process_id`` whose title contains ``title``."""

    from dsh_game_core.windows import list_windows

    user32 = ctypes.windll.user32
    found: list[int] = []
    for window in list_windows():
        if title.lower() not in str(window.get("title") or "").lower():
            continue
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(int(window["hwnd"]), ctypes.byref(owner))
        if int(owner.value) == int(process_id):
            found.append(int(window["hwnd"]))
    return found


def _wait_for_window(
    session: GameSession,
    title: str,
    timeout_s: float,
    process_id: int | None = None,
) -> dict | None:
    """Attach to the target window.

    With ``process_id`` the handle is pinned to that browser process, so a
    leftover window with the same title (an older game session) is never
    picked by mistake.
    """

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if process_id:
                handles = _hwnds_for_process(process_id, title)
                if handles:
                    return session.attach({"hwnd": handles[0]})
            else:
                return session.attach({"window": title})
        except Exception:  # noqa: BLE001 - keep polling until the timeout
            pass
        time.sleep(0.5)
    return None


def _ocr_text(lines) -> list[str]:
    return [str(line.get("text") or "") for line in (lines or [])]


def play_one(
    *,
    session: GameSession,
    policy,
    max_steps: int,
    step_interval_ms: int,
    labels: list[str],
    end_phrases: list[str],
    stale_limit: int,
    ocr_every: int,
    run_id: str,
    game: str,
    build: str,
    seed: int | None,
) -> RunRecord:
    started = time.monotonic()
    steps = 0
    errors = 0
    end_reason = "step_limit"
    score: int | None = None
    best: int | None = None
    last_signature = None
    stale = 0
    hwnd = int((session.status().get("attached") or {}).get("hwnd") or 0)

    for step in range(max_steps):
        # OCR costs 1-5 s on a full window, so it runs every few steps; the
        # per-step capture is cheap and only proves the engine is still alive.
        want_ocr = step == 0 or (ocr_every > 0 and step % ocr_every == 0)
        try:
            snap = session.snapshot(ocr=want_ocr)
        except Exception as error:  # noqa: BLE001 - count and continue
            errors += 1
            print(f"  snapshot error: {type(error).__name__}: {error}", flush=True)
            time.sleep(0.2)
            continue
        if want_ocr:
            lines = snap.get("ocr") or []
            numbers = parse_labeled_numbers(lines, labels)
            for label, value in numbers.items():
                if labels and label == labels[0].upper():
                    score = value
                elif len(labels) > 1 and label == labels[1].upper():
                    best = value
            phrase = find_phrase(lines, end_phrases)
            if phrase:
                end_reason = f"phrase:{phrase}"
                break
            signature = tuple(_ocr_text(lines))
            if signature == last_signature:
                stale += 1
                if stale >= stale_limit:
                    end_reason = "static"
                    break
            else:
                stale = 0
                last_signature = signature

        key = policy.choose()
        if hwnd:
            fg = foreground_window() or {}
            if int(fg.get("hwnd") or 0) != hwnd:
                force_foreground(hwnd)
        try:
            session.act({"button": key, "duration_ms": 60})
            steps += 1
        except Exception as error:  # noqa: BLE001
            errors += 1
            print(f"  act error: {type(error).__name__}: {error}", flush=True)
        time.sleep(max(0.0, step_interval_ms / 1000.0))

    # Read the final score three times and take the median: OCR on animating
    # digits is the one place a single frame can be wrong, and this value is
    # what gets compared against the model runs.
    final_scores: list[int] = []
    final_bests: list[int] = []
    for attempt in range(3):
        try:
            snap = session.snapshot(ocr=True)
            numbers = parse_labeled_numbers(snap.get("ocr") or [], labels)
            if labels and labels[0].upper() in numbers:
                final_scores.append(numbers[labels[0].upper()])
            if len(labels) > 1 and labels[1].upper() in numbers:
                final_bests.append(numbers[labels[1].upper()])
        except Exception:  # noqa: BLE001
            errors += 1
        if attempt < 2:
            time.sleep(0.4)
    if final_scores:
        score = int(statistics.median(final_scores))
    if final_bests:
        best = int(statistics.median(final_bests))

    return RunRecord(
        run_id=run_id,
        date=time.strftime("%Y-%m-%d", time.localtime()),
        player=policy.mode,
        game=game,
        build=build,
        steps=steps,
        wall_s=round(time.monotonic() - started, 2),
        score=score,
        best=best,
        end_reason=end_reason,
        errors=errors,
        seed=seed,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run random/cycle baselines for M5")
    parser.add_argument("--window", required=True, help="window title substring (case-insensitive)")
    parser.add_argument("--mode", default="random", choices=["random", "cycle"])
    parser.add_argument("--keys", default="UP,RIGHT,DOWN,LEFT")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument("--step-interval-ms", type=int, default=350)
    parser.add_argument("--stale-limit", type=int, default=10, help="end after N OCR checks with unchanged text")
    parser.add_argument("--ocr-every", type=int, default=10, help="OCR every N steps (0 = only at start/end)")
    parser.add_argument("--labels", default="SCORE,BEST", help="OCR labels, primary score first")
    parser.add_argument("--end-phrases", default="game over,try again")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--game", default="")
    parser.add_argument("--build", default="")
    parser.add_argument("--url", default="", help="with --browser: launch a fresh browser window per run")
    parser.add_argument("--browser", default=DEFAULT_BROWSER)
    parser.add_argument("--window-size", default="760,900")
    parser.add_argument("--startup-s", type=float, default=25.0)
    parser.add_argument("--dry-run", action="store_true", help="record actions without injecting input")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args()

    keys = [key.strip().upper() for key in args.keys.split(",") if key.strip()]
    labels = [label.strip().upper() for label in args.labels.split(",") if label.strip()]
    end_phrases = [phrase.strip() for phrase in args.end_phrases.split(",") if phrase.strip()]
    game = args.game or Path(args.window).name
    out = Path(args.out) if args.out else REPO / "experiments" / "results" / "m5-baseline.jsonl"
    records: list[RunRecord] = []

    for index in range(1, max(1, args.runs) + 1):
        process = None
        profile_dir = None
        session = GameSession(control_backend="dry-run" if args.dry_run else "keyboard", capture_mode="window")
        try:
            if args.url:
                profile_dir = REPO / "tmp" / "m5-baseline" / f"profile-{args.mode}-{index}"
                if profile_dir.exists():
                    shutil.rmtree(profile_dir, ignore_errors=True)
                process = _launch_browser(args.browser, args.url, profile_dir, args.window_size)
                time.sleep(2.0)
            attached = _wait_for_window(
                session,
                args.window,
                args.startup_s,
                process_id=process.pid if process is not None else None,
            )
            if attached is None:
                print(f"run {index}: window {args.window!r} not found", flush=True)
                continue
            hwnd = int((attached.get("attached") or {}).get("hwnd") or 0)
            if hwnd:
                force_foreground(hwnd)
                time.sleep(0.5)
            policy = make_policy(args.mode, keys=keys, seed=args.seed + index - 1)
            run_id = make_run_id(f"{args.mode}", index)
            print(f"run {index}/{args.runs} ({args.mode}) started: {run_id}", flush=True)
            record = play_one(
                session=session,
                policy=policy,
                max_steps=args.max_steps,
                step_interval_ms=args.step_interval_ms,
                labels=labels,
                end_phrases=end_phrases,
                stale_limit=args.stale_limit,
                ocr_every=args.ocr_every,
                run_id=run_id,
                game=game,
                build=args.build,
                seed=args.seed + index - 1,
            )
            records.append(record)
            print(
                f"run {index}: steps={record.steps} wall={record.wall_s}s "
                f"score={record.score} best={record.best} end={record.end_reason} errors={record.errors}",
                flush=True,
            )
        finally:
            try:
                session.stop()
                session.close()
            except Exception:  # noqa: BLE001
                pass
            if process is not None:
                _close_browser(process)

    if records:
        write_jsonl(out, records)
    summary = summarize_records(records)
    if args.json:
        print(json.dumps({"out": str(out), "summary": summary}, ensure_ascii=False, indent=2))
    else:
        print(f"\nresults appended to {out}")
        median_score = (summary.get("score") or {}).get("median")
        if median_score is not None:
            print(f"score median={median_score} (n={(summary['score'] or {}).get('n')})")
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
