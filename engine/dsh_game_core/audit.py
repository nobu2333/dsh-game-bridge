"""本地审计日志：每次 attach / act / plan / stop / abort 写一行 JSONL。

为什么要有：插件会给用户机器注入输入，出错时「它到底做了什么」必须能自证。
日志只写本地、不发网络；窗口名会进日志，所以路径由用户配置，默认关闭。

设计取舍：
- **默认关闭**（`DSH_GAME_BRIDGE_AUDIT_LOG` 未设置时不落盘），避免替用户
  悄悄写文件；打开后路径完全由用户指定；
- 写入失败绝不抛出：审计不能反过来弄坏正常操作，但错误会进内存条目的 `error`；
- 同时保留内存环形尾巴（最近 N 条），供 `game_status` 直接展示。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_TAIL = 20


class AuditLog:
    def __init__(self, path: str | os.PathLike | None = None, *, keep: int = 200):
        self.path = str(path) if path not in (None, "") else None
        self.keep = keep
        self.entries: list[dict] = []

    def write(self, event: dict) -> dict:
        record = {"ts_ms": int(time.time() * 1000), **event}
        self.entries.append(record)
        if len(self.entries) > self.keep:
            del self.entries[: len(self.entries) - self.keep]
        if self.path:
            try:
                target = Path(self.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as error:
                record["audit_write_error"] = f"{type(error).__name__}: {error}"
        return record

    def tail(self, count: int = DEFAULT_TAIL) -> list[dict]:
        return self.entries[-count:]
