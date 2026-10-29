"""Fake engine fixture: canned responses for the plugin's protocol.

It exists so integration tests can drive the *plugin* (tools, schemas, image
pipeline, attach/act flow) without a real screen, real gamepad, or safety state.
Real capture/OCR and the real safety gate are covered by engine/ unit tests.
"""
import json
import sys

SAFETY = {
    "allowed": True,
    "reasons": [],
    "anticheat": [],
    "idle_seconds": 0.0,
    "takeover": False,
}


def handle(method, params, state):
    if method == "ping":
        return {"ok": True, "version": "0.0.1"}
    if method == "selftest":
        return {"engine": "fixture", "deps": {}, "monitors": [], "ocr_ready": False}
    if method == "windows":
        return {
            "count": 2,
            "windows": [
                {"title": "Fixture Game", "process": "fixture.exe", "width": 1280, "height": 720},
                {"title": "Editor", "process": "editor.exe", "width": 1024, "height": 768},
            ],
        }
    if method == "events":
        return {"event": "changed", "mean_diff": 3.25, "changed_ratio": 0.0412, "elapsed_ms": 220, "width": 160, "height": 90}
    if method == "attach":
        state["attached"] = {"window": params.get("window") or "fixture-game"}
        return {"attached": state["attached"], "backend": "dry-run", "safety": SAFETY}
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
            "actions_total": state["actions"],
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
        return {"plan": dict(state["plan"]), "safety": SAFETY}
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
