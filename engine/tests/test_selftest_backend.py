"""引擎 selftest 的后端就绪度 / 前台窗口 / 依赖字段。

全部用假实现：假的 vgamepad 模块、假的 OCR 与显示器枚举、假的控制器；
测试不依赖真实设备，也绝不按任何键。
"""

import io
import json
import sys
import types

import pytest

import dsh_game_core.__main__ as main_module
from dsh_game_core import control
from dsh_game_core import windows as windows_module


def _fake_vgamepad(monkeypatch, version="9.9.9"):
    module = types.ModuleType("vgamepad")
    module.__version__ = version
    module.VX360Gamepad = object
    monkeypatch.setitem(sys.modules, "vgamepad", module)
    return module


@pytest.fixture
def selftest_env(monkeypatch):
    """把可能很重或依赖本机硬件的自检项换成空实现（OCR 模型、DXcam 枚举）。"""
    capture_module = types.ModuleType("dsh_game_core.capture")
    capture_module.list_monitors = lambda: []
    monkeypatch.setitem(sys.modules, "dsh_game_core.capture", capture_module)

    ocr_module = types.ModuleType("dsh_game_core.ocr")

    class _FakeOcr:
        def warmup(self) -> float:
            return 0.0

    ocr_module.Ocr = _FakeOcr
    monkeypatch.setitem(sys.modules, "dsh_game_core.ocr", ocr_module)
    monkeypatch.delenv("DSH_GAME_BRIDGE_CONTROL", raising=False)


FOREGROUND = {
    "hwnd": 1234,
    "title": "Fake Game",
    "process": "fake.exe",
    "left": 0,
    "top": 0,
    "width": 800,
    "height": 600,
}


def test_selftest_reports_backend_foreground_and_deps(selftest_env, monkeypatch):
    monkeypatch.setattr(windows_module, "foreground_window", lambda: dict(FOREGROUND))
    monkeypatch.setattr(control, "xinput_connected_slots", lambda: [0, 2])

    report = main_module.selftest()

    assert report["backend"] == {
        "name": "dry-run",
        "ready": True,
        "detail": "records actions only",
        "xinput_slot": None,
        "warnings": [],
    }
    assert report["foreground"] == FOREGROUND
    assert report["xinput_slots_connected"] == [0, 2]
    assert "vgamepad" in report["deps"]
    assert isinstance(report["deps"]["vgamepad"], str)
    assert report["capture_ok"] is None  # capture=False 不抓帧


def test_selftest_foreground_is_none_when_helper_missing(selftest_env, monkeypatch):
    monkeypatch.delattr(windows_module, "foreground_window", raising=False)
    report = main_module.selftest()
    assert "foreground" in report
    assert report["foreground"] is None


def test_selftest_gamepad_alias_maps_to_vgamepad_without_probe(selftest_env, monkeypatch):
    monkeypatch.setenv("DSH_GAME_BRIDGE_CONTROL", "gamepad")
    _fake_vgamepad(monkeypatch)

    def explode(*_args, **_kwargs):
        raise AssertionError("probe_devices=False 时不应该创建虚拟手柄")

    monkeypatch.setattr(control, "VGamepadController", explode)

    report = main_module.selftest()

    backend = report["backend"]
    assert backend["name"] == "vgamepad"
    assert backend["ready"] is True
    assert backend["xinput_slot"] is None
    assert backend["warnings"] == []
    assert "not probed" in backend["detail"]
    assert report["deps"]["vgamepad"] == "9.9.9"


def test_selftest_probe_creates_and_closes_pad_without_pressing(selftest_env, monkeypatch):
    monkeypatch.setenv("DSH_GAME_BRIDGE_CONTROL", "vgamepad")
    _fake_vgamepad(monkeypatch)
    events: list[str] = []

    class StubController:
        def __init__(self):
            events.append("created")

        def backend_info(self):
            return {
                "backend": "vgamepad",
                "ready": True,
                "detail": "virtual pad created; XInput slot 0",
                "xinput_slot": 0,
                "warnings": ["example warning"],
            }

        def close(self):
            events.append("closed")

    monkeypatch.setattr(control, "VGamepadController", StubController)

    report = main_module.selftest(probe_devices=True)

    assert events == ["created", "closed"]
    backend = report["backend"]
    assert backend["name"] == "vgamepad"
    assert backend["ready"] is True
    assert backend["xinput_slot"] == 0
    assert backend["warnings"] == ["example warning"]
    assert "slot 0" in backend["detail"]


def test_selftest_probe_failure_degrades_instead_of_raising(selftest_env, monkeypatch):
    monkeypatch.setenv("DSH_GAME_BRIDGE_CONTROL", "vgamepad")
    _fake_vgamepad(monkeypatch)

    class BrokenController:
        def __init__(self):
            raise RuntimeError("ViGEmBus driver not installed")

    monkeypatch.setattr(control, "VGamepadController", BrokenController)

    report = main_module.selftest(probe_devices=True)

    backend = report["backend"]
    assert backend["name"] == "vgamepad"
    assert backend["ready"] is False
    assert "pad probe failed" in backend["detail"]
    assert backend["xinput_slot"] is None
    assert report["capture_ok"] is None


def test_selftest_vgamepad_import_failure_reported(selftest_env, monkeypatch):
    monkeypatch.setenv("DSH_GAME_BRIDGE_CONTROL", "vgamepad")
    monkeypatch.setitem(sys.modules, "vgamepad", None)

    report = main_module.selftest(probe_devices=True)

    backend = report["backend"]
    assert backend["name"] == "vgamepad"
    assert backend["ready"] is False
    assert "vgamepad unavailable" in backend["detail"]
    assert backend["xinput_slot"] is None


def test_cli_selftest_probe_devices_flag(selftest_env, monkeypatch, capsys):
    calls: dict = {}

    def fake_selftest(capture=False, probe_devices=False):
        calls.update(capture=capture, probe_devices=probe_devices)
        return {"engine": "fake"}

    monkeypatch.setattr(main_module, "selftest", fake_selftest)

    assert main_module.main(["selftest", "--probe-devices"]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "fake"
    assert calls == {"capture": False, "probe_devices": True}


def test_serve_selftest_passes_probe_devices(selftest_env, monkeypatch):
    calls: dict = {}

    def fake_selftest(capture=False, probe_devices=False):
        calls.update(capture=capture, probe_devices=probe_devices)
        return {"backend": {"name": "vgamepad"}}

    monkeypatch.setattr(main_module, "selftest", fake_selftest)

    class FakeSession:
        def close(self):
            pass

    fake_session_module = types.ModuleType("dsh_game_core.session")
    fake_session_module.GameSession = FakeSession
    monkeypatch.setitem(sys.modules, "dsh_game_core.session", fake_session_module)

    request = {"id": 7, "method": "selftest", "params": {"probe_devices": True}}
    stdout = io.StringIO()
    assert main_module.serve(stdin=io.StringIO(json.dumps(request) + "\n"), stdout=stdout) == 0

    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == 7
    assert response["ok"] is True
    assert calls == {"capture": False, "probe_devices": True}
