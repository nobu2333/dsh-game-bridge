"""安全闸：反作弊硬阻断、随时可夺回。

两条规则必须在**输出通道**这一层实现，而不是靠文档或提示词：

1. **反作弊不接**：命中 EAC / BattlEye / Vanguard / ACE 等进程名即拒绝一切注入；
2. **随时可夺回**：F12 热键一按，立即松手（下一次 act 直接拒绝，并把状态标出来）。

历史上还有第三条「无人不自娱」（超过若干秒没有任何键鼠输入就停止输出）。这条规则
是从宿主项目继承来的，对 dsh-game-bridge 不适用：本插件的正常用法就是让 agent 自己
玩；用键鼠遥测判断「人在不在」既会误杀手柄玩家，又会被 keyboard 后端的注入反过来
刷新时间戳（自我遮蔽），闸本身也不可靠。因此已移除；无人值守是否使用由用户自己
决定，真实输出后端仍然有 DSH 审批闸兜底。

所有外部事实（进程列表 / 热键状态）都通过可注入的函数获取，这样规则本身可以在
没有 Windows 的环境里被单测钉死。
"""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# 已知反作弊进程名（小写前缀匹配）。名单宁可多不可少：误拒只损失一次操作，
# 漏判会让用户账号冒封号风险。
KNOWN_ANTICHEAT_PROCESSES: dict[str, str] = {
    "easyanticheat": "EasyAntiCheat (EAC)",
    "easyanticheat_eos": "EasyAntiCheat (EOS)",
    "beservice": "BattlEye",
    "bedaisy": "BattlEye",
    "vgtray": "Riot Vanguard",
    "vgc": "Riot Vanguard",
    "vgk": "Riot Vanguard",
    "sguard64": "AntiCheatExpert (ACE)",
    "sguardbec": "AntiCheatExpert (ACE)",
    "uncheater": "AntiCheatExpert (ACE)",
    "gamemon": "nProtect GameGuard",
    "gamemon64": "nProtect GameGuard",
    "xhunter1": "XIGNCODE3",
    "xxd-0": "XIGNCODE3",
    "pnkbstra": "PunkBuster",
    "pnkbstrb": "PunkBuster",
    "randgrid": "RICOCHET Anti-Cheat",
}

TAKEOVER_VK = 0x7B  # F12


def list_process_names() -> list[str]:
    """Windows tasklist → 进程名列表；失败返回空列表（宁可放行也不误伤？不）。

    注意：失败时返回空列表会被 SafetyGate 视为「没有反作弊」——这是唯一的
    放行口。因此调用方在 `fail_closed=True` 时应把空列表当异常处理。
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except Exception:  # noqa: BLE001
        return []
    names: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith('"'):
            names.append(line.split('"', 2)[1])
    return names


def scan_processes(names: Iterable[str]) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    for raw in names:
        stem = Path(raw.strip()).stem.lower()
        for prefix, label in sorted(KNOWN_ANTICHEAT_PROCESSES.items(), key=lambda kv: len(kv[0]), reverse=True):
            if stem == prefix or stem.startswith(prefix):
                entry = f"{label} ({raw.strip()})"
                if entry not in seen:
                    seen.add(entry)
                    hits.append(entry)
                break
    return hits


def takeover_pressed(vk: int = TAKEOVER_VK) -> bool:
    if not hasattr(ctypes, "windll"):
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:  # noqa: BLE001
        return False


@dataclass
class SafetyReport:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    anticheat: list[str] = field(default_factory=list)
    takeover: bool = False

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "anticheat": self.anticheat,
            "takeover": self.takeover,
        }


class SafetyGate:
    """命中任一硬闸即拒绝：反作弊进程、F12 夺回闩锁。"""

    def __init__(
        self,
        *,
        process_source: Callable[[], list[str]] = list_process_names,
        takeover_source: Callable[[], bool] = takeover_pressed,
        process_ttl_s: float = 2.0,
    ):
        self.process_ttl_s = process_ttl_s
        self._process_source = process_source
        self._takeover_source = takeover_source
        self.takeover_latched = False
        self._process_cache: list[str] = []
        self._process_cache_at = -1e9

    def _anticheat_hits(self) -> list[str]:
        """进程扫描带缓存：20 Hz 闭环里每拍都跑 tasklist 是不可接受的。

        缓存 2 秒只会让「刚启动的反作弊」最多晚 2 秒被看到——而反作弊通常是
        游戏启动前就在跑的，真正影响判定的时间窗远大于 2 秒。
        """
        import time as _time

        now = _time.monotonic()
        if now - self._process_cache_at > self.process_ttl_s:
            self._process_cache = scan_processes(self._process_source())
            self._process_cache_at = now
        return self._process_cache

    def evaluate(self) -> SafetyReport:
        reasons: list[str] = []
        anticheat = self._anticheat_hits()
        if anticheat:
            reasons.append("anti-cheat detected; output channels are refused")
        if self._takeover_source():
            self.takeover_latched = True
        if self.takeover_latched:
            reasons.append("takeover latched (F12); press again after re-attaching to resume")
        return SafetyReport(
            allowed=not reasons,
            reasons=reasons,
            anticheat=anticheat,
            takeover=self.takeover_latched,
        )

    def reset_takeover(self) -> None:
        self.takeover_latched = False
