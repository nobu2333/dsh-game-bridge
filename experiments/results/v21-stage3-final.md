# v2.1 三臂最终复盘（2026-11-06）

## 结论

- **感知修复有效**：`player_stale_ratio` 从 baseline 0.256 降到 reactive 0.192 / hybrid 0.190；`threat_active_ratio` 始终约 0.99；完整 traces 可复盘。
- **但没有策略臂超过 baseline**：baseline median 2.55；reactive 1.94；hybrid 2.11；均 no_gain。
- **p10 略有改善**：reactive 1.48、hybrid 1.72 vs baseline 1.49，说明 reactive 减少了一些“开局即死”，却牺牲了平均值。
- **周期盲跳仍是强基线**：完全关闭它导致 cornered 死亡增加；hybrid 只部分恢复，仍不足。

## 三臂数据（各 10 局，75s 上限）

| 臂 | mean | median | p10 | max | stale | threat | damage |
|:--|--:|--:|--:|--:|--:|--:|--:|
| baseline | 2.29 | **2.55** | 1.49 | 3.23 | 0.256 | 0.993 | 6.5 |
| reactive | 1.97 | 1.94 | 1.48 | 3.33 | 0.192 | 0.988 | 6.8 |
| hybrid | 2.34 | 2.11 | **1.72** | 3.81 | 0.190 | 0.993 | 8.5 |

对比（baseline vs candidate，median peak）：

- reactive：-0.61，95% CI [-1.065, 0.048] → no_gain
- hybrid：-0.44，95% CI [-0.900, 0.339] → no_gain

## 为什么仍失败（来自 traces）

1. 部分局开局玩家仍未被捕获（`player_age_ms=None`, stale=1.0），reactive 缺少可靠相对威胁；
2. reactive 关闭周期跳后，地面停留更久，cornered 死亡增加；
3. `stop_shoot` 在近距离威胁时仍可能压过跳跃；
4. hybrid 的“无威胁时保底跳”触发频率不足以维持 baseline 的节奏。

## 产物

- 入库报告：
  - `experiments/results/v21-baseline-1.md`
  - `experiments/results/v21-reactive-3.md`
  - `experiments/results/v21-reactive3-vs-baseline.md`
  - `experiments/results/v21-hybrid-1.md`
  - `experiments/results/v21-hybrid1-vs-baseline.md`
  - 本文件
- 本地完整 traces / runs：`tmp/experiments/`（不入库）。

## 下一轮假设（未执行）

1. 先修玩家初始捕获（模板/颜色双通道 + 开局强制全屏重捕获），把 stale=1.0 的局消掉；
2. 保留 baseline 周期跳，仅叠加“高置信近迫威胁”的 reactive dash/jump（不替换底噪）；
3. 若仍无收益，说明当前 30Hz 视觉/键控不足以稳定森林关，需要换感知或接受上限。
