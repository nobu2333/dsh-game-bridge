"""RapidOCR（ONNXRuntime，CPU）薄封装。

为什么是 RapidOCR：输出就是 onnxruntime，不需要 paddlepaddle 那套重资产；
HUD 文字（血量/任务/菜单）是游戏里最便宜、最准的语义来源。

⚠️ 实测调优（来自 宿项目 2026-10-13 的踩坑，改动会击穿延迟预算）：
默认 `det_limit_type='min'` 会把 640×80 这类小区域强制放大到短边 736px，
检测耗时 ~1.3s；改成 `max`（长边 ≤960）后 det ~9ms、整条 ~40ms。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class TextLine:
    text: str
    score: float
    left: int
    top: int
    right: int
    bottom: int

    def to_dict(self) -> dict:
        return asdict(self)


class Ocr:
    """懒初始化：引擎加载有秒级延迟，第一次推理前先热一把。"""

    def __init__(self, min_score: float = 0.5):
        self._engine = None
        self._min_score = min_score

    def _ensure_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR(
                det_limit_type="max",
                det_limit_side_len=960,
                det_model_path="",
                use_angle_cls=False,
            )
            self._engine(np.zeros((32, 128, 3), dtype=np.uint8))

    def warmup(self) -> float:
        """预热并返回引擎初始化耗时（毫秒）。"""
        import time

        started = time.perf_counter()
        self._ensure_engine()
        return (time.perf_counter() - started) * 1000.0

    def read(self, img: np.ndarray) -> list[TextLine]:
        self._ensure_engine()
        result, _elapse = self._engine(img)
        if not result:
            return []
        lines: list[TextLine] = []
        for item in result:
            box, text, score = item[0], item[1], float(item[2])
            if score < self._min_score or not str(text).strip():
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            lines.append(
                TextLine(
                    text=str(text).strip(),
                    score=round(score, 4),
                    left=int(min(xs)),
                    top=int(min(ys)),
                    right=int(max(xs)),
                    bottom=int(max(ys)),
                )
            )
        return lines
