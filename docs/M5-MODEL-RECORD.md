# M5 模型局记录模板

模型会话跑完一局后，请把下面这段填好发回；不要只发自然语言总结。

```json
{
  "run_id": "model-YYYYMMDD-HHMMSS-01",
  "date": "YYYY-MM-DD",
  "player": "model:<name>",
  "game": "2048",
  "build": "gabrielecirulli/2048@local",
  "steps": 0,
  "actions_total": 0,
  "wall_s": null,
  "score": 0,
  "best_tile": 0,
  "end_reason": "game_over | static_5 | step_limit_300 | context_budget | user_stop",
  "score_source": "screen_ocr | model_report",
  "foreground_mismatches": 0,
  "used_game_plan_policy_intent": false,
  "plan_policy_intent_detail": "",
  "notes": []
}
```

## 必填口径

- `steps`：本局实际发出的按键次数；
- `actions_total`：`game_stop` 返回值；如果是累计值，在 notes 里说明包含之前会话；
- `score`：屏幕 SCORE；
- `best_tile`：屏幕上最大方块，不是 BEST 分数；
- `end_reason`：必须是真实结束原因；上下文停止写 `context_budget`，不要写 `game_over`；
- `foreground_mismatches`：`FOREGROUND_MISMATCH` 次数；
- `used_game_plan_policy_intent`：是否用过 `game_plan` / `game_policy` / `game_intent`。

## 同时保留

- 2048 窗口不要关，停在最终局面；
- 记录后由本地 `scripts/record_model_run.py` 再 OCR 读一次分，作为权威分数；
- 若 OCR 分数与模型自报不同，以 OCR 为准，在 notes 写差异。

## 本地落库

```powershell
python scripts\record_model_run.py `
  --window 2048 `
  --player model:deepseek `
  --game 2048 `
  --build "gabrielecirulli/2048@local" `
  --steps <steps> `
  --end-reason <end_reason>
```

记录追加到 `experiments/results/m5-model.jsonl`。
