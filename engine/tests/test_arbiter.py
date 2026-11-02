
from dsh_game_core.arbiter import IntentArbiter, local_intent_from_skill


def test_arbiter_ttl_and_priority():
    clock = {"now": 100.0}
    arbiter = IntentArbiter({"goal": "advance", "skill": "advance", "priority": 1}, now_fn=lambda: clock["now"])
    assert arbiter.submit({"goal": "avoid", "skill": "dodge_right", "priority": 7, "ttl_ms": 100})
    current = arbiter.current()
    assert current["skill"] == "dodge_right"
    assert current["arbiter"] == "model"
    clock["now"] += 0.2
    current = arbiter.current()
    assert current["skill"] == "advance"
    assert current["arbiter"] == "local"


def test_arbiter_safety_block_and_invalid():
    arbiter = IntentArbiter({"goal": "advance", "skill": "advance", "priority": 1})
    assert arbiter.submit({"goal": "advance"}) is False
    arbiter.block("foreground lost")
    current = arbiter.current()
    assert current["skill"] == "halt"
    assert current["source"] == "safety"
    arbiter.unblock()
    assert arbiter.current()["skill"] == "advance"


def test_local_intent_from_skill():
    intent = local_intent_from_skill("attack", reason="enemy ahead", target_id=3)
    assert intent["goal"] == "attack"
    assert intent["priority"] == 1
    assert intent["target_id"] == 3
    assert local_intent_from_skill("jump")["goal"] == "avoid"
