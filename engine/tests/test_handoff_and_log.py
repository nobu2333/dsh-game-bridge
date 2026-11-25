"""Unit tests for bounded cross-turn handoff and generic L2 log observer."""

from __future__ import annotations

import json

import pytest

from dsh_game_core.handoff import build_handoff, safe_game_id
from dsh_game_core.log_observer import LogObserver


def test_build_handoff_respects_budget_and_reads_notes_and_runs(tmp_path):
    game_dir = tmp_path / "games" / "turnbased-demo"
    game_dir.mkdir(parents=True)
    notes_lines = [f"- note {i}: keep tempo" for i in range(20)]
    (game_dir / "notes.md").write_text("\n".join(notes_lines) + "\n", encoding="utf-8")
    runs = [
        {"run_id": "r1", "date": "2026-11-25", "result": "loss", "score": 10, "steps": 12, "summary": "missed trade"},
        {"run_id": "r2", "date": "2026-11-25", "result": "win", "score": 25, "steps": 9, "summary": "clean lethal"},
        {"run_id": "r3", "date": "2026-11-25", "result": "win", "score": 30, "steps": 8, "summary": "held removal"},
    ]
    (game_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n", encoding="utf-8")

    bundle = build_handoff(
        "turnbased-demo",
        data_dir=tmp_path,
        m0_summary="Turn 4: 4 mana, enemy board empty",
        structured_state={"turn": 4, "resources": 4},
        max_notes_lines=5,
        max_runs=2,
        max_chars=1200,
    )
    assert bundle["game_id"] == "turnbased-demo"
    assert bundle["notes"]["truncated"] is True
    assert [r["run_id"] for r in bundle["recent_runs"]] == ["r3", "r2"]
    assert "Turn 4: 4 mana" in bundle["text"]
    assert '"turn": 4' in bundle["text"]
    assert "note 0" in bundle["text"]
    assert "note 6" not in bundle["text"]
    assert bundle["chars"] <= 1200

    with pytest.raises(ValueError):
        safe_game_id("../escape")


def test_log_observer_incremental_tail_partial_lines_and_rotation(tmp_path):
    log_path = tmp_path / "events.log"
    observer = LogObserver.from_config(
        {
            "path": str(log_path),
            "rules": [
                {"name": "turn", "pattern": r"TURN (?P<n>\d+) (?P<who>SELF|OPP)", "set": {"turn": "{n}", "active": "{who}"}},
                {"name": "draw", "pattern": r"DRAW (?P<card>[A-Z0-9_]+)", "inc": {"draws": 1}, "append": {"hand": "{card}"}, "max_list": 3},
            ],
        }
    )

    # Missing file degrades cleanly.
    assert observer.poll()["exists"] is False

    # Write one full line + one incomplete trailing line (no newline yet).
    log_path.write_text("TURN 1 SELF\nDRAW CARD_A\nDRAW CARD_", encoding="utf-8")
    res1 = observer.poll()
    assert res1["exists"] is True
    assert res1["lines_read"] == 2
    assert res1["state"] == {"turn": "1", "active": "SELF", "draws": 1, "hand": ["CARD_A"]}

    # Finish the partial line + add two more draws (hand caps at 3).
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("B\nDRAW CARD_C\nDRAW CARD_D\n")
    res2 = observer.poll()
    assert res2["lines_read"] == 3
    assert res2["state"]["hand"] == ["CARD_B", "CARD_C", "CARD_D"]
    assert res2["state"]["draws"] == 4

    # Log rotation / truncation restarts from offset 0.
    log_path.write_text("TURN 1 OPP\n", encoding="utf-8")
    res3 = observer.poll()
    assert res3["lines_read"] == 1
    assert res3["state"]["active"] == "OPP"
