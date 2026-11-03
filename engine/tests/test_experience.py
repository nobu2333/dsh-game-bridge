
from dsh_game_core.experience import Context, Outcome, SkillStats


def test_context_key_stable_and_coarse():
    a = Context(scene="gameplay", hp=3, threat_side="left", threat_ttc=0.31, threat_distance=0.18,
                space_left=0.2, space_right=0.8, move_type="charge")
    b = Context(scene="GamePlay", hp=3, threat_side="LEFT", threat_ttc=0.30, threat_distance=0.17,
                space_left=0.21, space_right=0.79, move_type="Charge")
    assert a.key() == b.key()
    c = Context(scene="gameplay", hp=2, threat_side="left", threat_ttc=0.31, threat_distance=0.18,
                space_left=0.2, space_right=0.8, move_type="charge")
    assert a.key() != c.key()


def test_outcome_reward():
    assert Outcome(damage=1, progress_delta=2.0, died=False).reward() == -0.6
    assert Outcome(damage=0, progress_delta=0.0, died=True).reward() == -5.0


def test_skill_stats_ucb_and_persistence():
    stats = SkillStats()
    ctx = Context(scene="gameplay", hp=3, threat_side="left", threat_ttc=0.3).key()
    assert stats.choose(ctx, ["jump", "advance"], epsilon=0.0) == "jump"  # untried first
    stats.update(ctx, "jump", 1.0)
    stats.update(ctx, "advance", -1.0)
    chosen = stats.choose(ctx, ["jump", "advance"], epsilon=0.0)
    assert chosen == "jump"
    assert stats.mean(ctx, "jump") == 1.0
    payload = stats.to_dict()
    restored = SkillStats.from_dict(payload)
    assert restored.mean(ctx, "jump") == 1.0
    assert restored.summary()["samples"] == 2

def test_context_coarse_ignores_ttc_distance():
    a = Context(scene="gameplay", hp=3, threat_side="left", threat_ttc=0.2, threat_distance=0.1)
    b = Context(scene="gameplay", hp=3, threat_side="left", threat_ttc=0.8, threat_distance=0.4)
    assert a.key() != b.key()
    assert a.key(coarse=True) == b.key(coarse=True)
