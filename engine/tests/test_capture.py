"""DXcam 输出匹配：把 Win32 显示器映射到抓屏输出序号。"""

from dsh_game_core.capture import MonitorInfo, match_output_index


def test_unique_resolution_match_wins():
    outputs = [MonitorInfo(index=0, width=1920, height=1080, primary=True), MonitorInfo(index=1, width=2560, height=1440)]
    assert match_output_index({"width": 2560, "height": 1440, "primary": False}, outputs) == 1


def test_primary_flag_disambiguates_same_resolution():
    outputs = [MonitorInfo(index=0, width=1920, height=1080, primary=True), MonitorInfo(index=1, width=1920, height=1080)]
    assert match_output_index({"width": 1920, "height": 1080, "primary": True}, outputs) == 0
    assert match_output_index({"width": 1920, "height": 1080, "primary": False}, outputs) == 1


def test_no_resolution_match_returns_none():
    outputs = [MonitorInfo(index=0, width=1920, height=1080, primary=True)]
    assert match_output_index({"width": 3840, "height": 2160}, outputs) is None


def test_ambiguous_same_size_falls_back_deterministically():
    outputs = [MonitorInfo(index=2, width=1920, height=1080), MonitorInfo(index=1, width=1920, height=1080)]
    assert match_output_index({"width": 1920, "height": 1080, "primary": False}, outputs) == 1
