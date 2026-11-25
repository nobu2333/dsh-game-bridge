# 低步数点击闭环实机验证：Mini Minesweeper（2026-11-25）

## 结论

**相对坐标点击 + 压缩截图 + OCR 归一化坐标 + `attach_actions` 实机闭环通过。**

在本地 4×4 扫雷（`tmp/click-puzzle/index.html`，3 雷，13 安全格）上，通过真实 `SendInput` 鼠标点击与 `PrintWindow` 窗口抓屏（`max_width=640`）：

- 10/10 步均由 RapidOCR 读取未翻开格子标签的归一化中心 `(cx, cy)`，经 `game_act {rx, ry}` 换算成屏幕像素点击；
- `MOVES` 从 `0` 推进到 `10`，`SAFE LEFT` 从 `13` 降到 `0`，第 10 步后进入 `YOU WIN`；
- `status.attach_actions == 10`，`stop.attach_actions == 10`，重新 `attach` 后 `attach_actions` 归零（`0`），`actions_total` 保留累计值 `10`。

## 验证参数与边界

- 窗口：`Mini Minesweeper`（Chrome app，786×753）
- 引擎抓屏：`capture_mode="window"`，`max_width=640`（返回 `640×608`）
- 控制后端：`keyboard`（真实 `SendInput` 鼠标左键）
- 测试脚本：`tmp/run_minesweeper_smoke.py`（仅本地验证使用，不入库；脚本用已知安全格列表按 OCR 坐标逐格点开，用于验证“看 OCR 坐标 → 相对坐标点中目标格”的操控精度，不代表自主推理通关）
- **`auto_focus` 实机边界**：本次附着时 `auto_focus=true`，但 Chrome 启动后本身已处于前台（`FG_BEFORE_STEP1: Mini Minesweeper`），因此实机尚未测到“从其他前台窗口抢回”的分支（该分支已由 [test_session_foreground.py](../../engine/tests/test_session_foreground.py) 与 [test_click_pipeline.py](../../engine/tests/test_click_pipeline.py) 覆盖）。

## 实测观察到的工程细节

1. `max_width=640` 足够让 4×4 格子与 HUD 数字被 RapidOCR 稳定识别，同时显著减小了图像尺寸；
2. 4×4 棋盘（16 格）+ 顶部 HUD 一帧约 22–26 条 OCR 行，默认 `ocr_limit=16` 会截断底部几格，因此点击多格界面时建议显式传 `ocr_limit=32`（`game_snapshot` 已支持 `1..40`）。
3. 本次验证通过引擎 `GameSession` 直接执行，尚未经真实 DSH 模型多轮对话驱动扫雷；模型端到端对局仍是下一步。
