"""向 drive_server.py 发一条指令并打印 JSON 响应。

用法：
    python ctl.py <method> ['<json params>']
例如：
    python ctl.py snapshot
    python ctl.py act '{"button": "START", "duration_ms": 120}'
    python ctl.py play '{"hold": ["X", "DPAD_RIGHT"], "tap": ["A"], "duration_ms": 3000}'
"""
import json
import socket
import sys

PORT = 47654


def main():
    method = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    with socket.create_connection(("127.0.0.1", PORT), timeout=180) as sock:
        sock.sendall((json.dumps({"method": method, "params": params}) + "\n").encode("utf-8"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
    print(b"".join(chunks).decode("utf-8").strip())


if __name__ == "__main__":
    main()
