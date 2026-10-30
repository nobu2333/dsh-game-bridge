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
    ):
        self.engine = engine or GameEngine()
        self.gate = gate or SafetyGate()
        self.backend = control_backend or os.environ.get("DSH_GAME_BRIDGE_CONTROL", "dry-run")
        self.audit = audit or AuditLog(os.environ.get("DSH_GAME_BRIDGE_AUDIT_LOG") or None)
        self._window_resolver = window_resolver
        self._window_rect_source = window_rect_source
        self._window_monitor_source = window_monitor_source
        self._controller = None
        self.attached: dict | None = None
        self.history: list[dict] = []
        self._plan: dict | None = None
        self._plan_thread: threading.Thread | None = None
        self._plan_stop = threading.Event()

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
        # 重新 attach 视为用户重新授权：清掉夺权闩锁，并丢掉旧的帧差基线。
        self.gate.reset_takeover()
        reset_diff = getattr(self.engine, "reset_diff", None)
        if callable(reset_diff):
            reset_diff()
        warmup = getattr(self.engine, "warmup_capture", None)
        if callable(warmup):
            warmup((self.attached or {}).get("monitor"))
        safety = self.gate.evaluate().to_dict()
        self.audit.write(
            {
                "event": "attach",
                "window": self.attached["window"],
                "hwnd": self.attached.get("hwnd"),
                "backend": self.backend,
                "safety": safety,
            }
        )
        return {"attached": self.attached, "backend": self.backend, "safety": safety}

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
        action = self._controller_instance().press(button, duration)
        entry = {**action, "at_ms": int(time.time() * 1000)}
        self.history.append(entry)
        self.audit.write({"event": "act", "button": action.get("button"), "duration_ms": duration, "backend": action.get("backend"), "dry_run": action.get("dry_run")})
        return {"action": action, "safety": report.to_dict(), "attached": self.attached, "actions_total": len(self.history)}

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
        }
        self._plan = state
        self._plan_stop.clear()
        self.audit.write({"event": "plan_start", "plan": state["id"], "mode": mode, "button": button, "duration_ms": duration})
        self._plan_thread = threading.Thread(target=self._run_plan, args=(state,), daemon=True)
        self._plan_thread.start()
        return {"plan": self._plan_snapshot(), "safety": report.to_dict()}

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

    def stop(self) -> dict:
        self._stop_plan(join=True)
        if self._controller is not None:
            self._controller.release_all()
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

    def snapshot(self, *, ocr: bool = True, max_width: int | None = None) -> dict:
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
        return self.engine.snapshot(ocr=ocr, max_width=max_width, region=region, monitor=monitor)

    def close(self) -> None:
        self._stop_plan(join=True)
        if self._controller is not None:
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        self.engine.close()
