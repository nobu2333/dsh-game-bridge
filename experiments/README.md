# 实验记录（P4）

> 目的：让“这个机制是否值得保留”可复现、可审计，而不是看单局高值。
> 只提交 spec 与结论摘要；本机 runs/frames 不入库。

## 目录

```text
experiments/
  README.md
  specs/<name>.json          # 提交：实验设计
  results/<name>.md          # 提交：结论摘要（可选）
  <name>/runs.jsonl          # 本地：每局 RunMetrics（忽略）
  <name>/frames/             # 本地：关键帧（忽略）
```

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
