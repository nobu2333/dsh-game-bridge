
import json

from dsh_game_core.experiment import RunMetrics, append_run
from dsh_game_core.experiment_cli import main, metrics_from_status


def test_metrics_from_status_death():
    status = {
        "scene": "death",
        "hz": 31.5,
        "scroll_s": -5.25,
        "death_context": {"cause": "cornered", "ts": 10.0},
        "started_at": 2.0,
        "damage_events": [{} for _ in range(7)],
        "level_memory": {"summary": {"damage": 7, "deaths": 1, "causes": {"cornered": 1}}},
    }
    metrics = metrics_from_status(status, run_id="r1")
    assert metrics.peak_screens == 5.25
    assert metrics.duration_s == 8.0
    assert metrics.damage_taken == 7
    assert metrics.deaths == 1
    assert metrics.death_causes["cornered"] == 1
    assert metrics.clear is False


def test_metrics_from_status_damage_events_are_per_run():
    status = {
        "scene": "death",
        "scroll_s": -3.0,
        "damage_events": [{"ts": 1.0}, {"ts": 2.0}],
        "level_memory": {"summary": {"damage": 999}},
    }
    metrics = metrics_from_status(status, run_id="r2")
    assert metrics.damage_taken == 2


def test_experiment_cli_summary_and_compare(tmp_path, capsys):
    base = tmp_path / "base.jsonl"
    cand = tmp_path / "cand.jsonl"
    for value in (3, 4, 4, 5, 3, 4, 3, 4):
        append_run(base, RunMetrics(run_id="b", peak_screens=value))
    for value in (5, 6, 5, 6, 5, 6, 5, 6):
        append_run(cand, RunMetrics(run_id="c", peak_screens=value))
    assert main(["summary", str(base)]) == 0
    assert "median" in capsys.readouterr().out
    assert main(["compare", str(base), str(cand), "--min-runs", "5"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "promote"
    report_file = tmp_path / "report.md"
    assert main(["report", str(cand), "--baseline", str(base), "--label", "test-batch", "--out", str(report_file)]) == 0
    assert report_file.is_file()
    assert "批次复盘报告：test-batch" in report_file.read_text(encoding="utf-8")
