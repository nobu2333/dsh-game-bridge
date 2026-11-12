"""M5 baseline helpers: policies, OCR score reading, run records."""

from __future__ import annotations

import json

from dsh_game_core.baseline import (
    CyclePolicy,
    RandomPolicy,
    RunRecord,
    find_phrase,
    make_policy,
    make_run_id,
    parse_labeled_numbers,
    summarize_records,
    write_jsonl,
)


def _line(text, left, top, right, bottom, score=0.99):
    return {"text": text, "left": left, "top": top, "right": right, "bottom": bottom, "score": score}


SCORE_BOARD = [
    _line("2048", 31, 7, 65, 25),
    _line("SCORE", 497, 128, 542, 146),
    _line("BEST", 571, 128, 608, 146),
    _line("128", 510, 148, 550, 170),
    _line("64", 581, 149, 599, 169),
]


def test_random_policy_is_seeded_and_reproducible():
    first = [RandomPolicy(seed=7).choose() for _ in range(1)]
    values_a = [RandomPolicy(seed=7).choose() for _ in range(20)]
    rng_a = RandomPolicy(seed=7)
    rng_b = RandomPolicy(seed=7)
    assert [rng_a.choose() for _ in range(20)] == [rng_b.choose() for _ in range(20)]
    assert first and values_a
    assert set(values_a) <= {"UP", "RIGHT", "DOWN", "LEFT"}


def test_cycle_policy_walks_in_order_and_wraps():
    policy = CyclePolicy(keys=("A", "B"))
    assert [policy.choose() for _ in range(5)] == ["A", "B", "A", "B", "A"]


def test_make_policy_rejects_unknown_mode():
    assert make_policy("random").mode == "random"
    assert make_policy("CYCLE").mode == "cycle"
    try:
        make_policy("greedy")
    except ValueError as error:
        assert "greedy" in str(error)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("unknown mode should raise")


def test_parse_labeled_numbers_reads_values_under_labels():
    assert parse_labeled_numbers(SCORE_BOARD, ["SCORE", "BEST"]) == {"SCORE": 128, "BEST": 64}


def test_parse_labeled_numbers_reads_glued_label_and_ignores_far_values():
    lines = [_line("SCORE 512", 497, 128, 600, 146), _line("BEST", 571, 128, 608, 146), _line("9", 10, 900, 20, 920)]
    assert parse_labeled_numbers(lines, ["SCORE", "BEST"]) == {"SCORE": 512}


def test_parse_labeled_numbers_never_guesses_missing_labels():
    assert parse_labeled_numbers([], ["SCORE"]) == {}
    assert parse_labeled_numbers([_line("SCORE", 0, 0, 10, 10)], ["SCORE"]) == {}


def test_find_phrase_is_case_insensitive():
    lines = [_line("GAME OVER", 0, 0, 10, 10)]
    assert find_phrase(lines, ["game over"]) == "game over"
    assert find_phrase(lines, ["try again"]) is None


def test_run_record_and_jsonl_roundtrip(tmp_path):
    record = RunRecord(
        run_id="random-20260101-000000-01",
        date="2026-01-01",
        player="random",
        game="2048",
        build="test",
        steps=42,
        wall_s=12.5,
        score=256,
        best=512,
        end_reason="phrase:game over",
        errors=1,
        seed=3,
    )
    path = write_jsonl(tmp_path / "runs.jsonl", [record])
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["score"] == 256
    assert line["end_reason"] == "phrase:game over"


def test_summarize_records_reports_median_and_extremes():
    records = [
        RunRecord("a", "2026-01-01", "random", "2048", "t", 10, 1.0, score=100),
        RunRecord("b", "2026-01-01", "random", "2048", "t", 20, 2.0, score=300),
        RunRecord("c", "2026-01-01", "random", "2048", "t", 30, 3.0, score=200),
    ]
    summary = summarize_records(records)
    assert summary["score"] == {"n": 3, "median": 200, "min": 100, "max": 300}
    assert summary["steps"]["median"] == 20


def test_make_run_id_contains_prefix_and_index():
    run_id = make_run_id("random", 3, now=1767225600)
    assert run_id.startswith("random-")
    assert run_id.endswith("-03")
