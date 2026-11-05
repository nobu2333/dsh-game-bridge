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

## 追加：jump_over 第三次（允许空中选中、落地执行）

- `jump_over` 去掉 `grounded` 前置，改为 canary 执行时等落地；解决 periodic_jump 占满 `jump_until` 导致永远不可选。
- `p4-canary-jump-3`：audit 通过（canary 真的 applied），n=10：
  - mean 2.8895 / median **3.483** / p10 1.903 / max 3.947。
- compare baseline（median 3.3825）：
  - diff +0.1005，95% CI [-1.3485, 0.424]，decision **no_gain**。
- 结论：jump_over 与 dash_through 都是有效 canary，但都 no_gain；option_canary 保持默认关闭，不 promotion。

## P4 首批总结

| 机制 | audit | median | 结论 |
|:--|:--|--:|:--|
| dash_through | 通过 | 3.174 | no_gain |
| jump_over | 通过 | 3.483 | no_gain（+0.10，CI 跨 0） |
| jump_over（旧） | 失败 | — | not_selected，无效 |

没有机制达到 +0.5 屏 / CI>0；不进入第二批。

## 追加：stop_shoot（第三个单机制）

- `p4-canary-stop`：n=10，mean 2.766 / median 3.036 / max 3.952。
- audit 失败：`option_canary enabled=true`、`applied=0`、全部 `vetoed=not_selected`。
- 说明 selector 没有把 `threat_near` 判成可停火输出；这批同样不能算 stop_shoot 的行为 A/B。

## P4 首批最终

- 有效执行：dash_through（no_gain）、jump_over（no_gain）。
- 未触发：stop_shoot（not_selected）。
- 没有任何机制达到 promotion 阈值。
- 结论：单机制 canary 不带来稳定提升；下一步必须改选择/仲裁，而不是继续逐个 option 试。

## 追加：option_stats（选择诊断）

8 秒实机 shadow 统计：

- advance selected 61；
- jump_over selected 61；
- dash_through selected 60；
- stop_shoot selected 51；
- strafe_right 20 / strafe_left 0。

说明：

- `stop_shoot` 并不是永远选不中；之前 canary applied=0 是因为 **option_canary 执行层不支持 stop_shoot**（会被 veto unsupported_option），不是选择层。
- 选择层高频切换（commit 为主），但 P4 两个可执行机制仍 no_gain；问题在“执行一个局部 option 不足”，不是“选项完全没被选中”。
