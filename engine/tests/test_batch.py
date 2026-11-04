
from dsh_game_core.batch import BatchConfig, collect_batch, is_death_status


def _status(peak=3.5, canary_enabled=False, canary_applied=0):
    return {
        "policy": {
            "scene": "death",
            "scroll_s": -peak,
            "hz": 32.0,
            "death_context": {"cause": "cornered"},
            "level_memory": {"summary": {"damage": 2}},
            "mechanisms": {
                "edge_escape": {"enabled": False, "counts": {"applied": 0}},
                "option_canary": {"enabled": canary_enabled, "counts": {"applied": canary_applied}},
            },
        }
    }


def test_is_death_status_handles_driver_envelope():
    assert is_death_status(_status()) is True
    assert is_death_status({"scene": "gameplay"}) is False


def test_collect_batch_writes_runs_and_audits(tmp_path):
    calls = {"start": 0, "stop": 0, "reset": 0}
    events = [_status(3.0), _status(4.0)]

    def start():
        calls["start"] += 1

    def stop():
        calls["stop"] += 1

    def reset():
        calls["reset"] += 1

    def status():
        return events.pop(0) if events else _status(2.0)

    out = tmp_path / "runs.jsonl"
    result = collect_batch(
        BatchConfig(runs=2, max_run_seconds=10, poll_seconds=1, reset_seconds=0),
        start=start,
        stop=stop,
        status=status,
        reset=reset,
        sleep=lambda _: None,
        out_path=out,
        profile={"combat": {"edge_escape": False}, "options": {"execute": False}},
    )
    assert calls == {"start": 2, "stop": 2, "reset": 1}
    assert len(result.runs) == 2
    assert result.summary["n"] == 2
    assert out.is_file()
    assert result.audit_failures == []


def test_collect_batch_reports_audit_failure(tmp_path):
    result = collect_batch(
        BatchConfig(runs=1, max_run_seconds=5),
        start=lambda: None,
        stop=lambda: None,
        status=lambda: _status(canary_enabled=False, canary_applied=0),
        reset=lambda: None,
        sleep=lambda _: None,
        out_path=tmp_path / "runs.jsonl",
        profile={"options": {"execute": True, "canary": "jump_over"}},
    )
    assert len(result.audit_failures) == 1
    assert result.audit_failures[0]["checks"][1]["mechanism"] == "option_canary"
