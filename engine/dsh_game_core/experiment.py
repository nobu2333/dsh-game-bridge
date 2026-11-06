"""A/B 实验统计：把“某机制是否有持续收益”变成可复现的判定。

原则：
- 单局高值不算收益；
- 小样本用 bootstrap CI；
- 有主指标、最小效应、最差局 guardrail；
- 结论只有 promote / no_gain / regression / insufficient。
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class RunMetrics:
    run_id: str = ""
    peak_screens: float = 0.0
    duration_s: float = 0.0
    damage_taken: int = 0
    deaths: int = 1
    clear: bool = False
    hz: float | None = None
    player_stale_ratio: float | None = None
    threat_active_ratio: float | None = None
    option_counts: dict = field(default_factory=dict)
    mechanism_counts: dict = field(default_factory=dict)
    damage_events: list = field(default_factory=list)
    death_causes: dict = field(default_factory=dict)
    git_sha: str = ""
    profile_hash: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict) -> "RunMetrics":
        data = dict(payload or {})
        known = {name for name in cls.__dataclass_fields__}
        extra = {key: value for key, value in data.items() if key not in known}
        clean = {key: value for key, value in data.items() if key in known}
        metrics = cls(**clean)
        metrics.extra.update(extra)
        return metrics

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentSpec:
    name: str
    mechanism: str
    baseline_label: str = "baseline"
    candidate_label: str = "candidate"
    primary_metric: str = "peak_screens"
    min_runs: int = 10
    min_effect: float = 0.5
    min_ci_low: float = 0.0
    guardrail_drop: float = 1.0
    alpha: float = 0.05

    def to_dict(self) -> dict:
        return asdict(self)


def _values(runs: Iterable[RunMetrics], metric: str) -> list[float]:
    result = []
    for run in runs:
        value = getattr(run, metric, None)
        if value is None:
            continue
        result.append(float(value))
    return result


def summarize(runs: Iterable[RunMetrics], metric: str = "peak_screens") -> dict:
    runs_list = list(runs)
    values = _values(runs_list, metric)
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "max": None,
            "clear_rate": None,
            "mean_player_stale_ratio": None,
            "mean_threat_active_ratio": None,
            "mean_damage_taken": None,
            "death_causes": {},
        }
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.1 * (len(ordered) - 1)))))
    clear_rate = sum(1 for run in runs_list if run.clear) / max(1, len(runs_list))
    stale_vals = [float(run.player_stale_ratio) for run in runs_list if run.player_stale_ratio is not None]
    threat_vals = [float(run.threat_active_ratio) for run in runs_list if run.threat_active_ratio is not None]
    damage_vals = [float(run.damage_taken) for run in runs_list if run.damage_taken is not None]
    causes: dict[str, int] = {}
    for run in runs_list:
        for cause, count in (run.death_causes or {}).items():
            causes[str(cause)] = causes.get(str(cause), 0) + int(count or 0)
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p10": round(ordered[index], 4),
        "max": round(max(values), 4),
        "clear_rate": round(clear_rate, 4),
        "mean_player_stale_ratio": round(statistics.fmean(stale_vals), 4) if stale_vals else None,
        "mean_threat_active_ratio": round(statistics.fmean(threat_vals), 4) if threat_vals else None,
        "mean_damage_taken": round(statistics.fmean(damage_vals), 2) if damage_vals else None,
        "death_causes": causes,
    }


def bootstrap_median_diff(
    baseline: Iterable[float],
    candidate: Iterable[float],
    *,
    samples: int = 2000,
    seed: int = 0,
) -> dict:
    base = [float(value) for value in baseline]
    cand = [float(value) for value in candidate]
    if not base or not cand:
        return {"observed": None, "ci_low": None, "ci_high": None, "samples": 0}
    rng = random.Random(seed)
    observed = statistics.median(cand) - statistics.median(base)
    diffs = []
    for _ in range(max(100, int(samples))):
        b = [base[rng.randrange(len(base))] for _ in base]
        c = [cand[rng.randrange(len(cand))] for _ in cand]
        diffs.append(statistics.median(c) - statistics.median(b))
    diffs.sort()
    low_index = int(0.025 * (len(diffs) - 1))
    high_index = int(0.975 * (len(diffs) - 1))
    return {
        "observed": round(observed, 4),
        "ci_low": round(diffs[low_index], 4),
        "ci_high": round(diffs[high_index], 4),
        "samples": len(diffs),
    }


def evaluate_experiment(
    spec: ExperimentSpec,
    baseline: list[RunMetrics],
    candidate: list[RunMetrics],
) -> dict:
    base_summary = summarize(baseline, spec.primary_metric)
    cand_summary = summarize(candidate, spec.primary_metric)
    result = {
        "name": spec.name,
        "mechanism": spec.mechanism,
        "primary_metric": spec.primary_metric,
        "baseline": base_summary,
        "candidate": cand_summary,
        "decision": "insufficient",
        "reason": "",
        "diff": None,
    }
    if base_summary["n"] < spec.min_runs or cand_summary["n"] < spec.min_runs:
        result["reason"] = f"need >= {spec.min_runs} runs per arm"
        return result
    base_values = _values(baseline, spec.primary_metric)
    cand_values = _values(candidate, spec.primary_metric)
    diff = bootstrap_median_diff(base_values, cand_values, seed=0)
    result["diff"] = diff
    median_diff = diff["observed"]
    if median_diff is None:
        result["reason"] = "no metric values"
        return result
    if median_diff < 0 and abs(median_diff) > spec.guardrail_drop:
        result["decision"] = "regression"
        result["reason"] = f"median dropped {median_diff} beyond guardrail {spec.guardrail_drop}"
        return result
    if diff["ci_low"] is not None and diff["ci_low"] < spec.min_ci_low:
        result["decision"] = "no_gain"
        result["reason"] = f"95% CI low {diff['ci_low']} <= {spec.min_ci_low}"
        return result
    if median_diff < spec.min_effect:
        result["decision"] = "no_gain"
        result["reason"] = f"median diff {median_diff} < min effect {spec.min_effect}"
        return result
    result["decision"] = "promote"
    result["reason"] = f"median +{median_diff} with CI low {diff['ci_low']}"
    return result


def load_runs(path: str | Path) -> list[RunMetrics]:
    target = Path(path)
    if not target.is_file():
        return []
    runs = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            runs.append(RunMetrics.from_dict(json.loads(line)))
        except Exception:  # noqa: BLE001
            continue
    return runs


def append_run(path: str | Path, run: RunMetrics) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run.to_dict(), ensure_ascii=False) + "\n")
