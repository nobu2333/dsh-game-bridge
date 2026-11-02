
from dsh_game_core.observation import build_observation, choose_skill


def test_observation_and_attack():
    obs = build_observation(
        scene="gameplay",
        hp=3,
        entities=[{"role": "harmful", "distance": 0.2, "behind": False}],
    )
    assert obs["enemy_ahead"] is True
    assert choose_skill(obs)["skill"] == "attack"


def test_gap_and_prompt_precedence():
    gap = build_observation(scene="gameplay", hp=3, terrain_gap=True)
    assert choose_skill(gap)["skill"] == "jump"
    prompt = build_observation(scene="gameplay", hp=3, prompt="Z")
    assert choose_skill(prompt)["skill"] == "confirm"


def test_recover_and_retreat_and_advance():
    assert choose_skill(build_observation(scene="death"))["skill"] == "recover"
    retreat = build_observation(
        scene="gameplay",
        hp=1,
        entities=[{"role": "chaser", "distance": 0.1, "behind": True}],
    )
    assert choose_skill(retreat)["skill"] == "retreat"
    assert choose_skill(build_observation(scene="gameplay", hp=3))["skill"] == "advance"
