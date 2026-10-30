"""本地反射策略（小脑）：profile 驱动的 60 Hz 闭环。

设计边界：

- **不识别游戏**：键位、阈值全部来自 profile（见 general-state-contract.md）；
  引擎里没有 Cuphead 之类的游戏数据。
- **每拍都过安全闸**：反作弊 / F12 夺回在**当前拍**就停手——先 evaluate()，
  再决定按不按键，不存在「先按键后检查」的窗口。
- **线程不漏异常**：所有异常收在 `_run` 里；无论怎么结束，`release_all()` 一定执行。
  `stop()` 在等待线程退出后还会再释放一次，避免「线程卡死、按键卡住」。
- **只按 profile 声明的键**：`combat.hold` / `combat.advance` / `dodge.keys` /
  `stuck.probe_keys`，其它名字一律不碰。
- 观测走 `cheap_entities`（不 OCR）；没装 state.py 的阶段性开发环境退化为
  「看不到实体」，而不是抛错。

`status()` 形状（插件侧只依赖这一份）：

    {"running": bool, "ticks": int, "hz": float, "actions": int, "escapes": int,
     "stop_reason": str | None, "scene": str | None, "last_entities": int}
"""

from __future__ import annotations

import ctypes
import math
import threading
import time
from collections import deque
from collections.abc import Mapping
from typing import Any, Callable

import numpy as np

DEFAULT_TICK_HZ = 60
MAX_TICK_HZ = 240

# 缺省值按合同给的 profile schema：所有键可选，缺失时用这里的默认。
DEFAULT_THREAT_RADIUS = 0.18
DEFAULT_DODGE_COOLDOWN_MS = 350
DEFAULT_DODGE_PRESS_MS = 60
DEFAULT_JUMP_KEYS = ("Z",)  # 默认跳跃键；真实键位由 profile 覆盖
DEFAULT_STATIC_MEAN_DIFF = 0.9
DEFAULT_STUCK_AFTER_MS = 600
DEFAULT_PROBE_MS = 350
# 玩家在画面里的默认锚点（下中）。威胁距离以它为原点计算；
# 优先用 profile 的 self_pos（与 state.py 同一个约定），player_anchor/anchor 是别名。
DEFAULT_PLAYER_ANCHOR = (0.5, 0.72)

_STATIC_WIDTH = 160  # 静止判定的下采样宽度，和 grab_diff 保持同一量级

# Windows 默认 sleep 粒度约 15.6ms，60 Hz 环会被拖到 ~22ms/拍。开 1ms 定时器
# 让 sleep(10ms) 真的只睡 ~10ms（只影响本进程，退出时恢复）。
_HIGH_RES_ACTIVE = False


def _enable_high_res_timer() -> None:
    global _HIGH_RES_ACTIVE
    if _HIGH_RES_ACTIVE or not hasattr(ctypes, "windll"):
        return
    try:
        if ctypes.windll.winmm.timeBeginPeriod(1) == 0:
            _HIGH_RES_ACTIVE = True
    except Exception:  # noqa: BLE001 - 非 Windows/受限环境保持默认粒度
        pass


def _disable_high_res_timer() -> None:
    global _HIGH_RES_ACTIVE
    if not _HIGH_RES_ACTIVE:
        return
    try:
        ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:  # noqa: BLE001
        pass
    finally:
        _HIGH_RES_ACTIVE = False


def _as_float(value: Any, default: float | None) -> float | None:
    """把任意值转成有限浮点；失败/NaN/Inf 一律回落到 default。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _key_list(value: Any) -> list[str]:
    """profile 里的键名可以是单个字符串，也可以是字符串列表。"""
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def _point(value: Any) -> tuple[float, float] | None:
    """归一化坐标点：{"x", "y"} 或 [x, y]；非法时 None。"""
    if isinstance(value, Mapping):
        x = _as_float(value.get("x"), None)
        y = _as_float(value.get("y"), None)
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x = _as_float(value[0], None)
        y = _as_float(value[1], None)
    else:
        return None
    if x is None or y is None:
        return None
    return (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))


def _gate_verdict(report: Any) -> tuple[bool, list[str]]:
    """兼容 SafetyReport 对象与 {"allowed", "reasons"} 字典；认不出来就 fail-closed。"""
    if isinstance(report, dict):
        allowed = report.get("allowed", True)
        reasons = report.get("reasons") or []
    else:
        allowed = getattr(report, "allowed", None)
        if allowed is None:
            return False, ["safety gate returned an unrecognized report"]
        reasons = getattr(report, "reasons", None) or []
    if not isinstance(reasons, (list, tuple)):
        reasons = [str(reasons)]
    return bool(allowed), [str(reason) for reason in reasons]


def _approaching(track: Any, anchor: tuple[float, float]) -> float:
    """轨迹速度朝玩家方向的分量（归一化/秒）；负值表示远离。"""
    dx = anchor[0] - track.x
    dy = anchor[1] - track.y
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0.0
    return (track.vx * dx + track.vy * dy) / length


def _frame_small(frame: np.ndarray) -> np.ndarray:
    """先切片下采样再转 float；对 962x567 帧只需处理 ~160x94，避免每拍全帧转换。"""
    if frame is None or frame.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    height, width = frame.shape[:2]
    step = max(1, int(width) // _STATIC_WIDTH)
    small = frame[::step, ::step]
    if small.ndim == 3:
        return small.astype(np.float32).mean(axis=2)
    return small.astype(np.float32)


def _static_metric(previous: np.ndarray, current: np.ndarray) -> float:
    """帧间平均绝对差（0..255 量级，阈值语义同 profile.combat.stuck）。"""
    try:
        before = _frame_small(previous)
        after = _frame_small(current)
    except Exception:  # noqa: BLE001 - 指标算不出来就当作「在动」，绝不误判卡住
        return float("inf")
    if before.shape != after.shape or before.size == 0:
        return float("inf")
    return float(np.abs(after - before).mean())


def _estimate_scroll_dx(previous: np.ndarray, current: np.ndarray) -> float | None:
    """估计横版镜头/画面水平位移（下采样像素）。

    整帧静止判定会被背景动画/弹幕骗过；镜头是否滚动更能说明「有没有在前进」。
    用相位相关（cv2.phaseCorrelate）在 ~160x94 灰度图上做，约 1ms。
    """
    try:
        import cv2

        before = _frame_small(previous)
        after = _frame_small(current)
        if before.shape != after.shape or before.size == 0:
            return None
        # 纯色/几乎无纹理的画面相位相关会给出垃圾值，直接放弃让调用方退回整帧差分。
        if float(before.std()) < 1.0 or float(after.std()) < 1.0:
            return None
        shift, response = cv2.phaseCorrelate(before, after)
        if not math.isfinite(response) or response < 0.05:
            return None
        if abs(float(shift[0])) > 24.0:
            return None
        return float(shift[0])
    except Exception:  # noqa: BLE001 - 滚动估计失败时退回整帧差分
        return None


class PolicyRunner:
    """60 Hz 本地反射策略：按住持续键 → 看威胁闪避 → 卡住脱困 → 安全闸收尾。"""

    def __init__(
        self,
        *,
        capture: Callable[[], Any],
        controller: Any,
        gate: Any,
        profile: dict | None,
        tick_hz: float = DEFAULT_TICK_HZ,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
        entities: Callable[..., list] | None = None,
        scene_source: Callable[[], str | None] | None = None,
        foreground_ok: Callable[[], bool | None] | None = None,
        focus_window: Callable[[], Any] | None = None,
        hp_source: Callable[[], Any] | None = None,
        on_danger_outcome: Callable[[str, str], Any] | None = None,
        prompt_source: Callable[[Any, Any], Any] | None = None,
    ):
        self._capture = capture
        self._controller = controller
        self._gate = gate
        self._profile = profile if isinstance(profile, dict) else {}
        self._clock = clock if callable(clock) else time.monotonic
        self._sleep = sleep if callable(sleep) else time.sleep
        # 可注入实体检测（单测用）；默认懒加载 .state.cheap_entities。
        self._entities_source = entities if callable(entities) else None
        # 可选：给 status.scene 提供场景（60 Hz 路径不做 OCR，由调用方缓存喂进来）。
        self._scene_source = scene_source if callable(scene_source) else None
        # 可选：逐拍前台校验 + 重新聚焦（SendInput 只送前台窗口）。
        self._foreground_ok = foreground_ok if callable(foreground_ok) else None
        self._focus_window = focus_window if callable(focus_window) else None
        # 可选：缓存 HP + 危险卡结果回调（结果回写由会话持久化）。
        self._hp_source = hp_source if callable(hp_source) else None
        self._on_danger_outcome = on_danger_outcome if callable(on_danger_outcome) else None
        self._prompt_source = prompt_source if callable(prompt_source) else None
        # walk-until-affordance：按住方向走，检测到交互图标就停步确认（地图入口）。
        navigation = self._profile.get("navigation")
        navigation = navigation if isinstance(navigation, dict) else {}
        self._nav_mode = bool(navigation.get("walk_to_affordance", False))
        nav_direction = navigation.get("direction")
        self._nav_direction = str(nav_direction) if nav_direction else None
        nav_confirm = navigation.get("confirm")
        self._nav_confirm = str(nav_confirm) if nav_confirm else "confirm"
        self._nav_every = max(1, int(_as_float(navigation.get("prompt_every_n_ticks"), 5) or 5))
        self._danger_armed: dict | None = None
        self._danger_armed_at = 0.0
        self._timings = {
            name: deque(maxlen=120)
            for name in ("grab", "entities", "player", "memory", "hit", "loop")
        }
        self._entities_missing = False
        self._last_error: str | None = None

        hz = _as_float(tick_hz, DEFAULT_TICK_HZ) or DEFAULT_TICK_HZ
        self._tick_hz = min(max(hz, 1.0), MAX_TICK_HZ)
        self._period = 1.0 / self._tick_hz

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # ── 计数器（status() 的形状） ──
        self._running = False
        self._ticks = 0
        self._actions = 0
        self._escapes = 0
        self._stop_reason: str | None = None
        self._scene: str | None = None
        self._last_entities = 0
        self._started_at: float | None = None
        self._ended_at: float | None = None

        # ── profile 解析（全部兜底，坏 profile 不抛） ──
        controls = self._profile.get("controls")
        self._controls: dict[str, str] = {}
        if isinstance(controls, dict):
            self._controls = {
                str(name).strip().lower(): value.strip()
                for name, value in controls.items()
                if isinstance(value, str) and value.strip()
            }

        combat = self._profile.get("combat")
        combat = combat if isinstance(combat, dict) else {}

        advance = self._resolve_key(combat.get("advance"))
        self._advance_key = advance
        hold_keys: list[str] = []
        for key in [*self._resolve_keys(combat.get("hold")), *([advance] if advance else [])]:
            if key not in hold_keys:
                hold_keys.append(key)
        self._hold_keys: tuple[str, ...] = tuple(hold_keys)

        dodge = combat.get("dodge")
        dodge = dodge if isinstance(dodge, dict) else {}
        # 缺省「按跳跃」：优先用 controls.jump 的键位，没有才退回通用默认。
        jump = self._controls.get("jump")
        default_jump_keys = (jump,) if jump else DEFAULT_JUMP_KEYS
        self._dodge_keys = (
            tuple(self._resolve_keys(dodge.get("keys"))) if "keys" in dodge else default_jump_keys
        )
        self._threat_radius = max(0.0, _as_float(dodge.get("threat_radius"), DEFAULT_THREAT_RADIUS) or 0.0)
        self._dodge_cooldown_ms = max(
            0.0, _as_float(dodge.get("cooldown_ms"), DEFAULT_DODGE_COOLDOWN_MS) or 0.0
        )
        self._dodge_press_ms = max(1.0, _as_float(dodge.get("press_ms"), DEFAULT_DODGE_PRESS_MS) or 1.0)
        # 威胁距离以「自己在画面里的位置」为原点。沿用 state.py 的 self_pos 约定
        # （profile.self_pos / combat.self_pos / player.self_pos / player.{x,y}），
        # 另外接受 player_anchor / anchor 作为早期别名。
        player = self._profile.get("player")
        player = player if isinstance(player, dict) else {}
        self._anchor = (
            _point(self._profile.get("self_pos"))
            or _point(combat.get("self_pos"))
            or _point(player.get("self_pos"))
            or _point(player)
            or _point(combat.get("player_anchor"))
            or _point(combat.get("anchor"))
            or DEFAULT_PLAYER_ANCHOR
        )

        stuck = combat.get("stuck")
        stuck = stuck if isinstance(stuck, dict) else {}
        self._stuck_static_mean_diff = _as_float(
            stuck.get("static_mean_diff"), DEFAULT_STATIC_MEAN_DIFF
        )
        self._stuck_after_ms = max(0.0, _as_float(stuck.get("after_ms"), DEFAULT_STUCK_AFTER_MS) or 0.0)
        self._probe_ms = max(1.0, _as_float(stuck.get("probe_ms"), DEFAULT_PROBE_MS) or 1.0)
        # 镜头水平位移小于该值（下采样像素）视为「没有前进」，比整帧静止更可靠。
        self._scroll_min_px = max(0.0, _as_float(stuck.get("scroll_min_px"), 0.8) or 0.0)
        self._probe_keys = (
            tuple(self._resolve_keys(stuck.get("probe_keys")))
            if "probe_keys" in stuck
            else default_jump_keys
        )
        # 赶路时周期性跳跃（通用「跑酷段」辅助）：非 0 时每隔 N ms 按一次跳跃键。
        # 背景动画会让整帧「静止」判定失灵，周期性跳跃比纯静止检测更适合横版移动。
        self._jump_every_ms = max(0.0, _as_float(combat.get("jump_every_ms"), 0.0) or 0.0)
        self._jump_keys: tuple[str, ...] = self._dodge_keys or self._probe_keys
        # 赶路时周期性冲刺（横版跑酷可跨障碍/拉开距离）。
        self._dash_every_ms = max(0.0, _as_float(combat.get("dash_every_ms"), 0.0) or 0.0)
        dash_key = self._controls.get("dash")
        self._dash_keys: tuple[str, ...] = (dash_key,) if dash_key else ()
        # 交战距离：威胁进入该半径时先停前进、继续射击，避免「一路走进敌人身上」。
        self._engage_radius = max(0.0, _as_float(combat.get("engage_radius"), 0.0) or 0.0)
        self._engage_hold_ms = max(0.0, _as_float(combat.get("engage_hold_ms"), 220.0) or 0.0)
        # 基本操作先验：交战停步不能无限持续，否则会在原地「磨蹭」不推进。
        self._engage_max_ms = max(0.0, _as_float(combat.get("engage_max_ms"), 0.0) or 0.0)
        # 受击后短暂强制推进/跳跃，避免掉血后原地发呆。
        self._post_hit_ms = max(0.0, _as_float(combat.get("post_hit_ms"), 450.0) or 0.0)
        self._engage_stop_ms = 0.0
        self._last_engage_at: float | None = None
        self._engage_suppressed_until = 0.0
        self._hurt_until = 0.0
        self._hurt_jump_pending = False
        self._entity_roles = []
        self._turn_until = 0.0
        self._last_hazard_jump = 0.0
        self._macro_used = set()
        self._macro_state = None
        # 实体跟踪 / 交战细节（通用，可按游戏关闭）。
        self._ignore_own_bullets = bool(combat.get("ignore_own_bullets", True))
        self._face_back = bool(combat.get("face_back", True))
        self._turn_press_ms = max(20.0, _as_float(combat.get("turn_press_ms"), 90.0) or 90.0)
        self._track_radius = max(0.01, _as_float(combat.get("track_match_radius"), 0.08) or 0.08)
        # 单机「一次学习」反射：candidate 危险卡也允许在对应坐标执行一次规避动作。
        self._danger_reflex = bool(combat.get("danger_reflex", False))
        # 对象级理解 + 背后追击者处理（默认关闭，profile 开启）。
        self._entity_memory_enabled = bool(combat.get("entity_memory", False))
        self._entity_every = max(1, int(_as_float(combat.get("entity_every_n_ticks"), 6) or 6))
        self._turn_and_shoot = bool(combat.get("turn_and_shoot", False))
        self._turn_shoot_ms = max(200.0, _as_float(combat.get("turn_shoot_ms"), 600.0) or 600.0)
        self._entity_memory = None
        self._entity_roles: list[dict] = []
        self._turn_until = 0.0
        # 静态危险物（地面毒蘑菇/地刺）：颜色区域检测 + 临近跳跃。
        self._static_hazards = bool(combat.get("static_hazards", False))
        self._hazard_every = max(1, int(_as_float(combat.get("hazard_every_n_ticks"), 6) or 6))
        self._hazard_cooldown_ms = max(200.0, _as_float(combat.get("hazard_cooldown_ms"), 700.0) or 700.0)
        self._hazard_distance = max(0.05, _as_float(combat.get("hazard_distance"), 0.32) or 0.32)
        self._last_hazard_jump = 0.0
        macros = self._profile.get("macros")
        self._macros = macros if isinstance(macros, list) else []
        self._macro_used = set()
        self._macro_state = None
        terrain = self._profile.get("terrain")
        terrain = terrain if isinstance(terrain, dict) else {}
        self._gap_enabled = bool(terrain.get("gap_enabled", False))
        self._gap_every = max(1, int(_as_float(terrain.get("gap_every_n_ticks"), 6) or 6))
        self._gap_cooldown_ms = max(200.0, _as_float(terrain.get("gap_cooldown_ms"), 600.0) or 600.0)
        self._last_gap_jump = 0.0
        self._tracker = None
        self._tracks: list[Any] = []
        # 场景门控/恢复：profile.scenes = {scene: {"recover": [{"press": "confirm"}], ...}}
        scenes = self._profile.get("scenes")
        self._scenes = scenes if isinstance(scenes, dict) else {}
        self._recover_interval_ms = max(200.0, _as_float(self._profile.get("scene", {}).get("recover_interval_ms") if isinstance(self._profile.get("scene"), dict) else None, 800.0) or 800.0)
        self._recover_max_attempts = 40
        self._recover_scene: str | None = None
        self._recover_attempts = 0
        self._last_recover_at = 0.0
        self._latest_frame = None

        # 玩家追踪：profile.player.track=true 时定期用 state.find_player 更新锚点，
        # 让闪避/交战半径跟着角色走，而不是固定 self_pos。
        player_cfg = self._profile.get("player")
        player_cfg = player_cfg if isinstance(player_cfg, dict) else {}
        self._track_player = bool(player_cfg.get("track", False))
        self._player_every = max(1, int(_as_float(player_cfg.get("every_n_ticks"), 3) or 3))
        self._player_source: Callable[..., Any] | None = None
        self._player_candidate = None
        # 关卡记忆：滚动坐标 + 可选的 DangerCard 列表（由会话按 game/level 注入）。
        self._locator = None
        self._dangers = self._profile.get("danger_cards")
        self._danger_window = max(0.1, _as_float(self._profile.get("danger_window"), 1.2) or 1.2)
        self._nearby_danger: dict | None = None
        self._scroll_s = 0.0
        self._last_danger_id: str | None = None
        self._prev_scene: str | None = None
        self._danger_armed = None
        self._danger_armed_at = 0.0
        # 快环受击信号：HP 区域白色像素数变化（OCR 只做数值确认）。
        hud = self._profile.get("hud")
        hp = hud.get("hp") if isinstance(hud, dict) else None
        box = hp.get("box") if isinstance(hp, dict) else None
        self._hp_box = tuple(box) if isinstance(box, (list, tuple)) and len(box) >= 4 else None
        self._hp_signature: int | None = None
        self._last_hit: dict | None = None
        self._last_hit_at = 0.0

        # ── 线程内状态 ──
        self._held: set[str] = set()
        self._last_dodge_at: float | None = None
        self._last_jump_at: float | None = None
        self._last_dash_at: float | None = None
        self._engage_until = 0.0
        self._engage_started: float | None = None
        self._engage_stop_ms = 0.0
        self._last_engage_at = None
        self._engage_suppressed_until = 0.0
        self._hurt_until = 0.0
        self._hurt_jump_pending = False
        self._entity_roles = []
        self._turn_until = 0.0
        self._last_hazard_jump = 0.0
        self._macro_used = set()
        self._macro_state = None
        self._tracks = []
        # 非阻塞点按：press() 会 sleep 按住时长，60 Hz 环里不能调用它；
        # 这里改用 hold + 到期 release，避免跳跃/闪避把整拍拖慢。
        self._pending_releases: list[tuple[float, str]] = []

    # ── profile 键位解析 ──────────────────────────────────────────────
    def _resolve_key(self, value: Any) -> str | None:
        """把 profile 里的名字解析成后端键名。

        `combat.advance` 既可以写后端键名（"RIGHT"），也可以写 controls 的语义名
        （"right"）；两种都通过同一张 controls 表映射，未知名字原样透传。
        """
        if not isinstance(value, str):
            return None
        clean = value.strip()
        if not clean:
            return None
        mapped = self._controls.get(clean.lower())
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
        return clean

    def _resolve_keys(self, value: Any) -> list[str]:
        keys: list[str] = []
        for name in _key_list(value):
            key = self._resolve_key(name)
            if key is not None and key not in keys:
                keys.append(key)
        return keys

    # ── 生命周期 ──────────────────────────────────────────────────────
    def start(self) -> dict:
        """启动守护线程；已在运行时幂等返回当前 status。"""
        with self._lock:
            if self._running:
                return self._status_locked()
            self._reset_locked()
            self._stop_event.clear()
            self._running = True
            self._started_at = self._clock()
            _enable_high_res_timer()
            self._thread = threading.Thread(target=self._run, name="dsh-game-policy", daemon=True)
            self._thread.start()
            return self._status_locked()

    def stop(self) -> dict:
        """停止闭环：请线程退出、等待、再释放所有按键；可重复调用。"""
        thread = self._thread
        self._stop_event.set()
        current = threading.current_thread()
        if thread is not None and thread is not current and thread.is_alive():
            thread.join(timeout=max(1.0, self._period * 8.0))
        try:
            self._controller.release_all()
        except Exception:  # noqa: BLE001 - 收尾失败不掩盖主流程
            pass
        with self._lock:
            self._held.clear()
            if self._started_at is not None and self._stop_reason is None:
                self._stop_reason = "stopped"
            self._running = False
            self._ended_at = self._clock()
            return self._status_locked()

    def join(self, timeout: float | None = None) -> bool:
        """等待线程结束（主要给测试/收尾用）；True 表示线程已经不在了。"""
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout)
        return not thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def last_error(self) -> str | None:
        """最近一次抓帧/实体检测的软失败（安全闸阻断不算），便于排查。"""
        return self._last_error

    def _reset_locked(self) -> None:
        self._ticks = 0
        self._actions = 0
        self._escapes = 0
        self._stop_reason = None
        self._scene = None
        self._last_entities = 0
        self._ended_at = None
        self._last_dodge_at = None
        self._last_jump_at = None
        self._last_dash_at = None
        self._engage_until = 0.0
        self._engage_started: float | None = None
        self._engage_stop_ms = 0.0
        self._last_engage_at = None
        self._engage_suppressed_until = 0.0
        self._hurt_until = 0.0
        self._hurt_jump_pending = False
        self._entity_roles = []
        self._turn_until = 0.0
        self._last_hazard_jump = 0.0
        self._macro_used = set()
        self._macro_state = None
        self._pending_releases = []
        self._held = set()
        self._tracks = []
        self._recover_scene = None
        self._recover_attempts = 0
        self._last_recover_at = 0.0
        self._player_candidate = None
        self._nearby_danger = None
        self._scroll_s = 0.0
        self._last_danger_id = None
        self._prev_scene = None
        self._last_error = None

    def _status_locked(self) -> dict:
        hz = 0.0
        if self._started_at is not None and self._ticks > 0:
            ended = self._ended_at
            elapsed = (ended if ended is not None else self._clock()) - self._started_at
            if elapsed > 0:
                hz = round(self._ticks / elapsed, 1)
        role_map = {
            int(observation.get("id")): observation
            for observation in self._entity_roles
            if isinstance(observation, dict) and observation.get("id") is not None
        }
        return {
            "running": bool(self._running),
            "ticks": int(self._ticks),
            "hz": hz,
            "actions": int(self._actions),
            "escapes": int(self._escapes),
            "stop_reason": self._stop_reason,
            "scene": self._scene,
            "last_entities": int(self._last_entities),
            "scroll_s": round(float(self._scroll_s), 3),
            "danger": self._nearby_danger,
            "player": {"x": round(float(self._anchor[0]), 4), "y": round(float(self._anchor[1]), 4)},
            "hit": self._last_hit,
            "tracks": [
                {
                    "id": int(track.id),
                    "kind": str(track.kind),
                    "x": round(float(track.x), 4),
                    "y": round(float(track.y), 4),
                    "vx": round(float(track.vx), 4),
                    "vy": round(float(track.vy), 4),
                    "speed": round(float(track.speed), 4),
                    "role": (role_map.get(int(track.id)) or {}).get("role"),
                    "cluster": (role_map.get(int(track.id)) or {}).get("cluster"),
                }
                for track in getattr(self, "_tracks", [])[:8]
            ],
            "timing": {
                name: round(sum(values) / len(values) * 1000.0, 2) if values else 0.0
                for name, values in self._timings.items()
            },
        }

    # ── 线程主体 ──────────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            self._loop()
        except BaseException as error:  # noqa: BLE001 - 线程里绝不能让异常漏出去
            self._stop_reason = f"error: {type(error).__name__}: {error}"
        finally:
            _disable_high_res_timer()
            self._running = False
            with self._lock:
                self._ended_at = self._clock()
            try:
                self._controller.release_all()
            except Exception:  # noqa: BLE001 - 释放失败不掩盖真实错误
                pass
            with self._lock:
                self._held.clear()

    def _loop(self) -> None:
        if self._entities_source is None:
            self._entities_source = self._load_entities()
        if self._track_player and self._player_source is None:
            self._player_source = self._load_player()
        if self._tracker is None:
            self._tracker = self._load_tracker()
        previous_frame: np.ndarray | None = None
        previous_tick_at: float | None = None
        static_ms = 0.0
        while not self._stop_event.is_set():
            tick_started = self._clock()
            # 用真实经过时间累计「静止」时长：抓帧/按键可能比一拍慢，固定周期会失真。
            dt_ms = 0.0
            if previous_tick_at is not None:
                dt_ms = min(max((tick_started - previous_tick_at) * 1000.0, 0.0), 1000.0)
            previous_tick_at = tick_started

            # 1) 安全闸：本拍任何输出之前先问一次；不允许「先按键后检查」。
            allowed, reasons = _gate_verdict(self._gate.evaluate())
            if not allowed:
                self._stop_reason = "safety: " + ("; ".join(reasons) if reasons else "blocked")
                self._stop_event.set()
                break
            self._release_due()

            # 1.5) 前台校验：SendInput 只送前台窗口；DSH 可能在工具调用期间抢回前台。
            if self._foreground_ok is not None:
                try:
                    foreground_ok = self._foreground_ok() is not False
                except Exception:  # noqa: BLE001 - 前台查询失败不阻塞闭环
                    foreground_ok = True
                if not foreground_ok:
                    if self._focus_window is not None:
                        try:
                            self._focus_window()
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        foreground_ok = self._foreground_ok() is not False
                    except Exception:  # noqa: BLE001
                        foreground_ok = False
                    if not foreground_ok:
                        self._release_all_keys()
                        self._last_error = "foreground lost; paused"
                        self._ticks += 1
                        delay = self._period
                        if delay > 0:
                            self._sleep(delay)
                        continue

            # 2) 一帧原始 BGR（不 OCR、不编码）。
            grab_started = self._clock()
            frame = self._grab()
            self._mark_timing("grab", grab_started)
            self._latest_frame = frame
            if frame is not None and self._nav_mode:
                self._run_navigation(frame)
                self._ticks += 1
                delay = self._period
                if delay > 0:
                    self._sleep(delay)
                continue
            entities: list[dict] = []
            if frame is None:
                # 看不到画面时不盲按：先松开持续键，等下一拍恢复再重新按住。
                static_ms = 0.0
                self._release_holds()
                previous_frame = None
                self._last_entities = 0
            else:
                self._read_scene()
                if self._scene != self._prev_scene:
                    # 死亡/换装/菜单回到 gameplay = 新的一条命，关卡坐标从 0 重新累计。
                    if self._scene == "gameplay" and self._prev_scene in (
                        "death",
                        "equip",
                        "cutscene",
                        "menu",
                        "loading",
                    ):
                        self._scroll_s = 0.0
                        self._last_danger_id = None
                        self._hp_signature = None
                        if self._locator is not None:
                            self._locator.reset()
                    self._prev_scene = self._scene
                # 2.5) 场景门控：非 gameplay 只做恢复，不跑战斗策略。
                if self._scene is not None and self._scene != "gameplay":
                    entities = self._entities(frame, previous_frame)
                    self._release_all_keys()
                    self._maybe_recover()
                    self._ticks += 1
                    delay = self._period
                    if delay > 0:
                        self._sleep(delay)
                    continue
                entities_started = self._clock()
                entities = self._entities(frame, previous_frame)
                self._mark_timing("entities", entities_started)
                self._last_entities = len(entities)
                hit_started = self._clock()
                self._update_hit_signal(frame)
                self._mark_timing("hit", hit_started)
                self._update_tracks(entities)
                self._update_entity_memory(frame)
                self._maybe_static_hazard(frame)
                self._maybe_gap_jump(frame)
                player_started = self._clock()
                self._update_player(frame)
                self._mark_timing("player", player_started)
                memory_started = self._clock()
                self._update_memory(previous_frame, frame)
                self._mark_timing("memory", memory_started)
                self._check_danger_outcome()
                if self._route_macro_tick():
                    self._ticks += 1
                    delay = self._period
                    if delay > 0:
                        self._sleep(delay)
                    continue
                self._maybe_engage(entities)
                self._maybe_turn_shoot()

            # 3) 持续键（射击 / 前进）：缺什么补什么，已经按住的不重复按。
            self._ensure_holds()
            self._maybe_jump()
            self._maybe_dash()

            if frame is not None:
                self._maybe_dodge(entities)
                if previous_frame is not None and self._is_advancing():
                    dx = _estimate_scroll_dx(previous_frame, frame)
                    if dx is not None:
                        moving = abs(dx) >= self._scroll_min_px
                    else:
                        moving = _static_metric(previous_frame, frame) >= self._stuck_static_mean_diff
                    if moving:
                        static_ms = 0.0
                    else:
                        static_ms += dt_ms
                    if static_ms >= self._stuck_after_ms:
                        # 卡住：松开前进 → 短按脱困键 → 重新前进。
                        self._escape()
                        static_ms = 0.0
                previous_frame = frame

            self._read_scene()
            self._ticks += 1
            delay = self._period - (self._clock() - tick_started)
            if delay > 0:
                self._sleep(delay)

    # ── 单拍动作 ──────────────────────────────────────────────────────
    def _ensure_holds(self) -> None:
        engage = self._clock() < self._engage_until
        if self._clock() < self._engage_suppressed_until:
            engage = False
        turning = self._clock() < self._turn_until
        for key in self._hold_keys:
            if key in self._held:
                continue
            if (engage or turning) and key == self._advance_key:
                continue
            self._controller.hold(key)
            self._held.add(key)
            self._actions += 1
        if self._advance_key is not None and self._advance_key in self._held:
            self._engage_stop_ms = 0.0
            self._last_engage_at = None

    def _update_entity_memory(self, frame: np.ndarray) -> None:
        if not self._entity_memory_enabled:
            return
        if self._entity_memory is None:
            try:
                from .entity_memory import EntityMemory

                self._entity_memory = EntityMemory()
            except Exception:  # noqa: BLE001
                return
        if self._ticks % self._entity_every != 0:
            return
        try:
            self._entity_roles = self._entity_memory.update(
                self._tracks,
                frame,
                self._anchor,
                hp=self._current_hp(),
                now=self._clock(),
            )
        except Exception:  # noqa: BLE001 - 对象记忆失败只损失语义
            self._entity_roles = []

    def _run_navigation(self, frame: np.ndarray) -> None:
        """按住方向走，检测交互图标；出现即停步、确认、结束策略。"""
        direction = self._resolve_key(self._nav_direction) if self._nav_direction else None
        if direction is None:
            return
        for key in list(self._held):
            if key != direction:
                self._release_key(key)
        if direction not in self._held:
            self._controller.hold(direction)
            self._held.add(direction)
            self._actions += 1
        if self._ticks % self._nav_every != 0 and self._ticks > 1:
            return
        found = None
        try:
            if self._prompt_source is not None:
                found = self._prompt_source(frame, self._profile)
            else:
                from .state import detect_prompt_icon

                found = detect_prompt_icon(frame, self._profile)
        except Exception:  # noqa: BLE001
            found = None
        if not isinstance(found, dict) or not found.get("key"):
            return
        self._release_all_keys()
        key = self._resolve_key(self._nav_confirm) if self._nav_confirm else None
        if key:
            self._tap(key, 140.0)
        self._stop_reason = "affordance_confirm"
        self._stop_event.set()

    def _maybe_gap_jump(self, frame: np.ndarray) -> None:
        """前方地面变暗（断崖/坑）时跳一次。"""
        if not self._gap_enabled or not self._jump_keys:
            return
        if self._ticks % self._gap_every != 0:
            return
        now = self._clock()
        if (now - self._last_gap_jump) * 1000.0 < self._gap_cooldown_ms:
            return
        try:
            from .state import detect_gap_ahead

            if detect_gap_ahead(frame, self._profile, self._anchor):
                self._tap(self._jump_keys[0], 140.0)
                self._last_gap_jump = now
        except Exception:  # noqa: BLE001
            return

    def _maybe_static_hazard(self, frame: np.ndarray) -> None:
        """地面静态危险物：靠近且在前方时跳一次（颜色区域检测，profile 驱动）。"""
        if not self._static_hazards or not self._jump_keys:
            return
        if self._ticks % self._hazard_every != 0:
            return
        now = self._clock()
        if (now - self._last_hazard_jump) * 1000.0 < self._hazard_cooldown_ms:
            return
        try:
            from .state import detect_static_hazards

            hazards = detect_static_hazards(frame, self._profile)
        except Exception:  # noqa: BLE001
            return
        anchor_x, anchor_y = self._anchor
        for hazard in hazards:
            dx = float(hazard.get("x") or 0.0) - anchor_x
            if dx <= 0.02 or dx > self._hazard_distance:
                continue
            if abs(float(hazard.get("y") or 0.0) - anchor_y) > 0.45:
                continue
            self._tap(self._jump_keys[0], 140.0)
            self._last_hazard_jump = now
            return

    def _route_macro_tick(self) -> bool:
        """在 profile.macros 指定的 scroll_s 附近执行一段按键序列；返回是否接管本拍。"""
        state = self._macro_state
        now = self._clock()
        if state is None:
            if not self._macros:
                return False
            for index, macro in enumerate(self._macros):
                if index in self._macro_used or not isinstance(macro, dict):
                    continue
                try:
                    target = float(macro.get("scroll_s"))
                    window = float(macro.get("window") or 0.8)
                except (TypeError, ValueError):
                    continue
                if abs(self._scroll_s - target) > window:
                    continue
                steps = macro.get("steps")
                if not isinstance(steps, list) or not steps:
                    continue
                self._macro_used.add(index)
                self._release_all_keys()
                self._macro_state = {"steps": steps, "index": 0, "step_started": None, "holds": []}
                state = self._macro_state
                break
            else:
                return False
        steps = state["steps"]
        if state["index"] >= len(steps):
            self._macro_state = None
            return False
        step = steps[state["index"]]
        if not isinstance(step, dict):
            state["index"] += 1
            return True
        if state["step_started"] is None:
            self._release_all_keys()
            holds = [self._resolve_key(str(key)) for key in (step.get("hold") or [])]
            holds = [key for key in holds if key]
            for key in holds:
                self._controller.hold(key)
                self._held.add(key)
            state["holds"] = holds
            for key in step.get("tap") or []:
                resolved = self._resolve_key(str(key))
                if resolved:
                    self._tap(resolved, 120.0)
            state["step_started"] = now
            self._actions += 1
            return True
        duration_ms = max(50.0, _as_float(step.get("duration_ms"), 400.0) or 400.0)
        if (now - state["step_started"]) * 1000.0 < duration_ms:
            return True
        for key in state["holds"]:
            if key in self._held:
                self._release_key(key)
        state["holds"] = []
        state["step_started"] = None
        state["index"] += 1
        if state["index"] >= len(steps):
            self._macro_state = None
        return True

    def _maybe_turn_shoot(self) -> None:
        """背后有 approaching/chaser 时：停步、短点转向持续射击，再恢复推进。

        不能持续按住左键：横版关卡左侧可能是墙，会把自己顶在墙边。
        """
        if not self._turn_and_shoot:
            return
        now = self._clock()
        left = self._resolve_key("left") or "LEFT"
        advance = self._advance_key
        if now < self._turn_until:
            if advance is not None and advance in self._held:
                self._release_key(advance)
            if left in self._held:
                self._release_key(left)
            return
        if self._turn_until:
            self._turn_until = 0.0
        for observation in self._entity_roles:
            role = observation.get("role")
            harmful = int(observation.get("harmful_hits") or 0) > 0
            if role not in ("chaser", "approaching") and not harmful:
                continue
            if not observation.get("behind"):
                continue
            if float(observation.get("distance") or 1.0) > 0.6:
                continue
            self._turn_until = now + self._turn_shoot_ms / 1000.0
            if advance is not None and advance in self._held:
                self._release_key(advance)
            self._tap(left, 90.0)
            return

    def _maybe_engage(self, entities: list[dict]) -> None:
        """威胁进入交战半径：松开前进、保持射击；背后威胁则先转身。

        有轨迹时用轨迹（速度/方位）过滤「持续射击产生的己方子弹」：
        己方子弹速度快、朝远离玩家方向飞，不应触发交战/闪避。
        """
        if self._engage_radius <= 0:
            return
        if self._clock() < self._engage_suppressed_until:
            return
        anchor_x, anchor_y = self._anchor
        target = None
        if self._tracks:
            for track in self._tracks:
                if getattr(track, "kind", None) != "threat":
                    continue
                distance = math.hypot(track.x - anchor_x, track.y - anchor_y)
                if distance > self._engage_radius:
                    continue
                approach = _approaching(track, (anchor_x, anchor_y))
                if self._ignore_own_bullets and track.speed > 0.35 and approach < -0.05:
                    continue
                if target is None or distance < target[0]:
                    target = (distance, track.x, track)
        else:
            for entity in entities:
                if entity.get("kind") != "threat":
                    continue
                x = _as_float(entity.get("x"), None)
                y = _as_float(entity.get("y"), None)
                if x is None or y is None:
                    continue
                distance = math.hypot(x - anchor_x, y - anchor_y)
                if distance <= self._engage_radius and (target is None or distance < target[0]):
                    target = (distance, x, entity)
        if target is None:
            self._engage_stop_ms = 0.0
            self._last_engage_at = None
            return
        now = self._clock()
        if self._last_engage_at is not None:
            self._engage_stop_ms += max(0.0, (now - self._last_engage_at) * 1000.0)
        self._last_engage_at = now
        if self._engage_max_ms > 0 and self._engage_stop_ms >= self._engage_max_ms:
            # 累计停步太久：即使还有威胁也恢复推进一段时间，避免原地发呆。
            self._engage_suppressed_until = now + 0.8
            self._engage_stop_ms = 0.0
            return
        target_distance, target_x, _target = target
        self._engage_until = self._clock() + self._engage_hold_ms / 1000.0
        advance = self._advance_key
        if advance is not None and advance in self._held:
            self._release_key(advance)
        if self._face_back and target_x is not None and target_x < anchor_x - 0.04:
            turn = self._resolve_key("left") or "LEFT"
            self._tap(turn, self._turn_press_ms)

    def _release_holds(self) -> None:
        for key in [held for held in self._hold_keys if held in self._held]:
            self._release_key(key)

    def _release_all_keys(self) -> None:
        """前台丢失/暂停时一次性释放全部按键与待释放点按。"""
        try:
            self._controller.release_all()
        except Exception:  # noqa: BLE001
            pass
        self._held.clear()
        self._pending_releases = []
        self._actions += 1

    def _release_key(self, key: str) -> None:
        try:
            self._controller.release(key)
        finally:
            self._held.discard(key)
        self._actions += 1

    def _tap(self, key: str, duration_ms: float) -> None:
        """非阻塞点按：先 hold，到期后由下一拍 release（press() 会 sleep，不能用）。"""
        if key in self._held:
            return
        self._controller.hold(key)
        self._held.add(key)
        self._actions += 1
        self._pending_releases.append(
            (self._clock() + max(1.0, duration_ms) / 1000.0, key)
        )

    def _release_due(self) -> None:
        now = self._clock()
        remaining: list[tuple[float, str]] = []
        for release_at, key in self._pending_releases:
            if now >= release_at:
                try:
                    self._controller.release(key)
                    self._actions += 1
                finally:
                    self._held.discard(key)
            else:
                remaining.append((release_at, key))
        self._pending_releases = remaining

    def _is_advancing(self) -> bool:
        return self._advance_key is not None and self._advance_key in self._held

    def _maybe_dodge(self, entities: list[dict]) -> None:
        """威胁进入锚点半径且冷却结束时，按一次闪避键组。"""
        if not self._dodge_keys or not entities:
            return
        now = self._clock()
        if (
            self._last_dodge_at is not None
            and (now - self._last_dodge_at) * 1000.0 < self._dodge_cooldown_ms
        ):
            return
        anchor_x, anchor_y = self._anchor
        for entity in entities:
            if entity.get("kind") != "threat":
                continue
            x = _as_float(entity.get("x"), None)
            y = _as_float(entity.get("y"), None)
            if x is None or y is None:
                continue
            if math.hypot(x - anchor_x, y - anchor_y) <= self._threat_radius:
                for key in self._dodge_keys:
                    self._tap(key, self._dodge_press_ms)
                self._last_dodge_at = now
                return

    def _maybe_jump(self) -> None:
        """赶路时按固定间隔按一次跳跃键（profile.combat.jump_every_ms）。"""
        if not self._is_advancing() or self._jump_every_ms <= 0 or not self._jump_keys:
            return
        now = self._clock()
        if (
            self._last_jump_at is not None
            and (now - self._last_jump_at) * 1000.0 < self._jump_every_ms
        ):
            return
        for key in self._jump_keys:
            self._tap(key, self._dodge_press_ms)
        self._last_jump_at = now

    def _maybe_dash(self) -> None:
        """赶路时按固定间隔按一次冲刺键（profile.combat.dash_every_ms）。"""
        if not self._is_advancing() or self._dash_every_ms <= 0 or not self._dash_keys:
            return
        now = self._clock()
        if (
            self._last_dash_at is not None
            and (now - self._last_dash_at) * 1000.0 < self._dash_every_ms
        ):
            return
        for key in self._dash_keys:
            self._tap(key, self._dodge_press_ms)
        self._last_dash_at = now

    def _escape(self) -> None:
        """卡住脱困：release(advance) → press(probe_keys, probe_ms) → hold(advance)。"""
        advance = self._advance_key
        if advance is None:
            return
        if advance in self._held:
            self._release_key(advance)
        for key in self._probe_keys:
            self._tap(key, self._probe_ms)
        self._controller.hold(advance)
        self._held.add(advance)
        self._actions += 1
        self._escapes += 1

    # ── 观测 ──────────────────────────────────────────────────────────
    def _grab(self) -> np.ndarray | None:
        """抓一帧；失败返回 None（闭环继续，不盲按）。"""
        try:
            frame = self._capture()
        except Exception as error:  # noqa: BLE001 - 抓屏偶发失败不该杀掉闭环
            self._last_error = f"{type(error).__name__}: {error}"
            return None
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
            self._last_error = f"bad frame: {type(frame).__name__}"
            return None
        self._last_error = None
        return frame

    def _entities(self, frame: np.ndarray, previous_frame: np.ndarray | None) -> list[dict]:
        source = self._entities_source
        if source is None:
            return []
        try:
            found = source(frame, previous_frame, profile=self._profile)
        except Exception as error:  # noqa: BLE001 - 检测器坏了只损失本拍信息
            self._last_error = f"entities: {type(error).__name__}: {error}"
            return []
        if not isinstance(found, (list, tuple)):
            return []
        return [item for item in found if isinstance(item, dict)]

    def _load_entities(self) -> Callable[..., list]:
        """懒加载 .state.cheap_entities；state.py 还没落地时退化成空列表。"""
        try:
            from .state import cheap_entities
        except Exception:  # noqa: BLE001 - 阶段性开发允许 state.py 缺席
            self._entities_missing = True
            return lambda frame, previous, profile=None: []
        return cheap_entities

    def _load_player(self) -> Callable[..., Any] | None:
        try:
            from .state import find_player
        except Exception:  # noqa: BLE001
            return None
        return find_player

    def _load_tracker(self):
        try:
            from .tracking import EntityTracker
        except Exception:  # noqa: BLE001 - 阶段性开发允许 tracking.py 缺席
            return None
        return EntityTracker(match_radius=self._track_radius)

    def _load_locator(self):
        try:
            from .memory import LevelLocator
        except Exception:  # noqa: BLE001
            return None
        return LevelLocator()

    def _update_memory(self, previous_frame: np.ndarray | None, frame: np.ndarray) -> None:
        """把镜头滚动累积成关卡坐标，并检索附近的 DangerCard。"""
        if self._locator is None:
            self._locator = self._load_locator()
        if self._locator is not None and previous_frame is not None:
            try:
                dx = _estimate_scroll_dx(previous_frame, frame)
                if dx is not None:
                    self._locator.update(dx / float(_STATIC_WIDTH))
                    self._scroll_s = float(self._locator.position()["scroll_s"])
            except Exception:  # noqa: BLE001 - 定位失败只损失记忆检索
                pass
        self._nearby_danger = None
        if not isinstance(self._dangers, (list, tuple)):
            return
        best = None
        for card in self._dangers:
            if not isinstance(card, dict):
                continue
            place = card.get("place") if isinstance(card.get("place"), dict) else {}
            distance = abs(_as_float(place.get("scroll_s"), 0.0) - self._scroll_s)
            if distance <= self._danger_window and (best is None or distance < best[0]):
                best = (distance, card)
        if best is None:
            return
        distance, card = best
        trigger = card.get("trigger") if isinstance(card.get("trigger"), dict) else {}
        response = card.get("response") if isinstance(card.get("response"), dict) else {}
        self._nearby_danger = {
            "id": str(card.get("id") or "")[:80],
            "distance": round(distance, 3),
            "trigger": str(trigger.get("template") or trigger.get("kind") or "")[:64],
            "skill": str(response.get("skill") or "")[:32],
            "status": str(card.get("status") or "candidate")[:16],
            "acted": bool(card.get("id") and str(card.get("id")) == self._last_danger_id),
        }
        # 已人工/评测确认的危险点才执行预设技能；开 danger_reflex 时 candidate 也执行一次。
        status = str(card.get("status") or "candidate")
        skill = str(response.get("skill") or "")
        params = response.get("params") if isinstance(response.get("params"), dict) else {}
        default_distance = 0.18 if skill in ("jump_over", "unknown", "") else 0.24
        trigger_distance = max(0.05, _as_float(params.get("trigger_distance"), default_distance) or default_distance)
        card_id = self._nearby_danger["id"]
        allowed = status in ("validated", "trusted") or (self._danger_reflex and status == "candidate")
        if allowed and skill in ("jump_over", "evade", "unknown") and distance <= trigger_distance and card_id != self._last_danger_id:
            if skill == "evade":
                keys = self._dodge_keys
            else:
                keys = self._jump_keys
            key = keys[0] if keys else None
            if key:
                self._tap(key, 140.0)
            self._last_danger_id = card_id
            self._nearby_danger["acted"] = True
            self._danger_armed = {"id": card_id, "hp": self._current_hp()}
            self._danger_armed_at = self._clock()

    def _update_hit_signal(self, frame: np.ndarray) -> None:
        """快环 HP 区域白色像素签名；变化时记录 t_hit 和当时的关卡坐标。"""
        if self._hp_box is None or self._scene != "gameplay":
            return
        try:
            h, w = frame.shape[:2]
            left, top, bw, bh = self._hp_box
            x0 = int(max(0.0, min(1.0, float(left))) * w)
            y0 = int(max(0.0, min(1.0, float(top))) * h)
            x1 = int(max(0.0, min(1.0, float(left) + float(bw))) * w)
            y1 = int(max(0.0, min(1.0, float(top) + float(bh))) * h)
            if x1 <= x0 or y1 <= y0:
                return
            crop = frame[y0:y1, x0:x1]
            gray = crop.astype(np.uint8).mean(axis=2) if crop.ndim == 3 else crop
            signature = int(np.count_nonzero(gray > 200))
        except Exception:  # noqa: BLE001 - 签名失败只损失快环 t_hit
            return
        now = self._clock()
        if (
            self._hp_signature is not None
            and abs(signature - self._hp_signature) >= 8
            and now - self._last_hit_at >= 0.4
        ):
            self._last_hit = {
                "t": round(now, 3),
                "scroll_s": round(float(self._scroll_s), 3),
                "before": self._hp_signature,
                "after": signature,
            }
            self._last_hit_at = now
        self._hp_signature = signature

    def _mark_timing(self, name: str, started: float) -> None:
        try:
            self._timings[name].append(max(0.0, self._clock() - started))
        except Exception:  # noqa: BLE001 - 计时失败不影响主流程
            pass

    def _current_hp(self) -> int | None:
        if self._hp_source is None:
            return None
        try:
            value = self._hp_source()
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
        except Exception:  # noqa: BLE001 - HP 源失败只损失结果回写
            return None

    def _check_danger_outcome(self) -> None:
        """危险卡执行后：掉血算 failed，离开窗口一段时间未掉血算 avoided。"""
        armed = self._danger_armed
        if not armed:
            return
        current_hp = self._current_hp()
        outcome = None
        if current_hp is not None and armed.get("hp") is not None and current_hp < int(armed["hp"]):
            outcome = "failed"
        elif self._clock() - self._danger_armed_at >= 2.8:
            nearby = self._nearby_danger
            if not nearby or nearby.get("id") != armed.get("id"):
                outcome = "avoided"
        if outcome is None:
            return
        callback = self._on_danger_outcome
        if callback is not None:
            try:
                callback(str(armed.get("id") or ""), outcome)
            except Exception:  # noqa: BLE001 - 回写失败不影响玩法
                pass
        self._danger_armed = None

    def _update_tracks(self, entities: list[dict]) -> None:
        if self._tracker is None:
            self._tracks = []
            return
        try:
            self._tracks = self._tracker.update(entities, now=self._clock())
        except Exception:  # noqa: BLE001 - 跟踪失败只损失本拍方位信息
            self._tracks = []

    def _update_player(self, frame: np.ndarray) -> None:
        """定期更新角色屏幕坐标；低置信度/跳变过大时保留上一个可信锚点。"""
        if not self._track_player or self._player_source is None:
            return
        if self._ticks % self._player_every != 0:
            return
        try:
            found = self._player_source(frame, self._profile, previous=self._anchor)
        except TypeError:
            try:
                found = self._player_source(frame, self._profile)
            except Exception:  # noqa: BLE001
                return
        except Exception:  # noqa: BLE001 - 追踪失败只损失本拍精度
            return
        if not isinstance(found, dict):
            return
        x = _as_float(found.get("x"), None)
        y = _as_float(found.get("y"), None)
        score = _as_float(found.get("score"), 0.0) or 0.0
        if x is None or y is None or score < 0.35:
            return
        previous_x, previous_y = self._anchor
        distance = math.hypot(x - previous_x, y - previous_y)
        # 单帧模板可能误匹配到别的精灵：大幅度跳变需要连续两帧一致才接受。
        if distance > 0.25:
            if score < 0.9:
                return
            candidate = getattr(self, "_player_candidate", None)
            if candidate is None or math.hypot(x - candidate[0], y - candidate[1]) > 0.08:
                self._player_candidate = (x, y)
                return
        self._player_candidate = None
        # 轻量平滑，避免锚点抖动导致闪避/交战判定抖。
        x = previous_x * 0.35 + x * 0.65
        y = previous_y * 0.35 + y * 0.65
        self._anchor = (min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    def latest_frame(self) -> np.ndarray | None:
        """最近一帧原始 BGR（给异步 OCR/场景线程读取；不要修改它）。"""
        return self._latest_frame

    def _maybe_recover(self) -> None:
        """非 gameplay 场景的恢复脚本：按 profile.scenes[scene].recover 逐个按键。"""
        scene = self._scene
        if scene != self._recover_scene:
            self._recover_scene = scene
            self._recover_attempts = 0
            self._last_recover_at = 0.0
        config = self._scenes.get(scene) if isinstance(self._scenes, dict) else None
        if not isinstance(config, dict):
            return
        steps = config.get("recover")
        if not isinstance(steps, (list, tuple)) or not steps:
            return
        max_attempts = int(_as_float(config.get("max_attempts"), self._recover_max_attempts) or self._recover_max_attempts)
        now = self._clock()
        if (now - self._last_recover_at) * 1000.0 < self._recover_interval_ms:
            return
        step = steps[min(self._recover_attempts, len(steps) - 1)]
        press = step.get("press") if isinstance(step, dict) else step
        key = self._resolve_key(str(press)) if press is not None else None
        if key:
            try:
                self._tap(key, 140.0)
            except Exception as error:  # noqa: BLE001 - 非法恢复键不能炸掉整条闭环
                self._stop_reason = f"recovery: {type(error).__name__}: {error}"
                self._stop_event.set()
                return
        self._recover_attempts += 1
        self._last_recover_at = now
        if self._recover_attempts > max_attempts:
            self._stop_reason = f"scene unrecoverable: {scene}"
            self._stop_event.set()

    def _read_scene(self) -> None:
        if self._scene_source is None:
            return
        try:
            scene = self._scene_source()
        except Exception:  # noqa: BLE001 - 场景只是附加信息
            return
        if isinstance(scene, str) and scene:
            self._scene = scene
