"""审计日志：写了什么、写到哪、以及「失败不能弄坏主流程」。"""

import json

from dsh_game_core.audit import AuditLog
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession


class FakeEngine:
    def snapshot(self, **_kwargs):
        return {"png_b64": "", "width": 1, "height": 1, "ocr": [], "captured_at_ms": 0}

    def close(self):
        pass


def allowed_gate(*, idle=1.0, processes=()):
    return SafetyGate(
        unattended_after_s=180,
        process_source=lambda: list(processes),
        idle_source=lambda: idle,
        takeover_source=lambda: False,
        process_ttl_s=0,
    )


def test_audit_log_keeps_memory_and_file(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.write({"event": "attach", "window": "fixture"})
    log.write({"event": "stop"})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["window"] == "fixture"
    assert [entry["event"] for entry in log.tail(2)] == ["attach", "stop"]


def test_audit_write_failure_does_not_raise(tmp_path):
    # 指向一个非法路径（目录当文件用），写入失败只能记在条目里。
    bad = tmp_path / "adir"
    bad.mkdir()
    log = AuditLog(bad)
    record = log.write({"event": "attach"})
    assert record["audit_write_error"]


def test_session_audits_attach_act_plan_and_blocked_attempts():
    audit = AuditLog()
    session = GameSession(engine=FakeEngine(), gate=allowed_gate(), control_backend="dry-run", audit=audit)
    session.attach({"window": "unspecified"})
    session.act({"button": "A", "duration_ms": 30})
    session.plan({"mode": "hold", "button": "A", "duration_ms": 150})
    session.stop()

    events = [entry["event"] for entry in audit.tail(10)]
    assert events[0] == "attach"
    assert "act" in events
    assert "plan_start" in events
    assert "plan_end" in events
    assert events[-1] == "stop"
    status = session.status()
    assert status["audit"]["tail"], "status must expose the audit tail"


def test_blocked_attempt_is_audited():
    audit = AuditLog()
    session = GameSession(
        engine=FakeEngine(),
        gate=allowed_gate(processes=("EasyAntiCheat.exe",)),
        control_backend="dry-run",
        audit=audit,
    )
    session.attach({"window": "unspecified"})
    try:
        session.act({"button": "A"})
    except Exception:  # noqa: BLE001 - 期望 SAFETY_BLOCKED
        pass
    assert any(entry["event"] == "act_blocked" for entry in audit.tail(5))

