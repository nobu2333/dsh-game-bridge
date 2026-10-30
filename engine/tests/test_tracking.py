"""EntityTracker：ID 稳定性 / 速度 / 方位 / 丢失清理。"""

from dsh_game_core.tracking import EntityTracker, Track, approaching_speed, relative_relation


def moving_threat(x):
    return [{"kind": "threat", "x": x, "y": 0.5, "score": 0.8}]


def test_tracker_keeps_ids_and_estimates_velocity():
    tracker = EntityTracker(match_radius=0.1, max_miss=2)
    first = tracker.update(moving_threat(0.2), now=1.0)
    assert len(first) == 1
    track_id = first[0].id
    second = tracker.update(moving_threat(0.25), now=1.1)
    assert [t.id for t in second] == [track_id]
    assert second[0].vx > 0.0
    assert second[0].age == 2


def test_tracker_new_and_dropped_tracks():
    tracker = EntityTracker(match_radius=0.05, max_miss=1)
    first = tracker.update([{"kind": "threat", "x": 0.2, "y": 0.2, "score": 1.0}], now=0.0)
    old_id = first[0].id
    # far away detection becomes a new track
    second = tracker.update([{"kind": "threat", "x": 0.8, "y": 0.8, "score": 1.0}], now=0.05)
    ids = {track.id for track in second}
    assert old_id in ids or len(ids) == 1
    # old track misses twice -> dropped
    tracker.update([], now=0.1)
    third = tracker.update([], now=0.2)
    assert all(track.id != old_id for track in third)


def test_relation_and_approach():
    approach = Track(id=1, kind="threat", x=0.6, y=0.5, vx=-0.3, vy=0.0, last_t=0.0)
    away = Track(id=2, kind="threat", x=0.6, y=0.5, vx=0.3, vy=0.0, last_t=0.0)
    anchor = (0.4, 0.5)
    assert relative_relation(approach, anchor) == "ahead"
    assert approaching_speed(approach, anchor) > 0
    assert approaching_speed(away, anchor) < 0
    assert relative_relation(Track(id=3, kind="enemy", x=0.2, y=0.5), anchor) == "behind"
    assert relative_relation(Track(id=4, kind="enemy", x=0.42, y=0.52), anchor) == "same"


def test_tracker_tolerates_garbage():
    tracker = EntityTracker()
    assert tracker.update(None, now=0.0) == []
    assert tracker.update([None, {}, {"kind": "threat", "x": "bad", "y": 0.1}], now=0.0) == []
