# v2.1 Stage 2 批次复盘：解决感知断路后，纯反应式仍 no_gain（2026-11-06）

## 实验假设

修复感知断路后，关闭 `jump_every_ms=420` 周期盲跳，改用 WorldModel 威胁触发 `jump_over` / `dash_through` / `stop_shoot`，应减少早期死亡、提高推进。

## 配置

- 基线：`jump_every_ms=420`, `dash_every_ms=800`, `engage_radius=0.0`, `edge_escape=false`，`reactive_mode=false`；
- 候选：同上 + `combat.reactive_mode=true`（周期跳/冲被 veto，由 reactive_control 触发）；
- 每臂 10 局，max 75s；
- 全程每局写入 `traces/<run_id>.jsonl`，含感知健康度、威胁、选中 option、动作和 veto。

## 结果

### Baseline（`v21-baseline-1`）

```json
{"n":10,"mean":2.2923,"median":2.5505,"p10":1.493,"max":3.229,
 "mean_player_stale_ratio":0.2563,"mean_threat_active_ratio":0.9934,
 "death_causes":{"low_hp":4,"hit":4,"cornered":2}}
```

### Reactive（`v21-reactive-3`，ttc=None 优先跳的修正版）

```json
{"n":10,"mean":1.9697,"median":1.936,"p10":1.481,"max":3.326,
 "mean_player_stale_ratio":0.1918,"mean_threat_active_ratio":0.9878,
 "death_causes":{"hit":3,"low_hp":2,"cornered":5}}
```

### 对比

```json
{"decision":"no_gain",
 "diff":{"observed":-0.6145,"ci_low":-1.065,"ci_high":0.048}}
```

## 结论

1. **感知修复有效**：`player_stale_ratio` 0.256→0.192，`threat_active_ratio` 0.99；轨迹中能看到真实威胁和 option/veto。
2. **纯反应式策略 no_gain**：median -0.61 屏，CI 跨 0；p10 基本持平。
3. **失败局原因（来自 traces）**：
   - 开局若干局玩家追踪仍未捕获（`player_age_ms=None`, stale=1.0），reactive 无可靠相对威胁；
   - 关闭周期跳后，角色在地面停留更久，接触/角落死亡增加（cornered 5）；
   - `stop_shoot` 在近距离威胁时仍可能压过跳跃，造成停滞。
4. **不能把“感知修复”误当成“策略提升”**：感知健康度达标，但策略仍未超过盲跳基线。

## 下一轮假设（待验证）

- **Hybrid**：保留低频周期跳作为“无威胁/无缺口”时的保底，仅在明确威胁时由 reactive 覆盖；用来检验“周期跳是否是不可缺的移动底噪”。
- 或优先修玩家初始捕获（模板/颜色双通道），减少 stale=1.0 的局。
- 在没有新假设前，不再重复跑相同 reactive 批次。

## 产物

- 本地完整轨迹：`tmp/experiments/traces/v21-baseline-1/`、`tmp/experiments/traces/v21-reactive-3/`（不入库）；
- 入库报告：`experiments/results/v21-baseline-1.md`、`v21-reactive-3.md`、`v21-reactive3-vs-baseline.md`；
- 单局账本：`tmp/experiments/v21-*.jsonl`（不入库）。
