
import json

from dsh_game_core.review import build_review


def write_episode(root):
    directory = root / "ep"
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(
        json.dumps({"game": "cuphead", "level": "forest-follies", "frame_count": 1, "event_count": 1}),
        encoding="utf-8",
    )
    (directory / "events.jsonl").write_text(json.dumps({"type": "damage", "t": 1.0}) + "\n", encoding="utf-8")
    (directory / "frames.jsonl").write_text(
        json.dumps({"index": 0, "t": 1.0, "state": {"scroll_s": -1.0}}) + "\n", encoding="utf-8"
    )
    return directory


def test_build_review_contains_timeline_frames_cards(tmp_path):
    directory = write_episode(tmp_path)
    cards = [
        {
            "id": "cuphead/forest-follies/danger-x",
            "status": "candidate",
            "place": {"scroll_s": -1.0},
            "trigger": {"kind": "enemy"},
            "response": {"skill": "jump_over"},
            "stats": {"avoided": 1, "response_tries": 2, "response_failures": 1},
            "response_efficacy": 0.5,
        }
    ]
    text = build_review(directory, cards)
    assert "# Episode review" in text
    assert "damage: 1" in text
    assert "timeline" in text.lower()
    assert "danger-x" in text
    assert "Suggested review questions" in text


def test_build_review_missing_episode(tmp_path):
    text = build_review(tmp_path / "missing")
    assert "not found" in text
