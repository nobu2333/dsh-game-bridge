"""窗口解析与「attach 之后只截目标窗口」的单测。

窗口列表与矩形都通过注入提供，测试不依赖真实桌面；真实窗口验证另行手跑
（只读抓屏，见 docs/RELEASE.md 的发布前自检）。
"""

from dsh_game_core.engine import EngineError
from dsh_game_core.safety import SafetyGate
from dsh_game_core.session import GameSession
from dsh_game_core.windows import find_window


class RecordingEngine:
    def __init__(self):
        self.calls = []

    def snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return {"png_b64": "", "width": 10, "height": 10, "ocr": [], "captured_at_ms": 0}

    def close(self):
        pass


def allowed_gate():
    return SafetyGate(process_source=lambda: [], takeover_source=lambda: False, process_ttl_s=0)


WINDOWS = [
    {"hwnd": 1, "title": "Knock", "process": "Knock.exe", "left": 308, "top": 138, "width": 1100, "height": 903},
    {"hwnd": 2, "title": "Knock - Launcher", "process": "launcher.exe", "left": 0, "top": 0, "width": 400, "height": 300},
    {"hwnd": 3, "title": "Steam", "process": "steam.exe", "left": 0, "top": 0, "width": 1200, "height": 900},
]


def test_find_window_prefers_exact_then_prefix_then_largest():
    assert find_window(WINDOWS, "knock")["hwnd"] == 1  # 精确标题优先
    assert find_window(WINDOWS, "steam")["hwnd"] == 3
    assert find_window(WINDOWS, "KNO")["hwnd"] == 1  # 子串 + 最大窗口
    assert find_window(WINDOWS, "nothing-here") is None
    assert find_window(WINDOWS, "") is None


def make_session(engine, *, window_rect=(308, 138, 1408, 1041), monitor=None):
    return GameSession(
        engine=engine,
        gate=allowed_gate(),
        control_backend="dry-run",
        window_resolver=lambda match: find_window(WINDOWS, match),
        window_rect_source=lambda hwnd: window_rect,
        window_monitor_source=lambda hwnd: monitor or {"left": 0, "top": 0, "width": 1920, "height": 1200, "primary": True},
    )


def test_attach_resolves_window_and_snapshot_crops_to_it():
    engine = RecordingEngine()
    session = make_session(engine)
    result = session.attach({"window": "Knock"})
    assert result["attached"]["hwnd"] == 1
    assert result["attached"]["window"] == "Knock"

    session.snapshot(ocr=False)
    assert engine.calls[-1]["region"] == {"left": 308, "top": 138, "width": 1100, "height": 903}


def test_attach_without_match_fails_with_window_list():
    session = make_session(RecordingEngine())
    try:
        session.attach({"window": "definitely-not-a-window"})
    except EngineError as error:
        assert error.code == "WINDOW_NOT_FOUND"
        # 报错必须给人话提示：说明找不到，并列出当前可见窗口（帮助用户改关键词）。
        assert "definitely-not-a-window" in error.message
        assert "可见窗口" in error.message
    else:  # pragma: no cover
        raise AssertionError("expected WINDOW_NOT_FOUND")


def test_snapshot_uses_monitor_relative_region_on_secondary_display():
    """窗口在副屏时，裁剪区必须减掉显示器原点，并带上 monitor 让引擎选对应输出。"""
    engine = RecordingEngine()
    monitor = {"left": 1920, "top": 0, "width": 1920, "height": 1200, "primary": False}
    session = make_session(engine, window_rect=(2000, 100, 3000, 900), monitor=monitor)
    session.attach({"window": "Knock"})
    session.snapshot(ocr=False)

    call = engine.calls[-1]
    assert call["monitor"] == monitor
    assert call["region"] == {"left": 80, "top": 100, "width": 1000, "height": 800}


def test_attach_unspecified_falls_back_to_full_screen():
    engine = RecordingEngine()
    session = make_session(engine)
    session.attach({"window": "unspecified"})
    assert session.attached["window"] == "unspecified"
    session.snapshot(ocr=False)
    assert engine.calls[-1]["region"] is None


def test_live_window_capture_when_a_desktop_window_exists():
    """真实窗口抓屏冒烟（只读、不注入）。无桌面窗口的环境（如 CI）自动跳过。"""
    import pytest

    from dsh_game_core.engine import GameEngine
    from dsh_game_core.windows import list_windows

    windows = list_windows()
    target = next((w for w in windows if w["width"] >= 400 and w["height"] >= 300), None)
    if target is None:
        pytest.skip("no visible desktop window to capture")

    session = GameSession(
        engine=GameEngine(),
        gate=allowed_gate(),
        control_backend="dry-run",
    )
    session.attach({"window": target["title"]})
    frame = session.snapshot(ocr=False)
    session.close()

    region = frame.get("region")
    assert region, "attached to a window but the frame was not cropped"
    assert frame["width"] <= target["width"]
    assert frame["height"] <= target["height"]
