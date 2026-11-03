
import random

from dsh_game_core.experience import Context, Outcome
from dsh_game_core.learner import EpisodeTrace, Learner


def context_for(side: str) -> Context:
    return Context(scene="gameplay", hp=3, threat_side=side, threat_ttc=0.3,
                   threat_distance=0.2, space_left=0.3, space_right=0.7, move_type="charge")


def run_episode(learner: Learner, side: str, rng: random.Random, *, learn: bool) -> float:
    context = context_for(side)
    actions = ["jump", "advance"]
    action = learner.choose(context, actions, epsilon=0.0) if learn else rng.choice(actions)
    if side == "left":
        reward = 1.0 if action == "jump" else -1.0
    else:
        reward = 1.0 if action == "advance" else -1.0
    if learn:
        trace = EpisodeTrace()
        trace.add(context, action, Outcome(damage=0 if reward > 0 else 1, progress_delta=0.2))
        learner.apply(trace)
    return reward


def test_learning_curve_improves():
    rng = random.Random(7)
    learner = Learner()
    sides = ["left", "right"]
    early = [run_episode(learner, sides[i % 2], rng, learn=True) for i in range(20)]
    late = [run_episode(learner, sides[i % 2], rng, learn=True) for i in range(20, 60)]
    assert sum(late) / len(late) > sum(early) / len(early) + 0.1
