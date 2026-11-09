"""Serve a local Unity/WebGL build with correct Brotli headers.

Local-only helper for T1 onboarding of browser games. It is not part of the
engine and does not know any game name.

  python scripts/serve_webgl.py --root E:\\path\\to\\webgl --port 8765
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
from pathlib import Path


class BrotliHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".data": "application/octet-stream",
    }

    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0].lower()
        if path.endswith(".br"):
            self.send_header("Content-Encoding", "br")
        super().end_headers()

    def guess_type(self, path: str) -> str:  # noqa: D401 - stdlib contract
        lower = path.lower()
        if lower.endswith(".js.br") or lower.endswith(".js"):
            return "text/javascript"
        if lower.endswith(".wasm.br") or lower.endswith(".wasm"):
            return "application/wasm"
        if lower.endswith(".json.br") or lower.endswith(".json"):
            return "application/json"
        return super().guess_type(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a local Unity/WebGL build")
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    handler = functools.partial(BrotliHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"serving {root} at http://{args.bind}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
