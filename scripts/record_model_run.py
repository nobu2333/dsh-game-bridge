"""Record one model run from the still-open game window (docs/PLAY.md §8).

The model plays through a real DSH session; this script only reads the final
score from the same window with the same OCR parser the baselines use, so the
model arm and the control arms are scored the same way.

  python scripts/record_model_run.py --window 2048 --player model:deepseek \
      --game 2048 --build "gabrielecirulli/2048@master" \
      --steps 87 --wall-s 640 --end-reason "phrase:game over"
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from dsh_game_core.baseline import (  # noqa: E402
    RunRecord,
    make_run_id,
    parse_labeled_numbers,
    write_jsonl,
)
from dsh_game_core.session import GameSession  # noqa: E402


def read_scores(window: str, labels: list[str], reads: int) -> tuple[int | None, int | None, list[str]]:
    session = GameSession(control_backend="dry-run", capture_mode="window")
    scores: list[int] = []
    bests: list[int] = []
    texts: list[str] = []
    try:
        session.attach({"window": window})
        for attempt in range(max(1, reads)):
            snap = session.snapshot(ocr=True)
            numbers = parse_labeled_numbers(snap.get("ocr") or [], labels)
            texts = [str(line.get("text") or "") for line in (snap.get("ocr") or [])][:20]
            if labels and labels[0].upper() in numbers:
                scores.append(numbers[labels[0].upper()])
            if len(labels) > 1 and labels[1].upper() in numbers:
                bests.append(numbers[labels[1].upper()])
            if attempt < reads - 1:
                time.sleep(0.5)
    finally:
        session.stop()
        session.close()
    score = int(statistics.median(scores)) if scores else None
    best = int(statistics.median(bests)) if bests else None
    return score, best, texts


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a model run's final score from OCR")
    parser.add_argument("--window", required=True)
    parser.add_argument("--player", default="model")
    parser.add_argument("--game", default="")
    parser.add_argument("--build", default="")
    parser.add_argument("--steps", type=int, default=0)
    parser.add_argument("--wall-s", type=float, default=0.0)
    parser.add_argument("--end-reason", default="")
    parser.add_argument("--errors", type=int, default=0)
    parser.add_argument("--labels", default="SCORE,BEST")
    parser.add_argument("--reads", type=int, default=3)
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true", help="read the score only (sanity check)")
    args = parser.parse_args()

    labels = [label.strip().upper() for label in args.labels.split(",") if label.strip()]
    score, best, texts = read_scores(args.window, labels, args.reads)
    record = RunRecord(
        run_id=make_run_id("model", 1),
        date=time.strftime("%Y-%m-%d", time.localtime()),
        player=args.player,
        game=args.game or args.window,
        build=args.build,
        steps=int(args.steps),
        wall_s=float(args.wall_s),
        score=score,
        best=best,
        end_reason=args.end_reason,
        errors=int(args.errors),
    )
    out = Path(args.out) if args.out else REPO / "experiments" / "results" / "m5-model.jsonl"
    if not args.no_write:
        write_jsonl(out, [record])
    payload = {"out": None if args.no_write else str(out), "record": record.as_dict(), "ocr_head": texts}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        target = "not written" if args.no_write else str(out)
        print(f"recorded {record.run_id}: score={score} best={best} -> {target}")
        print("OCR head: " + " | ".join(texts[:8]))
    return 0 if score is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())
