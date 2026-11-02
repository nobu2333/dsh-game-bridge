"""冷启动 profile 合并：file / web / probe / prior 四类来源 → 一份 controls profile。

规则：
- 每条候选带 action/key/source/confidence；
- 同 action 冲突时按 confidence 选主候选，保留 alternatives；
- prior 只给“可能是什么”，不覆盖实测；
- 输出 evidence/conflicts，方便复盘。

纯数据逻辑，不启动游戏、不读屏幕。
"""

from __future__ import annotations

from typing import Any

SOURCE_CONFIDENCE = {
    "file": 0.80,
    "probe": 0.95,
    "web": 0.60,
    "prior": 0.45,
    "unknown": 0.20,
}


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _norm_action(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def merge_controls(candidates: list[dict]) -> dict:
    """Merge control candidates into {controls, alternatives, conflicts, sources}.

    candidate: {"action": str, "key": str, "source": file|web|probe|prior,
                "confidence": optional float, "evidence": optional str}
    """
    by_action: dict[str, list[dict]] = {}
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        action = _norm_action(raw.get("action"))
        key = _norm_key(raw.get("key"))
        if not action or not key:
            continue
        source = str(raw.get("source") or "unknown").lower()
        confidence = raw.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else SOURCE_CONFIDENCE.get(source, 0.2)
        except (TypeError, ValueError):
            confidence = SOURCE_CONFIDENCE.get(source, 0.2)
        entry = {
            "action": action,
            "key": key,
            "source": source,
            "confidence": round(min(0.99, max(0.0, confidence)), 3),
            "evidence": str(raw.get("evidence") or "")[:200],
        }
        by_action.setdefault(action, []).append(entry)

    controls: dict[str, dict] = {}
    alternatives: dict[str, list[dict]] = {}
    conflicts: list[dict] = []
    for action, entries in by_action.items():
        entries.sort(key=lambda item: (-item["confidence"], item["source"] != "probe"))
        chosen = dict(entries[0])
        controls[action] = chosen
        rest = entries[1:]
        if rest:
            alternatives[action] = rest
        keys = {entry["key"] for entry in entries}
        if len(keys) > 1:
            conflicts.append(
                {
                    "action": action,
                    "chosen": chosen["key"],
                    "alternatives": sorted(keys - {chosen["key"]}),
                }
            )
    return {
        "controls": controls,
        "alternatives": alternatives,
        "conflicts": conflicts,
        "sources": sorted({entry["source"] for entries in by_action.values() for entry in entries}),
    }


def scan_to_candidates(scan: dict) -> list[dict]:
    """Convert game_probe.scan_game output to control candidates."""
    candidates: list[dict] = []
    for item in (scan or {}).get("keybinds") or []:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "action": item.get("action"),
                "key": item.get("key"),
                "source": "file",
                "confidence": SOURCE_CONFIDENCE["file"],
                "evidence": item.get("source") or "",
            }
        )
    return candidates


def probe_to_candidates(probe_results: dict[str, dict]) -> list[dict]:
    """Convert ControlsProbe.results() to candidates with effect=screen_change."""
    candidates: list[dict] = []
    for key, record in (probe_results or {}).items():
        if not isinstance(record, dict) or not record.get("changed"):
            continue
        candidates.append(
            {
                "action": f"effect_{key}",
                "key": key,
                "source": "probe",
                "confidence": min(0.95, 0.5 + float(record.get("diff") or 0.0) / 10.0),
                "evidence": f"screen_change diff={record.get('diff')}",
            }
        )
    return candidates


def build_profile(
    *,
    engine: str = "unknown",
    scan_candidates: list[dict] | None = None,
    web_candidates: list[dict] | None = None,
    probe_candidates: list[dict] | None = None,
    prior_candidates: list[dict] | None = None,
) -> dict:
    merged = merge_controls(
        list(scan_candidates or []) + list(web_candidates or []) + list(probe_candidates or []) + list(prior_candidates or [])
    )
    return {
        "schema": 1,
        "engine": engine,
        "controls": merged["controls"],
        "alternatives": merged["alternatives"],
        "conflicts": merged["conflicts"],
        "sources": merged["sources"],
        "verified_in_game": any(item.get("source") == "probe" for item in merged["controls"].values()),
    }

def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from .game_probe import scan_game

    parser = argparse.ArgumentParser(description="Read-only cold-start profile scan (no game launch).")
    parser.add_argument("root")
    args = parser.parse_args(argv)
    scan = scan_game(args.root)
    from .coldstart import build_profile, scan_to_candidates

    profile = build_profile(engine=scan.get("engine", "unknown"), scan_candidates=scan_to_candidates(scan))
    print(json.dumps({"scan": scan, "profile": profile}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
