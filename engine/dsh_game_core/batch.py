"""P4 实机跑批器（注入式）：不绑定具体 driver，便于先离线测试。

职责：
- 跑 N 局，直到 death/超时；
- 把每局 status 转成 RunMetrics 写 JSONL；
- 每局做 mechanism audit；
- 返回批次摘要 + 审计失败列表。

真实使用时由调用方注入 start/stop/status/reset/sleep。游戏/驱动不进入引擎。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .experiment import RunMetrics, append_run, summarize
from .experiment_cli import metrics_from_status, render_postmortem_report
from .mechanism_audit import audit_mechanisms, expectations_from_profile


@dataclass
class BatchConfig:
    runs: int = 10
    max_run_seconds: float = 90.0
    poll_seconds: float = 1.0
    reset_seconds: float = 6.0
    run_id_prefix: str = "run"
    metric: str = "peak_screens"


@dataclass
class BatchResult:
    runs: list[RunMetrics] = field(default_factory=list)
    audit_failures: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    out_path: str = ""
    trace_dir: str = ""
    report_path: str = ""

    def to_dict(self) -> dict:
        return {
            "runs": [run.to_dict() for run in self.runs],
            "audit_failures": self.audit_failures,
            "summary": self.summary,
            "out_path": self.out_path,
            "trace_dir": self.trace_dir,
            "report_path": self.report_path,
        }


def apply_canary(profile: dict | None, canary: str | None) -> dict:
    """Return a copy of profile with options.execute/canary set for one arm."""
    result = dict(profile or {})
    options = dict(result.get("options") or {}) if isinstance(result.get("options"), dict) else {}
    options["execute"] = bool(canary)
    if canary:
        options["canary"] = str(canary)
    else:
        options.pop("canary", None)
    result["options"] = options
    return result


def _policy_payload(status: dict) -> dict:
    if not isinstance(status, dict):
        return {}
    if isinstance(status.get("policy"), dict):
        return status["policy"]
    if isinstance(status.get("status"), dict):
        return status["status"]
    return status


def is_death_status(status: dict) -> bool:
    return _policy_payload(status).get("scene") == "death"


def collect_batch(
    config: BatchConfig,
    *,
    start: Callable[[], Any],
    stop: Callable[[], Any],
    status: Callable[[], dict],
    reset: Callable[[], Any],
    sleep: Callable[[float], Any],
    out_path: str | Path,
    profile: dict | None = None,
    git_sha: str = "",
    trace_dir: str | Path | None = None,
    report_path: str | Path | None = None,
    baseline_runs: list[RunMetrics] | None = None,
    hypothesis: str = "",
) -> BatchResult:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_trace_dir = Path(trace_dir) if trace_dir is not None else (target.parent / "traces" / target.stem)
    resolved_trace_dir.mkdir(parents=True, exist_ok=True)
    result = BatchResult(
        out_path=str(target),
        trace_dir=str(resolved_trace_dir),
        report_path=str(report_path) if report_path else "",
    )
    expectations = expectations_from_profile(profile or {})
    for index in range(max(1, int(config.runs))):
        start()
        elapsed = 0.0
        snapshot: dict = {}
        trace_by_tick: dict[int, dict] = {}
        while elapsed < config.max_run_seconds:
            sleep(config.poll_seconds)
            elapsed += config.poll_seconds
            snapshot = status() or {}
            payload = _policy_payload(snapshot)
            for item in payload.get("trace_tail") or []:
                if isinstance(item, dict) and item.get("tick") is not None:
                    trace_by_tick[int(item["tick"])] = item
            if is_death_status(snapshot):
                break
        run_id = f"{config.run_id_prefix}-{index + 1:02d}"
        metrics = metrics_from_status(snapshot, run_id=run_id, git_sha=git_sha)
        result.runs.append(metrics)
        append_run(target, metrics)
        if trace_by_tick:
            trace_file = resolved_trace_dir / f"{run_id}.jsonl"
            ordered_ticks = sorted(trace_by_tick)
            with trace_file.open("w", encoding="utf-8") as handle:
                for tick in ordered_ticks:
                    handle.write(json.dumps(trace_by_tick[tick], ensure_ascii=False) + "\n")
        audit = audit_mechanisms(snapshot, expectations) if expectations else None
        if audit is not None and not audit.ok:
            result.audit_failures.append({"run": run_id, "checks": audit.checks})
        stop()
        if index + 1 < config.runs:
            reset()
            sleep(config.reset_seconds)
    result.summary = summarize(result.runs, config.metric)
    if report_path:
        rpath = Path(report_path)
        rpath.parent.mkdir(parents=True, exist_ok=True)
        md = render_postmortem_report(
            config.run_id_prefix,
            result.runs,
            baseline_runs=baseline_runs,
            audit_failures=result.audit_failures,
            hypothesis=hypothesis,
            trace_dir=resolved_trace_dir,
        )
        rpath.write_text(md, encoding="utf-8")
    return result
