# 通用游戏矩阵（v3）

本目录是 [GENERAL-PLUGIN-V3.md](../../docs/GENERAL-PLUGIN-V3.md) 的执行清单，不是游戏数据仓库。

## 规则

- 只列单机、无反作弊的游戏；在线竞技一律排除。
- 不提交 ROM、录像、账号、本机路径或游戏资源。
- 每款游戏先做 **T1**，再考虑 **T2**；不要求通关。
- 反作弊字段不是 `none` 的游戏，GamePack 直接拒绝加载。
- Cuphead 只做 depth regression，不再作为总 KPI。

## 层级

| 层级 | 验收 |
|:--|:--|
| T0 | attach + 抓屏 + 窗口/前台 |
| T1 | 菜单/键位 + 首个有效动作，5 分钟内，无需人示范 |
| T2 | 连续 5 分钟有意义游玩 |
| T3 | 通关第一关/Boss（可选） |
| T4 | 稳定重复（可选） |

## 当前选择

- **T1 主目标（3/3）**：Cuphead ✅、2048 ✅、Dinosaur Game ✅
- **T2（2/2）**：T-Rex ✅（301.55s autoplay，score 53→89）；2048 ✅（302.14s，340 actions，5 次 pack restart，多棋盘有得分推进）
- **可选**：NES Battle City via RetroArch（需要先确认模拟器与合法 ROM）；SuperTux（二进制缺失）；Block Blast（构建不可玩）
- **排除**：Overwatch、Honkai: Star Rail、Wuthering Waves（在线/反作弊）；Brotato 暂不可用

具体状态见 [matrix.json](matrix.json)。新游戏先在此登记，再生成 pack 草稿。

## 来源与严格 T2（2026-11-10）

- 每个 pack 增加 `origin`（auto / assisted / human）、`interventions`、可选 `probe`。
- **T1 必须区分来源**：人工/探针辅助的 pack 不能算作“自动 onboarding 成功”。
- 当前矩阵：T1 4（全部 assisted）、T2 2，但 **T1-auto = 0**；严格 T2（不允许重开/死亡刷时长）尚未满足。
- `python -m dsh_game_core.coverage --matrix experiments/games/matrix.json --packs <paths>` 输出：
  - t1_total / t1_auto / t1_assisted / t1_human；
  - t2_total / strict_t2；
  - interventions / missing_evidence / target_met / auto_target_met。
- 下一款游戏必须优先证明 **T1-auto**：零人工键位/pack，5 分钟内自动生成并验证。
