"""Generic incremental L2 log observer (data-driven regex rules, zero game names).

Slow-paced games that write local plain-text event logs can feed exact state
deltas in <10ms without OCR guesswork or memory reading. The caller supplies
a file path and declarative regex rules; this module tails new complete lines,
handles log rotation/truncation, and maintains bounded state counters/fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass
class LogRule:
    name: str
    pattern: re.Pattern[str]
    set_fields: dict[str, str] = field(default_factory=dict)
    inc_fields: dict[str, int] = field(default_factory=dict)
    append_fields: dict[str, str] = field(default_factory=dict)
    max_list: int = 20

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LogRule":
        name = str(raw.get("name") or "").strip()
        pattern_text = raw.get("pattern")
        if not name or not isinstance(pattern_text, str) or not pattern_text:
            raise ValueError("log rule requires non-empty 'name' and 'pattern'")
        return cls(
            name=name,
            pattern=re.compile(pattern_text),
            set_fields={str(k): str(v) for k, v in (raw.get("set") or {}).items()},
            inc_fields={str(k): int(v) for k, v in (raw.get("inc") or {}).items()},
            append_fields={str(k): str(v) for k, v in (raw.get("append") or {}).items()},
            max_list=max(1, min(100, int(raw.get("max_list") or 20))),
        )


def _render_template(template: str, groups: Mapping[str, Any]) -> str:
    text = template
    for key, val in groups.items():
        text = text.replace("{" + str(key) + "}", str(val if val is not None else ""))
    return text


class LogObserver:
    """Tail a plain-text log incrementally and fold matched lines into state."""

    def __init__(self, path: str | Path, rules: list[LogRule] | None = None, *, from_end: bool = False) -> None:
        self.path = Path(path)
        self.rules: list[LogRule] = list(rules or [])
        self.offset: int = 0
        self.state: dict[str, Any] = {}
        self._remainder: str = ""
        if from_end and self.path.is_file():
            self.offset = self.path.stat().st_size

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "LogObserver":
        path = config.get("path")
        if not path:
            raise ValueError("log observer config requires 'path'")
        raw_rules = config.get("rules") or []
        rules = [LogRule.from_dict(item) for item in raw_rules if isinstance(item, Mapping)]
        return cls(path=path, rules=rules, from_end=bool(config.get("from_end", False)))

    def reset(self) -> None:
        self.offset = 0
        self.state = {}
        self._remainder = ""

    def poll(self, *, max_lines: int = 500) -> dict:
        if not self.path.is_file():
            return {"exists": False, "lines_read": 0, "events": [], "state": dict(self.state), "offset": self.offset}

        size = self.path.stat().st_size
        if size < self.offset:
            # File truncated / rotated: restart from offset 0 cleanly.
            self.offset = 0
            self._remainder = ""

        events: list[dict] = []
        lines_read = 0
        if size > self.offset:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
                self.offset = handle.tell()
            combined = self._remainder + chunk
            raw_lines = combined.splitlines(keepends=True)
            if raw_lines and not raw_lines[-1].endswith(("\n", "\r")):
                self._remainder = raw_lines.pop()
            else:
                self._remainder = ""
            cap = max(1, int(max_lines))
            for raw in raw_lines[:cap]:
                line = raw.rstrip("\r\n")
                lines_read += 1
                self._apply_line(line, events)

        return {
            "exists": True,
            "lines_read": lines_read,
            "events": events,
            "state": {k: (list(v) if isinstance(v, list) else v) for k, v in self.state.items()},
            "offset": self.offset,
        }

    def _apply_line(self, line: str, events: list[dict]) -> None:
        for rule in self.rules:
            match = rule.pattern.search(line)
            if not match:
                continue
            groups = match.groupdict()
            for field_name, template in rule.set_fields.items():
                self.state[field_name] = _render_template(template, groups)
            for field_name, delta in rule.inc_fields.items():
                try:
                    current = int(self.state.get(field_name) or 0)
                except (TypeError, ValueError):
                    current = 0
                self.state[field_name] = current + delta
            for field_name, template in rule.append_fields.items():
                bucket = self.state.get(field_name)
                if not isinstance(bucket, list):
                    bucket = []
                bucket.append(_render_template(template, groups))
                if len(bucket) > rule.max_list:
                    bucket = bucket[-rule.max_list :]
                self.state[field_name] = bucket
            events.append({"rule": rule.name, "groups": dict(groups), "line": line[:200]})
