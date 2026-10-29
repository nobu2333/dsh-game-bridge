"""会话：把「眼睛（engine）」和「手（controller）」与安全闸绑在一起。

M2 的范围只有单步动作（press）+ 状态查询；20 Hz 闭环（plan/stop）在 M3，
但它必须复用同一套 safety 判定与同一个 controller 实例——这样「无人不自娱」
与「随时可夺回」不会在两条路径上出现两种实现。
"""

from __future__ import annotations

import os
import time

from .control import DryRunController, VGamepadController
from .engine import EngineError, GameEngine
from .safety import SafetyGate

DEFAULT_BUTTON_DURATION_MS = 80
MAX_BUTTON_DURATION_MS = 2000


class GameSession:
    def __init__(
        self,
        engine: GameEngine | None = None,
        gate: SafetyGate | None = None,
        control_backend: str | None = None,
    ):
        self.engine = engine or GameEngine()
        unattended_after_s = float(os.environ.get("DSH_GAME_BRIDGE_UNATTENDED_S", "180"))
        self.gate = gate or SafetyGate(unattended_after_s=unattended_after_s)
        self.backend = control_backend or os.environ.get("DSH_GAME_BRIDGE_CONTROL", "dry-run")
        self._controller = None
        self.attached: dict | None = None
        self.history: list[dict] = []

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
        window = str(params.get("window") or "unspecified")
        self.attached = {"window": window, "attached_at_ms": int(time.time() * 1000)}
        # 重新 attach 视为用户重新授权：清掉夺权闩锁。
        self.gate.reset_takeover()
        return {"attached": self.attached, "backend": self.backend, "safety": self.gate.evaluate().to_dict()}

    def act(self, params: dict | None = None) -> dict:
        params = params or {}
        if self.attached is None:
            raise EngineError("NOT_ATTACHED", "还没有 attach 任何窗口：先调 game_attach，再调 game_act")
        report = self.gate.evaluate()
        if not report.allowed:
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
        return {"action": action, "safety": report.to_dict(), "attached": self.attached, "actions_total": len(self.history)}

    def stop(self) -> dict:
        if self._controller is not None:
            self._controller.release_all()
        self.attached = None
        self.gate.reset_takeover()
        return {"stopped": True, "actions_total": len(self.history)}

    def status(self) -> dict:
        return {
            "attached": self.attached,
            "backend": self.backend,
            "safety": self.gate.evaluate().to_dict(),
            "actions_total": len(self.history),
            "last_action": self.history[-1] if self.history else None,
        }

    # ── 眼 ────────────────────────────────────────────────────────────
    def snapshot(self, *, ocr: bool = True, max_width: int | None = None) -> dict:
        return self.engine.snapshot(ocr=ocr, max_width=max_width)

    def close(self) -> None:
        if self._controller is not None:
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
                pass
        self.engine.close()
