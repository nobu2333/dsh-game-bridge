# P4 第一批：option_canary（2026-11-05）

## 环境

- Cuphead Forest Follies，窗口 960×540；
- profile：jump=420 / dash=800 / hold=260 / engage=0.0 / edge_escape=false；
- driver 本地 127.0.0.1:47655；
- baseline 10 局 / canary 10 局，max 75s/局；
- 机制审计每局执行。

## 结果

### Baseline（`p4-baseline-clean.jsonl`，n=10）

| 指标 | 值 |
|:--|--:|
| mean peak | 3.214 |
| median | 3.383 |
| p10 | 2.769 |
| max | 3.821 |
| clear rate | 0 |

### Canary jump_over（`p4-canary-jump-1.jsonl`，n=10）

| 指标 | 值 |
|:--|--:|
| mean peak | 2.666 |
| median | 2.959 |
| p10 | 1.709 |
| max | 3.997 |
| clear rate | 0 |

**机制审计失败**：`option_canary enabled=true`，但 `applied=0`，全部 `vetoed=not_selected`。  
说明 shadow 选项从未选中 `jump_over`；这批不能作为 jump_over 的行为 A/B，只能算“canary 未触发”。

### Canary dash_through（`p4-canary-dash.jsonl`，n=10）

| 指标 | 值 |
|:--|--:|
| mean peak | 2.708 |
| median | 3.174 |
| p10 | 0.623 |
| max | 4.043 |
| clear rate | 0 |

机制审计通过（canary 确实 applied）。

### 对比 baseline vs dash_through

```json
{
  "decision": "no_gain",
  "diff": {"observed": -0.209, "ci_low": -1.491, "ci_high": 0.516}
}
```

## 判定

- **不 promotion**；
- `dash_through` 首机制 A/B：no_gain，中位数还低 0.21 屏；
- `jump_over`：canary 未触发（audit fail），不能算收益；
- `option_canary` 保持默认关闭；
- 单局最高 4.135，仍无通关。

## 下一步

1. 先修/验证 shadow 选项为什么从不选 `jump_over`（world_model 威胁是否为空）；
2. 再试 `stop_shoot` 或换 trigger 条件；
3. 每个机制仍需 3 批独立验证，不能因这批就认为 option 策略有效或无效。

## 追加：jump_over 第二次（tracks 注入后）

- 新增 tracks→WorldModel：`world_model.threats` 已能看到 `track-152`（side=right, ttc≈0.16）。
- 但 `option_shadow` 实际选 `strafe_right`（reason=commit），不是 `jump_over`。
- `p4-canary-jump-2`：audit 仍失败，`applied=0`，`vetoed=not_selected`。
- 结论：jump_over canary 未触发的原因不在感知为空，而在选项选择/承诺/动作状态（jump_over 与周期跳竞争）；这批仍不能作为行为 A/B。
- dash_through 的有效 no_gain 结果保留。
