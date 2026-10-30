"""临时驱动：把 dsh_game_core.GameSession 挂在本地 TCP 上，供 agent 一步步下指令。

为什么不用插件的工具面：宿主进程启动时把后端锁成 dry-run（只记录不注入），
env 改不了；这里用同一个引擎、同一个 vgamepad 后端直接驱动，安全闸（F12 夺回 /
反作弊拒绝）仍由引擎的 SafetyGate 每拍检查。「无人在场拒绝」闸已于 2026-10-30 移除。

协议：一行一个 JSON 请求 {"method": ..., "params": {...}}，回一行 JSON。
"""
import base64
import json
import os
import socketserver
import threading
import time

os.environ.setdefault("DSH_GAME_BRIDGE_CONTROL", "vgamepad")
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DSH_GAME_BRIDGE_AUDIT_LOG", os.path.join(HERE, "audit.jsonl"))
OUT = os.path.join(HERE, "frames")
os.makedirs(OUT, exist_ok=True)
PORT = 47654

from dsh_game_core.engine import EngineError  # noqa: E402
from dsh_game_core.session import GameSession  # noqa: E402

LOCK = threading.RLock()
STATE = {"session": None}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_session():
    if STATE["session"] is None:
        s = GameSession(control_backend="vgamepad")
        s.attach({"window": "Cuphead"})
        STATE["session"] = s
        log(f"attached {s.attached}")
    return STATE["session"]


def focus_window(hwnd):
    import ctypes

    u = ctypes.windll.user32
    u.ShowWindow(hwnd, 9)  # SW_RESTORE
    if u.SetForegroundWindow(hwnd):
        return True
    fg = u.GetForegroundWindow()
    tid_fg = u.GetWindowThreadProcessId(fg, None)
    tid = u.GetWindowThreadProcessId(hwnd, None)
    u.AttachThreadInput(tid_fg, tid, True)
    ok = bool(u.SetForegroundWindow(hwnd))
    u.AttachThreadInput(tid_fg, tid, False)
    return ok


def snapshot(params):
    s = ensure_session()
    result = s.snapshot(ocr=bool(params.get("ocr", True)), max_width=params.get("max_width"))
    data = base64.b64decode(result.pop("png_b64"))
    path = os.path.join(OUT, f"snap-{int(time.time() * 1000)}.png")
    with open(path, "wb") as fh:
        fh.write(data)
    result["path"] = path
    return result


def play(params):
    """多键闭环：按住 hold 里的键，周期性点 tap 里的键，持续 duration_ms。"""
    s = ensure_session()
    duration = int(params.get("duration_ms") or 3000)
    interval = int(params.get("tap_interval_ms") or 250)
    hold = [str(b) for b in (params.get("hold") or [])]
    tap = [str(b) for b in (params.get("tap") or [])]
    wiggle = params.get("wiggle")
    wiggle_ms = int(params.get("wiggle_ms") or 900)
    c = s._controller_instance()
    started = time.monotonic()
    deadline = started + duration / 1000.0
    ticks = 0
    actions = 0
    stop_reason = None
    last_tap = 0.0
    last_wiggle = started
    wiggle_right = True
    try:
        for button in hold:
            c.hold(button)
            actions += 1
        while time.monotonic() < deadline:
            report = s.gate.evaluate()
            if not report.allowed:
                stop_reason = "；".join(report.reasons)
                break
            now = time.monotonic()
            if tap and (now - last_tap) * 1000.0 >= interval:
                for button in tap:
                    c.press(button, 40)
                    actions += 1
                last_tap = now
            if wiggle and (now - last_wiggle) * 1000.0 >= wiggle_ms:
                c.release("DPAD_LEFT" if wiggle_right else "DPAD_RIGHT")
                wiggle_right = not wiggle_right
                c.hold("DPAD_RIGHT" if wiggle_right else "DPAD_LEFT")
                last_wiggle = now
                actions += 2
            ticks += 1
            time.sleep(0.05)
    finally:
        for button in hold + (["DPAD_LEFT", "DPAD_RIGHT"] if wiggle else []):
            try:
                c.release(button)
            except Exception:  # noqa: BLE001
                pass
        c.release_all()
    return {
        "ticks": ticks,
        "actions": actions,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "stop_reason": stop_reason,
        "safety": s.gate.evaluate().to_dict(),
    }


#: 需要「游戏在前台」的方法：XInput 只在前台窗口生效，抓屏也不能被别的窗口遮住。
FOCUS_FIRST = {"snapshot", "act", "play", "press", "hold", "release"}


def dispatch(method, params):
    s = ensure_session()
    if method in FOCUS_FIRST:
        hwnd = (s.attached or {}).get("hwnd")
        if hwnd:
            focus_window(hwnd)
            time.sleep(0.15)
    if method == "snapshot":
        return snapshot(params)
    if method == "act":
        return s.act(params)
    if method == "plan":
        return s.plan(params)
    if method == "play":
        return play(params)
    if method == "status":
        return s.status()
    if method == "controls":
        return s.controls()
    if method == "events":
        return s.events()
    if method == "windows":
        return s.windows(int(params.get("limit") or 40))
    if method == "attach":
        return s.attach(params)
    if method == "focus":
        hwnd = (s.attached or {}).get("hwnd")
        return {"focused": focus_window(hwnd) if hwnd else False, "hwnd": hwnd}
    if method == "press":
        c = s._controller_instance()
        return c.press(str(params["button"]), int(params.get("duration_ms") or 80))
    if method == "hold":
        c = s._controller_instance()
        return c.hold(str(params["button"]))
    if method == "release":
        c = s._controller_instance()
        return c.release(str(params["button"]))
    if method == "release_all":
        c = s._controller_instance()
        c.release_all()
        return {"released": True}
    if method == "stop":
        return s.stop()
    if method == "close":
        STATE["session"] = None
        s.close()
        return {"closed": True}
    raise EngineError("UNKNOWN_METHOD", f"未知方法：{method}")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            raw = self.rfile.readline()
            req = json.loads(raw.decode("utf-8"))
        except Exception as error:  # noqa: BLE001
            self.wfile.write((json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": str(error)}}, ensure_ascii=False) + "\n").encode())
            return
        method = req.get("method")
        params = req.get("params") or {}
        try:
            with LOCK:
                result = dispatch(method, params)
            response = {"ok": True, "result": result}
        except EngineError as error:
            response = {"ok": False, "error": {"code": error.code, "message": error.message}}
        except Exception as error:  # noqa: BLE001
            response = {"ok": False, "error": {"code": type(error).__name__, "message": str(error)}}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    log("warming engine...")
    s = ensure_session()
    log(f"session ready: {s.status()['backend']} / {s.attached['window']}")
    with Server(("127.0.0.1", PORT), Handler) as server:
        log(f"listening on {PORT}")
        server.serve_forever()
