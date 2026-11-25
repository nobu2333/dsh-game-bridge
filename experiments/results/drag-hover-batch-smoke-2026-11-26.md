# 桌面交互原语实机验证：`hover` / `drag` / `game_act_batch`（2026-11-26）

## 结论

**`hover`、`drag` 与有界批量动作 `act_batch` 实机闭环通过。**

在本地交互测试页（`tmp/click-puzzle/drag-hover.html`）上，通过真实 `SendInput` + `PrintWindow`（`max_width=640`）：

- `hover`：按 OCR 归一化中心 `(rx=0.5023, ry=0.8506)` 移动指针到 `CARD ONE` 上方，不触发点击（`STATUS: IDLE`）；
- `act_batch`：单次调用按顺序执行 2 步：
  1. `drag` 从 `CARD ONE` 拖拽到 `DROP TARGET`（220ms 平滑插值，尾随 `wait_ms=150`）；
  2. `click` 点击 `END TURN`；
- 执行后 `game_snapshot` OCR 验证界面变化：
  - `STATUS:IDLE` → **`STATUS:PLAYED`**
  - `DROP TARGET` → **`DROPPED OK`**
  - `TURN: OPEN` → **`TURN:ENDED`**
- 步数账本：`executed=2/2`，`attach_actions=3`（1 次 hover + 2 步 batch），`actions_total=3`。

## 备注

- 测试页面、浏览器实例与本地静态服务器已在验证后关闭；
- 单测同时覆盖了批量中途命中 F12 夺回时立即中断后续步骤（`SAFETY_BLOCKED`）；
- 本验证使用直接的 `GameSession` 脚本，未接任何外部商业游戏本体。
