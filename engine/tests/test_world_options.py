
from dsh_game_core.options import OptionSpec, UtilityArbiter, default_options, score_option
from dsh_game_core.world_model import build_world_model


def _world(**overrides):
    obs = {
        "hp": 3,
        "player": {"x": 0.5},
        "enemy_ahead": True,
        "enemy_side": "right",
        "enemy_ttc": 0.3,
        "enemy_distance": 0.25,
        "enemy_role": "projectile",
        "gap_ahead": False,
        "counts": {"enemies": 1},
    }
    obs.update(overrides)
    return build_world_model(obs, action_state={"grounded": True, "hurt": False}, hp=obs["hp"], scroll_s=2.0)


def test_world_model_space_threat_self():
    world = _world()
    assert abs(world.space.left - 0.5) < 1e-6
    assert abs(world.space.right - 0.5) < 1e-6
    assert world.space.ground is True
    assert world.threats and world.threats[0].side == "right"
    assert world.threats[0].ttc == 0.3
    assert world.self_state.hp == 3
    assert world.to_dict()["source"] == "observation"


def test_edge_flags_and_gap():
    world = _world(player={"x": 0.02}, gap_ahead=True)
    assert world.space.left_edge is True
    assert world.space.gap_ahead is True


def test_jump_over_preferred_for_gap():
    arbiter = UtilityArbiter(default_options())
    result = arbiter.select(_world(player={"x": 0.02}, gap_ahead=True), now_ms=1000)
    assert result["shadow"] is True
    assert result["option"] == "jump_over"


def test_commitment_holds_option():
    arbiter = UtilityArbiter([OptionSpec("advance", min_commit_ms=500, base_utility=1.0)], hysteresis=0.0)
    first = arbiter.select(_world(), now_ms=1000)
    second = arbiter.select(_world(), now_ms=1200)
    assert first["option"] == "advance"
    assert second["reason"] == "commit"


def test_safety_veto_left_edge():
    world = _world(player={"x": 0.02})
    left = next(option for option in default_options() if option.id == "strafe_left")
    assert score_option(left, world) <= 0.0
    arbiter = UtilityArbiter(default_options())
    result = arbiter.select(world, now_ms=1000)
    assert result["option"] != "strafe_left"

def test_world_model_uses_tracks_when_observation_has_no_enemy():
    class Track:
        id = 1
        kind = "threat"
        x = 0.7
        y = 0.5
        speed = 0.1

    world = build_world_model(
        {"player": {"x": 0.5, "y": 0.5}, "hp": 3},
        action_state={"grounded": True},
        tracks=[Track()],
    )
    assert world.threats
    assert world.threats[0].side == "right"
    assert world.threats[0].ttc is not None

def test_option_selection_stats_explain_rejections():
    arbiter = UtilityArbiter(default_options())
    result = arbiter.select(_world(player={"x": 0.02}, gap_ahead=True), now_ms=1000)
    stats = arbiter.snapshot()
    assert result["option"] == "jump_over"
    assert stats["jump_over"]["selected"] >= 1
    assert stats["strafe_left"]["rejected"] >= 1
    assert stats["strafe_left"]["reasons"]

def test_world_model_treats_nearby_parry_as_threat():
    class Track:
        id = 9
        kind = "parry"
        x = 0.6
        y = 0.55
        speed = 0.2

    world = build_world_model(
        {"player": {"x": 0.5, "y": 0.5}, "hp": 3},
        action_state={"grounded": True},
        tracks=[Track()],
    )
    assert world.threats
    assert world.threats[0].type == "parry"
    assert world.threats[0].parryable is True
