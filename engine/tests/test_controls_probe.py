
import numpy as np

from dsh_game_core.controls_probe import ControlsProbe, frame_diff


def test_controls_probe_detects_changed_key():
    probe = ControlsProbe(["A", "B"], press_ms=50, change_threshold=1.0)
    before = np.zeros((60, 100, 3), dtype=np.uint8)
    after_change = before.copy()
    after_change[20:40, 20:50] = 200
    first = probe.next_action()
    assert first.key == "A"
    record = probe.submit(before, after_change)
    assert record["changed"] is True

    second = probe.next_action()
    assert second.key == "B"
    unchanged = probe.submit(before, before.copy())
    assert unchanged["changed"] is False
    assert probe.changed_keys() == ["A"]
    assert probe.profile_candidates()[0]["source"] == "probe"
    assert probe.next_action() is None
    assert probe.done() is True


def test_frame_diff_tolerates_bad_input():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert frame_diff(frame, frame) == 0.0
    assert frame_diff(None, frame) == 0.0
    assert frame_diff(frame, np.zeros((5, 5, 3), dtype=np.uint8)) == 0.0
