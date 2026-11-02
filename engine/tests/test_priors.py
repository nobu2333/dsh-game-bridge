
from dsh_game_core.priors import all_priors, controls_hints, prior_for


def test_genre_priors_have_source_and_confidence():
    prior = prior_for("platformer")
    assert prior["source"] == "generic_prior"
    assert prior["confidence"] > 0
    assert prior["prior"]["advance"] == "right"
    assert prior["verified_in_game"] is False
    unknown = prior_for("nonsense")
    assert unknown["confidence"] == 0.0
    assert controls_hints("platformer")
    data = all_priors()
    assert "platformer" in data["genres"]
