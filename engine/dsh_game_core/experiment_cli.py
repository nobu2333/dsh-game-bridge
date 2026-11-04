"""P4 实验工具：把 policy status 转成 RunMetrics，并对 runs.jsonl 做统计/两臂比较。

用法（本地）：
  python -m dsh_game_core.experiment_cli summary runs.jsonl
  python -m dsh_game_core.experiment_cli compare baseline.jsonl candidate.jsonl \
      --mechanism option_canary --min-runs 10 --min-effect 0.5
"""

from __future__ import annotations

import argparse
import json

from .experiment import ExperimentSpec, RunMetrics, evaluate_experiment, load_runs, summarize


def metrics_from_status(
    status: dict,
    *,
    run_id: str = "",
    git_sha: str = "",
    profile_hash: str = "",
    clear: bool = False,
) -> RunMetrics:
    payload = status.get("policy") if isinstance(status.get("policy"), dict) else (status or {})
    scroll = payload.get("scroll_s")
    peak = abs(float(scroll)) if isinstance(scroll, (int, float)) else 0.0
    death = payload.get("death_context") or {}
    memory = payload.get("level_memory") or {}
    summary = memory.get("summary") if isinstance(memory, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    causes = summary.get("causes") or {}
    duration = 0.0
    extra = {}
    if isinstance(death, dict):
        cause = death.get("cause")
        if cause:
            causes = {cause: 1}
        ts = death.get("ts")
        started = payload.get("started_at")
        if isinstance(ts, (int, float)) and isinstance(started, (int, float)):
            duration = max(0.0, float(ts) - float(started))
    scene = payload.get("scene")
    if scene in ("level_complete", "clear", "results"):
        clear = True
    if scene == "death":
        extra["died"] = True
    return RunMetrics(
        run_id=run_id,
        peak_screens=round(peak, 3),
        duration_s=round(duration, 3),
        damage_taken=int(summary.get("damage") or 0),
        deaths=1 if scene == "death" else 0,
        clear=bool(clear),
        hz=payload.get("hz"),
        death_causes=causes if isinstance(causes, dict) else {},
        git_sha=git_sha,
        profile_hash=profile_hash,
        extra=extra,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline experiment metrics/compare.")
    sub = parser.add_subparsers(dest="command", required=True)
    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("runs")
    summary_parser.add_argument("--metric", default="peak_screens")
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--mechanism", default="unknown")
    compare_parser.add_argument("--name", default="experiment")
    compare_parser.add_argument("--primary", default="peak_screens")
    compare_parser.add_argument("--min-runs", type=int, default=10)
    compare_parser.add_argument("--min-effect", type=float, default=0.5)
    compare_parser.add_argument("--min-ci-low", type=float, default=0.0)
    compare_parser.add_argument("--guardrail-drop", type=float, default=1.0)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("status")
    audit_parser.add_argument("--profile")
    args = parser.parse_args(argv)

    if args.command == "audit":
        from .mechanism_audit import audit_mechanisms, expectations_from_profile

        with open(args.status, encoding="utf-8") as handle:
            status = json.load(handle)
        profile = {}
        if args.profile:
            with open(args.profile, encoding="utf-8") as handle:
                profile = json.load(handle)
        audit = audit_mechanisms(status, expectations_from_profile(profile))
        print(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2))
        return 0 if audit.ok else 2

    if args.command == "summary":
        runs = load_runs(args.runs)
        print(json.dumps(summarize(runs, args.metric), ensure_ascii=False, indent=2))
        return 0

    spec = ExperimentSpec(
        name=args.name,
        mechanism=args.mechanism,
        primary_metric=args.primary,
        min_runs=args.min_runs,
        min_effect=args.min_effect,
        min_ci_low=args.min_ci_low,
        guardrail_drop=args.guardrail_drop,
    )
    result = evaluate_experiment(spec, load_runs(args.baseline), load_runs(args.candidate))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
