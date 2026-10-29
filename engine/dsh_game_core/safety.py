"""安全闸：反作弊硬阻断、无人不自娱、随时可夺回。

三条规则来自项目铁律，必须在**输出通道**这一层实现，而不是靠文档或提示词：

1. **反作弊不接**：命中 EAC / BattlEye / Vanguard / ACE 等进程名即拒绝一切注入；
2. **无人不自娱**：超过 `unattended_after_s` 没有任何键鼠输入，就停止输出
   （agent 会话里没有真人在操作，这条最容易踩）；
3. **随时可夺回**：F12 热键一按，立即松手（下一次 act 直接拒绝，并把状态标出来）。

所有外部事实（进程列表 / 最后输入时间 / 热键状态）都通过可注入的函数获取，
这样规则本身可以在没有 Windows、没有真实输入的环境里被单测钉死。
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


def seconds_since_last_input() -> float | None:
    """距离上一次键盘/鼠标输入过了多少秒；非 Windows 或调用失败返回 None。"""
    if not hasattr(ctypes, "windll"):
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (now - info.dwTime) / 1000.0)
    except Exception:  # noqa: BLE001
        return None


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
    idle_seconds: float | None = None
    takeover: bool = False

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "anticheat": self.anticheat,
            "idle_seconds": None if self.idle_seconds is None else round(self.idle_seconds, 1),
            "takeover": self.takeover,
        }


class SafetyGate:
    """默认 fail-closed：拿不到人类在场证据就不许输出。"""

    def __init__(
        self,
        unattended_after_s: float = 180.0,
        *,
        process_source: Callable[[], list[str]] = list_process_names,
        idle_source: Callable[[], float | None] = seconds_since_last_input,
        takeover_source: Callable[[], bool] = takeover_pressed,
        process_ttl_s: float = 2.0,
    ):
        self.unattended_after_s = unattended_after_s
        self.process_ttl_s = process_ttl_s
        self._process_source = process_source
        self._idle_source = idle_source
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
        idle = self._idle_source()
        if idle is None:
            reasons.append("cannot verify human presence (no input telemetry)")
        elif idle > self.unattended_after_s:
            reasons.append(f"unattended for {idle:.0f}s > {self.unattended_after_s:.0f}s")
        return SafetyReport(
            allowed=not reasons,
            reasons=reasons,
            anticheat=anticheat,
            idle_seconds=idle,
            takeover=self.takeover_latched,
        )

    def reset_takeover(self) -> None:
        self.takeover_latched = False
