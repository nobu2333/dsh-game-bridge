
import json

from dsh_game_core.memory_context import build_memory_context
from dsh_game_core.memory_loader import MemoryLoader


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_context_only_current_scope(tmp_path):
    _write(tmp_path / "games" / "g" / "game.json", {"id": "g", "controls": {"jump": "Z"}})
    _write(tmp_path / "games" / "g" / "levels" / "l1.json", {"game": "g", "level": "l1", "segments": {"s:0": {"deaths": 2}}})
    _write(tmp_path / "games" / "g" / "levels" / "l2.json", {"game": "g", "level": "l2", "segments": {"s:0": {"deaths": 9}}})
    loader = MemoryLoader(tmp_path)
    loader.load_game("g")
    context = build_memory_context(loader)
    assert context["scope"] == "game"
    assert "level_memory" not in context
    loader.load_level("g", "l1")
    context = build_memory_context(loader, scroll_s=0.0)
    assert context["scope"] == "level"
    assert context["level_memory"]["hotspot"] is True
    assert context["level_memory"]["summary"]["deaths"] == 2


def test_context_guides_and_budget():
    guides = [
        {"scope": "game", "source_url": "", "facts": [{"type": "controls", "text": "Z jump" * 80}]},
        {"scope": "level", "source_url": "https://example.com", "facts": [{"type": "boss", "text": "jump sweep" * 80}]},
    ]
    context = build_memory_context(None, guide_cards=guides, max_chars=300)
    assert context["truncated"] is True
    assert len(context["guides"]) <= 4
