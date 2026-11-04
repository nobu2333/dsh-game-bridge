"""机制审计：把“开关状态 + 实际执行计数”变成 pass/fail。

用途：
- 实验结束后检查：该启用的机制是否真的 applied>0；
- 该关闭的机制是否 applied==0；
- option_canary 这类默认关闭机制，若 enabled=True 但 applied==0，说明没有真正生效。

这不是业务逻辑，而是检测机制的自检。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MechanismExpectation:
    mechanism: str
    enabled: bool | None = None
    min_applied: int = 0
    max_applied: int | None = None
    note: str = ""


@dataclass
class AuditResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks}


def audit_mechanisms(status: dict, expectations: list[MechanismExpectation]) -> AuditResult:
    mechanisms = (status or {}).get("mechanisms") or {}
    checks = []
    ok = True
    for expectation in expectations:
        snapshot = mechanisms.get(expectation.mechanism)
        if not isinstance(snapshot, dict):
            ok = False
            checks.append(
                {
                    "mechanism": expectation.mechanism,
                    "ok": False,
                    "reason": "missing_mechanism",
                    "expected": expectation.__dict__,
                    "actual": None,
                }
            )
            continue
        counts = snapshot.get("counts") or {}
        enabled = bool(snapshot.get("enabled"))
        applied = int(counts.get("applied") or 0)
        reasons = []
        if expectation.enabled is not None and enabled != expectation.enabled:
            reasons.append(f"enabled={enabled} expected={expectation.enabled}")
        if applied < expectation.min_applied:
            reasons.append(f"applied={applied} < min={expectation.min_applied}")
        if expectation.max_applied is not None and applied > expectation.max_applied:
            reasons.append(f"applied={applied} > max={expectation.max_applied}")
        passed = not reasons
        ok = ok and passed
        checks.append(
            {
                "mechanism": expectation.mechanism,
                "ok": passed,
                "reason": "; ".join(reasons) if reasons else "ok",
                "expected": expectation.__dict__,
                "actual": {"enabled": enabled, "counts": counts, "last_reason": snapshot.get("last_reason")},
            }
        )
    return AuditResult(ok=ok, checks=checks)


def expectations_from_profile(profile: dict) -> list[MechanismExpectation]:
    """Generic expectations derived only from profile switches, no game names."""
    profile = profile or {}
    combat = profile.get("combat") if isinstance(profile.get("combat"), dict) else {}
    options = profile.get("options") if isinstance(profile.get("options"), dict) else {}
    canary = str(options.get("canary") or "")
    execute = bool(options.get("execute", False))
    expectations = [
        MechanismExpectation(
            "edge_escape",
            enabled=bool(combat.get("edge_escape", True)),
            min_applied=0,
            note="disabled must have applied=0",
        ),
        MechanismExpectation(
            "option_canary",
            enabled=execute and bool(canary),
            min_applied=1 if execute and canary else 0,
            max_applied=None if execute and canary else 0,
            note="enabled canary must actually apply; disabled must never apply",
        ),
    ]
    return expectations
