from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "dsh_game_core"
GAME_NAMES = ("cuphead", "dino", "trex", "2048", "blockblast", "forest-follies")


def test_core_has_no_game_specific_names_or_paths():
    offenders = []
    for path in sorted(CORE.glob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for name in GAME_NAMES:
            if name in text:
                offenders.append(f"{path.name}:{name}")
    assert not offenders, f"game-specific data in engine core: {offenders}"
