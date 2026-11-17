
from dsh_game_core.m5_compare import summarize_m5


def _runs(player, scores):
    return [{"player": player, "score": score} for score in scores]


def test_single_pilot_is_insufficient_even_if_high():
    result = summarize_m5(_runs("model:deepseek", [900]), _runs("random", [100, 110, 120, 130, 140]))
    assert result["status"] == "insufficient_model_runs"


def test_full_pass_requires_both_controls_and_worst_threshold():
    model = _runs("model:deepseek", [900, 800, 700])
    baseline = _runs("random", [100, 110, 120, 130, 140]) + _runs("cycle", [200, 210, 220, 230, 240])
    result = summarize_m5(model, baseline)
    assert result["status"] == "m5_pass"
    assert result["criteria"]["worst_not_below_half"] is True


def test_worst_below_half_fails():
    model = _runs("model:deepseek", [900, 800, 50])
    baseline = _runs("random", [100, 110, 120, 130, 140]) + _runs("cycle", [200, 210, 220, 230, 240])
    result = summarize_m5(model, baseline)
    assert result["status"] == "m5_fail"
    assert result["criteria"]["worst_not_below_half"] is False


def test_mediocre_model_fails():
    model = _runs("model:deepseek", [100, 200, 300])
    baseline = _runs("random", [100, 110, 120, 130, 140]) + _runs("cycle", [200, 210, 220, 230, 240])
    result = summarize_m5(model, baseline)
    assert result["status"] == "m5_fail"
    assert result["criteria"]["model_beats_cycle"] is False
