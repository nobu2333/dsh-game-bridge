"""P4 实机跑批器（注入式）：不绑定具体 driver，便于先离线测试。

职责：
- 跑 N 局，直到 death/超时；
- 把每局 status 转成 RunMetrics 写 JSONL；
- 每局做 mechanism audit；
- 返回批次摘要 + 审计失败列表。

真实使用时由调用方注入 start/stop/status/reset/sleep。游戏/驱动不进入引擎。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .experiment import RunMetrics, append_run, summarize
from .experiment_cli import metrics_from_status
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

    def to_dict(self) -> dict:
        return {
            "runs": [run.to_dict() for run in self.runs],
            "audit_failures": self.audit_failures,
            "summary": self.summary,
            "out_path": self.out_path,
        }


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
) -> BatchResult:
    result = BatchResult(out_path=str(out_path))
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    expectations = expectations_from_profile(profile or {})
    for index in range(max(1, int(config.runs))):
        start()
        elapsed = 0.0
        snapshot: dict = {}
        while elapsed < config.max_run_seconds:
            sleep(config.poll_seconds)
            elapsed += config.poll_seconds
            snapshot = status() or {}
            if is_death_status(snapshot):
                break
        run_id = f"{config.run_id_prefix}-{index + 1:02d}"
        metrics = metrics_from_status(snapshot, run_id=run_id, git_sha=git_sha)
        result.runs.append(metrics)
        append_run(target, metrics)
        audit = audit_mechanisms(snapshot, expectations) if expectations else None
        if audit is not None and not audit.ok:
            result.audit_failures.append({"run": run_id, "checks": audit.checks})
        stop()
        if index + 1 < config.runs:
            reset()
            sleep(config.reset_seconds)
    result.summary = summarize(result.runs, config.metric)
    return result
