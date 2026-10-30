"""Fake engine fixture: canned responses for the plugin's protocol.

It exists so integration tests can drive the *plugin* (tools, schemas, image
pipeline, attach/act flow) without a real screen, real gamepad, or safety state.
Real capture/OCR and the real safety gate are covered by engine/ unit tests.
"""
import json
import os
import sys

SAFETY = {
    "allowed": True,
    "reasons": [],
    "anticheat": [],
    "takeover": False,
}

# 1x1 transparent PNG: enough for the plugin's screenshot → attachment pipeline.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

FOREGROUND = {
    "hwnd": 4242,
    "title": "Fixture Game",
    "process": "fixture.exe",
    "left": 0,
    "top": 0,
    "width": 1280,
    "height": 720,
}

CONTROL = {
    "backend": "dry-run",
    "ready": True,
    "detail": "records actions only",
    "xinput_slot": None,
    "warnings": [],
}


def backend_report():
    """selftest 的 backend 报告用 `name`（与真实引擎 selftest 一致）。"""
    report = dict(CONTROL)
    report.pop("backend", None)
    report["name"] = "dry-run"
    return report

OCCLUDED = {
    "available": True,
    "occluded_ratio": 0.0,
    "occluded": False,
    "covered_by": [],
}


def handle(method, params, state):
    if method == "ping":
        return {"ok": True, "version": "0.0.1"}
    if method == "selftest":
        return {
            "engine": "fixture",
            "version": "0.0.1",
            "deps": {"vgamepad": "MISSING: fixture engine has no real gamepad"},
            "monitors": [],
            "ocr_ready": False,
            "xinput_slots_connected": [],
            "backend": backend_report(),
            "foreground": dict(FOREGROUND),
        }
    if method == "windows":
        return {
            "count": 2,
            "windows": [
                {"title": "Fixture Game", "process": "fixture.exe", "width": 1280, "height": 720},
                {"title": "Editor", "process": "editor.exe", "width": 1024, "height": 768},
            ],
        }
    if method == "controls":
        return {"backend": "dry-run", "buttons": ["A", "B", "W", "SPACE"], "note": "fixture control list"}
    if method == "events":
        return {"event": "changed", "mean_diff": 3.25, "changed_ratio": 0.0412, "elapsed_ms": 220, "width": 160, "height": 90}
    if method == "snapshot":
        return {
            "width": 16,
            "height": 9,
            "png_b64": TINY_PNG_B64,
            "region": None,
            "ocr": [{"text": "fixture text", "score": 0.9}],
            "foreground": dict(FOREGROUND),
            "occluded": dict(OCCLUDED),
        }
    if method == "attach":
        state["attached"] = {
            "window": params.get("window") or "fixture-game",
            "hwnd": FOREGROUND["hwnd"],
        }
        return {
            "attached": state["attached"],
            "backend": "dry-run",
            "safety": SAFETY,
            "control": dict(CONTROL),
            "foreground": dict(FOREGROUND),
        }
    if method == "act":
        state["actions"] = state.get("actions", 0) + 1
        return {
            "action": {
                "backend": "dry-run",
                "button": params.get("button") or "A",
                "duration_ms": params.get("duration_ms") or 80,
                "dry_run": True,
            },
            "safety": SAFETY,
            "attached": state.get("attached"),
            "actions_total": state["actions"],
            "delivery": {
                "checked": True,
                "foreground": True,
                "hwnd": FOREGROUND["hwnd"],
                "title": FOREGROUND["title"],
            },
        }
    if method == "plan":
        state["plan"] = {
            "id": "plan-fixture",
            "mode": params.get("mode") or "hold",
            "button": params.get("button") or "A",
            "duration_ms": params.get("duration_ms") or 1000,
            "status": "running",
            "ticks": 0,
            "hz": 0,
        }
        return {
            "plan": dict(state["plan"]),
            "safety": SAFETY,
            "control": dict(CONTROL),
            "foreground": dict(FOREGROUND),
        }
    if method == "stop":
        state["attached"] = None
        if "plan" in state:
            state["plan"]["status"] = "stopped"
        return {"stopped": True, "actions_total": state.get("actions", 0), "plan": state.get("plan")}
    if method == "status":
        if "plan" in state:
            state["plan"].update({"status": "completed", "ticks": 6, "hz": 20.0})
        return {
            "attached": state.get("attached"),
            "backend": "dry-run",
            "safety": SAFETY,
            "actions_total": state.get("actions", 0),
            "plan": state.get("plan"),
            "control": dict(CONTROL),
            "foreground": dict(FOREGROUND),
        }
    return {}


def main() -> int:
    state = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        result = handle(request.get("method"), request.get("params") or {}, state)
        print(json.dumps({"id": request.get("id"), "ok": True, "result": result}), flush=True)
        # 测试引擎崩溃自愈：回完这一条就退出，逼插件下次调用时重建客户端。
        if os.environ.get("FAKE_ENGINE_EXIT_AFTER") == "1":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
