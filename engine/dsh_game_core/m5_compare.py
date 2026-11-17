"""M5 comparison: model vs random/cycle baselines (2048 protocol).

Pure data reduction; no screen, input, or game calls. The rule is from
docs/PLAY.md §9: the model median must beat both control medians, and the
model's worst run must be at least half of the control median. A single pilot
is never enough, even if its score looks high.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping

MODEL_MIN_RUNS = 3
CONTROL_MIN_RUNS = 5


def _rows(data: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [dict(row) for row in data if isinstance(row, Mapping)]


def _scores(rows: list[dict]) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row.get("score")))
        except (TypeError, ValueError):
            continue
    return values


def _summary(rows: list[dict]) -> dict:
    scores = _scores(rows)
    if not scores:
        return {"n": 0, "median": None, "min": None, "max": None, "scores": []}
    return {
        "n": len(scores),
        "median": statistics.median(scores),
        "min": min(scores),
        "max": max(scores),
        "scores": scores,
    }


def summarize_m5(
    model_rows: Iterable[Mapping[str, Any]],
    baseline_rows: Iterable[Mapping[str, Any]],
) -> dict:
    """Compare M5 model runs with random/cycle baselines.

    Returns a machine-readable verdict. ``insufficient_model_runs`` is the
    honest result for a single pilot; it is not a failure of the model.
    """
    model = _rows(model_rows)
    baseline = _rows(baseline_rows)
    model = [row for row in model if str(row.get("player") or "").startswith("model:")]
    random_rows = [row for row in baseline if str(row.get("player") or "").lower() == "random"]
    cycle_rows = [row for row in baseline if str(row.get("player") or "").lower() == "cycle"]
    model_summary = _summary(model)
    random_summary = _summary(random_rows)
    cycle_summary = _summary(cycle_rows)
    controls = [item for item in (random_summary, cycle_summary) if item["n"]]
    control_medians = [float(item["median"]) for item in controls if item["median"] is not None]
    criteria = {
        "model_runs": model_summary["n"] >= MODEL_MIN_RUNS,
        "random_runs": random_summary["n"] >= CONTROL_MIN_RUNS,
        "cycle_runs": cycle_summary["n"] >= CONTROL_MIN_RUNS,
        "model_beats_random": bool(
            model_summary["median"] is not None
            and random_summary["median"] is not None
            and model_summary["median"] > random_summary["median"]
        ),
        "model_beats_cycle": bool(
            model_summary["median"] is not None
            and cycle_summary["median"] is not None
            and model_summary["median"] > cycle_summary["median"]
        ),
        "worst_not_below_half": bool(
            model_summary["min"] is not None
            and control_medians
            and model_summary["min"] >= 0.5 * max(control_medians)
        ),
    }
    if not criteria["model_runs"]:
        status = "insufficient_model_runs"
    elif not criteria["random_runs"] or not criteria["cycle_runs"]:
        status = "insufficient_control_runs"
    elif all(criteria.values()):
        status = "m5_pass"
    else:
        status = "m5_fail"
    return {
        "status": status,
        "criteria": criteria,
        "model": model_summary,
        "random": random_summary,
        "cycle": cycle_summary,
        "rule": "model median > random median and > cycle median; model min >= 0.5 * max(control medians); >=3 model and >=5 each control",
    }


def load_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare M5 model runs with baseline runs.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    result = summarize_m5(load_jsonl(args.model), load_jsonl(args.baseline))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] in ("m5_pass", "m5_fail") else 2


if __name__ == "__main__":
    raise SystemExit(main())
