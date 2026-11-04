
from dsh_game_core.mechanisms import default_specs


def test_every_default_mechanism_has_owner_and_expectation():
    specs = default_specs()
    ids = {spec.id for spec in specs}
    assert {"periodic_jump", "periodic_dash", "edge_escape", "shadow_advice", "memory_context", "world_model", "option_shadow", "option_canary"} <= ids
    for spec in specs:
        assert spec.expected_trigger
        assert spec.effect
        assert spec.owner_test
    assert next(spec for spec in specs if spec.id == "option_canary").enabled is False
