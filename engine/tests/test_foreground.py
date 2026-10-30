"""前台窗口与遮挡判定的单测。

遮挡计算全部用注入的窗口矩形验证，不依赖真实桌面；真实前台的冒烟测试在
没有可见窗口的环境（如 CI）自动跳过。这里只读枚举，不注入、不抢焦点。
"""

import pytest

from dsh_game_core import windows as win


# 目标矩形：400 x 300 = 120000 面积，便于心算比例。
TARGET = (100, 100, 500, 400)


def window(hwnd, left, top, width, height, title="覆盖窗口"):
    return {"hwnd": hwnd, "title": title, "left": left, "top": top, "width": width, "height": height}


# ── 纯函数：交集与单窗口比例 ────────────────────────────────────────────


def test_intersection_area_handles_overlap_cases():
    assert win.rect_intersection_area((0, 0, 10, 10), (0, 0, 10, 10)) == 100  # 完全重合
    assert win.rect_intersection_area((0, 0, 10, 10), (20, 20, 30, 30)) == 0  # 不相交
    assert win.rect_intersection_area((0, 0, 10, 10), (5, 5, 15, 15)) == 25  # 斜角部分相交
    assert win.rect_intersection_area((0, 0, 100, 100), (20, 20, 30, 30)) == 100  # 包含
    assert win.rect_intersection_area((0, 0, 10, 10), (10, 10, 20, 20)) == 0  # 仅贴边不算
    # 非法矩形不抛异常，直接当没交集。
    assert win.rect_intersection_area((10, 10, 0, 0), (0, 0, 10, 10)) == 0
    assert win.rect_intersection_area("not-a-rect", (0, 0, 10, 10)) == 0


def test_intersection_area_accepts_window_dicts():
    assert win.rect_intersection_area(TARGET, window(1, 300, 200, 200, 200)) == 200 * 200
    assert win.rect_intersection_area(TARGET, {"left": 0, "top": 0, "width": 0, "height": 0}) == 0


def test_covered_ratio_clamps_when_window_is_larger_than_target():
    assert win.covered_ratio(TARGET, (300, 200, 700, 600)) == pytest.approx(1 / 3)  # 200x200
    assert win.covered_ratio(TARGET, (-1000, -1000, 2000, 2000)) == 1.0  # 窗口比目标大 -> 封顶
    assert win.covered_ratio(TARGET, (0, 0, 50, 50)) == 0.0  # 无交集
    assert win.covered_ratio(TARGET, (100, 100, 500, 400)) == 1.0  # 完全覆盖
    assert win.covered_ratio(None, (0, 0, 10, 10)) == 0.0  # 目标无效 -> 0
    assert win.covered_ratio((0, 0, 0, 0), (0, 0, 10, 10)) == 0.0


# ── 纯函数：整体遮挡（occlusion_from_windows）────────────────────────────


def test_target_below_covering_windows_is_occluded():
    covering = window(11, 100, 100, 400, 300)  # 与目标完全重合
    result = win.occlusion_from_windows(TARGET, [covering])
    assert result["available"] is True
    assert result["occluded"] is True
    assert result["occluded_ratio"] == 1.0
    assert result["covered_by"] == [{"hwnd": 11, "title": "覆盖窗口", "ratio": 1.0}]


def test_partial_cover_is_not_occluded_and_reports_ratio():
    # 覆盖 200x200，占 120000 的 1/3。
    result = win.occlusion_from_windows(TARGET, [window(7, 300, 200, 200, 200)])
    assert result["available"] is True
    assert result["occluded_ratio"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["occluded"] is False
    assert result["covered_by"] == [{"hwnd": 7, "title": "覆盖窗口", "ratio": pytest.approx(1 / 3, abs=1e-4)}]


def test_covered_by_keeps_top_three_by_ratio():
    # 从上到下 5 个窗口，分别盖住目标的 0.5 / 0.4 / 0.3 / 0.2 / 0.1。
    heights = {1: 150, 2: 120, 3: 90, 4: 60, 5: 30}
    covering = [window(hwnd, 100, 100, 400, height) for hwnd, height in heights.items()]
    result = win.occlusion_from_windows(TARGET, covering)
    assert result["available"] is True
    assert [item["hwnd"] for item in result["covered_by"]] == [1, 2, 3]
    assert [item["ratio"] for item in result["covered_by"]] == [0.5, 0.4, 0.3]
    # 总和 = 1.5，截断到 1.0；任一个窗口都只算一次。
    assert result["occluded_ratio"] == 1.0
    assert result["occluded"] is True


def test_overlapping_ratios_sum_then_clamp_to_one():
    # 三个窗口各 0.8，直接相加 2.4 -> 必须封顶 1.0。
    covering = [window(hwnd, 100, 100, 400, 240) for hwnd in (21, 22, 23)]
    result = win.occlusion_from_windows(TARGET, covering)
    assert result["occluded_ratio"] == 1.0
    assert result["occluded"] is True
    assert all(item["ratio"] == 0.8 for item in result["covered_by"])


def test_zero_ratio_windows_are_ignored():
    covering = [window(1, 0, 0, 10, 10), window(2, 900, 900, 50, 50)]
    result = win.occlusion_from_windows(TARGET, covering)
    assert result == {"available": True, "occluded_ratio": 0.0, "occluded": False, "covered_by": []}
    # 空列表同样安全。
    assert win.occlusion_from_windows(TARGET, [])["occluded"] is False


def test_equal_ratios_sort_by_hwnd_for_stable_output():
    covering = [window(9, 100, 100, 400, 150), window(3, 100, 100, 400, 150)]
    result = win.occlusion_from_windows(TARGET, covering)
    assert [item["hwnd"] for item in result["covered_by"]] == [3, 9]


def test_malformed_window_entries_are_skipped():
    covering = [
        "not-a-window",
        {"hwnd": 4, "title": "缺矩形"},
        window(5, 100, 100, 0, 300),  # 零宽
        window(6, 100, 100, 400, 300, title=None),  # 标题缺失也要能算
    ]
    result = win.occlusion_from_windows(TARGET, covering)
    assert result["available"] is True
    assert [item["hwnd"] for item in result["covered_by"]] == [6]
    assert result["covered_by"][0]["title"] == ""


def test_occlusion_degrades_without_raising_on_bad_input():
    unavailable = {"available": False, "occluded_ratio": 0.0, "occluded": False, "covered_by": []}
    assert win.occlusion_from_windows(None, []) == unavailable
    assert win.occlusion_from_windows((10, 10, 10, 10), []) == unavailable  # 零面积目标
    assert win.occlusion_from_windows(TARGET, None) == unavailable
    assert win.occlusion_from_windows(TARGET, 42) == unavailable
    assert win.occlusion_from_windows("bad-target", [window(1, 0, 0, 10, 10)]) == unavailable


# ── 只读探针：降级路径 ──────────────────────────────────────────────────


def test_foreground_window_returns_none_off_windows(monkeypatch):
    monkeypatch.setattr(win, "IS_WINDOWS", False)
    assert win.foreground_window() is None


def test_window_occlusion_returns_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(win, "IS_WINDOWS", False)
    assert win.window_occlusion(1234) == {
        "available": False,
        "occluded_ratio": 0.0,
        "occluded": False,
        "covered_by": [],
    }


class _FakeFunc:
    """可调用、可赋 restype 的假 ctypes 函数，模拟 GetForegroundWindow。"""

    def __init__(self, value=None, error=None):
        self._value = value
        self._error = error
        self.restype = None

    def __call__(self):
        if self._error is not None:
            raise self._error
        return self._value


class _FakeForegroundUser32:
    def __init__(self, value=None, error=None):
        self.GetForegroundWindow = _FakeFunc(value, error)


def test_foreground_window_assembles_contract_shape(monkeypatch):
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "_user32", lambda: _FakeForegroundUser32(0x1234))
    monkeypatch.setattr(win, "window_rect", lambda hwnd: (10, 20, 110, 70))
    monkeypatch.setattr(win, "_window_title", lambda hwnd: "Game")
    monkeypatch.setattr(win, "_process_name", lambda hwnd: "game.exe")
    assert win.foreground_window() == {
        "hwnd": 0x1234,
        "title": "Game",
        "process": "game.exe",
        "left": 10,
        "top": 20,
        "width": 100,
        "height": 50,
    }


def test_foreground_window_degrades_on_api_errors(monkeypatch):
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "_user32", lambda: _FakeForegroundUser32(None))
    assert win.foreground_window() is None  # 没有前台窗口
    monkeypatch.setattr(win, "_user32", lambda: _FakeForegroundUser32(error=RuntimeError("boom")))
    assert win.foreground_window() is None  # API 抛错
    monkeypatch.setattr(win, "_user32", lambda: _FakeForegroundUser32(0x1234))
    monkeypatch.setattr(win, "window_rect", lambda hwnd: None)
    assert win.foreground_window() is None  # 窗口矩形取不到


def test_window_occlusion_degrades_when_rect_or_enumeration_fails(monkeypatch):
    unavailable = {"available": False, "occluded_ratio": 0.0, "occluded": False, "covered_by": []}
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "window_rect", lambda hwnd: None)
    assert win.window_occlusion(1) == unavailable
    monkeypatch.setattr(win, "window_rect", lambda hwnd: TARGET)
    monkeypatch.setattr(win, "_windows_above", lambda hwnd: None)  # 目标不在枚举里
    assert win.window_occlusion(1) == unavailable
    monkeypatch.setattr(win, "_windows_above", lambda hwnd: 1 / 0)  # 意外异常
    assert win.window_occlusion(1) == unavailable


def test_window_occlusion_assembles_from_enumerated_windows(monkeypatch):
    monkeypatch.setattr(win, "IS_WINDOWS", True)
    monkeypatch.setattr(win, "window_rect", lambda hwnd: TARGET)
    monkeypatch.setattr(win, "_windows_above", lambda hwnd: [window(8, 100, 100, 400, 300)])
    result = win.window_occlusion(42)
    assert result["available"] is True
    assert result["occluded"] is True
    assert result["covered_by"][0]["hwnd"] == 8


# ── 真实桌面冒烟（只读；无窗口环境自动跳过）─────────────────────────────


def test_live_foreground_and_occlusion_smoke():
    foreground = win.foreground_window()
    if foreground is None:
        pytest.skip("no foreground window available")
    assert set(foreground) == {"hwnd", "title", "process", "left", "top", "width", "height"}
    assert isinstance(foreground["hwnd"], int) and foreground["hwnd"] > 0
    assert isinstance(foreground["title"], str)
    assert foreground["process"] is None or isinstance(foreground["process"], str)
    assert foreground["width"] > 0 and foreground["height"] > 0

    occlusion = win.window_occlusion(foreground["hwnd"])
    assert set(occlusion) == {"available", "occluded_ratio", "occluded", "covered_by"}
    assert isinstance(occlusion["available"], bool)
    assert 0.0 <= occlusion["occluded_ratio"] <= 1.0
    assert isinstance(occlusion["occluded"], bool)
    assert occlusion["occluded"] == (occlusion["occluded_ratio"] >= 0.5)
    assert len(occlusion["covered_by"]) <= 3
    for item in occlusion["covered_by"]:
        assert set(item) == {"hwnd", "title", "ratio"}
        assert item["ratio"] > 0.0


def test_live_occlusion_on_a_visible_window():
    candidates = win.list_windows(min_width=200, min_height=150)
    if not candidates:
        pytest.skip("no visible desktop window to inspect")
    result = win.window_occlusion(candidates[0]["hwnd"])
    assert set(result) == {"available", "occluded_ratio", "occluded", "covered_by"}
    assert 0.0 <= result["occluded_ratio"] <= 1.0
