# PlayerTracker 实机验证报告（2026-11-09）

## 结论

**玩家自识别修复成功**：

- 关闭 tracker（原颜色追踪）：20 局 `mean_player_stale_ratio=0.366`，多局整局失明；
- 开启 tracker：两批各 20 局，stale **0.036 / 0.035**，最大单局 **0.059 / 0.069**，**没有 stale>0.9 的局**；
- 第一局首帧 `player_age_ms=9ms`，初始捕获及时；
- tracker 模板数/状态可通过 `status.player_tracker` 观察。

性能上：

| 臂 | n | median peak | stale |
|:--|--:|--:|--:|
| tracker off | 20 | 1.526 | 0.366 |
| tracker on #1 | 20 | 2.472 | 0.036 |
| tracker on #2 | 20 | 2.408 | 0.035 |

对比 off vs on #1：**promote**，median **+0.946**，CI low **0.043**。  
对比 off vs on #2：median **+0.882**，但 CI low **-0.221** → **no_gain**。  
因此：**追踪改善确定，推进提升不稳定**；不能宣称 tracker 已让 Cuphead 明显变强。

## 实现

- `engine/dsh_game_core/player_tracker.py`：
  - 自动模板 bootstrap；
  - 速度预测 + ROI 多尺度模板匹配；
  - 颜色/几何/距离融合；
  - 丢失 2–3 拍放宽、≥5 拍全屏重捕获；
  - 模板最多 6 个，运行时裁剪，不入库。
- `profiles/cuphead.json`：`player.track=true`、`tracker="template"`、`every_n_ticks=4`。
- `status.player_tracker` 暴露 last/velocity/missing/stale/templates/source/score/age。

## 产物

- 本地 runs/traces：`tmp/experiments/ptracker-1/2`、`ptracker-off-1`；
- 入库自动报告：`experiments/results/ptracker-1.md`、`ptracker-2.md`、`ptracker-off-1.md`；
- 本报告。

## 结论边界

- 两批 tracker on 都是 20 局、无通关；
- 表现中位数约 2.4，仍低于历史最佳 4.19 / 单局 11.15，说明追踪只是必要条件，不是充分条件；
- off 批次的 death_causes 是 LevelMemory 累计值，计数明显偏大，不应作为死因分布结论；
- 下一步应在 tracker 稳定基础上重做策略 A/B（保留周期跳底噪 + 高置信 reactive 叠加），而不是继续调 tracker。
