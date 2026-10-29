"""会话：把「眼睛（engine）」「手（controller）」「小脑（20 Hz 闭环）」与安全闸绑在一起。

M3 的闭环是一个**本地线程**，不是让模型每拍调一次工具：模型给一个目标
（hold 某个方向 / 连点某个键，持续 N 毫秒），线程以约 20 Hz 运行，
**每一拍都重新过安全闸**——F12、键鼠恢复、反作弊出现都能在一拍内停手。

安全闸的实现与单步 act 完全共用，不允许出现「闭环路径绕过检查」。
"""

from __future__ import annotations

import os
import threading
import time

from .audit import AuditLog
from .control import DryRunController, VGamepadController
from .engine import EngineError, GameEngine
from .safety import SafetyGate

DEFAULT_BUTTON_DURATION_MS = 80
MAX_BUTTON_DURATION_MS = 2000
TICK_S = 0.05  # 20 Hz
MIN_PLAN_MS = 100
MAX_PLAN_MS = 120_000
DEFAULT_TAP_INTERVAL_MS = 150


class GameSession:
    def __init__(
        self,
        engine: GameEngine | None = None,
        gate: SafetyGate | None = None,
        control_backend: str | None = None,
        audit: AuditLog | None = None,
        window_resolver=None,
        window_rect_source=None,
    ):
        self.engine = engine or GameEngine()
        unattended_after_s = float(os.environ.get("DSH_GAME_BRIDGE_UNATTENDED_S", "180"))
        self.gate = gate or SafetyGate(unattended_after_s=unattended_after_s)
        self.backend = control_backend or os.environ.get("DSH_GAME_BRIDGE_CONTROL", "dry-run")
        self.audit = audit or AuditLog(os.environ.get("DSH_GAME_BRIDGE_AUDIT_LOG") or None)
        self._window_resolver = window_resolver
        self._window_rect_source = window_rect_source
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

    def _window_titles(self) -> list[str]:
        from .windows import list_windows

        return [window["title"] for window in list_windows()[:8]]

    # ── 手 ────────────────────────────────────────────────────────────
    def _controller_instance(self):
        if self._controller is None:
            if self.backend == "dry-run":
                self._controller = DryRunController()
            elif self.backend == "vgamepad":
                self._controller = VGamepadController()
            else:
                raise EngineError("BAD_CONTROL_BACKEND", f"未知输出后端：{self.backend!r}（只支持 dry-run / vgamepad）")
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
                "attached_at_ms": int(time.time() * 1000),
            }
        else:
            # 不指定窗口时退回整屏（仍是有用的兜底，但模型应优先 attach 具体窗口）。
            self.attached = {"window": "unspecified", "attached_at_ms": int(time.time() * 1000)}
        # 重新 attach 视为用户重新授权：清掉夺权闩锁。
        self.gate.reset_takeover()
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
        if mode not in ("hold", "tap"):
            raise EngineError("BAD_PLAN_MODE", f"mode 只支持 hold / tap，收到 {mode!r}")
        button = str(params.get("button") or "A")
        try:
            duration = int(params.get("duration_ms") or 1000)
            interval = int(params.get("tap_interval_ms") or DEFAULT_TAP_INTERVAL_MS)
        except (TypeError, ValueError) as error:
            raise EngineError("BAD_PLAN_PARAM", f"plan 参数不是整数：{error}") from error
        duration = max(MIN_PLAN_MS, min(duration, MAX_PLAN_MS))
        interval = max(20, min(interval, 1000))

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
            "started_at_ms": int(time.time() * 1000),
            "ended_at_ms": None,
            "ticks": 0,
            "actions": 0,
            "status": "running",
            "stop_reason": None,
        }
        self._plan = state
        self._plan_stop.clear()
        self.audit.write({"event": "plan_start", "plan": state["id"], "mode": mode, "button": button, "duration_ms": duration})
        self._plan_thread = threading.Thread(target=self._run_plan, args=(state,), daemon=True)
        self._plan_thread.start()
        return {"plan": self._plan_snapshot(), "safety": report.to_dict()}

    def _run_plan(self, state: dict) -> None:
        controller = self._controller_instance()
        mode = state["mode"]
        button = state["button"]
        deadline = time.monotonic() + state["duration_ms"] / 1000.0
        if mode == "hold":
            controller.hold(button)
            state["actions"] += 1
        try:
            while not self._plan_stop.is_set():
                now = time.monotonic()
                if now >= deadline:
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
                state["ticks"] += 1
                # 用固定节拍推进；长循环里 sleep 被中断也不会漂太多。
                self._plan_stop.wait(TICK_S)
        finally:
            if mode == "hold":
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
    def snapshot(self, *, ocr: bool = True, max_width: int | None = None) -> dict:
        region = None
        attached = self.attached or {}
        hwnd = attached.get("hwnd")
        if hwnd:
            rect = self._window_rect(hwnd)
            if rect is not None:
                left, top, right, bottom = rect
                region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        return self.engine.snapshot(ocr=ocr, max_width=max_width, region=region)

    def close(self) -> None:
        self._stop_plan(join=True)
        if self._controller is not None:
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        self.engine.close()
