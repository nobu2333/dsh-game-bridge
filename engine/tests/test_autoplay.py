from dsh_game_core.autoplay import evaluate_session, ocr_contains


def test_ocr_contains_is_case_insensitive():
    sample = {"ocr": ["Press Space", "GAMEOVER"]}
    assert ocr_contains(sample, ["gameover"]) == "GAMEOVER"
    assert ocr_contains(sample, ["广告"]) is None


def test_valid_session_requires_duration_and_no_stop_phrase():
    samples = [{"ocr": ["SCORE", "42"]}, {"ocr": ["SCORE", "88"]}]
    assert evaluate_session(requested_s=300, elapsed_s=301, samples=samples)["valid"] is True
    short = evaluate_session(requested_s=300, elapsed_s=10, samples=samples)
    assert short["valid"] is False
    assert short["reason"].startswith("too_short")


def test_stop_phrase_invalidates_session():
    samples = [{"ocr": ["SCORE", "42"]}, {"ocr": ["GAME OVER"]}]
    result = evaluate_session(requested_s=300, elapsed_s=301, samples=samples, stop_phrases=["GAME OVER"])
    assert result == {"valid": False, "reason": "stop_phrase:GAME OVER"}

def test_strict_session_actions_and_resets():
    samples = [{"ocr": ["SCORE", "42"]}]
    assert evaluate_session(requested_s=300, elapsed_s=301, samples=samples, actions=2, min_actions=3)["valid"] is False
    assert evaluate_session(requested_s=300, elapsed_s=301, samples=samples, resets=5, max_resets=2)["valid"] is False
    assert evaluate_session(requested_s=300, elapsed_s=301, samples=samples, progressed=False)["valid"] is False
    ok = evaluate_session(requested_s=300, elapsed_s=301, samples=samples, actions=10, min_actions=3, resets=1, max_resets=2)
    assert ok["valid"] is True
    assert ok["actions"] == 10
    assert ok["resets"] == 1
