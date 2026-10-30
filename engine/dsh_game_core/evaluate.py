"""离线评测：从本地 episode / DangerCard 生成一局或多局的指标报告。

这是「没有度量就没有改进」的最小实现：
- 输入：episode 目录（meta/events/frames.jsonl）和 KnowledgeStore 账本；
- 输出：受击/死亡/进度/响应成功率/卡片状态分布；
- 纯 Python，不依赖游戏进程，可重复跑、可进 CI。

注意：真正的「N 局 A/B」仍需要实机跑，本模块负责把跑出来的数据变成可比较的数字。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def load_episode(path: str | os.PathLike[str]) -> dict | None:
    directory = Path(path)
    try:
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    events: list[dict] = []
    try:
        for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:  # noqa: BLE001
        pass
    frames: list[dict] = []
    try:
        for line in (directory / "frames.jsonl").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return {"path": str(directory), "meta": meta, "events": events, "frames": frames}


def summarize_episode(episode: dict) -> dict:
    meta = episode.get("meta") or {}
    events = episode.get("events") or []
    frames = episode.get("frames") or []
    damage = sum(1 for event in events if event.get("type") == "damage")
    deaths = sum(1 for event in events if event.get("type") == "death")
    max_scroll = 0.0
    min_scroll = 0.0
    for frame in frames:
        state = frame.get("state") if isinstance(frame.get("state"), dict) else {}
        scroll = _num(state.get("scroll_s"), 0.0)
        max_scroll = max(max_scroll, scroll)
        min_scroll = min(min_scroll, scroll)
    return {
        "path": episode.get("path"),
        "game": meta.get("game"),
        "level": meta.get("level"),
        "frames": int(meta.get("frame_count") or len(frames)),
        "events": int(meta.get("event_count") or len(events)),
        "damage_events": damage,
        "deaths": deaths,
        "progress": round(abs(min_scroll), 3) if min_scroll < 0 else round(max_scroll, 3),
    }


def summarize_episodes(root: str | os.PathLike[str], *, game: str | None = None, level: str | None = None) -> dict:
    directory = Path(root)
    episodes = []
    if directory.is_dir():
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            episode = load_episode(child)
            if episode is None:
                continue
            summary = summarize_episode(episode)
            if game and summary.get("game") != game:
                continue
            if level and summary.get("level") != level:
                continue
            episodes.append(summary)
    total = len(episodes)
    return {
        "episodes": total,
        "damage_events": sum(item["damage_events"] for item in episodes),
        "deaths": sum(item["deaths"] for item in episodes),
        "damage_per_episode": round(sum(item["damage_events"] for item in episodes) / total, 2) if total else 0.0,
        "deaths_per_episode": round(sum(item["deaths"] for item in episodes) / total, 2) if total else 0.0,
        "best_progress": round(max((item["progress"] for item in episodes), default=0.0), 3),
        "episodes_detail": episodes[-20:],
    }


def summarize_cards(cards: list[dict]) -> dict:
    total = len(cards)
    statuses: dict[str, int] = {}
    avoided = 0
    failures = 0
    tries = 0
    efficacy = 0.0
    for card in cards:
        if not isinstance(card, dict):
            continue
        statuses[str(card.get("status") or "unknown")] = statuses.get(str(card.get("status") or "unknown"), 0) + 1
        stats = card.get("stats") if isinstance(card.get("stats"), dict) else {}
        avoided += int(_num(stats.get("avoided"), 0))
        failures += int(_num(stats.get("response_failures"), 0))
        tries += int(_num(stats.get("response_tries"), 0))
        efficacy += _num(card.get("response_efficacy"), 0.5)
    return {
        "cards": total,
        "statuses": statuses,
        "response_tries": tries,
        "avoided": avoided,
        "response_failures": failures,
        "avoid_rate": round(avoided / tries, 3) if tries else 0.0,
        "mean_response_efficacy": round(efficacy / total, 3) if total else 0.0,
    }


def load_cards(path: str | os.PathLike[str], game: str, level: str) -> list[dict]:
    from .memory import KnowledgeStore

    return KnowledgeStore(path).load(game, level)["cards"]


def format_report(summary: dict) -> str:
    lines = [
        "episodes: {episodes}".format(**summary),
        "damage events: {damage_events} (per episode {damage_per_episode})".format(**summary),
        "deaths: {deaths} (per episode {deaths_per_episode})".format(**summary),
        "best progress: {best_progress} screens".format(**summary),
    ]
    cards = summary.get("cards")
    if isinstance(cards, dict):
        lines.extend(
            [
                "cards: {cards} statuses={statuses}".format(**cards),
                "response tries: {response_tries} avoided={avoided} failures={response_failures} avoid_rate={avoid_rate}".format(**cards),
                "mean response efficacy: {mean_response_efficacy}".format(**cards),
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Summarize local episodes and DangerCards.")
    parser.add_argument("--data-root", default=os.environ.get("DSH_GAME_BRIDGE_DATA_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "dsh-game-bridge"
    ))
    parser.add_argument("--game", default="cuphead")
    parser.add_argument("--level", default="forest-follies")
    args = parser.parse_args(argv)
    episodes = summarize_episodes(os.path.join(args.data_root, "episodes"), game=args.game, level=args.level)
    cards = summarize_cards(load_cards(os.path.join(args.data_root, "knowledge"), args.game, args.level))
    episodes["cards"] = cards
    print(format_report(episodes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
