"""局后复盘：把一个 episode + 相关 DangerCard 压缩成模型可读的复盘包。

不是训练，而是「事件驱动复盘」：死亡/受击后给模型关键帧、时间线、卡片统计，
让模型提出具体补丁（换 response / 调 timing / 改 profile），补丁再由 A/B 验证。

输出 markdown，可本地保存或作为 game_review 的返回内容；不含原始大图，只引用路径。
"""

from __future__ import annotations

import os
from pathlib import Path

from .evaluate import load_episode, summarize_cards, summarize_episode


def _nearest_frames(frames: list[dict], times: list[float], limit: int = 6) -> list[dict]:
    picked = []
    for moment in times:
        best = None
        for frame in frames:
            distance = abs(float(frame.get("t") or 0.0) - moment)
            if best is None or distance < best[0]:
                best = (distance, frame)
        if best is not None and best[1] not in picked:
            picked.append(best[1])
        if len(picked) >= limit:
            break
    return picked


def build_review(episode_path: str | os.PathLike[str], cards: list[dict] | None = None, *, max_events: int = 12) -> str:
    episode = load_episode(episode_path)
    if episode is None:
        return "# Review\n\nepisode not found or unreadable.\n"
    summary = summarize_episode(episode)
    events = episode.get("events") or []
    frames = episode.get("frames") or []
    times = [float(event.get("t") or 0.0) for event in events]
    key_frames = _nearest_frames(frames, times)
    lines = [
        "# Episode review",
        "",
        "## Summary",
        f"- path: `{summary['path']}`",
        f"- game/level: {summary.get('game')} / {summary.get('level')}",
        f"- frames: {summary['frames']}  events: {summary['events']}",
        f"- damage: {summary['damage_events']}  deaths: {summary['deaths']}",
        f"- progress: {summary['progress']} screens",
        "",
        "## Timeline",
    ]
    for event in events[-max_events:]:
        lines.append(f"- t={event.get('t')} {event.get('type')} {event}")
    lines.append("")
    lines.append("## Key frames")
    for frame in key_frames:
        index = frame.get("index")
        path = Path(episode["path"]) / "frames" / f"{int(index):04d}.jpg"
        lines.append(f"- t={frame.get('t')} frame={index} `{path}`")
    if cards:
        summary_cards = summarize_cards(cards)
        lines.extend(
            [
                "",
                "## Cards",
                f"- cards: {summary_cards['cards']} statuses={summary_cards['statuses']}",
                f"- response tries: {summary_cards['response_tries']} avoided={summary_cards['avoided']} "
                f"failures={summary_cards['response_failures']} avoid_rate={summary_cards['avoid_rate']}",
                f"- mean response efficacy: {summary_cards['mean_response_efficacy']}",
            ]
        )
        for card in cards[:5]:
            lines.append(
                f"- `{card.get('id')}` place={card.get('place')} trigger={card.get('trigger')} "
                f"response={card.get('response')} stats={card.get('stats')}"
            )
    lines.append("")
    lines.append("## Suggested review questions")
    lines.append("- What caused the damage/death at the timeline entries?")
    lines.append("- Which card response should be validated/replaced, and with what params?")
    lines.append("- What profile change is testable in the next A/B run?")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build a compact review from a local episode.")
    parser.add_argument("episode")
    parser.add_argument("--data-root", default=os.environ.get("DSH_GAME_BRIDGE_DATA_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "dsh-game-bridge"
    ))
    parser.add_argument("--game", default="cuphead")
    parser.add_argument("--level", default="forest-follies")
    args = parser.parse_args(argv)
    from .memory import KnowledgeStore

    cards = KnowledgeStore(os.path.join(args.data_root, "knowledge")).load(args.game, args.level)["cards"]
    print(build_review(args.episode, cards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
