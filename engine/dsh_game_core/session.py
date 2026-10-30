"""会话：把「眼睛（engine）」「手（controller）」「小脑（20 Hz 闭环）」与安全闸绑在一起。

M3 的闭环是一个**本地线程**，不是让模型每拍调一次工具：模型给一个目标
（hold 某个方向 / 连点某个键，持续 N 毫秒），线程以约 20 Hz 运行，
**每一拍都重新过安全闸**——F12 夺回或反作弊出现都能在一拍内停手。

安全闸的实现与单步 act 完全共用，不允许出现「闭环路径绕过检查」。
"""

from __future__ import annotations

import os
import threading
import time

from .audit import AuditLog
from .control import DryRunController, SendInputController, VGamepadController
from .engine import EngineError, GameEngine
from .safety import SafetyGate

DEFAULT_BUTTON_DURATION_MS = 80
MAX_BUTTON_DURATION_MS = 2000
TICK_S = 0.05  # 20 Hz
MIN_PLAN_MS = 100
MAX_PLAN_MS = 120_000
DEFAULT_TAP_INTERVAL_MS = 150
DEFAULT_STUCK_MS = 800
DEFAULT_ESCAPE_MS = 150

# 「advance」卡住时往哪侧脱困：上下方向的侧移取左右，反之取上下。
DIRECTION_SIDES = {
    "DPAD_UP": ("DPAD_LEFT", "DPAD_RIGHT"),
    "DPAD_DOWN": ("DPAD_LEFT", "DPAD_RIGHT"),
    "DPAD_LEFT": ("DPAD_UP", "DPAD_DOWN"),
    "DPAD_RIGHT": ("DPAD_UP", "DPAD_DOWN"),
}


class GameSession:
    def __init__(
        self,
        engine: GameEngine | None = None,
        gate: SafetyGate | None = None,
        control_backend: str | None = None,
        audit: AuditLog | None = None,
        window_resolver=None,
        window_rect_source=None,
        window_monitor_source=None,
        foreground_source=None,
        occlusion_source=None,
    ):
        self.engine = engine or GameEngine()
        self.gate = gate or SafetyGate()
        self.backend = control_backend or os.environ.get("DSH_GAME_BRIDGE_CONTROL", "dry-run")
        self.audit = audit or AuditLog(os.environ.get("DSH_GAME_BRIDGE_AUDIT_LOG") or None)
        self._window_resolver = window_resolver
        self._window_rect_source = window_rect_source
        self._window_monitor_source = window_monitor_source
        self._foreground_source = foreground_source
        self._occlusion_source = occlusion_source
        self._controller = None
        self.attached: dict | None = None
        self.history: list[dict] = []
        self._plan: dict | None = None
        self._plan_thread: threading.Thread | None = None
        self._plan_stop = threading.Event()
        self._policy = None
        self._scene_cache = {"scene": None, "confidence": 0.0, "ts": 0.0}
        self._scene_stop = None
        self._scene_thread = None
        self._recorder = None
        self._record_next_at = 0.0
        self._record_game = "unknown"
        self._record_level = "level"
        self._last_recorded_scene = None
        self._last_hp: int | None = None

    # ── 窗口 ──────────────────────────────────────────────────────────
    def _resolve_window(self, match: str) -> dict | None:
        if self._window_resolver is not None:
            return self._window_resolver(match)
        from .windows import resolve_window

        return resolve_window(match)

    def _window_rect(self, hwnd: int):
        if self._window_rect_source is not None:
            return self._window_rect_source(hwnd)
        from .windows import window_rect

        return window_rect(hwnd)

    def _window_monitor(self, hwnd: int):
        if self._window_monitor_source is not None:
            return self._window_monitor_source(hwnd)
        from .windows import monitor_for_window

        return monitor_for_window(hwnd)

    def _window_titles(self) -> list[str]:
        from .windows import list_windows

        return [window["title"] for window in list_windows()[:8]]

    # ── 前台 / 遮挡 ───────────────────────────────────────────────────
    def _foreground(self) -> dict | None:
        if self._foreground_source is not None:
            return self._foreground_source()
        from .windows import foreground_window

        return foreground_window()

    def _occlusion(self, hwnd: int) -> dict | None:
        if self._occlusion_source is not None:
            return self._occlusion_source(hwnd)
        from .windows import window_occlusion

        return window_occlusion(hwnd)

    def _foreground_is_attached(self, foreground: dict | None) -> bool | None:
        """attached.hwnd 是否就是当前前台窗口；无法判断时返回 None。"""
        hwnd = (self.attached or {}).get("hwnd")
        if not hwnd or not isinstance(foreground, dict):
            return None
        return int(foreground.get("hwnd") or 0) == int(hwnd)

    def _delivery(self, foreground: dict | None) -> dict:
        same = self._foreground_is_attached(foreground)
        return {
            "checked": same is not None,
            "foreground": same,
            "hwnd": (self.attached or {}).get("hwnd"),
            "title": foreground.get("title") if isinstance(foreground, dict) else None,
        }

    def _foreground_required(self) -> bool:
        """真实后端才强制前台；dry-run 只记录，不因此拒绝。"""
        return (self.backend or "dry-run").lower() not in ("dry-run",)

    def _foreground_message(self, foreground: dict | None) -> str:
        title = foreground.get("title") if isinstance(foreground, dict) else None
        target = (self.attached or {}).get("window") or "目标窗口"
        return (
            f"{target} 不是前台窗口（当前前台：{title or '未知'}）；"
            "XInput/键盘输入只会送到前台窗口。把游戏切回前台（或让 DSH 窗口让出焦点）后再试；"
            "dry-run 下不会因此拒绝。"
        )

    def _backend_hint(self, control: dict) -> str:
        backend = (self.backend or "dry-run").lower()
        detail = str(control.get("detail") or "unknown error")
        if backend in ("vgamepad", "gamepad"):
            return (
                f"真实手柄后端不可用：{detail}；vgamepad 没装进引擎环境时，"
                "请在同一 venv 里安装（uv pip install --python <engine-python> vgamepad），"
                "或把 DSH_GAME_BRIDGE_CONTROL 切回 dry-run。"
            )
        if backend in ("keyboard", "sendinput"):
            return f"键盘后端不可用：{detail}；检查 DSH_GAME_BRIDGE_CONTROL 与 Win32 环境。"
        return f"输出后端 {backend} 不可用：{detail}"

    def backend_status(self, *, probe: bool = False) -> dict:
        """当前输出后端的就绪状态（供 attach/status 与 selftest 共用）。"""
        backend = (self.backend or "dry-run").lower()
        if backend == "dry-run":
            return {
                "backend": "dry-run",
                "ready": True,
                "detail": "records actions only",
                "xinput_slot": None,
                "warnings": [],
            }
        if self._controller is None and not probe:
            return {
                "backend": backend,
                "ready": None,
                "detail": "not initialized (attach probes the backend)",
                "xinput_slot": None,
                "warnings": [],
            }
        try:
            controller = self._controller_instance()
        except Exception as error:  # noqa: BLE001 - 就绪报告不应该炸
            return {
                "backend": backend,
                "ready": False,
                "detail": f"{type(error).__name__}: {error}",
                "xinput_slot": None,
                "warnings": [],
            }
        info = {
            "backend": backend,
            "ready": True,
            "detail": "",
            "xinput_slot": None,
            "warnings": [],
        }
        reported = getattr(controller, "backend_info", None)
        if callable(reported):
            try:
                info.update(reported())
            except Exception as error:  # noqa: BLE001
                info["ready"] = False
                info["detail"] = f"backend_info failed: {type(error).__name__}: {error}"
        return info

    # ── 手 ────────────────────────────────────────────────────────────
    def _controller_instance(self):
        if self._controller is None:
            backend = (self.backend or "dry-run").lower()
            if backend == "dry-run":
                self._controller = DryRunController()
            elif backend in ("vgamepad", "gamepad"):
                self._controller = VGamepadController()
            elif backend in ("keyboard", "sendinput"):
                self._controller = SendInputController()
            else:
                raise EngineError(
                    "BAD_CONTROL_BACKEND",
                    f"未知输出后端：{self.backend!r}（只支持 dry-run / vgamepad / keyboard）",
                )
        return self._controller

    def attach(self, params: dict | None = None) -> dict:
        params = params or {}
        match = str(params.get("window") or "").strip()
        if match and match.lower() != "unspecified":
            window = self._resolve_window(match)
            if window is None:
                titles = self._window_titles()
                raise EngineError(
                    "WINDOW_NOT_FOUND",
                    f"找不到标题包含 {match!r} 的窗口；当前可见窗口（前 8 个）：{titles}",
                )
            self.attached = {
                "window": window["title"],
                "hwnd": window["hwnd"],
                "process": window.get("process"),
                "left": window.get("left"),
                "top": window.get("top"),
                "width": window.get("width"),
                "height": window.get("height"),
                "monitor": self._window_monitor(window["hwnd"]),
                "attached_at_ms": int(time.time() * 1000),
            }
        else:
            # 不指定窗口时退回整屏（仍是有用的兜底，但模型应优先 attach 具体窗口）。
            self.attached = {"window": "unspecified", "attached_at_ms": int(time.time() * 1000)}
        # 真实后端：attach 时做一次就绪预检（会创建虚拟手柄），失败 fail-fast，
        # 不把「attach 成功、第一次 act 才炸」的问题留给模型。
        control = self.backend_status(probe=True)
        if self._foreground_required() and not control.get("ready"):
            self.attached = None
            raise EngineError("BACKEND_UNAVAILABLE", self._backend_hint(control))
        # 重新 attach 视为用户重新授权：清掉夺权闩锁，并丢掉旧的帧差基线。
        self.gate.reset_takeover()
        reset_diff = getattr(self.engine, "reset_diff", None)
        if callable(reset_diff):
            reset_diff()
        warmup = getattr(self.engine, "warmup_capture", None)
        if callable(warmup):
            warmup((self.attached or {}).get("monitor"))
        safety = self.gate.evaluate().to_dict()
        foreground = self._foreground()
        self.audit.write(
            {
                "event": "attach",
                "window": self.attached["window"],
                "hwnd": self.attached.get("hwnd"),
                "backend": self.backend,
                "safety": safety,
                "foreground": foreground,
            }
        )
        return {
            "attached": self.attached,
            "backend": self.backend,
            "safety": safety,
            "control": control,
            "foreground": foreground,
        }

    def act(self, params: dict | None = None) -> dict:
        params = params or {}
        if self.attached is None:
            raise EngineError("NOT_ATTACHED", "还没有 attach 任何窗口：先调 game_attach，再调 game_act")
        report = self.gate.evaluate()
        if not report.allowed:
            self.audit.write({"event": "act_blocked", "reasons": report.reasons})
            raise EngineError("SAFETY_BLOCKED", "；".join(report.reasons))
        button = str(params.get("button") or "A")
        try:
            duration = int(params.get("duration_ms") or DEFAULT_BUTTON_DURATION_MS)
        except (TypeError, ValueError) as error:
            raise EngineError("BAD_DURATION", f"duration_ms 不是整数：{params.get('duration_ms')!r}") from error
        duration = max(1, min(duration, MAX_BUTTON_DURATION_MS))
        foreground = self._foreground()
        delivery = self._delivery(foreground)
        if self._foreground_required() and delivery["checked"] and not delivery["foreground"]:
            self.audit.write({"event": "act_blocked", "reasons": ["foreground mismatch"], "foreground": foreground})
            raise EngineError("FOREGROUND_MISMATCH", self._foreground_message(foreground))
        action = self._controller_instance().press(button, duration)
        entry = {**action, "at_ms": int(time.time() * 1000)}
        self.history.append(entry)
        self.audit.write(
            {
                "event": "act",
                "button": action.get("button"),
                "duration_ms": duration,
                "backend": action.get("backend"),
                "dry_run": action.get("dry_run"),
                "delivery": delivery,
            }
        )
        return {
            "action": action,
            "safety": report.to_dict(),
            "attached": self.attached,
            "actions_total": len(self.history),
            "delivery": delivery,
        }

    # ── 小脑：20 Hz 闭环 ──────────────────────────────────────────────
    def plan(self, params: dict | None = None) -> dict:
        params = params or {}
        if self.attached is None:
            raise EngineError("NOT_ATTACHED", "还没有 attach 任何窗口：先调 game_attach，再调 game_plan")
        mode = str(params.get("mode") or "hold").lower()
        if mode not in ("hold", "tap", "advance"):
            raise EngineError("BAD_PLAN_MODE", f"mode 只支持 hold / tap / advance，收到 {mode!r}")
        button = str(params.get("button") or "A")
        try:
            duration = int(params.get("duration_ms") or 1000)
            interval = int(params.get("tap_interval_ms") or DEFAULT_TAP_INTERVAL_MS)
            stuck_after_ms = int(params.get("stuck_after_ms") or DEFAULT_STUCK_MS)
            escape_tap_ms = int(params.get("escape_tap_ms") or DEFAULT_ESCAPE_MS)
        except (TypeError, ValueError) as error:
            raise EngineError("BAD_PLAN_PARAM", f"plan 参数不是整数：{error}") from error
        duration = max(MIN_PLAN_MS, min(duration, MAX_PLAN_MS))
        interval = max(20, min(interval, 1000))
        stuck_after_ms = max(200, min(stuck_after_ms, 10_000))
        escape_tap_ms = max(30, min(escape_tap_ms, 1000))

        report = self.gate.evaluate()
        if not report.allowed:
            self.audit.write({"event": "plan_blocked", "reasons": report.reasons})
            raise EngineError("SAFETY_BLOCKED", "；".join(report.reasons))

        # 真实后端：闭环开始前先确认目标窗口在前台；运行中每拍再复检（下面 _run_plan）。
        foreground = self._foreground()
        delivery = self._delivery(foreground)
        if self._foreground_required() and delivery["checked"] and not delivery["foreground"]:
            self.audit.write({"event": "plan_blocked", "reasons": ["foreground mismatch"], "foreground": foreground})
            raise EngineError("FOREGROUND_MISMATCH", self._foreground_message(foreground))

        self._stop_plan(join=True)
        state = {
            "id": f"plan-{int(time.time() * 1000)}",
            "mode": mode,
            "button": button,
            "duration_ms": duration,
            "tap_interval_ms": interval,
            "stuck_after_ms": stuck_after_ms,
            "escape_tap_ms": escape_tap_ms,
            "started_at_ms": int(time.time() * 1000),
            "ended_at_ms": None,
            "ticks": 0,
            "actions": 0,
            "escapes": 0,
            "last_event": None,
            "status": "running",
            "stop_reason": None,
            "foreground_lost": False,
        }
        self._plan = state
        self._plan_stop.clear()
        self.audit.write({"event": "plan_start", "plan": state["id"], "mode": mode, "button": button, "duration_ms": duration})
        self._plan_thread = threading.Thread(target=self._run_plan, args=(state,), daemon=True)
        self._plan_thread.start()
        return {
            "plan": self._plan_snapshot(),
            "safety": report.to_dict(),
            "control": self.backend_status(),
            "foreground": foreground,
        }

    def _diff_event(self) -> dict | None:
        """在闭环里取一次帧差分事件；引擎异常时返回 None（闭环继续走）。"""
        monitor = (self.attached or {}).get("monitor")
        try:
            return self.engine.grab_diff(monitor=monitor)
        except Exception:  # noqa: BLE001 - 差分失败不该让闭环崩掉
            return None

    def _run_plan(self, state: dict) -> None:
        controller = self._controller_instance()
        mode = state["mode"]
        button = state["button"]
        hwnd = (self.attached or {}).get("hwnd")
        require_foreground = self._foreground_required() and bool(hwnd)
        deadline = time.monotonic() + state["duration_ms"] / 1000.0
        holds_direction = mode in ("hold", "advance")
        if holds_direction:
            controller.hold(button)
            state["actions"] += 1
        static_ms = 0.0
        previous_iteration = time.monotonic()
        try:
            while not self._plan_stop.is_set():
                iteration = time.monotonic()
                # 用真实经过时间累积「静止」时长：一拍的抓屏/差分可能远慢于 50ms，
                # 用固定 TICK 会让阈值失真（实测首拍 DXcam 初始化 ~340ms）。
                dt_ms = min((iteration - previous_iteration) * 1000.0, 500.0)
                previous_iteration = iteration
                if iteration >= deadline:
                    state["status"] = "completed"
                    break
                report = self.gate.evaluate()
                if not report.allowed:
                    state["status"] = "aborted"
                    state["stop_reason"] = "；".join(report.reasons)
                    break
                if require_foreground:
                    foreground = self._foreground()
                    if self._foreground_is_attached(foreground) is False:
                        title = foreground.get("title") if isinstance(foreground, dict) else None
                        state["status"] = "aborted"
                        state["foreground_lost"] = True
                        state["stop_reason"] = f"foreground lost (now: {title or 'unknown'})"
                        break
                if mode == "tap":
                    controller.press(button, 30)
                    state["actions"] += 1
                elif mode == "advance":
                    # 撞墙检测：画面连续静止超过阈值，就朝垂直方向短促侧移再继续走。
                    event = self._diff_event()
                    state["last_event"] = event.get("event") if event else "unknown"
                    if event and event.get("event") == "static":
                        static_ms += dt_ms
                    else:
                        static_ms = 0.0
                    if static_ms >= state["stuck_after_ms"]:
                        sides = DIRECTION_SIDES.get(button.upper())
                        if sides:
                            side = sides[state["escapes"] % len(sides)]
                            controller.release(button)
                            controller.press(side, state["escape_tap_ms"])
                            controller.hold(button)
                            state["actions"] += 2
                            state["escapes"] += 1
                        static_ms = 0.0
                state["ticks"] += 1
                # 用固定节拍推进；长循环里 sleep 被中断也不会漂太多。
                self._plan_stop.wait(TICK_S)
        finally:
            if holds_direction:
                controller.release(button)
            state["ended_at_ms"] = int(time.time() * 1000)
            self.audit.write(
                {
                    "event": "plan_end",
                    "plan": state["id"],
                    "status": state["status"],
                    "ticks": state["ticks"],
                    "actions": state["actions"],
                    "stop_reason": state["stop_reason"],
                }
            )

    def _plan_snapshot(self) -> dict | None:
        if self._plan is None:
            return None
        snapshot = dict(self._plan)
        elapsed = (snapshot.get("ended_at_ms") or int(time.time() * 1000)) - snapshot["started_at_ms"]
        snapshot["elapsed_ms"] = elapsed
        snapshot["hz"] = round(snapshot["ticks"] / (elapsed / 1000.0), 1) if elapsed > 0 else 0.0
        return snapshot

    def _stop_plan(self, join: bool = True) -> None:
        self._plan_stop.set()
        if self._plan is not None and self._plan.get("status") == "running":
            self._plan["status"] = "stopped"
        if join and self._plan_thread is not None and self._plan_thread.is_alive():
            self._plan_thread.join(timeout=1.5)
        self._plan_thread = None

    def _data_root(self) -> str:
        return os.environ.get("DSH_GAME_BRIDGE_DATA_DIR") or os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "dsh-game-bridge"
        )

    def _record_frame(self, frame) -> None:
        recorder = self._recorder
        if recorder is None or frame is None:
            return
        now = time.monotonic()
        if now < self._record_next_at:
            return
        self._record_next_at = now + 0.12  # ~8 fps 缩略图足够复盘
        recorder.add_frame(frame, None)

    def _save_episode(self, tag: str) -> str | None:
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            return None
        recorder.add_event({"type": "episode_end", "tag": tag})
        return recorder.save(f"{self._record_level}-{tag}")

    def _maybe_record_scene(self, scene: str) -> None:
        if self._recorder is None or scene == self._last_recorded_scene:
            return
        self._last_recorded_scene = scene
        if scene in ("death", "equip", "cutscene"):
            self._recorder.add_event({"type": "scene", "scene": scene})
            self._save_episode(scene)
            self._start_recorder()  # 继续录下一段

    def _maybe_record_hp(self, hp: int | None) -> None:
        """HP 下降时立刻落盘，并生成/更新一张 candidate DangerCard。"""
        if hp is None:
            return
        previous, self._last_hp = self._last_hp, int(hp)
        if self._recorder is None or previous is None or hp >= previous:
            return
        self._recorder.add_event(
            {"type": "damage", "hp_before": previous, "hp_after": int(hp)}
        )
        episode = self._save_episode("damage")
        self._record_damage_card(previous, int(hp), episode)
        self._start_recorder()

    def _attribute_damage(self, policy_status: dict) -> dict:
        """受击归因：找离玩家最近的轨迹，粗分 contact/projectile。"""
        player = policy_status.get("player") if isinstance(policy_status.get("player"), dict) else {}
        tracks = policy_status.get("tracks") if isinstance(policy_status.get("tracks"), list) else []
        try:
            px = float(player.get("x"))
            py = float(player.get("y"))
        except (TypeError, ValueError):
            return {"kind": "unknown", "template": "", "relation": "unknown", "cause": "unknown"}
        best = None
        for track in tracks:
            if not isinstance(track, dict):
                continue
            try:
                tx = float(track.get("x"))
                ty = float(track.get("y"))
            except (TypeError, ValueError):
                continue
            distance = ((tx - px) ** 2 + (ty - py) ** 2) ** 0.5
            if best is None or distance < best[0]:
                best = (distance, track)
        if best is None or best[0] > 0.28:
            return {"kind": "unknown", "template": "", "relation": "unknown", "cause": "unknown"}
        distance, track = best
        dx = float(track.get("x", px)) - px
        if abs(dx) <= 0.04:
            relation = "same"
        elif abs(dx) >= abs(float(track.get("y", py)) - py):
            relation = "ahead" if dx > 0 else "behind"
        else:
            relation = "below" if float(track.get("y", py)) > py else "above"
        speed = abs(float(track.get("speed") or 0.0))
        if distance <= 0.12:
            cause = "contact"
        elif speed >= 0.3:
            cause = "projectile"
        else:
            cause = "unknown"
        return {
            "kind": str(track.get("kind") or "threat")[:32],
            "template": "",
            "relation": relation,
            "cause": cause,
        }

    def _record_damage_card(self, hp_before: int, hp_after: int, episode: str | None) -> None:
        """把一次受击写成带关卡坐标/归因的 candidate 卡；同区域已有卡则累加统计。"""
        try:
            from .memory import KnowledgeStore

            policy_status = self._policy.status() if self._policy is not None else {}
            scroll_s = float(policy_status.get("scroll_s") or 0.0)
            nearby = policy_status.get("danger") if isinstance(policy_status.get("danger"), dict) else None
            attribution = self._attribute_damage(policy_status)
            store = KnowledgeStore(os.path.join(self._data_root(), "knowledge"))
            if nearby and nearby.get("id"):
                book = store.load(self._record_game, self._record_level)
                for card in book["cards"]:
                    if card["id"] != nearby["id"]:
                        continue
                    card["stats"]["damage_events"] = int(card["stats"].get("damage_events", 0)) + 1
                    card["stats"]["encounters"] = int(card["stats"].get("encounters", 0)) + 1
                    card["confidence"] = round(min(1.0, float(card.get("confidence", 0.3)) + 0.1), 3)
                    if attribution["cause"] != "unknown":
                        card["event"]["cause"] = attribution["cause"]
                    if card["trigger"].get("kind") in ("", "unknown") and attribution["kind"] != "unknown":
                        card["trigger"].update(
                            {
                                "kind": attribution["kind"],
                                "template": attribution["template"],
                                "relation": attribution["relation"],
                            }
                        )
                    if episode:
                        card["evidence"] = (card.get("evidence") or [])[-7:] + [episode]
                    store.save(self._record_game, self._record_level, book["cards"])
                    return
            card = {
                "game": self._record_game,
                "level": self._record_level,
                "place": {
                    "scroll_s": scroll_s,
                    "segment": int(scroll_s // 1.0),
                    "player_x": policy_status.get("player", {}).get("x", 0.4)
                    if isinstance(policy_status.get("player"), dict)
                    else 0.4,
                    "player_y": 0.8,
                },
                "trigger": {
                    "kind": attribution["kind"],
                    "template": attribution["template"],
                    "relation": attribution["relation"],
                },
                "event": {"type": "damage", "cause": attribution["cause"], "hp_before": hp_before, "hp_after": hp_after},
                "response": {"skill": "unknown"},
                "evidence": [episode] if episode else [],
                "stats": {"encounters": 1, "damage_events": 1, "avoided": 0},
                "confidence": 0.35,
                "status": "candidate",
            }
            store.upsert(card)
        except Exception:  # noqa: BLE001 - 记忆写入失败不影响游戏
            pass

    def _start_recorder(self) -> None:
        if self._recorder is not None:
            return
        from .recorder import EpisodeRecorder

        root = os.path.join(self._data_root(), "episodes")
        self._recorder = EpisodeRecorder(root, version="0.0.2")
        self._recorder.start(
            {
                "game": self._record_game,
                "level": self._record_level,
                "profile": self._record_game,
            }
        )
        self._record_next_at = 0.0
        self._last_recorded_scene = None

    def _stop_policy(self) -> None:
        """停掉本地反射策略并确保所有按键已释放。"""
        self._stop_scene_watcher()
        policy, self._policy = self._policy, None
        if policy is not None:
            try:
                policy.stop()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        self._save_episode("stop")

    # ── 异步场景识别（慢环写缓存，60Hz 快环只读） ──────────────────────
    def _scene_interval_s(self, profile: dict | None) -> float:
        section = (profile or {}).get("scene") if isinstance(profile, dict) else None
        try:
            value = float((section or {}).get("refresh_ms") or 700) / 1000.0
        except (TypeError, ValueError, AttributeError):
            value = 0.7
        return max(0.25, min(value, 2.0))

    def _start_scene_watcher(self, profile: dict | None) -> None:
        self._stop_scene_watcher()
        self._scene_cache = {"scene": None, "confidence": 0.0, "ts": time.time()}
        self._scene_stop = threading.Event()
        self._scene_thread = threading.Thread(
            target=self._scene_loop,
            args=(profile if isinstance(profile, dict) else {}, self._scene_stop),
            name="dsh-game-scene",
            daemon=True,
        )
        self._scene_thread.start()

    def _stop_scene_watcher(self) -> None:
        stop, self._scene_stop = self._scene_stop, None
        if stop is not None:
            stop.set()
        thread, self._scene_thread = self._scene_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)

    def _scene_loop(self, profile: dict, stop: threading.Event) -> None:
        try:
            from .ocr import Ocr
            from .state import detect_scene, extract_hp

            ocr = Ocr()
            ocr.warmup()
        except Exception:  # noqa: BLE001 - OCR 不可用时场景保持 unknown
            return
        interval = self._scene_interval_s(profile)
        while not stop.wait(interval):
            policy = self._policy
            frame = policy.latest_frame() if policy is not None else None
            if frame is None:
                continue
            try:
                scene_profile = profile.get("scene") if isinstance(profile, dict) else None
                max_width = int((scene_profile or {}).get("ocr_max_width") or 480)
                if frame.shape[1] > max_width:
                    import cv2

                    frame = cv2.resize(
                        frame,
                        (max_width, max(1, int(round(frame.shape[0] * max_width / frame.shape[1])))),
                        interpolation=cv2.INTER_AREA,
                    )
                lines = [line.to_dict() for line in ocr.read(frame)]
                hp, _hp_text = extract_hp(
                    lines, profile=profile, frame_size=(int(frame.shape[1]), int(frame.shape[0]))
                )
                scene, confidence = detect_scene(lines, profile=profile, hp=hp)
                self._scene_cache = {
                    "scene": scene,
                    "confidence": float(confidence),
                    "hp": hp,
                    "ts": time.time(),
                }
                self._maybe_record_hp(hp)
                self._maybe_record_scene(scene)
            except Exception:  # noqa: BLE001 - 单次 OCR 失败不终止慢环
                continue

    def stop(self) -> dict:
        self._stop_policy()
        self._stop_plan(join=True)
        if self._controller is not None:
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 松手失败不掩盖解绑
                pass
            close = getattr(self._controller, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
                self._controller = None
        self.attached = None
        self.gate.reset_takeover()
        self.audit.write({"event": "stop", "actions_total": len(self.history)})
        return {"stopped": True, "actions_total": len(self.history), "plan": self._plan_snapshot()}

    def status(self) -> dict:
        return {
            "attached": self.attached,
            "backend": self.backend,
            "safety": self.gate.evaluate().to_dict(),
            "actions_total": len(self.history),
            "last_action": self.history[-1] if self.history else None,
            "plan": self._plan_snapshot(),
            "audit": {"path": self.audit.path, "tail": self.audit.tail(5)},
            "control": self.backend_status(),
            "foreground": self._foreground(),
            "policy": self._policy.status() if self._policy is not None else None,
        }

    # ── 眼 ────────────────────────────────────────────────────────────
    def controls(self) -> dict:
        """当前后端支持哪些按钮/按键——省得模型瞎猜键名。"""
        from .control import VK_CODES

        backend = (self.backend or "dry-run").lower()
        if backend in ("vgamepad", "gamepad"):
            buttons = sorted(VGamepadController.BUTTONS)
            note = "Xbox 360 gamepad buttons"
        elif backend in ("keyboard", "sendinput"):
            buttons = sorted(VK_CODES)
            note = "keyboard keys (SendInput)"
        elif backend == "dry-run":
            buttons = sorted(set(VGamepadController.BUTTONS) | set(VK_CODES))
            note = "dry-run records any name; a real backend validates against its own list"
        else:
            buttons = []
            note = f"unknown backend {backend!r}"
        return {"backend": backend, "buttons": buttons, "note": note}

    def windows(self, limit: int = 40) -> dict:
        """列出当前可见窗口，供模型自己挑 attach 目标。"""
        from .windows import list_windows

        items = [
            {
                "title": window["title"],
                "process": window.get("process"),
                "width": window["width"],
                "height": window["height"],
            }
            for window in list_windows()[: max(1, limit)]
        ]
        return {"windows": items, "count": len(items)}

    def events(self) -> dict:
        """帧差分事件：不截图、不做 OCR 的廉价「刚才发生了什么」。"""
        monitor = (self.attached or {}).get("monitor")
        return self.engine.grab_diff(monitor=monitor)

    def _capture_geometry(self) -> tuple[dict | None, dict | None]:
        """返回 (region, monitor)：attach 窗口在屏幕/显示器上的裁剪区。"""
        region = None
        monitor = None
        attached = self.attached or {}
        hwnd = attached.get("hwnd")
        if hwnd:
            rect = self._window_rect(hwnd)
            if rect is not None:
                left, top, right, bottom = rect
                monitor = attached.get("monitor") or self._window_monitor(hwnd)
                if monitor:
                    # 换算成「相对该显示器」的裁剪区：多显示器下窗口可能在副屏，
                    # 而抓屏是按 output（显示器）来的。
                    region = {
                        "left": left - monitor["left"],
                        "top": top - monitor["top"],
                        "width": right - left,
                        "height": bottom - top,
                    }
                else:
                    region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        return region, monitor

    def snapshot(self, *, ocr: bool = True, max_width: int | None = None) -> dict:
        region, monitor = self._capture_geometry()
        frame = self.engine.snapshot(ocr=ocr, max_width=max_width, region=region, monitor=monitor)
        if isinstance(frame, dict):
            # 「我拍到的画面是不是目标窗口」：前台 + 遮挡元数据，让模型/用户能看出
            # 截到的是被别的窗口盖住的画面（整屏抓 + 裁剪的已知限制）。
            frame["foreground"] = self._foreground()
            hwnd = (self.attached or {}).get("hwnd")
            if hwnd:
                frame["occluded"] = self._occlusion(hwnd)
        return frame

    # ── 通用状态 / 反射策略 ─────────────────────────────────────────────
    def state(self, params: dict | None = None) -> dict:
        """抓一帧并提取通用 WorldState（视觉保底；profile 只提供键位/HUD/阈值）。"""
        params = params or {}
        profile = params.get("profile")
        if not isinstance(profile, dict):
            profile = None
        region, monitor = self._capture_geometry()
        captured = self.engine.snapshot(
            ocr=True,
            max_width=params.get("max_width") or 960,
            region=region,
            monitor=monitor,
        )
        import base64

        import cv2
        import numpy as np

        raw = base64.b64decode(captured.get("png_b64") or "")
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
        from .state import extract_visual_state

        state = extract_visual_state(frame, captured.get("ocr") or [], profile=profile)
        state["foreground"] = self._foreground()
        hwnd = (self.attached or {}).get("hwnd")
        if hwnd:
            state["occluded"] = self._occlusion(hwnd)
        game = state.setdefault("game", {})
        game["profile"] = (profile or {}).get("id")
        state["backend"] = self.backend
        return state

    def _focus_attached(self) -> bool:
        hwnd = (self.attached or {}).get("hwnd")
        if not hwnd:
            return False
        from .windows import focus_window

        return focus_window(int(hwnd))

    def policy_start(self, params: dict | None = None) -> dict:
        """启动本地 60 Hz 反射策略（profile 驱动：射击/前进/闪避/卡住脱困）。"""
        params = params or {}
        if self.attached is None:
            raise EngineError("NOT_ATTACHED", "还没有 attach 任何窗口：先调 game_attach，再调 game_policy")
        profile = params.get("profile")
        profile = dict(profile) if isinstance(profile, dict) else {}
        self._record_game = str(params.get("game") or profile.get("id") or "unknown")[:48]
        self._record_level = str(params.get("level") or "level")[:48]
        self._last_hp = None
        if params.get("knowledge", True):
            try:
                from .memory import KnowledgeStore

                store = KnowledgeStore(os.path.join(self._data_root(), "knowledge"))
                cards = store.load(self._record_game, self._record_level)["cards"]
                if cards:
                    profile["danger_cards"] = cards
            except Exception:  # noqa: BLE001 - 记忆读取失败不影响开局
                pass
        foreground = self._foreground()
        delivery = self._delivery(foreground)
        if self._foreground_required() and delivery["checked"] and not delivery["foreground"]:
            raise EngineError("FOREGROUND_MISMATCH", self._foreground_message(foreground))
        self._stop_policy()
        region, monitor = self._capture_geometry()
        from .policy import PolicyRunner

        if params.get("record"):
            self._start_recorder()

        def capture():
            frame = self.engine.grab_raw(monitor=monitor, region=region)
            self._record_frame(frame)
            return frame

        self._policy = PolicyRunner(
            capture=capture,
            controller=self._controller_instance(),
            gate=self.gate,
            profile=profile,
            tick_hz=int(params.get("tick_hz") or 60),
            foreground_ok=lambda: self._foreground_is_attached(self._foreground()),
            focus_window=self._focus_attached,
            scene_source=lambda: self._scene_cache.get("scene"),
        )
        started = self._policy.start()
        if params.get("scene_watch", True):
            self._start_scene_watcher(profile)
        self.audit.write({"event": "policy_start", "profile": (profile or {}).get("id")})
        return {"policy": started, "attached": self.attached, "backend": self.backend}

    def policy_stop(self, params: dict | None = None) -> dict:
        policy, self._policy = self._policy, None
        if policy is None:
            self._save_episode("stop")
            return {"stopped": False, "policy": None}
        status = policy.stop()
        self._stop_scene_watcher()
        self._save_episode("stop")
        self.audit.write({"event": "policy_stop", **status})
        return {"stopped": True, "policy": status}

    def close(self) -> None:
        self._stop_policy()
        self._stop_plan(join=True)
        if self._controller is not None:
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
            close = getattr(self._controller, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
            self._controller = None
        self.engine.close()
