
from dsh_game_core.mechanism_audit import (
    MechanismExpectation,
    audit_mechanisms,
    expectations_from_profile,
)


def _status(canary_enabled=False, canary_applied=0, edge_enabled=True):
    return {
        "mechanisms": {
            "edge_escape": {"enabled": edge_enabled, "counts": {"applied": 0}},
            "option_canary": {"enabled": canary_enabled, "counts": {"applied": canary_applied}},
        }
    }


def test_audit_disabled_canary_must_not_apply():
    result = audit_mechanisms(
        _status(canary_enabled=False, canary_applied=0),
        [MechanismExpectation("option_canary", enabled=False, max_applied=0)],
    )
    assert result.ok is True


def test_audit_enabled_canary_must_apply():
    result = audit_mechanisms(
        _status(canary_enabled=True, canary_applied=0),
        [MechanismExpectation("option_canary", enabled=True, min_applied=1)],
    )
    assert result.ok is False
    assert "applied=0" in result.checks[0]["reason"]


def test_audit_enabled_canary_applied_ok():
    result = audit_mechanisms(
        _status(canary_enabled=True, canary_applied=2),
        [MechanismExpectation("option_canary", enabled=True, min_applied=1)],
    )
    assert result.ok is True


def test_audit_missing_mechanism_fails():
    result = audit_mechanisms({}, [MechanismExpectation("option_canary")])
    assert result.ok is False
    assert result.checks[0]["reason"] == "missing_mechanism"


def test_expectations_from_profile():
    expectations = expectations_from_profile({"combat": {"edge_escape": False}, "options": {"execute": True, "canary": "jump_over"}})
    by_id = {item.mechanism: item for item in expectations}
    assert by_id["edge_escape"].enabled is False
    assert by_id["option_canary"].enabled is True
    assert by_id["option_canary"].min_applied == 1
