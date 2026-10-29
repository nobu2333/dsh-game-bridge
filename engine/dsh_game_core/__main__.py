"""stdio JSON 协议（一行一个请求 / 一行一个响应）。

请求：{"id": 1, "method": "snapshot", "params": {...}}
响应：{"id": 1, "ok": true, "result": {...}}
      {"id": 1, "ok": false, "error": {"code": "...", "message": "..."}}

为什么是自研的极简协议而不是 MCP：插件侧只需要 4 个方法，且要自己控制
「引擎未就绪」「超时」「崩溃重启」的语义；协议保持可被任何宿主翻译成 MCP。
stdout 只走协议，诊断一律 stderr——这条和 DSH 的 SDK 约定一致。
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time


def force_utf8_stdio() -> None:
    """把协议用的 stdout/stderr 强制成 UTF-8。

    Windows 控制台默认是 GBK（cp936）：窗口标题、OCR 文本里的中文/符号写 stdout
    会抛 UnicodeEncodeError，而引擎是被插件 spawn 的、没有 PYTHONIOENCODING，
    结果整个进程崩掉（实测：game_windows 在中文窗口标题上 exit 1）。
    协议是 UTF-8 JSON，所以这里无条件收紧，且对测试用的 StringIO 安全跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - 某些流不支持重配置时保持原样
                pass


from . import __version__


def _config() -> dict:
    return {"platform": f"{platform.system()}-{platform.machine()}", "python": platform.python_version()}


def selftest(capture: bool = False) -> dict:
    report: dict = {
        "engine": "dsh-game-core",
        "version": __version__,
        **_config(),
        "deps": {},
        "monitors": [],
        "capture_ok": None,
        "ocr_ready": None,
        "ocr_warmup_ms": None,
    }
    for module in ("numpy", "cv2", "dxcam", "rapidocr_onnxruntime"):
        try:
            imported = __import__(module)
            report["deps"][module] = getattr(imported, "__version__", "ok")
        except Exception as error:  # noqa: BLE001 - 自检要报告而不是抛
            report["deps"][module] = f"MISSING: {type(error).__name__}: {error}"

    try:
        from .capture import list_monitors

        report["monitors"] = [m.__dict__ for m in list_monitors()]
    except Exception as error:  # noqa: BLE001
        report["monitors_error"] = f"{type(error).__name__}: {error}"

    try:
        from .ocr import Ocr

        report["ocr_warmup_ms"] = round(Ocr().warmup(), 1)
        report["ocr_ready"] = True
    except Exception as error:  # noqa: BLE001
        report["ocr_ready"] = False
        report["ocr_error"] = f"{type(error).__name__}: {error}"

    if capture:
        try:
            from .engine import GameEngine

            engine = GameEngine()
            started = time.perf_counter()
            frame = engine.snapshot(ocr=False, max_width=1280)
            report["capture_ok"] = True
            report["capture_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            report["capture_size"] = [frame["width"], frame["height"]]
            engine.close()
        except Exception as error:  # noqa: BLE001
            report["capture_ok"] = False
            report["capture_error"] = f"{type(error).__name__}: {error}"
    return report


def serve(stdin=None, stdout=None) -> int:
    from .engine import EngineError
    from .session import GameSession

    force_utf8_stdio()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    session = GameSession()
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}
            if method == "ping":
                result = {"ok": True, "version": __version__}
            elif method == "selftest":
                result = selftest(capture=bool(params.get("capture")))
            elif method == "snapshot":
                result = session.snapshot(
                    ocr=bool(params.get("ocr", True)),
                    max_width=params.get("max_width"),
                )
            elif method == "windows":
                result = session.windows(limit=int(params.get("limit") or 40))
            elif method == "attach":
                result = session.attach(params)
            elif method == "act":
                result = session.act(params)
            elif method == "plan":
                result = session.plan(params)
            elif method == "status":
                result = session.status()
            elif method == "stop":
                result = session.stop()
            else:
                raise EngineError("UNKNOWN_METHOD", f"未知方法：{method!r}")
            response = {"id": request_id, "ok": True, "result": result}
        except EngineError as error:
            response = {"id": request_id, "ok": False, "error": {"code": error.code, "message": error.message}}
        except Exception as error:  # noqa: BLE001 - 协议层绝不因单个请求退出
            response = {
                "id": request_id,
                "ok": False,
                "error": {"code": "INTERNAL", "message": f"{type(error).__name__}: {error}"},
            }
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    session.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(prog="dsh-game-core", description="Local capture + OCR engine for dsh-game-bridge")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    selftest_parser = sub.add_parser("selftest", help="报告依赖、显示器、OCR 与抓屏状态（JSON）")
    selftest_parser.add_argument("--capture", action="store_true", help="真的抓一帧（只读，不注入输入）")
    windows_parser = sub.add_parser("windows", help="列出当前可见窗口（只读）")
    windows_parser.add_argument("--limit", type=int, default=40)
    sub.add_parser("serve", help="stdio JSON 服务（插件用）")
    args = parser.parse_args(argv)

    if args.command == "selftest":
        print(json.dumps(selftest(capture=args.capture), ensure_ascii=False, indent=2))
        return 0
    if args.command == "windows":
        from .session import GameSession

        print(json.dumps(GameSession().windows(limit=args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        return serve()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
