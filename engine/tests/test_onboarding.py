
from dsh_game_core.gamepack import validate_pack
from dsh_game_core.onboarding import auto_pack_draft, infer_auto_controls, t1_checklist


def _record(key, *, changed=True, ratio=0.01, ocr_changed=False, menu_changed=False):
    return {
        "key": key,
        "change": {"changed": changed, "ratio": ratio},
        "ocr_changed": ocr_changed,
        "menu_transition": {"changed": menu_changed},
    }


def test_infer_confirm_and_movement():
    records = [
        _record("ENTER", ratio=0.02, ocr_changed=True, menu_changed=True),
        _record("RIGHT", ratio=0.05),
        _record("LEFT", ratio=0.04),
        _record("SPACE", ratio=0.02),
        _record("ESC", changed=False),
    ]
    inferred = infer_auto_controls(records)
    assert inferred["controls"]["confirm"] == ["ENTER"]
    assert "right" in inferred["controls"]["move"]
    assert "left" in inferred["controls"]["move"]
    assert inferred["controls"]["jump"] == ["SPACE"]
    assert inferred["confidence"] >= 0.8


def test_infer_refuses_to_guess_without_evidence():
    inferred = infer_auto_controls([_record("RIGHT", changed=False)])
    assert "confirm" not in inferred["controls"]
    assert "confirm" in inferred["uncertain"]


def test_auto_pack_has_auto_provenance_and_validates():
    records = [_record("ENTER", ocr_changed=True, menu_changed=True), _record("RIGHT", ratio=0.06)]
    pack = auto_pack_draft(
        {"title": "Example", "process": "example.exe", "width": 800, "height": 600},
        records,
        ocr_texts=["START", "OPTIONS"],
        menu_observed=True,
        gameplay_observed=True,
    )
    pack = validate_pack(pack)
    assert pack["origin"] == "auto"
    assert pack["interventions"] == 0
    assert pack["controls"]["confirm"] == ["ENTER"]
    assert pack["recipes"][0]["id"] == "auto_start"
    assert pack["probe"]["inferred"]["gameplay_observed"] is True


def test_t1_checklist():
    assert t1_checklist(menu_observed=True, confirm_key="ENTER", gameplay_observed=True, first_action_key="RIGHT")["pass"] is True
    result = t1_checklist(menu_observed=True, confirm_key=None, gameplay_observed=False, first_action_key=None)
    assert result["pass"] is False
    assert "confirm" not in result["missing"]
    assert "confirm_inferred" in result["missing"]

from dsh_game_core.onboarding import find_dismiss_target

def test_find_close_target():
    lines = [
        {"text": "START", "left": 10, "top": 10, "right": 50, "bottom": 30},
        {"text": "Close", "left": 700, "top": 120, "right": 760, "bottom": 150},
    ]
    target = find_dismiss_target(lines, width=800, height=600)
    assert target is not None
    assert target["label"] == "CLOSE"
    assert 0.8 < target["x"] < 1.0
    assert 0.2 < target["y"] < 0.3
    assert find_dismiss_target([], width=800, height=600) is None
