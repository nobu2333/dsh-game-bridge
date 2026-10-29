"""Fake engine fixture: speaks just enough of the stdio protocol for ping."""
import json
import sys


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        if request.get("method") == "ping":
            result = {"ok": True, "version": "0.0.1"}
        else:
            result = {}
        print(json.dumps({"id": request.get("id"), "ok": True, "result": result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
