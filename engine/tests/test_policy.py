"""PolicyRunner：安全闸 / 闪避冷却 / 卡住脱困 / 释放 / 状态形状。

全部用假 capture/controller/gate + 虚拟时钟驱动，不碰真实屏幕、不按键、不 OCR，
跑一次几毫秒，结果完全确定。
"""

import json
import threading
import time

import numpy as np
import pytest

from dsh_game_core.policy import PolicyRunner

PROFILE = {
    "id": "test-profile",
    "controls": {
        "left": "LEFT",
        "right": "RIGHT",
        "up": "UP",
        "down": "DOWN",
        "jump": "Z",
        "shoot": "X",
        "dash": "SHIFT",
        "confirm": "Z",
    },
    "combat": {
        "hold": ["X"],
        "advance": "RIGHT",
        "self_pos": [0.5, 0.72],
        "dodge": {"keys": ["Z"], "threat_radius": 0.18, "cooldown_ms": 200, "press_ms": 10},
        "stuck": {
            "static_mean_diff": 0.9,
            "after_ms": 600,
            "probe_ms": 350,
            "probe_keys": ["Z"],
        },
    },
}

FRAME = np.full((60, 80, 3), 10, dtype=np.uint8)

STATUS_KEYS = {
    "running",
    "ticks",
    "hz",
    "actions",
    "escapes",
    "stop_reason",
    "scene",
    "last_entities",
    "scroll_s",
    "danger",
    "player",
    "tracks",
    "hit",
}


def make_profile(**combat_overrides):
    """复制 PROFILE，并按需覆盖 combat 下的字段（嵌套 dict 做浅合并）。"""
    profile = json.loads(json.dumps(PROFILE))
    for key, value in combat_overrides.items():
        current = profile["combat"].get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            current.update(value)
        else:
            profile["combat"][key] = value
    return profile


class VirtualClock:
    """虚拟时间：sleep() 只推进时钟，不真的等，测试因此是确定性的。"""

    def __init__(self, tick_hz=60.0):
        self.now = 1000.0
        self.period = 1.0 / tick_hz
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += max(float(seconds), self.period)


class FakeGate:
    def __init__(self, allowed=True, reasons=None):
        self.allowed = allowed
        self.reasons = list(reasons or [])
        self.calls = 0

    def evaluate(self):
        self.calls += 1
        return {"allowed": self.allowed, "reasons": self.reasons}


class BlockingGate:
    """前 `allow_ticks` 拍放行，之后开始阻断（模拟 F12 夺回）。"""

    def __init__(self, allow_ticks):
        self.allow_ticks = allow_ticks
        self.calls = 0

    def evaluate(self):
        self.calls += 1
        if self.calls > self.allow_ticks:
            return {"allowed": False, "reasons": ["takeover latched (F12)"]}
        return {"allowed": True, "reasons": []}


class FakeController:
    backend = "fake"

    def __init__(self):
        self.calls = []
        self.held = set()
        self.release_all_calls = 0
        self.clock = lambda: 0.0

    def _log(self, action, button):
        self.calls.append({"action": action, "button": button, "at": self.clock()})

    def hold(self, button):
        self._log("hold", button)
        self.held.add(button)
        return {"backend": self.backend, "button": button, "hold": True, "dry_run": True}

    def release(self, button):
        self._log("release", button)
        self.held.discard(button)
        return {"backend": self.backend, "button": button, "release": True, "dry_run": True}

    def press(self, button, duration_ms):
        self.calls.append(
            {"action": "press", "button": button, "duration_ms": duration_ms, "at": self.clock()}
        )
        return {"backend": self.backend, "button": button, "duration_ms": duration_ms, "dry_run": True}

    def release_all(self):
        self.release_all_calls += 1
        self.held.clear()


def flat_entities(*entities):
    return lambda frame, previous, profile=None: list(entities)


def no_entities(frame, previous, profile=None):
    return []


def build_runner(
    *,
    controller=None,
    gate=None,
    capture=None,
    profile=None,
    entities=None,
    budget_ticks=None,
    tick_hz=60.0,
    scene_source=None,
    hp_source=None,
    on_danger_outcome=None,
):
    """构造一个由「虚拟时间 + 拍数预算」自动收尾的 runner。"""
    controller = controller or FakeController()
    gate = gate or FakeGate()
    capture = capture or (lambda: FRAME)
    virtual = VirtualClock(tick_hz)
    holder = {"runner": None}

    def sleep(seconds):
        virtual.sleep(seconds)
        if budget_ticks is not None and len(virtual.sleeps) >= budget_ticks:
            holder["runner"].stop()

    runner = PolicyRunner(
        capture=capture,
        controller=controller,
        gate=gate,
        profile=profile if profile is not None else PROFILE,
        tick_hz=tick_hz,
        clock=virtual.clock,
        sleep=sleep,
        entities=entities if entities is not None else no_entities,
        scene_source=scene_source,
        hp_source=hp_source,
        on_danger_outcome=on_danger_outcome,
    )
    holder["runner"] = runner
    controller.clock = virtual.clock
    return runner, virtual, controller


def run_to_completion(runner, timeout=2.0):
    runner.start()
    assert runner.join(timeout) is True, "policy 线程没有按预算退出"
    return runner.status()


def test_status_shape_and_noop_without_threats():
    runner, virtual, controller = build_runner(budget_ticks=6, entities=no_entities)

    status = run_to_completion(runner)

    assert set(status) == STATUS_KEYS
    assert status["running"] is False
    assert status["ticks"] == 6
    assert status["hz"] == pytest.approx(60.0, abs=0.5)
    assert status["actions"] == 2  # X（射击）+ RIGHT（前进）各按一次
    assert status["escapes"] == 0
    assert status["stop_reason"] == "stopped"
    assert status["scene"] is None
    assert status["last_entities"] == 0

    log = controller.calls
    assert [(call["action"], call["button"]) for call in log] == [("hold", "X"), ("hold", "RIGHT")]
    assert controller.release_all_calls >= 1
    assert controller.held == set()
    assert runner.last_error() is None


def test_safety_block_before_any_output():
    gate = FakeGate(allowed=False, reasons=["takeover latched (F12)"])
    runner, _, controller = build_runner(gate=gate)

    status = run_to_completion(runner)

    assert gate.calls == 1
    assert status["running"] is False
    assert status["ticks"] == 0
    assert status["stop_reason"] == "safety: takeover latched (F12)"
    assert controller.calls == []  # 安全闸先于任何输出
    assert controller.release_all_calls >= 1


def test_safety_block_after_ticks_releases_held_keys():
    gate = BlockingGate(allow_ticks=2)
    runner, _, controller = build_runner(gate=gate)

    status = run_to_completion(runner)

    assert status["ticks"] == 2
    assert status["running"] is False
    assert status["stop_reason"].startswith("safety:")
    assert gate.calls == 3  # 前两拍放行，第三拍阻断
    assert ("hold", "X") in [(call["action"], call["button"]) for call in controller.calls]
    assert all(call["action"] != "press" for call in controller.calls)
    assert controller.held == set()  # 阻断后必须松手
    assert controller.release_all_calls >= 1


def test_dodge_respects_cooldown():
    threat = {"kind": "threat", "x": 0.5, "y": 0.72, "score": 0.9}  # 正好在锚点上
    runner, virtual, controller = build_runner(budget_ticks=30, entities=flat_entities(threat))

    status = run_to_completion(runner)

    # 非阻塞点按：hold 立刻发生，release 在后续拍到期；冷却按 hold 时间计算。
    holds = [call for call in controller.calls if call["action"] == "hold" and call["button"] == "Z"]
    releases = [call for call in controller.calls if call["action"] == "release" and call["button"] == "Z"]
    assert [call["button"] for call in holds] == ["Z", "Z", "Z"]
    assert len(releases) == 3
    times_ms = [call["at"] * 1000.0 for call in holds]
    gaps = [later - earlier for earlier, later in zip(times_ms, times_ms[1:])]
    assert gaps and all(gap >= 200.0 - 1e-6 for gap in gaps)
    assert status["last_entities"] == 1
    assert status["escapes"] == 0


def test_far_threat_does_not_dodge():
    threat = {"kind": "threat", "x": 0.9, "y": 0.1, "score": 0.9}
    runner, _, controller = build_runner(budget_ticks=5, entities=flat_entities(threat))

    run_to_completion(runner)

    assert all(call["action"] != "press" for call in controller.calls)


def test_estimate_scroll_dx_detects_horizontal_shift():
    import numpy as np

    from dsh_game_core.policy import _estimate_scroll_dx

    frame = np.zeros((120, 240, 3), dtype=np.uint8)
    frame[40:80, 40:120] = 200
    shifted = np.roll(frame, 12, axis=1)
    dx = _estimate_scroll_dx(frame, shifted)
    assert dx is not None
    assert abs(dx) > 3.0


def test_stuck_escape_releases_advance_probes_and_resumes():
    runner, _, controller = build_runner(budget_ticks=50, entities=no_entities)

    status = run_to_completion(runner)

    assert status["ticks"] == 50
    assert status["escapes"] == 1
    assert status["actions"] == 5  # 2 初始 hold + release RIGHT / hold Z / re-hold RIGHT

    log = [(call["action"], call["button"]) for call in controller.calls]
    escape_at = log.index(("release", "RIGHT"))
    assert log[escape_at : escape_at + 3] == [("release", "RIGHT"), ("hold", "Z"), ("hold", "RIGHT")]
    # 只按 profile 声明过的键
    assert {button for _, button in log} <= {"X", "RIGHT", "Z"}


def test_stop_while_running_releases_all_held_keys():
    controller = FakeController()
    release_sleep = threading.Event()

    def slow_sleep(_seconds):
        release_sleep.wait(0.5)  # 让线程停在拍间，主线程可以从容 stop

    runner = PolicyRunner(
        capture=lambda: FRAME,
        controller=controller,
        gate=FakeGate(),
        profile=make_profile(stuck={"after_ms": 600_000}),
        clock=time.monotonic,
        sleep=slow_sleep,
        entities=no_entities,
    )
    runner.start()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and controller.held != {"X", "RIGHT"}:
        time.sleep(0.001)
    assert controller.held == {"X", "RIGHT"}

    status = runner.stop()

    assert status["running"] is False
    assert status["stop_reason"] == "stopped"
    assert controller.held == set()
    assert controller.release_all_calls >= 1
    assert runner.join(2.0) is True


def test_capture_failures_do_not_kill_thread_or_leave_keys_held():
    def broken_capture():
        raise RuntimeError("capture exploded")

    runner, _, controller = build_runner(budget_ticks=5, capture=broken_capture)

    status = run_to_completion(runner)

    assert status["ticks"] == 5
    assert status["running"] is False
    assert status["stop_reason"] == "stopped"
    assert controller.held == set()
    assert runner.last_error() is not None and "capture exploded" in runner.last_error()


def test_safety_gate_report_object_is_understood():
    """session 传的是 SafetyReport 对象（不是 dict）：同样要挡住并松手。"""
    from dsh_game_core.safety import SafetyReport

    class ObjectGate:
        def evaluate(self):
            return SafetyReport(allowed=False, reasons=["anti-cheat detected"])

    runner, _, controller = build_runner(gate=ObjectGate())

    status = run_to_completion(runner)

    assert status["stop_reason"] == "safety: anti-cheat detected"
    assert controller.calls == []
    assert controller.release_all_calls >= 1


def test_unrecognized_gate_report_fails_closed():
    class WeirdGate:
        def evaluate(self):
            return None

    runner, _, controller = build_runner(gate=WeirdGate())

    status = run_to_completion(runner)

    assert status["stop_reason"].startswith("safety:")
    assert controller.calls == []


def test_scene_source_is_reported():
    runner, _, _ = build_runner(budget_ticks=2, scene_source=lambda: "gameplay")

    status = run_to_completion(runner)

    assert status["scene"] == "gameplay"

def test_status_reports_nearby_danger_card():
    profile = make_profile()
    profile["danger_cards"] = [
        {
            "id": "cuphead/forest-follies/danger-test",
            "game": "cuphead",
            "level": "forest-follies",
            "place": {"scroll_s": 0.0, "player_x": 0.4},
            "trigger": {"kind": "enemy", "template": "mushroom"},
            "response": {"skill": "jump_over"},
            "status": "candidate",
        }
    ]
    runner, _, _ = build_runner(budget_ticks=6, profile=profile)
    status = run_to_completion(runner)
    assert status["danger"] is not None
    assert status["danger"]["trigger"] == "mushroom"
    assert status["danger"]["skill"] == "jump_over"

def test_candidate_danger_reflex_jumps_once():
    profile = make_profile(danger_reflex=True)
    profile["danger_cards"] = [
        {
            "id": "cuphead/forest-follies/danger-reflex",
            "game": "cuphead",
            "level": "forest-follies",
            "place": {"scroll_s": 0.0, "player_x": 0.4},
            "trigger": {"kind": "threat", "template": "mushroom"},
            "response": {"skill": "jump_over"},
            "status": "candidate",
        }
    ]
    runner, _, controller = build_runner(budget_ticks=20, profile=profile)
    status = run_to_completion(runner)
    assert status["danger"] is not None
    assert status["danger"].get("acted") is True
    jump_holds = [call for call in controller.calls if call["action"] == "hold" and call["button"] == "Z"]
    assert len(jump_holds) == 1

def test_danger_reflex_uses_dodge_key_for_evade():
    profile = make_profile(danger_reflex=True)
    profile["combat"]["dodge"]["keys"] = ["SHIFT"]
    profile["danger_cards"] = [
        {
            "id": "cuphead/forest-follies/danger-evade",
            "game": "cuphead",
            "level": "forest-follies",
            "place": {"scroll_s": 0.0},
            "trigger": {"kind": "threat"},
            "response": {"skill": "evade"},
            "status": "candidate",
        }
    ]
    runner, _, controller = build_runner(budget_ticks=20, profile=profile)
    run_to_completion(runner)
    assert any(call["action"] == "hold" and call["button"] == "SHIFT" for call in controller.calls)
    assert not any(call["action"] == "hold" and call["button"] == "Z" for call in controller.calls)

def test_danger_outcome_failed_on_hp_drop():
    profile = make_profile(danger_reflex=True)
    profile["danger_cards"] = [
        {
            "id": "cuphead/forest-follies/danger-fail",
            "game": "cuphead",
            "level": "forest-follies",
            "place": {"scroll_s": 0.0},
            "trigger": {"kind": "enemy"},
            "response": {"skill": "jump_over"},
            "status": "candidate",
        }
    ]
    outcomes = []
    hp_values = [3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
    counter = {"i": 0}

    def hp_source():
        value = hp_values[min(counter["i"], len(hp_values) - 1)]
        counter["i"] += 1
        return value

    runner, _, _ = build_runner(
        budget_ticks=12,
        profile=profile,
        hp_source=hp_source,
        on_danger_outcome=lambda card_id, outcome: outcomes.append((card_id, outcome)),
    )
    run_to_completion(runner)
    assert outcomes
    assert outcomes[0][0] == "cuphead/forest-follies/danger-fail"
    assert outcomes[0][1] == "failed"
