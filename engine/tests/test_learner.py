
import json
from pathlib import Path

from dsh_game_core.experience import Context, Outcome
from dsh_game_core.learner import EpisodeTrace, Learner, append_jsonl, load_jsonl, trace_from_dicts


def test_learner_apply_and_death_credit():
    learner = Learner()
    trace = EpisodeTrace(died=True)
    ctx = Context(scene="gameplay", hp=3, threat_side="left", threat_ttc=0.3)
    for _ in range(3):
        trace.add(ctx, "advance", Outcome(damage=0, progress_delta=0.2))
    assert learner.apply(trace) == 3
    mean = learner.stats.mean(ctx.key(), "advance")
    assert mean is not None
    assert mean < 0.4  # death penalty lowers the last steps


def test_learner_save_load(tmp_path):
    learner = Learner()
    ctx = Context(scene="gameplay", hp=3)
    learner.stats.update(ctx.key(), "jump", 1.0)
    path = tmp_path / "learn.json"
    learner.save(path)
    restored = Learner.load(path)
    assert restored.stats.mean(ctx.key(), "jump") == 1.0
    assert restored.stats.summary()["samples"] == 1


def test_jsonl_and_trace_roundtrip(tmp_path):
    path = tmp_path / "steps.jsonl"
    row = {
        "ts": 1.0,
        "context": {"scene": "gameplay", "hp": 2, "threat_side": "right"},
        "action": "dodge_left",
        "outcome": {"damage": 0, "progress_delta": 1.0},
    }
    append_jsonl(path, row)
    rows = load_jsonl(path)
    assert len(rows) == 1
    trace = trace_from_dicts(rows)
    assert trace.steps[0].action == "dodge_left"
    assert trace.steps[0].context.hp == 2

def test_context_from_observation():
    from dsh_game_core.learner import context_from_observation

    ctx = context_from_observation(
        {"scene": "gameplay", "hp": 2, "enemy_ahead": True, "enemy_side": "left", "enemy_ttc": 0.3, "player": {"x": 0.4}}
    )
    assert ctx.hp == 2
    assert ctx.threat_side == "left"
    assert ctx.threat_ttc == 0.3
    assert ctx.space_left == 0.4
