"""P4 实验工具：把 policy status 转成 RunMetrics，并对 runs.jsonl 做统计/两臂比较。

用法（本地）：
  python -m dsh_game_core.experiment_cli summary runs.jsonl
  python -m dsh_game_core.experiment_cli compare baseline.jsonl candidate.jsonl \
      --mechanism option_canary --min-runs 10 --min-effect 0.5
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    if duration <= 0.0:
        ticks = payload.get("ticks")
        hz = payload.get("hz")
        if isinstance(ticks, (int, float)) and isinstance(hz, (int, float)) and float(hz) > 0:
            duration = float(ticks) / float(hz)
    scene = payload.get("scene")
    if scene in ("level_complete", "clear", "results"):
        clear = True
    if scene == "death":
        extra["died"] = True

    health = payload.get("perception_health") if isinstance(payload.get("perception_health"), dict) else {}
    if not health and isinstance(death, dict) and isinstance(death.get("perception_health"), dict):
        health = death["perception_health"]
    stale_ratio = health.get("player_stale_ratio")
    threat_ratio = health.get("threat_active_ratio")

    option_stats = payload.get("option_stats") if isinstance(payload.get("option_stats"), dict) else {}
    option_counts = {
        str(opt_id): int((entry or {}).get("selected") or 0)
        for opt_id, entry in option_stats.items()
        if isinstance(entry, dict)
    }

    mechanisms = payload.get("mechanisms") if isinstance(payload.get("mechanisms"), dict) else {}
    mechanism_counts = {
        str(mech_id): dict((entry or {}).get("counts") or {})
        for mech_id, entry in mechanisms.items()
        if isinstance(entry, dict)
    }

    damage_events = payload.get("damage_events")
    if not isinstance(damage_events, list):
        damage_events = (death.get("damage_events") if isinstance(death, dict) else None) or []
    # 只用本局受击事件数；LevelMemory.summary.damage 是跨局累计值，不能当单局伤害。
    damage_count = len(damage_events)

    if isinstance(death, dict) and death:
        extra["death_scroll_s"] = death.get("scroll_s")
        extra["death_cause"] = death.get("cause")

    return RunMetrics(
        run_id=run_id,
        peak_screens=round(peak, 3),
        duration_s=round(duration, 3),
        damage_taken=damage_count,
        deaths=1 if scene == "death" else 0,
        clear=bool(clear),
        hz=payload.get("hz"),
        player_stale_ratio=round(float(stale_ratio), 4) if isinstance(stale_ratio, (int, float)) else None,
        threat_active_ratio=round(float(threat_ratio), 4) if isinstance(threat_ratio, (int, float)) else None,
        option_counts=option_counts,
        mechanism_counts=mechanism_counts,
        damage_events=list(damage_events[-16:]),
        death_causes=causes if isinstance(causes, dict) else {},
        git_sha=git_sha,
        profile_hash=profile_hash,
        extra=extra,
    )


def render_postmortem_report(
    label: str,
    runs: list[RunMetrics],
    *,
    baseline_runs: list[RunMetrics] | None = None,
    audit_failures: list[dict] | None = None,
    hypothesis: str = "",
    trace_dir: str | Path | None = None,
) -> str:
    summary = summarize(runs, "peak_screens")
    lines = [
        f"# 批次复盘报告：{label}",
        "",
        f"- **局数 (n)**：{summary.get('n', 0)}",
        f"- **假设/说明**：{hypothesis or '常规批次评估与过程留痕复盘'}",
        f"- **机制审计**：{'通过 (0 failures)' if not audit_failures else f'失败 ({len(audit_failures)} failures)'}",
        "",
        "## 1. 核心表现与感知健康度汇总",
        "",
        "| 指标 | 当前批次 | 基线 (如有) |",
        "|:--|--:|--:|",
    ]
    base_summary = summarize(baseline_runs, "peak_screens") if baseline_runs else {}
    for key, title in (
        ("median", "Median Peak (screens)"),
        ("mean", "Mean Peak (screens)"),
        ("p10", "P10 Peak (screens)"),
        ("max", "Max Peak (screens)"),
        ("clear_rate", "Clear Rate"),
        ("mean_player_stale_ratio", "Mean Player Stale Ratio"),
        ("mean_threat_active_ratio", "Mean Threat Active Ratio"),
        ("mean_damage_taken", "Mean Damage Events"),
    ):
        cur_val = summary.get(key)
        base_val = base_summary.get(key) if base_summary else "—"
        lines.append(f"| {title} | {cur_val if cur_val is not None else '—'} | {base_val if base_val is not None else '—'} |")

    if baseline_runs and len(runs) >= 1 and len(baseline_runs) >= 1:
        spec = ExperimentSpec(name=label, mechanism="batch_compare", min_runs=min(len(runs), len(baseline_runs)))
        comp = evaluate_experiment(spec, baseline_runs, runs)
        diff = comp.get("diff") or {}
        lines.extend(
            [
                "",
                "### A/B 判定",
                f"- **Decision**: `{comp.get('decision')}` ({comp.get('reason')})",
                f"- **Median Diff**: `{diff.get('observed')}` (95% CI: `[{diff.get('ci_low')}, {diff.get('ci_high')}]`)",
            ]
        )

    lines.extend(
        [
            "",
            "## 2. 死因分布与单局明细",
            "",
            f"- **死因汇总**：`{json.dumps(summary.get('death_causes') or {}, ensure_ascii=False)}`",
            "",
            "| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |",
            "|:--|--:|--:|--:|--:|--:|:--|",
        ]
    )
    for run in runs:
        causes_str = ",".join(f"{k}:{v}" for k, v in (run.death_causes or {}).items()) or "—"
        lines.append(
            f"| {run.run_id} | {run.peak_screens} | {run.duration_s} | "
            f"{run.player_stale_ratio if run.player_stale_ratio is not None else '—'} | "
            f"{run.threat_active_ratio if run.threat_active_ratio is not None else '—'} | "
            f"{run.damage_taken} | {causes_str} |"
        )

    if audit_failures:
        lines.extend(["", "## 3. 机制审计失败明细", ""])
        for item in audit_failures[:5]:
            lines.append(f"- `{item.get('run')}`: `{json.dumps(item.get('checks'), ensure_ascii=False)}`")

    if trace_dir is not None:
        tdir = Path(trace_dir)
        trace_files = sorted(tdir.glob("*.jsonl")) if tdir.is_dir() else []
        if trace_files:
            lines.extend(["", "## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)", ""])
            for tf in trace_files[:3]:
                raw_lines = [ln.strip() for ln in tf.read_text(encoding="utf-8").splitlines() if ln.strip()]
                tail = raw_lines[-5:]
                lines.append(f"### `{tf.stem}` (共 {len(raw_lines)} 条轨迹采样)")
                for raw in tail:
                    try:
                        ev = json.loads(raw)
                        lines.append(
                            f"- `tick={ev.get('tick')}` `scroll={ev.get('scroll_s')}` `hp={ev.get('hp')}` "
                            f"`anchor={ev.get('anchor')}` `age_ms={ev.get('player_age_ms')}` "
                            f"`opt={ev.get('selected_option')}({ev.get('option_reason')})` "
                            f"`act={ev.get('applied_action')}` `threats={len(ev.get('threats_top2') or [])}`"
                        )
                    except Exception:  # noqa: BLE001
                        continue
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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
    report_parser = sub.add_parser("report")
    report_parser.add_argument("runs")
    report_parser.add_argument("--label", default="batch")
    report_parser.add_argument("--baseline")
    report_parser.add_argument("--traces")
    report_parser.add_argument("--hypothesis", default="")
    report_parser.add_argument("--out")
    args = parser.parse_args(argv)

    if args.command == "report":
        runs = load_runs(args.runs)
        base = load_runs(args.baseline) if args.baseline else None
        md = render_postmortem_report(
            args.label,
            runs,
            baseline_runs=base,
            hypothesis=args.hypothesis,
            trace_dir=args.traces,
        )
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
        print(md)
        return 0

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
