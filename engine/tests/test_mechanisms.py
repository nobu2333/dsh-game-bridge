
from dsh_game_core.experiment import (
    ExperimentSpec,
    RunMetrics,
    append_run,
    bootstrap_median_diff,
    evaluate_experiment,
    load_runs,
    summarize,
)
from dsh_game_core.mechanisms import MechanismRegistry, MechanismSpec


def test_registry_counts_and_disable():
    registry = MechanismRegistry([MechanismSpec(id="edge_escape")])
    registry.record("edge_escape", "evaluated")
    registry.record("edge_escape", "triggered")
    registry.record("edge_escape", "applied")
    snapshot = registry.snapshot()["edge_escape"]
    assert snapshot["counts"]["applied"] == 1
    registry.set_enabled("edge_escape", False)
    registry.record("edge_escape", "applied")
    snapshot = registry.snapshot()["edge_escape"]
    assert snapshot["counts"]["applied"] == 1
    assert snapshot["counts"]["noop"] == 1
    assert snapshot["last_reason"] == "disabled"


def test_experiment_promote_and_insufficient():
    spec = ExperimentSpec(name="x", mechanism="m", min_runs=5, min_effect=0.5)
    base = [RunMetrics(peak_screens=v) for v in (3, 4, 4, 5, 3)]
    cand = [RunMetrics(peak_screens=v) for v in (5, 6, 5, 6, 5)]
    result = evaluate_experiment(spec, base, cand)
    assert result["decision"] == "promote"
    assert result["diff"]["observed"] >= 1.0
    assert evaluate_experiment(spec, base[:3], cand)["decision"] == "insufficient"


def test_experiment_regression():
    spec = ExperimentSpec(name="x", mechanism="m", min_runs=5, min_effect=0.5, guardrail_drop=1.0)
    base = [RunMetrics(peak_screens=v) for v in (5, 5, 6, 5, 5)]
    cand = [RunMetrics(peak_screens=v) for v in (2, 2, 3, 2, 2)]
    result = evaluate_experiment(spec, base, cand)
    assert result["decision"] == "regression"


def test_append_load_and_summary(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_run(path, RunMetrics(run_id="a", peak_screens=4.0, clear=False))
    append_run(path, RunMetrics(run_id="b", peak_screens=6.0, clear=True))
    runs = load_runs(path)
    assert len(runs) == 2
    summary = summarize(runs)
    assert summary["n"] == 2
    assert summary["clear_rate"] == 0.5
    assert bootstrap_median_diff([1, 2, 3], [1, 2, 3])["observed"] == 0
