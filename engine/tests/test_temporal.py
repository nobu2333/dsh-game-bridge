
from dsh_game_core.temporal import TemporalState


def test_temporal_state_tracks_velocity_and_ttc():
    state = TemporalState(history_ms=600)
    # player moves right from 0.40 -> 0.44 over 0.4s
    state.update(100.0, {"x": 0.40, "y": 0.80}, [{"id": 1, "x": 0.80, "y": 0.80, "role": "approaching"}])
    state.update(100.2, {"x": 0.42, "y": 0.80}, [{"id": 1, "x": 0.70, "y": 0.80, "role": "approaching"}])
    out = state.update(100.4, {"x": 0.44, "y": 0.80}, [{"id": 1, "x": 0.60, "y": 0.80, "role": "approaching"}])
    threat = out["threats"][0]
    assert threat["side"] == "right"
    assert threat["vx"] < 0
    assert threat["ttc"] is not None
    assert threat["ttc"] > 0
    assert out["player"]["vx"] > 0


def test_temporal_state_empty_and_prune():
    state = TemporalState(history_ms=200)
    assert state.update(1.0, {"x": 0.5, "y": 0.8}, [])["threats"] == []
    state.update(1.0, {"x": 0.5, "y": 0.8}, [{"id": 2, "x": 0.6, "y": 0.8}])
    out = state.update(3.0, {"x": 0.5, "y": 0.8}, [])
    assert out["threats"] == []

def test_temporal_age_reported():
    from dsh_game_core.temporal import TemporalState
    state = TemporalState(history_ms=600)
    state.update(1.0, {"x": 0.5, "y": 0.8}, [{"id": 1, "x": 0.7, "y": 0.8}])
    out = state.update(1.1, {"x": 0.5, "y": 0.8}, [])
    assert "age_ms" in out["threats"][0]
    assert out["threats"][0]["age_ms"] >= 100
