"""evaluate.py：episode / DangerCard 指标汇总。"""

import json
from pathlib import Path

from dsh_game_core.evaluate import (
    format_report,
    load_cards,
    summarize_cards,
    summarize_episode,
    summarize_episodes,
)


def write_episode(root: Path, name: str, *, game="cuphead", level="forest-follies", damage=1, deaths=0, scroll=-2.5):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps({"game": game, "level": level, "frame_count": 2, "event_count": damage + deaths}),
        encoding="utf-8",
    )
    events = [{"type": "damage"}] * damage + [{"type": "death"}] * deaths
    (directory / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    (directory / "frames.jsonl").write_text(
        json.dumps({"index": 0, "t": 0, "state": {"scroll_s": scroll}}) + "\n"
        + json.dumps({"index": 1, "t": 0.1, "state": {"scroll_s": scroll - 0.5}}) + "\n",
        encoding="utf-8",
    )
    return directory


def test_summarize_episodes_counts_damage_death_progress(tmp_path):
    write_episode(tmp_path, "a", damage=2, deaths=1, scroll=-3.0)
    write_episode(tmp_path, "b", damage=0, deaths=0, scroll=-1.0)
    write_episode(tmp_path, "other", game="other", damage=9)
    summary = summarize_episodes(tmp_path, game="cuphead", level="forest-follies")
    assert summary["episodes"] == 2
    assert summary["damage_events"] == 2
    assert summary["deaths"] == 1
    assert summary["damage_per_episode"] == 1.0
    assert summary["best_progress"] == 3.5


def test_summarize_cards_and_report(tmp_path):
    cards = [
        {"status": "candidate", "stats": {"avoided": 1, "response_failures": 1, "response_tries": 2}, "response_efficacy": 0.6},
        {"status": "validated", "stats": {"avoided": 1, "response_failures": 0, "response_tries": 1}, "response_efficacy": 0.7},
    ]
    summary = summarize_cards(cards)
    assert summary["cards"] == 2
    assert summary["avoided"] == 2
    assert summary["response_tries"] == 3
    assert summary["avoid_rate"] == round(2 / 3, 3)
    write_episode(tmp_path / "episodes", "a", damage=1)
    report = format_report({**summarize_episodes(tmp_path / "episodes"), "cards": summary})
    assert "episodes: 1" in report
    assert "cards: 2" in report
    assert "avoid_rate" in report


def test_load_cards_uses_knowledge_store(tmp_path):
    from dsh_game_core.memory import KnowledgeStore

    store = KnowledgeStore(tmp_path)
    store.upsert(
        {
            "game": "cuphead",
            "level": "forest-follies",
            "place": {"scroll_s": 1.0},
            "trigger": {"kind": "enemy"},
        }
    )
    cards = load_cards(tmp_path, "cuphead", "forest-follies")
    assert len(cards) == 1
    episode = write_episode(tmp_path / "episodes", "a", damage=1)
    from dsh_game_core.evaluate import load_episode

    parsed = load_episode(episode)
    assert parsed is not None
    assert summarize_episode(parsed)["damage_events"] == 1

def test_coordinate_drift_from_episode_frames(tmp_path):
    from dsh_game_core.evaluate import summarize_coordinate_drift

    for name, scroll in (("a", -1.00), ("b", -1.05), ("c", -1.40)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "meta.json").write_text(
            json.dumps({"game": "cuphead", "level": "forest-follies", "frame_count": 1, "event_count": 0}),
            encoding="utf-8",
        )
        (directory / "frames.jsonl").write_text(
            json.dumps({"index": 0, "t": 0, "state": {"danger": "card-a", "scroll_s": scroll}}) + "\n",
            encoding="utf-8",
        )
    summary = summarize_coordinate_drift(tmp_path, game="cuphead", level="forest-follies")
    assert summary["cards_with_multiple_visits"] == 1
    assert summary["max_spread"] == 0.4
    assert summary["ok"] is False
