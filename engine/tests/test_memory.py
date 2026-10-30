"""DangerCard / KnowledgeStore / LevelLocator：数据层与检索。"""

from dsh_game_core.memory import (
    DANGER_SCHEMA,
    KnowledgeStore,
    LevelLocator,
    normalize_danger_card,
)


def make_card(**overrides):
    card = {
        "game": "cuphead",
        "level": "forest-follies",
        "place": {"scroll_s": 3.4, "segment": 3, "player_x": 0.4, "player_y": 0.8, "landmark": "tree"},
        "trigger": {"kind": "enemy", "template": "mushroom", "relation": "ahead"},
        "event": {"type": "damage", "cause": "contact", "hp_before": 3, "hp_after": 2},
        "response": {"skill": "jump_over", "params": {"before_px": 120}},
        "evidence": ["episode-1/frame-01.jpg"],
        "status": "candidate",
    }
    card.update(overrides)
    return card


def test_normalize_clamps_and_rejects_garbage():
    assert normalize_danger_card(None) is None
    assert normalize_danger_card({"game": "cuphead"}) is None
    assert normalize_danger_card(make_card(level="../../etc")) is None
    card = normalize_danger_card(make_card(game="../y", place={"scroll_s": "bad", "player_x": 9}))
    assert card["game"] == "unknown"
    assert card["place"]["scroll_s"] == 0.0
    assert card["place"]["player_x"] == 1.0
    assert card["schema"] == DANGER_SCHEMA
    assert card["status"] == "candidate"


def test_store_upsert_merge_and_nearby(tmp_path):
    store = KnowledgeStore(tmp_path)
    first = store.upsert(make_card())
    assert first is not None
    again = dict(make_card())
    again["stats"] = {"encounters": 3, "damage_events": 1, "avoided": 1}
    again["confidence"] = 0.8
    store.upsert(again)
    cards = store.load("cuphead", "forest-follies")["cards"]
    assert len(cards) == 1
    assert cards[0]["stats"]["encounters"] == 3
    assert cards[0]["confidence"] >= 0.8
    store.upsert(make_card(place={"scroll_s": 9.0, "player_x": 0.5}, trigger={"kind": "projectile", "template": "bullet"}))
    cards = store.load("cuphead", "forest-follies")["cards"]
    assert len(cards) == 2
    near = store.nearby("cuphead", "forest-follies", 3.5, window=1.0)
    assert len(near) == 1
    assert near[0]["trigger"]["template"] == "mushroom"


def test_store_bad_json_is_empty_and_bad_ids_are_safe(tmp_path):
    store = KnowledgeStore(tmp_path)
    path = tmp_path / "cuphead" / "forest-follies.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert store.load("cuphead", "forest-follies")["cards"] == []
    card = store.upsert(make_card(level="forest-follies", game="../y"))
    assert card is not None
    assert card["game"] == "unknown"
    assert card["level"] == "forest-follies"
    assert (tmp_path / "unknown" / "forest-follies.json").exists()


def test_level_locator_accumulates_and_resets():
    locator = LevelLocator(segment_width=1.0)
    assert locator.position()["scroll_s"] == 0.0
    locator.update(0.5)
    locator.update(0.7)
    position = locator.position()
    assert position["scroll_s"] == 1.2
    assert position["segment"] == 1
    locator.update("bad")
    assert locator.position()["scroll_s"] == 1.2
    locator.reset()
    assert locator.position()["scroll_s"] == 0.0

from dsh_game_core.memory import GuideStore, normalize_guide_card


def test_guide_normalization_and_store(tmp_path):
    assert normalize_guide_card(None) is None
    assert normalize_guide_card({"game": "cuphead"}) is None
    bad = normalize_guide_card(
        {"game": "cuphead", "level": "forest-follies", "source_url": "javascript:alert(1)", "facts": [{"text": "jump"}]}
    )
    assert bad["source_url"] == ""
    good = normalize_guide_card(
        {
            "game": "cuphead",
            "level": "forest-follies",
            "title": "walkthrough",
            "source_url": "https://example.com/guide",
            "facts": [{"type": "hazard", "text": "mushrooms pop up"}],
            "confidence": 0.5,
        }
    )
    store = GuideStore(tmp_path)
    assert store.upsert(good) is not None
    cards = store.load("cuphead", "forest-follies")
    assert len(cards) == 1
    assert cards[0]["facts"][0]["text"] == "mushrooms pop up"
    assert cards[0]["status"] == "unverified"

def test_upsert_does_not_chain_merge_distant_hits(tmp_path):
    store = KnowledgeStore(tmp_path)
    first = make_card(place={"scroll_s": -1.34}, trigger={"kind": "threat", "template": ""})
    second = make_card(place={"scroll_s": -1.79}, trigger={"kind": "threat", "template": ""})
    store.upsert(first)
    store.upsert(second)
    cards = store.load("cuphead", "forest-follies")["cards"]
    assert len(cards) == 2


def test_split_inconsistent_cards(tmp_path):
    store = KnowledgeStore(tmp_path)
    card = make_card(
        place={"scroll_s": -1.71},
        trigger={"kind": "threat", "template": ""},
    )
    card["stats"] = {"damage_scrolls": [-1.79, -1.71, -1.34], "damage_events": 3}
    store.upsert(card)
    assert store.split_inconsistent_cards("cuphead", "forest-follies") == 1
    cards = store.load("cuphead", "forest-follies")["cards"]
    assert len(cards) == 2
    for item in cards:
        scrolls = item["stats"]["damage_scrolls"]
        assert max(scrolls) - min(scrolls) <= 0.35

def test_split_chained_scrolls_over_budget(tmp_path):
    store = KnowledgeStore(tmp_path)
    card = make_card(place={"scroll_s": -1.15}, trigger={"kind": "threat", "template": ""})
    card["stats"] = {"damage_scrolls": [-1.0, -1.1, -1.2, -1.3], "damage_events": 4}
    store.upsert(card)
    assert store.split_inconsistent_cards("cuphead", "forest-follies") == 1
    cards = store.load("cuphead", "forest-follies")["cards"]
    assert len(cards) == 2
    for item in cards:
        scrolls = item["stats"]["damage_scrolls"]
        assert max(scrolls) - min(scrolls) <= 0.2
