"""Bounded cross-turn / cross-run context handoff for slow-paced games.

Instead of keeping 70+ screenshots in one conversation until context_budget
triggers, an outer runner or fresh session can call `build_handoff` to carry
only:
- M2 game notes (`games/<id>/notes.md`, capped by lines and bytes);
- recent compact M0 run summaries (`games/<id>/runs.jsonl`);
- optional current M0 turn summary and L2 structured state.

No game names, no screenshots, and strict character budgeting.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

_ID_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def safe_game_id(value: str) -> str:
    text = str(value or "").strip()
    if text in (".", "..") or not _ID_SAFE.match(text):
        raise ValueError(f"invalid game id {value!r}")
    return text


def default_data_dir() -> Path:
    explicit = os.environ.get("DSH_GAME_BRIDGE_DATA_DIR")
    if explicit:
        return Path(explicit)
    cache = os.environ.get("DSH_GAME_BRIDGE_CACHE_DIR")
    if cache:
        return Path(cache)
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(local) / "dsh-game-bridge"


def load_notes_budgeted(
    game_id: str,
    *,
    data_dir: str | Path | None = None,
    max_lines: int = 80,
    max_bytes: int = 6144,
) -> dict:
    safe_id = safe_game_id(game_id)
    root = Path(data_dir) if data_dir is not None else default_data_dir()
    path = root / "games" / safe_id / "notes.md"
    if not path.is_file():
        return {"found": False, "text": "", "total_lines": 0, "truncated": False}
    raw = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff").rstrip("\r\n")
    lines = raw.splitlines() if raw else []
    kept: list[str] = []
    used = 0
    truncated = False
    for line in lines:
        if len(kept) >= max(1, int(max_lines)):
            truncated = True
            break
        size = len(line.encode("utf-8")) + (1 if kept else 0)
        if used + size > max(128, int(max_bytes)):
            truncated = True
            break
        kept.append(line)
        used += size
    return {
        "found": True,
        "text": "\n".join(kept).rstrip(),
        "total_lines": len(lines),
        "truncated": truncated,
    }


def load_recent_runs(
    game_id: str,
    *,
    data_dir: str | Path | None = None,
    limit: int = 5,
) -> list[dict]:
    safe_id = safe_game_id(game_id)
    root = Path(data_dir) if data_dir is not None else default_data_dir()
    path = root / "games" / safe_id / "runs.jsonl"
    if not path.is_file():
        return []
    parsed: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
            if isinstance(item, dict):
                parsed.append(item)
        except json.JSONDecodeError:
            continue
    cap = max(1, min(30, int(limit)))
    return list(reversed(parsed[-cap:]))


def build_handoff(
    game_id: str,
    *,
    data_dir: str | Path | None = None,
    m0_summary: str | None = None,
    structured_state: Mapping[str, Any] | None = None,
    max_notes_lines: int = 80,
    max_notes_bytes: int = 6144,
    max_runs: int = 5,
    max_chars: int = 8000,
) -> dict:
    """Assemble a bounded Markdown/JSON handoff for a fresh turn or session."""
    safe_id = safe_game_id(game_id)
    notes = load_notes_budgeted(
        safe_id, data_dir=data_dir, max_lines=max_notes_lines, max_bytes=max_notes_bytes
    )
    runs = load_recent_runs(safe_id, data_dir=data_dir, limit=max_runs)

    sections: list[str] = [f"# Session Handoff: {safe_id}"]
    if m0_summary and str(m0_summary).strip():
        sections.append("## Current Run (M0)\n" + str(m0_summary).strip()[:1500])
    if structured_state:
        serialized = json.dumps(dict(structured_state), ensure_ascii=False, indent=2)
        if len(serialized) > 2000:
            serialized = serialized[:1980] + "\n..."
        sections.append("## Structured State (L2)\n```json\n" + serialized + "\n```")
    if runs:
        run_lines = []
        for run in runs:
            summary = f" — {run['summary']}" if run.get("summary") else ""
            score = f" score={run['score']}" if run.get("score") is not None else ""
            steps = f" steps={run['steps']}" if run.get("steps") is not None else ""
            run_lines.append(f"- `{run.get('run_id', '?')}` [{run.get('date', '')}] {run.get('result', '?')}{score}{steps}{summary}")
        sections.append("## Recent Runs\n" + "\n".join(run_lines))
    if notes["found"] and notes["text"]:
        suffix = "\n*(notes truncated)*" if notes["truncated"] else ""
        sections.append("## Game Notes (M2)\n" + notes["text"] + suffix)

    text = "\n\n".join(sections)
    cap = max(256, int(max_chars))
    text_truncated = False
    if len(text) > cap:
        text = text[: cap - 16].rstrip() + "\n...(truncated)"
        text_truncated = True

    return {
        "game_id": safe_id,
        "notes": notes,
        "recent_runs": runs,
        "m0_summary": str(m0_summary).strip() if m0_summary else None,
        "structured_state": dict(structured_state) if structured_state else None,
        "text": text,
        "chars": len(text),
        "truncated": bool(text_truncated or notes["truncated"]),
    }
