"""P4 实机跑批入口（需要 tmp/play_server.py 在 127.0.0.1:47655）。

示例：
  python scripts/ab_batch.py --label baseline --runs 10
  python scripts/ab_batch.py --label canary-jump --runs 10 --canary jump_over

每局写入 tmp/experiments/<label>.jsonl，并输出 summary + mechanism audit 失败。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from dsh_game_core.batch import BatchConfig, apply_canary, collect_batch  # noqa: E402

PORT = 47655


def send(method: str, params: dict | None = None) -> dict:
    with socket.create_connection(("127.0.0.1", PORT), timeout=180) as sock:
        sock.sendall((json.dumps({"method": method, "params": params or {}}) + "\n").encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
    payload = json.loads(b"".join(chunks).decode("utf-8").strip())
    if not payload.get("ok"):
        raise RuntimeError(json.dumps(payload.get("error"), ensure_ascii=False))
    return payload.get("result") or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a P4 experiment batch through the local driver.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--max-seconds", type=float, default=90)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--reset-seconds", type=float, default=6.0)
    parser.add_argument("--canary", default=None)
    parser.add_argument("--reactive", action="store_true")
    parser.add_argument("--game", default="cuphead")
    parser.add_argument("--level", default="forest-follies")
    parser.add_argument("--profile", default=str(ROOT / "profiles" / "cuphead.json"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--trace-dir", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--hypothesis", default="")
    args = parser.parse_args(argv)

    from dsh_game_core.experiment import load_runs

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    profile = apply_canary(profile, args.canary)
    if args.reactive:
        combat = dict(profile.get("combat") or {}) if isinstance(profile.get("combat"), dict) else {}
        combat["reactive_mode"] = True
        profile["combat"] = combat
    out_path = Path(args.out) if args.out else ROOT / "tmp" / "experiments" / f"{args.label}.jsonl"
    trace_dir = Path(args.trace_dir) if args.trace_dir else ROOT / "tmp" / "experiments" / "traces" / args.label
    report_path = Path(args.report) if args.report else ROOT / "experiments" / "results" / f"{args.label}.md"
    baseline_runs = load_runs(args.baseline) if args.baseline else None
    config = BatchConfig(
        runs=args.runs,
        max_run_seconds=args.max_seconds,
        poll_seconds=args.poll_seconds,
        reset_seconds=args.reset_seconds,
        run_id_prefix=args.label,
    )

    def start():
        send("policy_start", {"profile": profile, "game": args.game, "level": args.level, "record": False})

    def stop():
        try:
            send("policy_stop")
        except Exception:  # noqa: BLE001
            pass

    def status():
        return send("status")

    def reset():
        send("press", {"button": "Z", "duration_ms": 120})

    result = collect_batch(
        config,
        start=start,
        stop=stop,
        status=status,
        reset=reset,
        sleep=time.sleep,
        out_path=out_path,
        profile=profile,
        trace_dir=trace_dir,
        report_path=report_path,
        baseline_runs=baseline_runs,
        hypothesis=args.hypothesis,
    )
    print(
        json.dumps(
            {
                "label": args.label,
                "runs": len(result.runs),
                "summary": result.summary,
                "audit_failures": result.audit_failures,
                "out": str(out_path),
                "trace_dir": str(trace_dir),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
