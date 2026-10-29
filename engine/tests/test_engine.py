import base64
import io
import json

import numpy as np

from dsh_game_core.__main__ import serve
from dsh_game_core.engine import GameEngine
from dsh_game_core.ocr import Ocr, TextLine


class FakeCapturer:
    def __init__(self, height=400, width=800):
        self.height = height
        self.width = width
        self.closed = False

    def grab(self):
        # 确定性渐变帧：不依赖随机数，失败可复现。
        rows = np.linspace(0, 255, self.height, dtype=np.uint8)[:, None]
        return np.repeat(np.repeat(rows[:, :, None], self.width, axis=1), 3, axis=2)

    def close(self):
        self.closed = True


class FakeOcr:
    def read(self, _img):
        return [TextLine(text="HP 100", score=0.99, left=1, top=2, right=3, bottom=4)]


def test_snapshot_encodes_png_and_downscales():
    engine = GameEngine(capturer=FakeCapturer(), ocr=FakeOcr(), max_width=400)
    result = engine.snapshot()

    assert result["width"] == 400
    assert result["scale"] == 0.5
    assert base64.b64decode(result["png_b64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["ocr"][0]["text"] == "HP 100"
    assert result["captured_at_ms"] > 0


def test_snapshot_can_skip_ocr():
    engine = GameEngine(capturer=FakeCapturer(), ocr=FakeOcr(), max_width=800)
    result = engine.snapshot(ocr=False)
    assert result["ocr"] == []
    assert result["width"] == 800


def test_ocr_reads_text_drawn_with_opencv():
    """真实 OCR 冒烟：不依赖屏幕，只验证模型能读出渲染出来的字。"""
    import cv2

    img = np.full((120, 480, 3), 20, dtype=np.uint8)
    cv2.putText(img, "HP 100/100", (16, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (240, 240, 240), 3, cv2.LINE_AA)
    lines = Ocr().read(img)
    assert lines, "OCR 没读出任何文字"
    joined = " ".join(line.text for line in lines)
    assert "100" in joined or "HP" in joined.upper()


def test_stdio_protocol_answers_and_contains_errors():
    stdin = io.StringIO(
        '{"id": 1, "method": "ping"}\n'
        '{"id": 2, "method": "does_not_exist"}\n'
        'not json at all\n'
    )
    stdout = io.StringIO()
    assert serve(stdin, stdout) == 0

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses[0]["ok"] is True
    assert responses[1]["ok"] is False and responses[1]["error"]["code"] == "UNKNOWN_METHOD"
    assert responses[2]["ok"] is False and responses[2]["error"]["code"] == "INTERNAL"
