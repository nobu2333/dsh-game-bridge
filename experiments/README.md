# 实验记录（P4）

> 目的：让“这个机制是否值得保留”可复现、可审计，而不是看单局高值。
> 只提交 spec 与结论摘要；本机 runs/frames 不入库。

## 目录

```text
experiments/
  README.md
  specs/<name>.json          # 提交：实验设计
  results/<name>.md          # 提交：批次复盘报告（假设、感知健康度、A/B 统计、失败局时间线剖析）
tmp/experiments/<batch_id>/  # 本地完整留痕（不入库）
  runs.jsonl                 # 每局 RunMetrics + 感知健康度 + 掉血事件 + 死亡快照
  traces/<run_id>.jsonl      # 每局 5-10Hz / 事件驱动决策轨迹（死前 3s 回放）
  frames/                    # 可选关键帧缩略图
```

## 全量留痕与复盘闭环（2026-11-06 新增硬性要求）

可以接受新策略暂时无法通关，但**每次测试过程必须完整记录、可复盘、可循环优化**：

1. **过程轨迹（`traces/<run_id>.jsonl`）**：记录 `ts, scroll_s, hp, anchor, player_age_ms, threats_top2, selected_option, applied_action, veto_reason`，确保任何一次受击/死亡都能还原“当时看到了什么、为什么选这个动作”；
2. **单局健康度与归因（`runs.jsonl`）**：记录 `player_stale_ratio`、`threat_active_ratio`、`option_counts`、`damage_events`、`death_context`；
3. **入库复盘报告（`experiments/results/<batch_id>.md`）**：每次跑批结束后生成结构化复盘报告并提交 Git，指导下一轮迭代。

## Spec 字段

```json
{
  "name": "option-canary-jump-over",
  "mechanism": "option_canary",
  "baseline_label": "baseline",
  "candidate_label": "canary-jump",
  "primary_metric": "peak_screens",
  "min_runs": 10,
  "min_effect": 0.5,
  "min_ci_low": 0.0,
  "guardrail_drop": 1.0,
  "alpha": 0.05,
  "protocol": "3 independent batches",
  "baseline_config": {"options": {"execute": false}},
  "candidate_config": {"options": {"execute": true, "canary": "jump_over"}}
}
```

## 判定规则

一个机制只有连续 **3 个独立批次** 满足以下条件才允许 promotion：

1. 主指标中位数提升 `>= min_effect`（默认 +0.5 屏），或 clear rate 提升 `>= 10pt`；
2. bootstrap 95% CI 下界 `> min_ci_low`；
3. 最差局不恶化超过 `guardrail_drop`；
4. 关闭机制时收益消失（可逆）；
5. `mechanism_audit` 通过：
   - 启用机制 `applied > 0`；
   - 关闭机制 `applied == 0`。

否则：`no_gain` / `regression`，回退并记录。

## 跑法

```bash
# baseline
python scripts/ab_batch.py --label baseline --runs 10

# candidate
python scripts/ab_batch.py --label canary-jump --runs 10 --canary jump_over

# 判定
python -m dsh_game_core.experiment_cli compare \
  tmp/experiments/baseline.jsonl tmp/experiments/canary-jump.jsonl \
  --mechanism option_canary --min-runs 10 --min-effect 0.5

# 机制审计（status.json 从 driver/status 落盘）
python -m dsh_game_core.experiment_cli audit status.json --profile profiles/cuphead.json
```

## 当前 spec

- `specs/option-canary-jump-over.json`：P4 第一个单机制 canary，默认关闭，先 10+10 局。
