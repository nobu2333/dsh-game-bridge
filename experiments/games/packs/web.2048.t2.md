# 2048 T2 证据（2026-11-09）

## 结论

2048 达到 **T2**（按本 goal 的“5 分钟有意义游玩”定义）：

- 连续 **302.14 秒**；
- **340** 次方向键动作；
- **5** 次 New Game 重置（pack 数据中的 `restart`，不是引擎分支）；
- 0 错误；
- 多个棋盘都有实际得分推进（24/76/96/132/164/180/188/256/320/340/396/452/464/504/620…）。

## 命令

```powershell
python scripts/play_pack.py --pack experiments/games/packs/web.2048.t1.json --duration 300
```

## 有效性检查

`play_pack.py` 在本次报告生成后增加了通用 `evaluate_session`（时长 + stop phrase）。
2048 pack 没有设置 `stop_phrases`；按当前检查器：

- duration 302.14s ≥ 300s；
- 没有 stop phrase；
- 因此 valid。

报告本身生成时还没有 `valid` 字段；这是事后复核，不是重新跑了一遍。

## 边界

- 这是“5 分钟多棋盘游玩”，不是“单棋盘连续 5 分钟”；
- restart 由 pack 的 `autoplay.restart` 点击 New Game 完成，不是引擎特判；
- 2048 仍是开源浏览器目标，不是商业 3A；
- 该证据与 T-Rex 的 5 分钟（允许死亡/重开）采用同一 T2 语义。
